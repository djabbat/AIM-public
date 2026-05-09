//! aim-ai-regression-alert CLI — Phase 9 Tier 2 #6 (2026-05-07).
//!
//! Format a detected regression as a notification payload. Side-effect
//! free: actual delivery (Telegram / email) stays in the Python
//! `agents.notify` mux until that gets ported.
//!
//! Subcommands:
//!   check                         # detect + build, JSON Alert (or "null")
//!   build                         # read Regression JSON from stdin → Alert JSON

use std::io::Read;
use std::process::ExitCode;

use aim_ai_ledger::Ledger;
use aim_ai_regression::Regression;
use aim_ai_regression_alert::{build, check};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-regression-alert: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("check");
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "check" => {
            let ledger = Ledger::open_default()?;
            match check(&ledger)? {
                Some(a) => println!("{}", serde_json::to_string(&a)?),
                None => println!("null"),
            }
            Ok(())
        }
        "build" => {
            let mut s = String::new();
            std::io::stdin().read_to_string(&mut s)?;
            let r: Regression = serde_json::from_str(&s)?;
            match build(&r) {
                Some(a) => println!("{}", serde_json::to_string(&a)?),
                None => println!("null"),
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn print_usage() {
    println!(
        "aim-ai-regression-alert — format detected regression as alert payload\n\n\
USAGE:\n\
  aim-ai-regression-alert check    # detect + build, JSON Alert | \"null\"\n\
  aim-ai-regression-alert build    # read Regression JSON from stdin → Alert JSON\n\n\
ENV: AI_DIAGNOSTIC_DB"
    );
}
