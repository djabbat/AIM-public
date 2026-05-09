//! aim-ai-dashboard — DB1.
//!
//! One-button consolidated view of AIM/AI subproject state. Each
//! section is built best-effort — if one fails (missing data, missing
//! crate not yet ported), the dashboard still emits with the section
//! body marked unavailable.
//!
//! Rust port of `AI/ai/dashboard.py`. Sections currently wired:
//!  - score (aim-ai-health)
//!  - ledger (aim-ai-ledger)
//!  - regression (aim-ai-regression)
//!  - prompt drift (aim-ai-prompt-versions)
//!  - cases (aim-ai-cases)
//!
//! Sections still TODO (Python predecessors not yet ported):
//!  - safety_gate, suppressions, prompt_impact, compliance,
//!    distillation, gaps, reflexion. These render as
//!    `_section unavailable: not yet ported_` placeholders to keep
//!    the layout stable.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Section {
    pub name: String,
    pub title: String,
    pub body: String,
    pub ok: bool,
    pub error: Option<String>,
}

pub fn sections() -> Vec<Section> {
    vec![
        score_section(),
        explainer_section(),
        wiring_section(),
        safety_section(),
        ledger_section(),
        regression_section(),
        suppressions_section(),
        prompt_section(),
        prompt_impact_section(),
        compliance_section(),
        distillation_section(),
        gaps_section(),
        reflexion_section(),
        cases_section(),
    ]
}

fn explainer_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let e = aim_ai_explainer::explain(&ledger)?;
        Ok(aim_ai_explainer::summary(&e))
    })();
    section_from("explainer", "Score explainer", s)
}

fn wiring_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
        let probes = aim_ai_doctor::diagnose(&cwd);
        let crit: Vec<&aim_ai_doctor::Probe> = probes
            .iter()
            .filter(|p| !p.ok && p.severity == aim_ai_doctor::Severity::Crit)
            .collect();
        let warn: Vec<&aim_ai_doctor::Probe> = probes
            .iter()
            .filter(|p| !p.ok && p.severity == aim_ai_doctor::Severity::Warn)
            .collect();
        if crit.is_empty() && warn.is_empty() {
            return Ok("✅ wiring clean — all probes ok".into());
        }
        let mut out: Vec<String> = Vec::new();
        if !crit.is_empty() {
            out.push(format!("❌ {} critical probe(s):", crit.len()));
            for p in crit {
                let head = p.detail.lines().next().unwrap_or("");
                out.push(format!("   • {}: {}", p.name, head));
            }
        }
        if !warn.is_empty() {
            out.push(format!("⚠ {} warning(s):", warn.len()));
            for p in warn {
                let head = p.detail.lines().next().unwrap_or("");
                out.push(format!("   • {}: {}", p.name, head));
            }
        }
        Ok(out.join("\n"))
    })();
    section_from("wiring", "Wiring (doctor)", s)
}

fn safety_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let v = aim_ai_safety_gate::can_run(&ledger)?;
        Ok(aim_ai_safety_gate::summary(&v))
    })();
    section_from("safety", "Safety gate (cooldown + budget)", s)
}

fn suppressions_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let store = aim_ai_suppressions::SuppressionStore::open_default()?;
        let active = store.active()?;
        if active.is_empty() {
            return Ok("(no finding suppressions)".into());
        }
        Ok(format!(
            "🔇 Finding suppressions — {} active",
            active.len()
        ))
    })();
    section_from("suppressions", "Finding suppressions", s)
}

fn prompt_impact_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let store = aim_ai_prompt_versions::PromptStore::open_default()?;
        let rows = aim_ai_prompt_impact::impact_per_revision(&ledger, &store)?;
        Ok(aim_ai_prompt_impact::summary(&rows))
    })();
    section_from("prompt_impact", "Prompt-impact analysis", s)
}

fn compliance_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let r = aim_ai_compliance_promoter::recommend(&ledger)?;
        Ok(aim_ai_compliance_promoter::summary(&r))
    })();
    section_from("compliance", "Compliance threshold tuner", s)
}

fn distillation_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let store = aim_ai_distillation::DistillStore::open_default()?;
        let m = store.compare_tiers()?;
        if m.is_empty() {
            return Ok("(no distillation runs yet)".into());
        }
        let tiers: std::collections::BTreeSet<&String> =
            m.values().flat_map(|row| row.keys()).collect();
        Ok(format!(
            "🧪 Distillation matrix — {} cases × {} tiers",
            m.len(),
            tiers.len()
        ))
    })();
    section_from("distillation", "Per-tier distillation matrix", s)
}

fn gaps_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let surr = aim_ai_gap_detector::surrenders();
        if surr.is_empty() {
            return Ok("(no capability gaps detected)".into());
        }
        let g = aim_ai_gap_detector::gaps(&surr, 0.20);
        Ok(format!(
            "🕳 Capability gaps — {} clusters / {} surrenders",
            g.len(),
            surr.len()
        ))
    })();
    section_from("gaps", "Capability gaps", s)
}

fn reflexion_section() -> Section {
    // Cannot read feedback memory without depending on Claude memory layout.
    // Emit a placeholder note that the section is wired but needs source.
    Section {
        name: "reflexion".into(),
        title: "Reflexion themes".into(),
        body: "(reflexion source not configured — pass notes to aim_ai_reflexion::cluster)".into(),
        ok: true,
        error: None,
    }
}

fn score_section() -> Section {
    use aim_ai_health::{compute, info_line};
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let score = compute(&ledger)?;
        Ok(format!(
            "{}\n  notes: {}",
            info_line(&score),
            if score.notes.is_empty() {
                "—".to_string()
            } else {
                score.notes.join("; ")
            }
        ))
    })();
    section_from("score", "Health score", s)
}

fn ledger_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let t = ledger.trend()?;
        if t.n_runs == 0 {
            return Ok("(no diagnostic runs recorded)".into());
        }
        Ok(format!(
            "📈 Diagnostic ledger — {} runs (first {} → last {})\n  avg compliance: {:.0}%\n  avg crit: {:.1}\n  retry share: {:.0}%",
            t.n_runs,
            t.first_ts.as_deref().unwrap_or("?").chars().take(10).collect::<String>(),
            t.last_ts.as_deref().unwrap_or("?").chars().take(10).collect::<String>(),
            t.avg_compliance * 100.0,
            t.avg_crit,
            t.retry_share * 100.0,
        ))
    })();
    section_from("ledger", "Diagnostic ledger trend", s)
}

fn regression_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let ledger = aim_ai_ledger::Ledger::open_default()?;
        let r = aim_ai_regression::detect(&ledger)?;
        if !r.have_baseline {
            return Ok("(no baseline — need ≥2 ledger rows)".into());
        }
        let pg = r.prev_grade.clone().unwrap_or_else(|| "?".into());
        let cg = r.curr_grade.clone().unwrap_or_else(|| "?".into());
        let pc = r.prev_crit.map(|n| n.to_string()).unwrap_or_else(|| "?".into());
        let cc = r.curr_crit.map(|n| n.to_string()).unwrap_or_else(|| "?".into());
        let verdict = if r.regressed() {
            "⚠ REGRESSED"
        } else if r.improved() {
            "✅ IMPROVED"
        } else {
            "= stable"
        };
        Ok(format!(
            "🔍 Regression check\n  grade: {pg} → {cg}\n  crit:  {pc} → {cc}\n  new findings:   {}\n  fixed findings: {}\n  {}",
            r.new_findings.len(),
            r.fixed_findings.len(),
            verdict
        ))
    })();
    section_from("regression", "Regression check", s)
}

fn prompt_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let store = aim_ai_prompt_versions::PromptStore::open_default()?;
        let drift = store.drift_since_last(None)?;
        if !drift.prompt_present {
            return Ok("(prompt file missing)".into());
        }
        if !drift.have_baseline {
            return Ok(format!(
                "📝 Prompt fingerprinted for the first time:\n  sha {}…",
                drift
                    .current_sha
                    .as_deref()
                    .unwrap_or("?")
                    .chars()
                    .take(12)
                    .collect::<String>()
            ));
        }
        if !drift.changed {
            return Ok("📝 Prompt unchanged since last record".into());
        }
        Ok(format!(
            "📝 Prompt drift since {}\n  sha {} → {}\n  bytes Δ {:+}  lines Δ {:+}",
            drift.last_ts.as_deref().unwrap_or("?"),
            drift.last_sha.as_deref().unwrap_or("?").chars().take(8).collect::<String>(),
            drift.current_sha.as_deref().unwrap_or("?").chars().take(8).collect::<String>(),
            drift.delta_bytes,
            drift.delta_lines,
        ))
    })();
    section_from("prompt", "Diagnostic prompt drift", s)
}

fn cases_section() -> Section {
    let s = (|| -> Result<String, Box<dyn std::error::Error>> {
        let r = aim_ai_cases::validate_dir(None);
        if r.n_cases == 0 {
            return Ok("(no eval cases found)".into());
        }
        Ok(format!(
            "📋 Case validator — {} cases ({} ok / {} failed)",
            r.n_cases, r.n_ok, r.n_failed
        ))
    })();
    section_from("cases", "Eval case validator", s)
}

fn section_from(
    name: &str,
    title: &str,
    result: Result<String, Box<dyn std::error::Error>>,
) -> Section {
    match result {
        Ok(body) => Section {
            name: name.into(),
            title: title.into(),
            body,
            ok: true,
            error: None,
        },
        Err(e) => Section {
            name: name.into(),
            title: title.into(),
            body: "(unavailable)".into(),
            ok: false,
            error: Some(format!("{}", e)),
        },
    }
}

pub fn render() -> String {
    let mut out: Vec<String> = vec!["# AIM/AI Dashboard\n".into()];
    for s in sections() {
        out.push(format!("## {}", s.title));
        out.push(String::new());
        out.push(s.body.clone());
        if let Some(e) = s.error {
            out.push(format!("_section error: {}_", e));
        }
        out.push(String::new());
    }
    let mut joined = out.join("\n");
    while joined.ends_with('\n') {
        joined.pop();
    }
    joined.push('\n');
    joined
}

pub fn render_json() -> serde_json::Value {
    let payload: Vec<_> = sections()
        .into_iter()
        .map(|s| {
            serde_json::json!({
                "name": s.name,
                "title": s.title,
                "body": s.body,
                "ok": s.ok,
                "error": s.error,
            })
        })
        .collect();
    serde_json::json!({ "sections": payload })
}

pub fn render_compact() -> String {
    let mut out: Vec<String> = vec!["📡 AIM/AI compact".into()];
    for s in sections() {
        let head = s
            .body
            .lines()
            .find(|l| !l.trim().is_empty() && !l.trim().starts_with('#'))
            .map(|l| l.trim().to_string())
            .unwrap_or_else(|| "(empty)".into());
        let head = strip_emoji_prefix(&head);
        let mark = if s.ok { "✓" } else { "✗" };
        out.push(format!("{} {}: {}", mark, s.title, head));
    }
    out.join("\n")
}

fn strip_emoji_prefix(s: &str) -> String {
    let trimmed: String = s
        .chars()
        .skip_while(|c| !c.is_alphanumeric())
        .collect();
    trimmed.chars().take(120).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn render_emits_all_sections() {
        let txt = render();
        assert!(txt.contains("# AIM/AI Dashboard"));
        assert!(txt.contains("## Health score"));
        assert!(txt.contains("## Diagnostic ledger trend"));
        assert!(txt.contains("## Regression check"));
        assert!(txt.contains("## Diagnostic prompt drift"));
        assert!(txt.contains("## Eval case validator"));
        assert!(txt.contains("## Reflexion themes"));
    }

    #[test]
    fn render_json_envelope() {
        let v = render_json();
        let arr = v["sections"].as_array().unwrap();
        assert!(arr.len() >= 5);
        for s in arr {
            assert!(s["name"].is_string());
            assert!(s["title"].is_string());
            assert!(s["body"].is_string());
        }
    }

    #[test]
    fn render_compact_one_line_per_section() {
        let c = render_compact();
        assert!(c.starts_with("📡 AIM/AI compact"));
        let lines: Vec<&str> = c.lines().collect();
        // Header + one per section
        assert!(lines.len() >= 6);
    }

    #[test]
    fn reflexion_section_present() {
        let secs = sections();
        let r = secs.iter().find(|s| s.name == "reflexion").unwrap();
        // No failure mode yet — wired but needs an external notes source.
        assert!(r.body.contains("reflexion source"));
    }
}
