//! aim-ai-regression CLI — Phase 9 Tier 2 #5 (2026-05-07).
//!
//! Diff the two most recent ledger rows; flag NEW critical findings.
//! Replaces `AI/ai/regression_detector.py`.
//!
//! Subcommands:
//!   detect      # JSON Regression
//!   summary     # plain-text summary

use std::process::ExitCode;

use aim_ai_ledger::Ledger;
use aim_ai_regression::detect;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-regression: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("detect");
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "detect" => {
            let ledger = Ledger::open_default()?;
            let r = detect(&ledger)?;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        "summary" => {
            let ledger = Ledger::open_default()?;
            let r = detect(&ledger)?;
            if !r.have_baseline {
                println!("(no baseline — need at least 2 ledger rows)");
                return Ok(());
            }
            let prev_g = r.prev_grade.as_deref().unwrap_or("?");
            let curr_g = r.curr_grade.as_deref().unwrap_or("?");
            let prev_c = r
                .prev_crit
                .map(|x| x.to_string())
                .unwrap_or_else(|| "?".into());
            let curr_c = r
                .curr_crit
                .map(|x| x.to_string())
                .unwrap_or_else(|| "?".into());
            println!("📈 Regression check");
            println!("  prev: {} (crit={})", prev_g, prev_c);
            println!("  curr: {} (crit={})", curr_g, curr_c);
            if !r.new_findings.is_empty() {
                println!("  ⚠ new findings: {}", r.new_findings.len());
                for f in r.new_findings.iter().take(5) {
                    println!("    + {f}");
                }
                if r.new_findings.len() > 5 {
                    println!("    (+{} more)", r.new_findings.len() - 5);
                }
            } else {
                println!("  no new findings");
            }
            if !r.fixed_findings.is_empty() {
                println!("  ✓ fixed findings: {}", r.fixed_findings.len());
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn print_usage() {
    println!(
        "aim-ai-regression — diff last two ledger rows for new critical findings\n\n\
USAGE:\n\
  aim-ai-regression detect    # JSON Regression\n\
  aim-ai-regression summary   # plain-text\n\n\
ENV: AI_DIAGNOSTIC_DB"
    );
}
