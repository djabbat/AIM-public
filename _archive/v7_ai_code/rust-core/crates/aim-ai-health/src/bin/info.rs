//! `aim-ai-health-info` — print one-line cron summary OR a full JSON
//! report.
//!
//!     aim-ai-health-info             → AIM/AI: 80/100 B  wir=30 ...
//!     aim-ai-health-info --json      → JSON envelope: {score, trend, regression}

use aim_ai_health::{compute, info_line};
use aim_ai_ledger::Ledger;
use aim_ai_regression::detect as detect_regression;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let json_mode = std::env::args().any(|a| a == "--json");
    let ledger = Ledger::open_default()?;
    let score = compute(&ledger)?;
    if json_mode {
        let trend = ledger.trend()?;
        let regression = detect_regression(&ledger)?;
        let envelope = serde_json::json!({
            "score": score,
            "trend": trend,
            "regression": {
                "have_baseline": regression.have_baseline,
                "regressed": regression.regressed(),
                "improved": regression.improved(),
                "new_findings_count": regression.new_findings.len(),
                "fixed_findings_count": regression.fixed_findings.len(),
                "prev_grade": regression.prev_grade,
                "curr_grade": regression.curr_grade,
                "prev_crit": regression.prev_crit,
                "curr_crit": regression.curr_crit,
            }
        });
        println!("{}", serde_json::to_string_pretty(&envelope)?);
    } else {
        println!("{}", info_line(&score));
    }
    Ok(())
}
