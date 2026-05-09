//! aim-ai-auto-sweep — AS1 periodic maintenance sweep.
//!
//! 1. Fingerprint the current SELF_DIAGNOSTIC_PROMPT.md (PV1).
//! 2. Validate every yaml case in AIM_EVAL_CASES_DIR (CV1).
//! 3. Archive stale FE1-generated regression cases (CA1).
//! 4. Compute prompt-impact deltas (PI1).
//! 5. Prune phantom ledger rows whose report files are gone.
//! 6. Prune expired finding suppressions.
//! 7. Snapshot the health score post-cleanup (production state).
//!
//! Each step is best-effort; per-step failure adds a note and the
//! sweep continues. `dry_run` skips all writes.
//!
//! Rust port of `AI/ai/auto_sweep.py`.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SweepResult {
    pub started_at: String,
    pub finished_at: String,
    pub prompt_recorded: bool,
    /// `None` when this is the first-ever fingerprint.
    pub prompt_changed: Option<bool>,
    pub n_cases_validated: u64,
    pub n_cases_invalid: u64,
    pub n_archived_candidates: u64,
    pub n_archived_moved: u64,
    pub n_prompt_revisions: u64,
    pub n_phantom_removed: u64,
    pub n_suppressions_pruned: u64,
    pub health_score_recorded: bool,
    pub notes: Vec<String>,
}

impl SweepResult {
    pub fn all_clean(&self) -> bool {
        self.n_cases_invalid == 0
    }
}

fn now_string() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

pub fn sweep(dry_run: bool) -> SweepResult {
    let started = now_string();
    let mut notes: Vec<String> = Vec::new();

    // 1. Prompt fingerprint
    let mut prompt_recorded = false;
    let mut prompt_changed: Option<bool> = None;
    match aim_ai_prompt_versions::PromptStore::open_default() {
        Ok(store) => {
            let path = aim_ai_prompt_versions::default_prompt_path();
            match aim_ai_prompt_versions::fingerprint_of(&path) {
                Ok(cur) => {
                    let history = store.history().unwrap_or_default();
                    prompt_changed = if history.is_empty() {
                        None
                    } else {
                        Some(cur.sha256 != history.last().unwrap().sha256)
                    };
                    if !dry_run {
                        match store.record_current(None, None) {
                            Ok(_) => prompt_recorded = true,
                            Err(e) => notes.push(format!("prompt record failed: {e}")),
                        }
                    }
                }
                Err(e) => notes.push(format!("prompt fingerprint failed: {e}")),
            }
        }
        Err(e) => notes.push(format!("prompt store unavailable: {e}")),
    }

    // 2. Case validation
    let cv = aim_ai_cases::validate_dir(None);
    if cv.n_failed > 0 {
        for s in &cv.statuses {
            if !s.ok {
                let n = s.issues.len();
                let name = s
                    .path
                    .file_name()
                    .and_then(|p| p.to_str())
                    .unwrap_or("?");
                notes.push(format!("invalid case: {name} ({n} issue(s))"));
            }
        }
    }

    // Open ledger once for steps that need it.
    let ledger_res = aim_ai_ledger::Ledger::open_default();
    if let Err(ref e) = ledger_res {
        notes.push(format!("ledger open failed: {e}"));
    }

    // 3. Archive stale cases (use ledger if open)
    let mut n_cands = 0u64;
    let mut n_moved = 0u64;
    if let Ok(ledger) = ledger_res.as_ref() {
        let opts = aim_ai_case_archiver::ArchiveOpts {
            dry_run,
            ..Default::default()
        };
        match aim_ai_case_archiver::archive(ledger, &opts) {
            Ok(res) => {
                n_cands = res.n_candidates;
                n_moved = res.n_moved;
            }
            Err(e) => notes.push(format!("archive step failed: {e}")),
        }
    }

    // 4. Prompt impact (read-only)
    let mut n_revs = 0u64;
    if let Ok(ledger) = ledger_res.as_ref() {
        if let Ok(store) = aim_ai_prompt_versions::PromptStore::open_default() {
            match aim_ai_prompt_impact::impact_per_revision(ledger, &store) {
                Ok(rows) => n_revs = rows.len() as u64,
                Err(e) => notes.push(format!("impact step failed: {e}")),
            }
        }
    }

    // 5. Prune phantom ledger rows
    let mut n_phantom = 0u64;
    if let Ok(ledger) = ledger_res.as_ref() {
        match ledger.prune_phantom(dry_run) {
            Ok(res) => {
                n_phantom = if dry_run { res.would_remove } else { res.removed };
            }
            Err(e) => notes.push(format!("prune phantom failed: {e}")),
        }
    }

    // 6. Prune expired suppressions
    let mut n_supp = 0u64;
    if !dry_run {
        match aim_ai_suppressions::SuppressionStore::open_default() {
            Ok(store) => match store.prune_expired() {
                Ok(n) => {
                    n_supp = n;
                    if n > 0 {
                        notes.push(format!("removed {n} expired suppression(s)"));
                    }
                }
                Err(e) => notes.push(format!("suppression prune failed: {e}")),
            },
            Err(e) => notes.push(format!("suppression store unavailable: {e}")),
        }
    }

    // 7. Snapshot health score
    let mut health_recorded = false;
    if !dry_run {
        if let Ok(ledger) = ledger_res.as_ref() {
            match aim_ai_health::compute(ledger) {
                Ok(score) => {
                    match aim_ai_health::HealthStore::open_default() {
                        Ok(hs) => match hs.record(&score, None) {
                            Ok(()) => health_recorded = true,
                            Err(e) => notes.push(format!("score record failed: {e}")),
                        },
                        Err(e) => notes.push(format!("health store unavailable: {e}")),
                    }
                }
                Err(e) => notes.push(format!("score compute failed: {e}")),
            }
        }
    }

    SweepResult {
        started_at: started,
        finished_at: now_string(),
        prompt_recorded,
        prompt_changed,
        n_cases_validated: cv.n_cases,
        n_cases_invalid: cv.n_failed,
        n_archived_candidates: n_cands,
        n_archived_moved: n_moved,
        n_prompt_revisions: n_revs,
        n_phantom_removed: n_phantom,
        n_suppressions_pruned: n_supp,
        health_score_recorded: health_recorded,
        notes,
    }
}

pub fn summary(r: &SweepResult, dry_run: bool) -> String {
    let mode = if dry_run { "dry-run" } else { "live" };
    let mut parts: Vec<String> = vec![format!(
        "🧹 Auto-sweep ({mode}) — {}",
        r.started_at
    )];
    match r.prompt_changed {
        None if r.prompt_recorded => {
            parts.push("  • prompt fingerprint recorded for the first time".into())
        }
        Some(true) if r.prompt_recorded => {
            parts.push("  • prompt CHANGED — new revision logged".into())
        }
        Some(false) => parts.push("  • prompt unchanged".into()),
        _ => {}
    }
    parts.push(format!(
        "  • cases validated: {} ({} invalid)",
        r.n_cases_validated, r.n_cases_invalid
    ));
    if r.n_archived_candidates > 0 {
        if dry_run {
            parts.push(format!(
                "  • would archive: {} stale regression case(s)",
                r.n_archived_candidates
            ));
        } else {
            parts.push(format!(
                "  • archived: {} stale regression case(s)",
                r.n_archived_moved
            ));
        }
    } else {
        parts.push("  • no cases ready for archive".into());
    }
    if r.n_phantom_removed > 0 {
        let verb = if dry_run { "would remove" } else { "removed" };
        parts.push(format!(
            "  • {verb} {} phantom ledger row(s)",
            r.n_phantom_removed
        ));
    }
    parts.push(format!(
        "  • prompt revisions tracked: {}",
        r.n_prompt_revisions
    ));
    if !r.notes.is_empty() {
        parts.push("  notes:".into());
        for n in &r.notes {
            parts.push(format!("    - {n}"));
        }
    }
    parts.push(format!("  finished {}", r.finished_at));
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Smoke test: sweep on an empty environment doesn't panic and
    /// produces a result with zero counts.
    #[test]
    fn sweep_dry_run_does_not_panic() {
        // Use a temp HOME so we don't touch the user's real cache.
        let d = tempfile::tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        let r = sweep(true);
        assert_eq!(r.n_cases_validated, 0);
        assert_eq!(r.n_cases_invalid, 0);
        assert_eq!(r.n_archived_candidates, 0);
        assert_eq!(r.n_phantom_removed, 0);
        // dry_run never records anything
        assert!(!r.prompt_recorded);
    }

    #[test]
    fn summary_renders_layout() {
        let r = SweepResult {
            started_at: "2026-05-04T00:00:00Z".into(),
            finished_at: "2026-05-04T00:01:00Z".into(),
            prompt_recorded: true,
            prompt_changed: None,
            n_cases_validated: 5,
            n_cases_invalid: 0,
            n_archived_candidates: 0,
            n_archived_moved: 0,
            n_prompt_revisions: 1,
            n_phantom_removed: 0,
            n_suppressions_pruned: 0,
            health_score_recorded: true,
            notes: vec![],
        };
        let s = summary(&r, false);
        assert!(s.contains("🧹 Auto-sweep"));
        assert!(s.contains("first time"));
        assert!(s.contains("cases validated: 5"));
    }

    #[test]
    fn all_clean_predicate() {
        let mut r = SweepResult {
            started_at: "".into(),
            finished_at: "".into(),
            prompt_recorded: false,
            prompt_changed: None,
            n_cases_validated: 5,
            n_cases_invalid: 0,
            n_archived_candidates: 0,
            n_archived_moved: 0,
            n_prompt_revisions: 0,
            n_phantom_removed: 0,
            n_suppressions_pruned: 0,
            health_score_recorded: false,
            notes: vec![],
        };
        assert!(r.all_clean());
        r.n_cases_invalid = 1;
        assert!(!r.all_clean());
    }
}
