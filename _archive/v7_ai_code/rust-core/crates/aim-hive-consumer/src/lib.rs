//! aim-hive-consumer — worker pull side.
//!
//! Pulls eval-gated updates from the queen, applies three local gates
//! before installation:
//!
//! 1. **L_CONSENT** — opt-out per `kind` and optional glob pattern over
//!    string fields in the body.
//! 2. **Signature integrity** — minimal length check for now (real
//!    deployment will verify against queen's public key).
//! 3. **L_VERIFIABILITY** — `eval_delta < 0` from queen ⇒ skip; later
//!    re-runs the worker-local eval.
//!
//! Approved updates are installed:
//! - `skill` → `~/.aim/skills/<skill_id>.json`
//! - `eval_case` → `$AIM_EVAL_CASES_DIR/<case_id>.yaml`
//!   (or `~/.cache/aim/eval_cases/`)
//! - `prompt_patch` → recorded only; no auto-rewrite of the prompt
//!
//! Decisions are recorded in a sync_log SQLite table for auditing and
//! to compute `since` on the next pull.
//!
//! Rust port of `AI/ai/hive_consumer.py`.

pub mod consent;
pub mod state;

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub use state::ConsumerState;

#[derive(Debug, Error)]
pub enum ConsumerError {
    #[error("transport: {0}")]
    Transport(#[from] reqwest::Error),
    #[error("queen: status {0}")]
    Queen(u16),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("config: {0}")]
    Config(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Update {
    pub id: String,
    pub ts: String,
    pub kind: String,
    pub body: serde_json::Value,
    pub source_n: u32,
    pub eval_delta: Option<f64>,
    pub signature: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApplyResult {
    pub update_id: String,
    pub installed: bool,
    pub skipped: bool,
    pub skipped_reason: Option<String>,
    pub notes: Vec<String>,
}

/// HTTP pull. Returns updates newer than `since` (or last seen, if None).
pub async fn pull(
    queen_url: Option<&str>,
    since: Option<&str>,
    state: &ConsumerState,
) -> Result<Vec<Update>, ConsumerError> {
    let url = match queen_url
        .map(|s| s.to_string())
        .or_else(|| std::env::var("AIM_HIVE_QUEEN_URL").ok())
    {
        Some(u) => u,
        None => {
            tracing::debug!("no queen URL — skipping pull");
            return Ok(Vec::new());
        }
    };
    let resolved_since = match since {
        Some(s) => Some(s.to_string()),
        None => state.last_seen_ts()?,
    };
    let endpoint = format!("{}/v1/hive/updates", url.trim_end_matches('/'));
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;
    let mut req = client.get(&endpoint);
    if let Some(s) = resolved_since.as_ref() {
        req = req.query(&[("since", s)]);
    }
    if let Ok(tok) = std::env::var("AIM_USER_TOKEN") {
        req = req.bearer_auth(tok);
    }
    let resp = req.send().await?;
    let status = resp.status();
    if !status.is_success() {
        return Err(ConsumerError::Queen(status.as_u16()));
    }
    #[derive(Deserialize)]
    struct UpdatesEnvelope {
        updates: Vec<Update>,
    }
    let env: UpdatesEnvelope = resp.json().await?;
    Ok(env.updates)
}

/// Options for [`apply`].
#[derive(Debug, Default)]
pub struct ApplyOpts {
    pub dry_run: bool,
    /// Override `~/.aim/skills/`.
    pub skills_dir: Option<PathBuf>,
    /// Override `$AIM_EVAL_CASES_DIR` / `~/.cache/aim/eval_cases/`.
    pub eval_cases_dir: Option<PathBuf>,
}

/// Run all gates and (if approved) install. Records the decision
/// in `state.sync_log`.
pub fn apply(
    update: &Update,
    state: &ConsumerState,
    opts: &ApplyOpts,
) -> Result<ApplyResult, ConsumerError> {
    let mut notes: Vec<String> = Vec::new();
    let seen_at = chrono::Utc::now()
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true);

    // Gate 1: L_CONSENT
    if state.is_opted_out(&update.kind, &update.body)? {
        let reason = "L_CONSENT: user opted out of this kind/pattern".to_string();
        if !opts.dry_run {
            state.record_decision(update, false, true, Some(&reason), &seen_at)?;
        }
        return Ok(ApplyResult {
            update_id: update.id.clone(),
            installed: false,
            skipped: true,
            skipped_reason: Some(reason),
            notes,
        });
    }

    // Gate 2: signature integrity (length check; real impl verifies key)
    if update.signature.len() < 8 {
        let reason = "signature missing or too short".to_string();
        if !opts.dry_run {
            state.record_decision(update, false, true, Some(&reason), &seen_at)?;
        }
        return Ok(ApplyResult {
            update_id: update.id.clone(),
            installed: false,
            skipped: true,
            skipped_reason: Some(reason),
            notes,
        });
    }

    // Gate 3: L_VERIFIABILITY (queen-declared eval_delta)
    if let Some(d) = update.eval_delta {
        if d < 0.0 {
            let reason = format!("eval_delta {d} < 0");
            if !opts.dry_run {
                state.record_decision(update, false, true, Some(&reason), &seen_at)?;
            }
            return Ok(ApplyResult {
                update_id: update.id.clone(),
                installed: false,
                skipped: true,
                skipped_reason: Some(reason),
                notes,
            });
        }
    }

    if opts.dry_run {
        notes.push("dry_run — not installed".to_string());
        return Ok(ApplyResult {
            update_id: update.id.clone(),
            installed: false,
            skipped: false,
            skipped_reason: None,
            notes,
        });
    }

    // Install per kind
    let install_result: Result<(), String> = match update.kind.as_str() {
        "skill" => match install_skill(&update.body, opts.skills_dir.as_ref()) {
            Ok(()) => {
                notes.push("skill written to ~/.aim/skills/".to_string());
                Ok(())
            }
            Err(e) => Err(e.to_string()),
        },
        "prompt_patch" => {
            notes.push(
                "prompt_patch recorded; manual review required before apply (no auto-rewrite of SELF_DIAGNOSTIC_PROMPT.md)"
                    .to_string(),
            );
            Ok(())
        }
        "eval_case" => match install_eval_case(&update.body, opts.eval_cases_dir.as_ref()) {
            Ok(()) => {
                notes.push("eval case written to AIM_EVAL_CASES_DIR".to_string());
                Ok(())
            }
            Err(e) => Err(e.to_string()),
        },
        other => {
            notes.push(format!("unknown kind {other:?} — left untouched"));
            Ok(())
        }
    };

    if let Err(reason) = install_result {
        let r = format!("install error: {reason}");
        state.record_decision(update, false, true, Some(&r), &seen_at)?;
        return Ok(ApplyResult {
            update_id: update.id.clone(),
            installed: false,
            skipped: true,
            skipped_reason: Some(r),
            notes,
        });
    }
    state.record_decision(update, true, false, None, &seen_at)?;
    Ok(ApplyResult {
        update_id: update.id.clone(),
        installed: true,
        skipped: false,
        skipped_reason: None,
        notes,
    })
}

// ── installers ──────────────────────────────────────────────────

fn install_skill(body: &serde_json::Value, dir: Option<&PathBuf>) -> Result<(), ConsumerError> {
    let skill_id = body
        .get("skill_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| ConsumerError::Config("skill body missing skill_id".to_string()))?;
    if !is_safe_id(skill_id) {
        return Err(ConsumerError::Config(format!(
            "unsafe skill_id {skill_id:?}"
        )));
    }
    let dir = dir.cloned().unwrap_or_else(default_skills_dir);
    std::fs::create_dir_all(&dir)?;
    let out = dir.join(format!("{skill_id}.json"));
    std::fs::write(&out, serde_json::to_string_pretty(body)?)?;
    Ok(())
}

fn install_eval_case(
    body: &serde_json::Value,
    dir: Option<&PathBuf>,
) -> Result<(), ConsumerError> {
    let case_id = body
        .get("id")
        .or_else(|| body.get("case_id"))
        .and_then(|v| v.as_str())
        .ok_or_else(|| ConsumerError::Config("eval case missing id".to_string()))?;
    if !is_safe_id(case_id) {
        return Err(ConsumerError::Config(format!(
            "unsafe case_id {case_id:?}"
        )));
    }
    let dir = dir.cloned().unwrap_or_else(default_eval_cases_dir);
    std::fs::create_dir_all(&dir)?;
    let out = dir.join(format!("{case_id}.yaml"));
    let task_json = serde_json::to_string(
        body.get("task").unwrap_or(&serde_json::Value::String("(hive-distilled)".to_string())),
    )?;
    let mut yaml = format!("id: {case_id}\ntask: {task_json}\nrubrics:\n");
    let rubrics = body.get("rubrics").cloned().unwrap_or_else(|| {
        serde_json::json!({"min_length": 1})
    });
    if let serde_json::Value::Object(map) = rubrics {
        for (k, v) in map {
            yaml.push_str(&format!("  {k}: {}\n", serde_json::to_string(&v)?));
        }
    } else {
        yaml.push_str("  min_length: 1\n");
    }
    std::fs::write(&out, yaml)?;
    Ok(())
}

fn default_skills_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".aim").join("skills")
}

fn default_eval_cases_dir() -> PathBuf {
    if let Ok(s) = std::env::var("AIM_EVAL_CASES_DIR") {
        return PathBuf::from(s);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".cache").join("aim").join("eval_cases")
}

/// Allow only ASCII alphanumeric, dash, underscore. Prevents
/// path-traversal via `../` or `~/`.
fn is_safe_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() < 256
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh_state() -> (tempfile::TempDir, ConsumerState) {
        let d = tempdir().unwrap();
        let s = ConsumerState::open(d.path().join("hive_state.db")).unwrap();
        (d, s)
    }

    fn fake_update(kind: &str, body: serde_json::Value, eval_delta: Option<f64>) -> Update {
        Update {
            id: "u-1".to_string(),
            ts: "2026-05-04T00:00:00Z".to_string(),
            kind: kind.to_string(),
            body,
            source_n: 3,
            eval_delta,
            signature: "abcdef0123456789".to_string(),
        }
    }

    #[test]
    fn safe_id_rejects_traversal() {
        assert!(!is_safe_id(""));
        assert!(!is_safe_id("../etc/passwd"));
        assert!(!is_safe_id("a/b"));
        assert!(!is_safe_id("a b"));
        assert!(is_safe_id("auto-12345678"));
        assert!(is_safe_id("good_id_42"));
    }

    #[test]
    fn apply_skips_when_opted_out() {
        let (_d, st) = fresh_state();
        st.opt_out("skill", "*").unwrap();
        let u = fake_update("skill", serde_json::json!({"skill_id":"s1"}), None);
        let r = apply(&u, &st, &ApplyOpts::default()).unwrap();
        assert!(r.skipped);
        assert!(!r.installed);
        assert!(r.skipped_reason.unwrap().contains("L_CONSENT"));
    }

    #[test]
    fn apply_skips_short_signature() {
        let (_d, st) = fresh_state();
        let u = Update {
            signature: "abc".to_string(),
            ..fake_update("skill", serde_json::json!({"skill_id":"s1"}), None)
        };
        let r = apply(&u, &st, &ApplyOpts::default()).unwrap();
        assert!(r.skipped);
        assert!(r.skipped_reason.unwrap().contains("signature"));
    }

    #[test]
    fn apply_skips_negative_delta() {
        let (_d, st) = fresh_state();
        let u = fake_update("skill", serde_json::json!({"skill_id":"s1"}), Some(-0.05));
        let r = apply(&u, &st, &ApplyOpts::default()).unwrap();
        assert!(r.skipped);
        assert!(r.skipped_reason.unwrap().contains("eval_delta"));
    }

    #[test]
    fn apply_installs_skill_to_dir() {
        let (_d, st) = fresh_state();
        let dir = tempdir().unwrap();
        let u = fake_update("skill", serde_json::json!({"skill_id":"auto12345","theme":["a","b"]}), Some(0.05));
        let opts = ApplyOpts {
            skills_dir: Some(dir.path().to_path_buf()),
            ..Default::default()
        };
        let r = apply(&u, &st, &opts).unwrap();
        assert!(r.installed);
        assert!(dir.path().join("auto12345.json").exists());
    }

    #[test]
    fn apply_records_dry_run_does_not_persist() {
        let (_d, st) = fresh_state();
        let u = fake_update("skill", serde_json::json!({"skill_id":"s1"}), None);
        let opts = ApplyOpts {
            dry_run: true,
            ..Default::default()
        };
        let r = apply(&u, &st, &opts).unwrap();
        assert!(!r.installed);
        assert!(!r.skipped);
        let s = st.sync_state().unwrap();
        assert_eq!(s.n_installed, 0);
        assert_eq!(s.n_skipped, 0);
    }

    #[test]
    fn apply_unknown_kind_is_recorded_not_installed_dir() {
        let (_d, st) = fresh_state();
        let u = fake_update("weird-kind", serde_json::json!({}), Some(0.0));
        let r = apply(&u, &st, &ApplyOpts::default()).unwrap();
        // Recorded as installed=true (no install error), but with an
        // explanatory note.
        assert!(r.installed);
        assert!(r.notes.iter().any(|n| n.contains("unknown kind")));
    }

    #[test]
    fn install_eval_case_writes_yaml() {
        let dir = tempdir().unwrap();
        let body = serde_json::json!({"id":"case42","task":"do X","rubrics":{"min_length":5}});
        install_eval_case(&body, Some(&dir.path().to_path_buf())).unwrap();
        let written = std::fs::read_to_string(dir.path().join("case42.yaml")).unwrap();
        assert!(written.contains("id: case42"));
        assert!(written.contains("min_length"));
    }

    #[test]
    fn install_skill_rejects_unsafe_id() {
        let dir = tempdir().unwrap();
        let body = serde_json::json!({"skill_id":"../bad"});
        let r = install_skill(&body, Some(&dir.path().to_path_buf()));
        assert!(matches!(r, Err(ConsumerError::Config(_))));
    }
}
