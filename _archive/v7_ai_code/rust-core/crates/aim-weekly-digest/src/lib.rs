//! aim-weekly-digest — 7-day self-improvement digest renderer.
//!
//! Port of `scripts/weekly_digest.py`. Composes a markdown digest from
//! seven sources (pattern miner, A/B router, prompt evolver, tool
//! synthesis, skill synthesis, memory monitor, archive candidates,
//! eval scoreboard). Each source is a pluggable [`DigestSource`]; the
//! glue here handles section formatting + window filtering.

use chrono::{Duration, NaiveDate};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AbDecision {
    pub decided_at: String, // "YYYY-MM-DD…" — first 10 chars used to filter
    pub challenger: String,
    pub baseline: String,
    pub verdict: String,
    pub delta: Option<f64>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PromptPatch {
    pub ts: String,
    pub key: String,
    pub verdict: String,
    pub note: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SynthesisEvent {
    pub ts: String,
    pub event: String,
    pub name: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ArchiveCandidate {
    pub project: String,
    pub phase: String,
    pub idle_days: u32,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct EvalScore {
    pub run_at: String, // first 10 chars used
    pub version: String,
    pub avg_score: f64,
    pub n: u32,
}

pub trait DigestSource: Send + Sync {
    fn pattern_summary(&self, window_days: u32) -> Result<String, String>;
    fn ab_history(&self, limit: u32) -> Result<Vec<AbDecision>, String>;
    fn prompt_history(&self, limit: u32) -> Result<Vec<PromptPatch>, String>;
    fn tool_history(&self, limit: u32) -> Result<Vec<SynthesisEvent>, String>;
    fn skill_history(&self, limit: u32) -> Result<Vec<SynthesisEvent>, String>;
    fn memory_summary(&self, stale_months: u32) -> Result<String, String>;
    fn archive_candidates(&self, idle_months: u32, today: NaiveDate)
        -> Result<Vec<ArchiveCandidate>, String>;
    fn eval_scoreboard(&self, limit: u32) -> Result<Vec<EvalScore>, String>;
}

const UNAVAIL: &str = "(unavailable)";

fn safe<T, F: FnOnce() -> Result<T, String>>(call: F, default: T) -> T {
    call().unwrap_or(default)
}

fn safe_string<F: FnOnce() -> Result<String, String>>(call: F) -> String {
    call().unwrap_or_else(|_| UNAVAIL.to_string())
}

fn section(title: &str, body: &str) -> String {
    let body = body.trim_end();
    format!("### {}\n{}", title, body)
}

fn ymd(d: NaiveDate) -> String {
    d.format("%Y-%m-%d").to_string()
}

pub fn render_ab_lines(rows: &[AbDecision], cutoff: &str) -> String {
    if rows.is_empty() {
        return "(no A/B decisions yet)".into();
    }
    let mut kept: Vec<String> = Vec::new();
    for r in rows {
        let t: String = r.decided_at.chars().take(10).collect();
        if t.as_str() < cutoff {
            continue;
        }
        let mut s = format!(
            "  • {}  {} vs {} → {}",
            t, r.challenger, r.baseline, r.verdict
        );
        if let Some(d) = r.delta {
            s.push_str(&format!("  Δ={:+.3}", d));
        }
        kept.push(s);
    }
    if kept.is_empty() {
        "(no decisions in window)".into()
    } else {
        kept.join("\n")
    }
}

pub fn render_prompt_lines(rows: &[PromptPatch], cutoff: &str) -> String {
    if rows.is_empty() {
        return "(no prompt evolution events yet)".into();
    }
    let kept: Vec<&PromptPatch> = rows
        .iter()
        .filter(|r| r.ts.chars().take(10).collect::<String>().as_str() >= cutoff)
        .collect();
    if kept.is_empty() {
        return "(no prompt evolution in window)".into();
    }
    kept.iter()
        .map(|r| {
            let ts: String = r.ts.chars().take(16).collect();
            format!("  • {}  {} → {}  {}", ts, r.key, r.verdict, r.note)
                .trim_end()
                .to_string()
        })
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn render_synth_lines(rows: &[SynthesisEvent], cutoff: &str, kind: &str) -> String {
    if rows.is_empty() {
        return format!("(no synthesised {} yet)", kind);
    }
    let kept: Vec<&SynthesisEvent> = rows
        .iter()
        .filter(|r| r.ts.chars().take(10).collect::<String>().as_str() >= cutoff)
        .collect();
    if kept.is_empty() {
        return format!("(no {} synthesis in window)", kind);
    }
    kept.iter()
        .map(|r| {
            let ts: String = r.ts.chars().take(16).collect();
            format!("  • {}  {:10}  {}", ts, r.event, r.name)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn render_archive_lines(rows: &[ArchiveCandidate]) -> String {
    if rows.is_empty() {
        return "(no archive candidates)".into();
    }
    rows.iter()
        .map(|c| format!("  • {}  phase={}  idle={}d", c.project, c.phase, c.idle_days))
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn render_eval_lines(rows: &[EvalScore]) -> String {
    if rows.is_empty() {
        return "(no eval runs yet)".into();
    }
    rows.iter()
        .map(|r| {
            let ts: String = r.run_at.chars().take(10).collect();
            format!(
                "  • {}  version={}  score={:.3}  n={}",
                ts, r.version, r.avg_score, r.n
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn render_digest(today: NaiveDate, window_days: u32, src: &dyn DigestSource) -> String {
    let start = today - Duration::days(window_days as i64);
    let cutoff = ymd(start);
    let mut parts: Vec<String> = Vec::new();
    parts.push("📊 AIM weekly self-improvement digest".to_string());
    parts.push(format!("   {} → {}", ymd(start), ymd(today)));
    parts.push(String::new());

    parts.push(section(
        "🔎 Pattern findings",
        &safe_string(|| src.pattern_summary(window_days)),
    ));
    parts.push(section(
        "⚖️ A/B router",
        &render_ab_lines(&safe(|| src.ab_history(50), Vec::new()), &cutoff),
    ));
    parts.push(section(
        "🧬 Prompt evolution",
        &render_prompt_lines(&safe(|| src.prompt_history(50), Vec::new()), &cutoff),
    ));
    parts.push(section(
        "🛠 Tool synthesis",
        &render_synth_lines(&safe(|| src.tool_history(50), Vec::new()), &cutoff, "tools"),
    ));
    parts.push(section(
        "🎯 Skill synthesis",
        &render_synth_lines(&safe(|| src.skill_history(50), Vec::new()), &cutoff, "skills"),
    ));
    parts.push(section(
        "🧠 Memory hygiene",
        &safe_string(|| src.memory_summary(6)),
    ));
    parts.push(section(
        "📦 Archive candidates",
        &render_archive_lines(&safe(
            || src.archive_candidates(6, today),
            Vec::new(),
        )),
    ));
    parts.push(section(
        "📈 Evals — latest score per version",
        &render_eval_lines(&safe(|| src.eval_scoreboard(5), Vec::new())),
    ));

    let joined = parts.join("\n\n");
    format!("{}\n", joined.trim_end())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(s: &str) -> NaiveDate {
        NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap()
    }

    struct EmptySource;
    impl DigestSource for EmptySource {
        fn pattern_summary(&self, _: u32) -> Result<String, String> {
            Err("no data".into())
        }
        fn ab_history(&self, _: u32) -> Result<Vec<AbDecision>, String> {
            Ok(vec![])
        }
        fn prompt_history(&self, _: u32) -> Result<Vec<PromptPatch>, String> {
            Ok(vec![])
        }
        fn tool_history(&self, _: u32) -> Result<Vec<SynthesisEvent>, String> {
            Ok(vec![])
        }
        fn skill_history(&self, _: u32) -> Result<Vec<SynthesisEvent>, String> {
            Ok(vec![])
        }
        fn memory_summary(&self, _: u32) -> Result<String, String> {
            Err("no data".into())
        }
        fn archive_candidates(&self, _: u32, _: NaiveDate) -> Result<Vec<ArchiveCandidate>, String> {
            Ok(vec![])
        }
        fn eval_scoreboard(&self, _: u32) -> Result<Vec<EvalScore>, String> {
            Ok(vec![])
        }
    }

    // ── ab lines ──────────────────────────────────────────────────────────

    #[test]
    fn ab_no_rows_message() {
        assert_eq!(render_ab_lines(&[], "2026-04-28"), "(no A/B decisions yet)");
    }

    #[test]
    fn ab_filters_by_cutoff() {
        let rows = vec![
            AbDecision {
                decided_at: "2026-04-20".into(),
                challenger: "x".into(),
                baseline: "y".into(),
                verdict: "promote".into(),
                delta: Some(0.05),
            },
            AbDecision {
                decided_at: "2026-05-01".into(),
                challenger: "x".into(),
                baseline: "y".into(),
                verdict: "keep".into(),
                delta: None,
            },
        ];
        let s = render_ab_lines(&rows, "2026-04-28");
        assert!(!s.contains("2026-04-20"));
        assert!(s.contains("2026-05-01"));
        assert!(s.contains("keep"));
    }

    #[test]
    fn ab_shows_delta_when_present() {
        let rows = vec![AbDecision {
            decided_at: "2026-05-01".into(),
            challenger: "ds-pro".into(),
            baseline: "ds-flash".into(),
            verdict: "promote".into(),
            delta: Some(-0.123),
        }];
        let s = render_ab_lines(&rows, "2026-04-25");
        assert!(s.contains("Δ=-0.123"));
    }

    // ── prompt lines ──────────────────────────────────────────────────────

    #[test]
    fn prompt_truncates_ts_to_16_chars() {
        let rows = vec![PromptPatch {
            ts: "2026-05-01T12:34:56".into(),
            key: "writer.peer_review".into(),
            verdict: "applied".into(),
            note: "+citation rule".into(),
        }];
        let s = render_prompt_lines(&rows, "2026-04-25");
        assert!(s.contains("2026-05-01T12:34"));
        assert!(!s.contains("12:34:56"));
    }

    // ── synth lines ───────────────────────────────────────────────────────

    #[test]
    fn synth_uses_kind_in_messages() {
        let s = render_synth_lines(&[], "x", "tools");
        assert!(s.contains("tools yet"));
        let s2 = render_synth_lines(&[], "x", "skills");
        assert!(s2.contains("skills yet"));
    }

    // ── archive lines ─────────────────────────────────────────────────────

    #[test]
    fn archive_renders_phase_and_idle() {
        let rows = vec![ArchiveCandidate {
            project: "Sulkalmakhi".into(),
            phase: "dormant".into(),
            idle_days: 187,
        }];
        let s = render_archive_lines(&rows);
        assert!(s.contains("Sulkalmakhi  phase=dormant  idle=187d"));
    }

    // ── eval lines ────────────────────────────────────────────────────────

    #[test]
    fn eval_truncates_run_at_to_10() {
        let rows = vec![EvalScore {
            run_at: "2026-05-01T12:00:00".into(),
            version: "2026-05-01".into(),
            avg_score: 0.873,
            n: 30,
        }];
        let s = render_eval_lines(&rows);
        assert!(s.contains("• 2026-05-01  version="));
        assert!(s.contains("score=0.873"));
        assert!(s.contains("n=30"));
    }

    // ── render_digest ─────────────────────────────────────────────────────

    #[test]
    fn render_digest_empty_source() {
        let s = render_digest(d("2026-05-05"), 7, &EmptySource);
        assert!(s.starts_with("📊 AIM weekly self-improvement digest"));
        assert!(s.contains("2026-04-28 → 2026-05-05"));
        assert!(s.contains("### 🔎 Pattern findings"));
        assert!(s.contains("(unavailable)"));
        assert!(s.contains("(no A/B decisions yet)"));
        assert!(s.contains("(no archive candidates)"));
        assert!(s.ends_with("\n"));
    }

    #[test]
    fn render_digest_window_size_drives_cutoff() {
        let s = render_digest(d("2026-05-05"), 14, &EmptySource);
        assert!(s.contains("2026-04-21 → 2026-05-05"));
    }

    // ── safe_string ───────────────────────────────────────────────────────

    #[test]
    fn safe_string_returns_unavail_on_error() {
        let s = safe_string(|| Err::<String, String>("boom".into()));
        assert_eq!(s, "(unavailable)");
    }

    #[test]
    fn safe_string_passes_through_ok() {
        let s = safe_string(|| Ok("hello".into()));
        assert_eq!(s, "hello");
    }
}
