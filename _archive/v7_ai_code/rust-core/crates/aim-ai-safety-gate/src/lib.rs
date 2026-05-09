//! aim-ai-safety-gate — SG1.
//!
//! Pre-flight gates before triggering an actual self-diagnostic run.
//! Cron schedules can fire even when conditions are wrong; this module
//! decides allow/deny + reason.
//!
//! Two gates:
//! - **Cooldown** — don't re-run if the latest ledger row is younger
//!   than `AI_DIAG_COOLDOWN_HOURS` (default 23 h).
//! - **Budget** — don't run when today's spent exceeds the daily cap.
//!   The Python predecessor reads `agents.cost_ledger`; that crate is
//!   not yet ported, so the Rust gate honours an env-supplied pair
//!   `AIM_DAILY_COST_USD` + `AIM_DAILY_BUDGET_USD`. Missing either ⇒
//!   gate stays open (do not block).
//!
//! Rust port of `AI/ai/safety_gate.py`.

use aim_ai_ledger::Ledger;
use chrono::DateTime;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SafetyError {
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Verdict {
    pub allowed: bool,
    pub reasons: Vec<String>,
    pub cooldown_ok: bool,
    pub budget_ok: bool,
    pub last_run_age_h: Option<f64>,
    pub daily_cost_usd: Option<f64>,
    pub daily_budget_usd: Option<f64>,
}

fn min_cooldown_hours() -> f64 {
    std::env::var("AI_DIAG_COOLDOWN_HOURS")
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(23.0)
}

fn daily_budget_state() -> (Option<f64>, Option<f64>) {
    let cost = std::env::var("AIM_DAILY_COST_USD")
        .ok()
        .and_then(|s| s.parse::<f64>().ok());
    let budget = std::env::var("AIM_DAILY_BUDGET_USD")
        .ok()
        .and_then(|s| s.parse::<f64>().ok());
    (cost, budget)
}

fn last_run_age_h(ledger: &Ledger) -> Result<Option<f64>, SafetyError> {
    let rows = ledger.recent(1)?;
    if rows.is_empty() {
        return Ok(None);
    }
    let ts = &rows[0].ts;
    // Try RFC3339 first; fall back to naive ISO without TZ.
    let parsed = DateTime::parse_from_rfc3339(ts)
        .ok()
        .map(|dt| dt.with_timezone(&chrono::Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(ts, "%Y-%m-%dT%H:%M:%S%.f")
                .or_else(|_| chrono::NaiveDateTime::parse_from_str(ts, "%Y-%m-%dT%H:%M:%S"))
                .ok()
                .map(|n| n.and_utc())
        });
    let Some(parsed) = parsed else { return Ok(None) };
    let now = chrono::Utc::now();
    let secs = (now - parsed).num_seconds();
    Ok(Some(secs as f64 / 3600.0))
}

/// Test-friendly config; `None` fields fall back to env / defaults.
#[derive(Debug, Default, Clone)]
pub struct GateConfig {
    pub cooldown_hours: Option<f64>,
    pub daily_cost_usd: Option<f64>,
    pub daily_budget_usd: Option<f64>,
}

pub fn can_run(ledger: &Ledger) -> Result<Verdict, SafetyError> {
    can_run_with(ledger, &GateConfig::default())
}

pub fn can_run_with(ledger: &Ledger, cfg: &GateConfig) -> Result<Verdict, SafetyError> {
    let mut reasons: Vec<String> = Vec::new();

    let age = last_run_age_h(ledger)?;
    let cool_min = cfg.cooldown_hours.unwrap_or_else(min_cooldown_hours);
    let cooldown_ok = match age {
        None => true,
        Some(a) if a >= cool_min => true,
        Some(a) => {
            reasons.push(format!(
                "cooldown not met: last run {a:.1}h ago (min {cool_min:.1}h)"
            ));
            false
        }
    };

    let (env_cost, env_budget) = daily_budget_state();
    let cost = cfg.daily_cost_usd.or(env_cost);
    let budget = cfg.daily_budget_usd.or(env_budget);
    let budget_ok = match (cost, budget) {
        (Some(c), Some(b)) if b > 0.0 => {
            if c < b {
                true
            } else {
                reasons.push(format!("daily budget exceeded: ${c:.2} ≥ ${b:.2}"));
                false
            }
        }
        _ => true, // unknown budget = don't block
    };

    Ok(Verdict {
        allowed: cooldown_ok && budget_ok,
        reasons,
        cooldown_ok,
        budget_ok,
        last_run_age_h: age,
        daily_cost_usd: cost,
        daily_budget_usd: budget,
    })
}

pub fn summary(verdict: &Verdict) -> String {
    let mut out: Vec<String> = Vec::new();
    out.push(
        if verdict.allowed {
            "🟢 safety gate: OK to run"
        } else {
            "🔴 safety gate: BLOCKED"
        }
        .into(),
    );
    let cool_min = min_cooldown_hours();
    match verdict.last_run_age_h {
        None => out.push("  cooldown: no prior run".into()),
        Some(age) => {
            let mark = if verdict.cooldown_ok { "✅" } else { "❌" };
            out.push(format!(
                "  {mark} cooldown: last run {age:.1}h ago (min {cool_min:.1}h)"
            ));
        }
    }
    match (verdict.daily_cost_usd, verdict.daily_budget_usd) {
        (Some(_), Some(b)) if b <= 0.0 => out.push("  budget: unlimited".into()),
        (Some(c), Some(b)) => {
            let mark = if verdict.budget_ok { "✅" } else { "❌" };
            out.push(format!("  {mark} budget: ${c:.2} / ${b:.2} today"));
        }
        _ => out.push("  budget: (unavailable)".into()),
    }
    if !verdict.reasons.is_empty() {
        out.push(String::new());
        out.push(" notes:".into());
        for r in &verdict.reasons {
            out.push(format!("  - {r}"));
        }
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh_ledger() -> (tempfile::TempDir, Ledger) {
        let d = tempdir().unwrap();
        let l = Ledger::open(d.path().join("ledger.db")).unwrap();
        (d, l)
    }

    #[test]
    fn empty_ledger_passes_cooldown() {
        let (_d, l) = fresh_ledger();
        let v = can_run_with(&l, &GateConfig::default()).unwrap();
        assert!(v.allowed);
        assert!(v.cooldown_ok);
        assert!(v.budget_ok);
        assert!(v.last_run_age_h.is_none());
    }

    #[test]
    fn recent_run_blocks_cooldown() {
        let (_d, l) = fresh_ledger();
        let ts = chrono::Utc::now().to_rfc3339();
        l.record("m", None, 0, 0, None, None, None, None, false, None, Some(&ts))
            .unwrap();
        let v = can_run_with(
            &l,
            &GateConfig {
                cooldown_hours: Some(10.0),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(!v.cooldown_ok);
        assert!(!v.allowed);
        assert!(v.reasons.iter().any(|r| r.contains("cooldown")));
    }

    #[test]
    fn budget_exceeded_blocks() {
        let (_d, l) = fresh_ledger();
        let v = can_run_with(
            &l,
            &GateConfig {
                daily_cost_usd: Some(5.0),
                daily_budget_usd: Some(3.0),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(!v.budget_ok);
        assert!(!v.allowed);
    }

    #[test]
    fn budget_zero_treated_as_unlimited() {
        let (_d, l) = fresh_ledger();
        let v = can_run_with(
            &l,
            &GateConfig {
                daily_cost_usd: Some(100.0),
                daily_budget_usd: Some(0.0),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(v.budget_ok);
    }

    #[test]
    fn summary_contains_marker() {
        let v = Verdict {
            allowed: true,
            reasons: vec![],
            cooldown_ok: true,
            budget_ok: true,
            last_run_age_h: None,
            daily_cost_usd: None,
            daily_budget_usd: None,
        };
        let s = summary(&v);
        assert!(s.contains("🟢"));
    }

    #[test]
    fn summary_blocked_format() {
        let v = Verdict {
            allowed: false,
            reasons: vec!["cooldown not met".into()],
            cooldown_ok: false,
            budget_ok: true,
            last_run_age_h: Some(2.0),
            daily_cost_usd: None,
            daily_budget_usd: None,
        };
        let s = summary(&v);
        assert!(s.contains("🔴"));
        assert!(s.contains("notes:"));
    }
}
