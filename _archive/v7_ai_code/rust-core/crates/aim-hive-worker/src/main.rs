//! aim-hive-telemetry CLI — Phase 9 Tier 4 #29 (2026-05-07).
//!
//! Replaces `AI/ai/hive_telemetry.py` (HV1).
//!
//! Subcommands:
//!   contribution                  # JSON anonymized payload
//!   preview                       # pretty JSON
//!   contribute [--dry-run] [--queen-url U] [--eps F]
//!                                 # JSON ContributionResult; default = real POST

use std::process::ExitCode;

use aim_hive_worker::{contribute, contribution, preview, ContributeOpts};

#[tokio::main]
async fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(args).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-hive-telemetry: {e}");
            ExitCode::FAILURE
        }
    }
}

async fn cli(args: Vec<String>) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("--help");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "contribution" => {
            let v = contribution(None)?;
            println!("{}", serde_json::to_string(&v)?);
            Ok(())
        }
        "preview" => {
            println!("{}", preview(None)?);
            Ok(())
        }
        "contribute" => {
            let mut v = rest;
            let dry_run = take_flag(&mut v, "--dry-run");
            let queen_url = take_opt(&mut v, "--queen-url");
            let eps = take_opt(&mut v, "--eps")
                .map(|s| s.parse::<f64>())
                .transpose()?;
            let opts = ContributeOpts {
                dry_run,
                queen_url,
                eps_per_round: eps,
                state_root: None,
            };
            let r = contribute(opts).await?;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn take_opt(rest: &mut Vec<&str>, key: &str) -> Option<String> {
    if let Some(i) = rest.iter().position(|a| *a == key) {
        if i + 1 < rest.len() {
            let v = rest[i + 1].to_string();
            rest.remove(i + 1);
            rest.remove(i);
            return Some(v);
        }
    }
    None
}

fn take_flag(rest: &mut Vec<&str>, key: &str) -> bool {
    if let Some(i) = rest.iter().position(|a| *a == key) {
        rest.remove(i);
        return true;
    }
    false
}

fn print_usage() {
    println!(
        "aim-hive-telemetry — anonymized worker → queen contribution\n\n\
USAGE:\n\
  aim-hive-telemetry contribution                    # JSON payload\n\
  aim-hive-telemetry preview                         # pretty JSON\n\
  aim-hive-telemetry contribute [--dry-run] [--queen-url U] [--eps F]\n\n\
ENV: AIM_HIVE_QUEEN_URL, AIM_USER_TOKEN, AIM_DP_BUDGET, AIM_HOME"
    );
}
