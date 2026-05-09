//! aim-ai-compliance-promoter — CP1.
//!
//! Recommend tightening / loosening `min_compliance` based on rolling
//! streaks at the head of the ledger. Recommendation only — no env var
//! or config is mutated. The dashboard surfaces the suggestion; the
//! human decides.
//!
//! Rust port of `AI/ai/compliance_promoter.py`.

use aim_ai_ledger::Ledger;
use serde::{Deserialize, Serialize};
use thiserror::Error;

const HIGH: f64 = 0.85;
const LOW: f64 = 0.40;
const MIN_STREAK: u32 = 3;
const WINDOW: usize = 10;

#[derive(Debug, Error)]
pub enum PromoterError {
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
}

/// "tighten" | "loosen" | "hold"
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Tighten,
    Loosen,
    Hold,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recommendation {
    pub current_threshold: f64,
    pub proposed_threshold: Option<f64>,
    pub direction: Direction,
    pub streak_high: u32,
    pub streak_low: u32,
    pub avg_recent: f64,
    pub n_recent: u32,
    pub reason: String,
}

fn current_threshold() -> f64 {
    std::env::var("AI_DIAG_MIN_COMPLIANCE")
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.5)
}

pub fn recommend(ledger: &Ledger) -> Result<Recommendation, PromoterError> {
    recommend_with(ledger, None)
}

pub fn recommend_with(
    ledger: &Ledger,
    threshold_override: Option<f64>,
) -> Result<Recommendation, PromoterError> {
    let cur = threshold_override.unwrap_or_else(current_threshold);
    let rows = ledger.recent(WINDOW)?;

    if rows.is_empty() {
        return Ok(Recommendation {
            current_threshold: cur,
            proposed_threshold: None,
            direction: Direction::Hold,
            streak_high: 0,
            streak_low: 0,
            avg_recent: 0.0,
            n_recent: 0,
            reason: "no diagnostic runs yet — keep default".into(),
        });
    }

    let avg_recent = rows.iter().map(|r| r.compliance).sum::<f64>() / rows.len() as f64;

    // Trailing streaks: walk most-recent backwards until a row breaks.
    let mut streak_high: u32 = 0;
    let mut streak_low: u32 = 0;
    for r in rows.iter().rev() {
        if r.compliance >= HIGH {
            streak_high += 1;
            if streak_low > 0 {
                break;
            }
        } else if r.compliance < LOW {
            streak_low += 1;
            if streak_high > 0 {
                break;
            }
        } else {
            break;
        }
    }

    if streak_high >= MIN_STREAK && cur < 0.8 {
        let proposed = (cur + 0.1).min(0.8);
        return Ok(Recommendation {
            current_threshold: cur,
            proposed_threshold: Some(proposed),
            direction: Direction::Tighten,
            streak_high,
            streak_low: 0,
            avg_recent,
            n_recent: rows.len() as u32,
            reason: format!(
                "{streak_high} consecutive runs ≥{:.0}% compliance; raise threshold to catch borderline runs earlier",
                HIGH * 100.0
            ),
        });
    }
    if streak_low >= MIN_STREAK && cur > 0.3 {
        let proposed = (cur - 0.1).max(0.3);
        return Ok(Recommendation {
            current_threshold: cur,
            proposed_threshold: Some(proposed),
            direction: Direction::Loosen,
            streak_high: 0,
            streak_low,
            avg_recent,
            n_recent: rows.len() as u32,
            reason: format!(
                "{streak_low} consecutive runs <{:.0}% compliance; threshold may be unrealistic — lower to reduce wasted retries",
                LOW * 100.0
            ),
        });
    }
    Ok(Recommendation {
        current_threshold: cur,
        proposed_threshold: None,
        direction: Direction::Hold,
        streak_high,
        streak_low,
        avg_recent,
        n_recent: rows.len() as u32,
        reason: "metric in normal band — no change recommended".into(),
    })
}

pub fn summary(r: &Recommendation) -> String {
    let mut parts = vec![
        format!("⚖ Compliance threshold — current {:.0}%", r.current_threshold * 100.0),
        format!(
            "  recent avg: {:.0}%  (n={})",
            r.avg_recent * 100.0,
            r.n_recent
        ),
    ];
    match r.direction {
        Direction::Hold => parts.push(format!("  → hold  ({})", r.reason)),
        Direction::Tighten => parts.push(format!(
            "  ↑ tighten to {:.0}%: {}",
            r.proposed_threshold.unwrap_or(0.0) * 100.0,
            r.reason
        )),
        Direction::Loosen => parts.push(format!(
            "  ↓ loosen to {:.0}%: {}",
            r.proposed_threshold.unwrap_or(0.0) * 100.0,
            r.reason
        )),
    }
    parts.join("\n")
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

    fn add_run(l: &Ledger, ts: &str, compliance: f64) {
        // Use n_refs=10, vary n_with_line so compliance = n_with_line/10
        let n_with_line = (compliance * 10.0).round() as i64;
        l.record(
            "m",
            None,
            10,
            n_with_line,
            None,
            None,
            None,
            None,
            false,
            None,
            Some(ts),
        )
        .unwrap();
    }

    #[test]
    fn empty_ledger_holds() {
        let (_d, l) = fresh();
        let r = recommend_with(&l, Some(0.5)).unwrap();
        assert_eq!(r.direction, Direction::Hold);
        assert_eq!(r.proposed_threshold, None);
        assert_eq!(r.n_recent, 0);
    }

    #[test]
    fn three_high_streak_tightens() {
        let (_d, l) = fresh();
        for i in 0..3 {
            add_run(&l, &format!("2026-05-04T0{}:00:00Z", i + 1), 0.9);
        }
        let r = recommend_with(&l, Some(0.5)).unwrap();
        assert_eq!(r.direction, Direction::Tighten);
        assert_eq!(r.proposed_threshold, Some(0.6));
        assert_eq!(r.streak_high, 3);
    }

    #[test]
    fn three_low_streak_loosens() {
        let (_d, l) = fresh();
        for i in 0..3 {
            add_run(&l, &format!("2026-05-04T0{}:00:00Z", i + 1), 0.3);
        }
        let r = recommend_with(&l, Some(0.5)).unwrap();
        assert_eq!(r.direction, Direction::Loosen);
        assert_eq!(r.proposed_threshold, Some(0.4));
        assert_eq!(r.streak_low, 3);
    }

    #[test]
    fn tighten_capped_at_eighty() {
        let (_d, l) = fresh();
        for i in 0..3 {
            add_run(&l, &format!("2026-05-04T0{}:00:00Z", i + 1), 0.9);
        }
        let r = recommend_with(&l, Some(0.79)).unwrap();
        // proposed should be 0.8 (clamped from 0.89)
        assert_eq!(r.direction, Direction::Tighten);
        assert!((r.proposed_threshold.unwrap() - 0.8).abs() < 1e-9);
    }

    #[test]
    fn high_streak_blocked_when_already_at_ceiling() {
        let (_d, l) = fresh();
        for i in 0..3 {
            add_run(&l, &format!("2026-05-04T0{}:00:00Z", i + 1), 0.9);
        }
        let r = recommend_with(&l, Some(0.8)).unwrap();
        assert_eq!(r.direction, Direction::Hold);
    }

    #[test]
    fn low_streak_blocked_when_already_at_floor() {
        let (_d, l) = fresh();
        for i in 0..3 {
            add_run(&l, &format!("2026-05-04T0{}:00:00Z", i + 1), 0.3);
        }
        let r = recommend_with(&l, Some(0.3)).unwrap();
        assert_eq!(r.direction, Direction::Hold);
    }

    #[test]
    fn middling_streaks_hold() {
        let (_d, l) = fresh();
        for i in 0..5 {
            add_run(&l, &format!("2026-05-04T0{}:00:00Z", i + 1), 0.6);
        }
        let r = recommend_with(&l, Some(0.5)).unwrap();
        assert_eq!(r.direction, Direction::Hold);
    }

    #[test]
    fn streak_breaks_on_middle_value() {
        let (_d, l) = fresh();
        // Older: 0.9, 0.9, then 0.6 (breaks the high streak), then high again
        add_run(&l, "2026-05-04T01:00:00Z", 0.9);
        add_run(&l, "2026-05-04T02:00:00Z", 0.9);
        add_run(&l, "2026-05-04T03:00:00Z", 0.6);
        add_run(&l, "2026-05-04T04:00:00Z", 0.9);
        add_run(&l, "2026-05-04T05:00:00Z", 0.9);
        let r = recommend_with(&l, Some(0.5)).unwrap();
        // Trailing streak from end is 2 high, then 0.6 breaks → streak_high=2 → not enough
        assert_eq!(r.streak_high, 2);
        assert_eq!(r.direction, Direction::Hold);
    }
}
