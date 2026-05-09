//! aim-ai-morning-brief — MB1.
//!
//! Single-shot wake-up briefing for AIM/AI subproject state. Pulls
//! signal from regression detector, ledger trend, and the case
//! archiver, surfaces only the lines worth reading first thing.
//!
//! Wiring/doctor and deadline-scanner sections in the Python
//! predecessor depend on `agents/doctor.py` and
//! `agents/deadline_scanner.py` — not yet ported. Those sections
//! render as `(pending Rust port)` placeholders to keep the layout
//! stable.
//!
//! Rust port of `AI/ai/morning_brief.py`.

use aim_ai_case_archiver::ArchiveOpts;
use aim_ai_ledger::Ledger;
use aim_ai_regression::detect as detect_regression;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Brief {
    pub headline: String,
    pub overall_bad: bool,
    pub deadlines: String,
    pub wiring: String,
    pub regression: String,
    pub ledger: String,
    pub archive: String,
}

pub fn render_struct(ledger: &Ledger) -> Brief {
    let (regr_text, regr_bad) = section_regression(ledger);
    let ledger_text = section_ledger(ledger);
    let archive_text = section_archive(ledger);
    // Wiring probe is still on the to-do list (agents/doctor.py).
    let wiring_text = "(wiring probe pending Rust port of agents/doctor)".to_string();
    let deadlines_text = section_deadlines();

    let overall_bad = regr_bad;
    let headline = if overall_bad {
        "⚠ AIM/AI needs attention this morning".to_string()
    } else {
        "🟢 AIM/AI is healthy this morning".to_string()
    };

    Brief {
        headline,
        overall_bad,
        deadlines: deadlines_text,
        wiring: wiring_text,
        regression: regr_text,
        ledger: ledger_text,
        archive: archive_text,
    }
}

pub fn render(ledger: &Ledger) -> String {
    let b = render_struct(ledger);
    let parts = vec![
        format!("# {}", b.headline),
        String::new(),
        "## High-criticality deadlines".into(),
        b.deadlines,
        String::new(),
        "## Wiring".into(),
        b.wiring,
        String::new(),
        "## Regression check".into(),
        b.regression,
        String::new(),
        "## Diagnostic trend".into(),
        b.ledger,
        String::new(),
        "## Case archive".into(),
        b.archive,
    ];
    parts.join("\n")
}

fn section_regression(ledger: &Ledger) -> (String, bool) {
    let r = match detect_regression(ledger) {
        Ok(v) => v,
        Err(e) => return (format!("⚠ regression check unavailable: {e}"), false),
    };
    if !r.have_baseline {
        return (
            "(no baseline yet — first 2 diagnostic runs needed)".to_string(),
            false,
        );
    }
    if r.regressed() {
        let mut sorted: Vec<&String> = r.new_findings.iter().collect();
        sorted.sort();
        let preview: Vec<String> =
            sorted.iter().take(3).map(|s| s.to_string()).collect();
        let joined = preview.join(", ");
        let more = if r.new_findings.len() > 3 {
            format!(" +{} more", r.new_findings.len() - 3)
        } else {
            String::new()
        };
        return (
            format!(
                "❌ REGRESSED — {} new finding(s): {}{}",
                r.new_findings.len(),
                joined,
                more
            ),
            true,
        );
    }
    if r.improved() {
        return (
            format!("✅ IMPROVED — {} finding(s) fixed", r.fixed_findings.len()),
            false,
        );
    }
    ("= stable since last run".to_string(), false)
}

fn section_ledger(ledger: &Ledger) -> String {
    let t = match ledger.trend() {
        Ok(v) => v,
        Err(e) => return format!("(ledger trend unavailable: {e})"),
    };
    if t.n_runs == 0 {
        return "(no diagnostic runs in ledger)".into();
    }
    let mut s = format!(
        "{} runs · avg compliance {:.0}% · avg crit {:.1}",
        t.n_runs,
        t.avg_compliance * 100.0,
        t.avg_crit
    );
    if t.retry_share > 0.0 {
        s.push_str(&format!(
            "\n  retry fired in {:.0}% of runs",
            t.retry_share * 100.0
        ));
    }
    s
}

fn section_archive(ledger: &Ledger) -> String {
    let cands = match aim_ai_case_archiver::candidates(ledger, &ArchiveOpts::default()) {
        Ok(v) => v,
        Err(e) => return format!("(archive scan failed: {e})"),
    };
    if cands.is_empty() {
        return "(no resolved cases to archive)".into();
    }
    format!(
        "{} regression case(s) ready to archive — run `aim ai archive-cases` to retire",
        cands.len()
    )
}

fn section_deadlines() -> String {
    let today = chrono::Local::now().date_naive();
    let opts = aim_deadline_scanner::ScanOpts::default();
    let deadlines = aim_deadline_scanner::scan_memory(today, &opts);
    if deadlines.is_empty() {
        return "(no deadlines on the radar)".into();
    }
    let buckets = aim_deadline_scanner::by_horizon(&deadlines, today);
    let n_high_pending = buckets.today.len() + buckets.this_week.len()
        + buckets
            .this_month
            .iter()
            .filter(|d| matches!(d.criticality, aim_deadline_scanner::Criticality::High))
            .count();
    if n_high_pending == 0 {
        return "(no high-criticality pending deadlines)".into();
    }
    let mut out = vec![format!("{} high-criticality pending:", n_high_pending)];
    let mut shown: Vec<&aim_deadline_scanner::Deadline> =
        buckets.today.iter().chain(buckets.this_week.iter()).collect();
    shown.sort_by_key(|d| d.when);
    for d in shown.iter().take(5) {
        let delta = d.days_from(today);
        let when = if delta == 0 {
            "TODAY".to_string()
        } else {
            format!("+{}d", delta)
        };
        let label: String = d.label.replace('\n', " ").chars().take(80).collect();
        out.push(format!("  • {:>5}  {}  {}", when, d.when, label));
    }
    if shown.len() > 5 {
        out.push(format!("  (+{} more)", shown.len() - 5));
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_ai_ledger::Ledger;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger) {
        let d = tempdir().unwrap();
        let l = Ledger::open(d.path().join("ledger.db")).unwrap();
        (d, l)
    }

    #[test]
    fn empty_ledger_healthy() {
        let (_d, l) = fresh();
        let b = render_struct(&l);
        assert!(!b.overall_bad);
        assert!(b.headline.contains("🟢"));
        assert!(b.regression.contains("no baseline"));
    }

    #[test]
    fn regression_flips_overall_bad() {
        let d = tempdir().unwrap();
        let p = d.path().join("ledger.db");
        let l = Ledger::open(&p).unwrap();
        // Reports with new finding
        let r1 = d.path().join("r1.md");
        let r2 = d.path().join("r2.md");
        std::fs::write(&r1, "clean").unwrap();
        std::fs::write(&r2, "issue at agents/foo.py:42").unwrap();
        l.record(
            "m",
            Some("A"),
            0,
            0,
            Some(0),
            None,
            None,
            None,
            false,
            Some(r1.to_str().unwrap()),
            Some("2026-05-04T00:00:00Z"),
        )
        .unwrap();
        l.record(
            "m",
            Some("A"),
            0,
            0,
            Some(0),
            None,
            None,
            None,
            false,
            Some(r2.to_str().unwrap()),
            Some("2026-05-04T01:00:00Z"),
        )
        .unwrap();
        let b = render_struct(&l);
        assert!(b.overall_bad);
        assert!(b.headline.contains("⚠"));
        assert!(b.regression.contains("REGRESSED"));
    }

    #[test]
    fn render_emits_full_layout() {
        let (_d, l) = fresh();
        let s = render(&l);
        assert!(s.contains("# "));
        assert!(s.contains("## Wiring"));
        assert!(s.contains("## Regression check"));
        assert!(s.contains("## Diagnostic trend"));
        assert!(s.contains("## Case archive"));
        assert!(s.contains("## High-criticality deadlines"));
    }

    #[test]
    fn section_ledger_with_runs() {
        let (_d, l) = fresh();
        l.record("m", Some("A"), 10, 9, Some(0), None, None, None, false, None,
                 Some("2026-05-04T00:00:00Z")).unwrap();
        let b = render_struct(&l);
        assert!(b.ledger.contains("90%"));
    }
}
