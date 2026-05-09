//! aim-ai-compliance-promoter CLI — Phase 9 Tier 2 #1 (2026-05-07).
//!
//! Recommend tighten/loosen of the diagnostic `min_compliance`
//! threshold based on rolling streaks in the ledger. Replaces
//! `AI/ai/compliance_promoter.py`.
//!
//! Subcommands:
//!   recommend          # JSON Recommendation
//!   summary            # plain-text summary
//!
//! ENV: AI_DIAG_MIN_COMPLIANCE (current threshold; default 0.5),
//!      AI_DIAGNOSTIC_DB (ledger DB path).

use std::process::ExitCode;

use aim_ai_compliance_promoter::{recommend, summary, Direction};
use aim_ai_ledger::Ledger;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-compliance-promoter: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("recommend");
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "recommend" => {
            let ledger = Ledger::open_default()?;
            let r = recommend(&ledger)?;
            // Direction → string for shim parity with Python ("tighten"|"loosen"|"hold").
            let v = serde_json::json!({
                "current_threshold": r.current_threshold,
                "proposed_threshold": r.proposed_threshold,
                "direction": match r.direction {
                    Direction::Tighten => "tighten",
                    Direction::Loosen => "loosen",
                    Direction::Hold => "hold",
                },
                "streak_high": r.streak_high,
                "streak_low": r.streak_low,
                "avg_recent": r.avg_recent,
                "n_recent": r.n_recent,
                "reason": r.reason,
            });
            println!("{}", serde_json::to_string(&v)?);
            Ok(())
        }
        "summary" => {
            let ledger = Ledger::open_default()?;
            let r = recommend(&ledger)?;
            println!("{}", summary(&r));
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn print_usage() {
    println!(
        "aim-ai-compliance-promoter — recommend min_compliance threshold tuning\n\n\
USAGE:\n\
  aim-ai-compliance-promoter recommend     # JSON Recommendation\n\
  aim-ai-compliance-promoter summary       # plain-text\n\n\
ENV: AI_DIAG_MIN_COMPLIANCE (default 0.5), AI_DIAGNOSTIC_DB"
    );
}
