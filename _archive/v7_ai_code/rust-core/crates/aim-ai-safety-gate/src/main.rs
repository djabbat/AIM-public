//! aim-ai-safety-gate CLI — Phase 9 Tier 2 #2 (2026-05-07).
//!
//! Pre-flight gates for self-diagnostic runs: cooldown + daily budget.
//! Replaces `AI/ai/safety_gate.py`.
//!
//! Subcommands:
//!   can-run     # JSON Verdict
//!   summary     # plain-text summary
//!
//! ENV: AI_DIAG_COOLDOWN_HOURS (default 23), AI_DIAGNOSTIC_DB,
//!      AIM_DAILY_COST_USD + AIM_DAILY_BUDGET_USD (optional).

use std::process::ExitCode;

use aim_ai_ledger::Ledger;
use aim_ai_safety_gate::{can_run, summary};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-safety-gate: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("can-run");
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "can-run" => {
            let ledger = Ledger::open_default()?;
            let v = can_run(&ledger)?;
            println!("{}", serde_json::to_string(&v)?);
            Ok(())
        }
        "summary" => {
            let ledger = Ledger::open_default()?;
            let v = can_run(&ledger)?;
            println!("{}", summary(&v));
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn print_usage() {
    println!(
        "aim-ai-safety-gate — pre-flight gates for self-diagnostic\n\n\
USAGE:\n\
  aim-ai-safety-gate can-run    # JSON Verdict\n\
  aim-ai-safety-gate summary    # plain-text\n\n\
ENV: AI_DIAG_COOLDOWN_HOURS (default 23), AI_DIAGNOSTIC_DB,\n\
     AIM_DAILY_COST_USD + AIM_DAILY_BUDGET_USD"
    );
}
