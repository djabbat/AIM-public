//! aim-ai-case-archiver CLI — Phase 9 Tier 2 #7 (2026-05-07).
//!
//! Move stale FE1 regression eval cases (`regr-*.yaml`) into
//! `_archived/` when the corresponding finding no longer shows up in
//! recent diagnostic reports.
//!
//! Subcommands:
//!   candidates [--lookback N] [--min-age-days F]
//!                                 # JSONL of Candidate
//!   archive    [--lookback N] [--min-age-days F] [--apply]
//!                                 # JSON ArchiveResult; default dry-run
//!   summary    [--lookback N] [--min-age-days F]
//!                                 # plain-text

use std::process::ExitCode;

use aim_ai_case_archiver::{archive, candidates, ArchiveOpts};
use aim_ai_ledger::Ledger;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-case-archiver: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("summary");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "candidates" => {
            let opts = parse_opts(&rest, false)?;
            let ledger = Ledger::open_default()?;
            for c in candidates(&ledger, &opts)? {
                println!("{}", serde_json::to_string(&c)?);
            }
            Ok(())
        }
        "archive" => {
            let opts = parse_opts(&rest, true)?;
            let ledger = Ledger::open_default()?;
            let r = archive(&ledger, &opts)?;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        "summary" => {
            let opts = parse_opts(&rest, false)?;
            let ledger = Ledger::open_default()?;
            let cands = candidates(&ledger, &opts)?;
            if cands.is_empty() {
                println!("(no archive candidates — all regression cases still active)");
                return Ok(());
            }
            println!("📦 {} regression cases ready to archive", cands.len());
            for c in cands.iter().take(10) {
                let line = c
                    .inferred_ref_line
                    .map(|l| format!(":{l}"))
                    .unwrap_or_default();
                println!(
                    "  • {}  ({}{}, age {:.1}d)",
                    c.case_id, c.inferred_ref_path, line, c.age_days
                );
            }
            if cands.len() > 10 {
                println!("  (+{} more)", cands.len() - 10);
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn parse_opts(rest: &[&str], allow_apply: bool) -> Result<ArchiveOpts, Box<dyn std::error::Error>> {
    let mut v: Vec<&str> = rest.to_vec();
    let lookback: u32 = take_opt(&mut v, "--lookback")
        .map(|s| s.parse::<u32>())
        .transpose()?
        .unwrap_or(7);
    let min_age_days: f64 = take_opt(&mut v, "--min-age-days")
        .map(|s| s.parse::<f64>())
        .transpose()?
        .unwrap_or(3.0);
    let apply = if allow_apply {
        take_flag(&mut v, "--apply")
    } else {
        false
    };
    Ok(ArchiveOpts {
        lookback,
        min_age_days,
        dry_run: !apply,
        cases_dir: None,
        archive_dir: None,
    })
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
        "aim-ai-case-archiver — retire stale FE1 regression cases\n\n\
USAGE:\n\
  aim-ai-case-archiver candidates [--lookback N] [--min-age-days F]\n\
  aim-ai-case-archiver archive    [--lookback N] [--min-age-days F] [--apply]\n\
  aim-ai-case-archiver summary    [--lookback N] [--min-age-days F]\n\n\
ENV: AI_DIAGNOSTIC_DB, AIM_EVAL_CASES_DIR, AIM_EVAL_ARCHIVE_DIR"
    );
}
