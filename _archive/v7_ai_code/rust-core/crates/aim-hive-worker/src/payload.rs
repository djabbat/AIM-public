//! Payload builder. Reads aggregated state from the AIM ledger SQLite
//! and other read-only sources (prompt file, suppressions JSON), and
//! emits an anonymized envelope for the queen.
//!
//! Source compatibility: this is the Rust port of
//! `AI/ai/hive_telemetry.py::contribution`. Both should produce the
//! same envelope shape so the queen can ingest from either worker
//! type during the migration.

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

// ── envelope ────────────────────────────────────────────────────

use crate::worker_id;
use crate::HiveError;

/// Top-level envelope. JSON shape stable across migration.
#[derive(Debug, Serialize, Deserialize)]
pub struct Payload {
    pub v: u32,
    pub ts: String,
    pub worker_id: String,
    pub ledger: serde_json::Value,
    pub prompt: serde_json::Value,
    pub skills: serde_json::Value,
    pub reflexion: serde_json::Value,
    pub suppressions: serde_json::Value,
    pub system: serde_json::Value,
}

/// Resolve the AIM state root: explicit arg → `AIM_STATE_ROOT` env →
/// `~/.aim/`.
fn resolve_state_root(explicit: Option<&PathBuf>) -> PathBuf {
    if let Some(p) = explicit {
        return p.clone();
    }
    if let Ok(s) = std::env::var("AIM_STATE_ROOT") {
        return PathBuf::from(s);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".aim")
}

pub fn build(state_root: Option<&PathBuf>) -> Result<Payload, HiveError> {
    let root = resolve_state_root(state_root);
    Ok(Payload {
        v: 1,
        ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        worker_id: worker_id(),
        ledger: ledger_signal(&root),
        prompt: prompt_signal(&root),
        skills: skills_signal(&root),
        reflexion: reflexion_signal(&root),
        suppressions: suppression_signal(&root),
        system: system_signal(),
    })
}

// ── ledger ──────────────────────────────────────────────────────

fn ledger_signal(root: &Path) -> serde_json::Value {
    let db = root.join("ai").join("diagnostic_ledger.db");
    let Ok(conn) = rusqlite::Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    ) else {
        return serde_json::json!({});
    };

    // Schema is owned by AI/ai/diagnostic_ledger.py. Best-effort SELECT
    // — if any column is missing or the table isn't there, return {}.
    let n_runs: i64 = match conn
        .query_row("SELECT COUNT(*) FROM diagnostics", [], |r| r.get(0))
    {
        Ok(v) => v,
        Err(_) => return serde_json::json!({}),
    };
    if n_runs == 0 {
        return serde_json::json!({"n_runs": 0});
    }

    let avg_compliance: f64 = conn
        .query_row(
            "SELECT COALESCE(AVG(line_compliance),0) FROM diagnostics",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0.0);
    let avg_crit: f64 = conn
        .query_row(
            "SELECT COALESCE(AVG(crit_score),0) FROM diagnostics",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0.0);
    let n_retries: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM diagnostics WHERE retried = 1",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0);

    let mut grade_dist = BTreeMap::new();
    if let Ok(mut stmt) = conn.prepare(
        "SELECT grade, COUNT(*) FROM diagnostics GROUP BY grade",
    ) {
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))
        });
        if let Ok(rows) = rows {
            for r in rows.flatten() {
                grade_dist.insert(r.0, r.1 as u64);
            }
        }
    }

    serde_json::json!({
        "n_runs": n_runs,
        "avg_compliance": (avg_compliance * 1000.0).round() / 1000.0,
        "avg_crit": (avg_crit * 100.0).round() / 100.0,
        "retry_share": (((n_retries as f64) / (n_runs as f64)) * 1000.0).round() / 1000.0,
        "grade_dist": grade_dist,
    })
}

// ── prompt ──────────────────────────────────────────────────────

fn prompt_signal(root: &Path) -> serde_json::Value {
    let p = root.join("ai").join("SELF_DIAGNOSTIC_PROMPT.md");
    let Ok(bytes) = std::fs::read(&p) else {
        return serde_json::json!({});
    };
    use sha2::Digest;
    let mut h = sha2::Sha256::new();
    h.update(&bytes);
    let digest = h.finalize();
    let line_count = bytes.iter().filter(|&&b| b == b'\n').count();
    serde_json::json!({
        "sha256": hex::encode(digest),
        "byte_count": bytes.len(),
        "line_count": line_count,
    })
}

// ── skills (placeholder, parity with Python) ────────────────────

fn skills_signal(_root: &Path) -> serde_json::Value {
    // Python returns {"skill_invocations": {}} pending session-log
    // integration. Same here.
    serde_json::json!({"skill_invocations": {}})
}

// ── reflexion (read-only summary file written by AI/ai/reflexion_cluster) ─

fn reflexion_signal(root: &Path) -> serde_json::Value {
    let p = root.join("ai").join("reflexion_clusters.json");
    let Ok(s) = std::fs::read_to_string(&p) else {
        return serde_json::json!({"clusters": []});
    };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(&s) else {
        return serde_json::json!({"clusters": []});
    };
    let mut out: Vec<serde_json::Value> = vec![];
    if let Some(clusters) = v.as_array() {
        for c in clusters.iter().take(20) {
            let theme = c
                .get("theme")
                .and_then(|t| t.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|w| w.as_str())
                        .take(5)
                        .map(|s| s.to_string())
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            let n = c.get("n").and_then(|n| n.as_u64()).unwrap_or(0);
            if !theme.is_empty() {
                out.push(serde_json::json!({"theme": theme, "n": n}));
            }
        }
    }
    serde_json::json!({"clusters": out})
}

// ── suppressions count ──────────────────────────────────────────

fn suppression_signal(root: &Path) -> serde_json::Value {
    let p = root.join("ai").join("finding_suppressions.json");
    let Ok(s) = std::fs::read_to_string(&p) else {
        return serde_json::json!({});
    };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(&s) else {
        return serde_json::json!({});
    };
    let n = v.as_array().map(|a| a.len()).unwrap_or(0);
    serde_json::json!({"n_active_suppressions": n})
}

// ── system ──────────────────────────────────────────────────────

fn system_signal() -> serde_json::Value {
    serde_json::json!({
        "aim_version": "AI-hive-rust-1",
        "rust_target": std::env::consts::ARCH,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn build_empty_state_returns_envelope() {
        let d = tempdir().unwrap();
        let root = d.path().to_path_buf();
        let p = build(Some(&root)).unwrap();
        assert_eq!(p.v, 1);
        assert!(p.worker_id.len() == 16);
        assert!(p.ledger.is_object());
        assert!(p.prompt.is_object());
        assert!(p.skills.is_object());
        assert!(p.reflexion.is_object());
        assert!(p.suppressions.is_object());
        assert!(p.system.is_object());
    }

    #[test]
    fn prompt_fingerprint_format() {
        let d = tempdir().unwrap();
        let root = d.path().to_path_buf();
        let ai = root.join("ai");
        std::fs::create_dir_all(&ai).unwrap();
        std::fs::write(ai.join("SELF_DIAGNOSTIC_PROMPT.md"), "hello\nworld\n").unwrap();
        let v = prompt_signal(&root);
        assert_eq!(v["byte_count"].as_u64(), Some(12));
        assert_eq!(v["line_count"].as_u64(), Some(2));
        let h = v["sha256"].as_str().unwrap();
        assert_eq!(h.len(), 64);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn suppression_count_reads_array() {
        let d = tempdir().unwrap();
        let root = d.path().to_path_buf();
        let ai = root.join("ai");
        std::fs::create_dir_all(&ai).unwrap();
        std::fs::write(ai.join("finding_suppressions.json"), "[1,2,3]").unwrap();
        let v = suppression_signal(&root);
        assert_eq!(v["n_active_suppressions"].as_u64(), Some(3));
    }

    #[test]
    fn reflexion_caps_clusters() {
        let d = tempdir().unwrap();
        let root = d.path().to_path_buf();
        let ai = root.join("ai");
        std::fs::create_dir_all(&ai).unwrap();
        let mut clusters: Vec<serde_json::Value> = vec![];
        for i in 0..30 {
            clusters.push(serde_json::json!({"theme": ["a", "b"], "n": i}));
        }
        std::fs::write(
            ai.join("reflexion_clusters.json"),
            serde_json::to_string(&clusters).unwrap(),
        )
        .unwrap();
        let v = reflexion_signal(&root);
        let arr = v["clusters"].as_array().unwrap();
        assert_eq!(arr.len(), 20);
    }
}
