//! aim-ai-self-modify CLI — Phase 9 Tier 2 #3 (2026-05-07).
//!
//! Code self-modification framework (S6). Gate closed by default —
//! refuses to mutate until baseline is mature (≥28 daily runs over
//! ≥28 d). Replaces `AI/ai/self_modify.py`.
//!
//! Subcommands:
//!   can-self-modify      # JSON Verdict
//!   propose <ref>        # JSON Proposal (no side effects)
//!   apply <ref> [--no-dry-run]   # JSON ApplyResult
//!   summary              # plain-text summary

use std::process::ExitCode;

use aim_ai_ledger::Ledger;
use aim_ai_self_modify::{apply, can_self_modify, propose, summary};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-self-modify: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("can-self-modify");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "can-self-modify" | "can_self_modify" => {
            let ledger = Ledger::open_default()?;
            let v = can_self_modify(&ledger)?;
            println!("{}", serde_json::to_string(&v)?);
            Ok(())
        }
        "propose" => {
            let r = rest.first().ok_or("propose: <finding_ref> required")?;
            let p = propose(r);
            println!("{}", serde_json::to_string(&p)?);
            Ok(())
        }
        "apply" => {
            let mut rest_v: Vec<&str> = rest.clone();
            let no_dry = take_flag(&mut rest_v, "--no-dry-run");
            let r = rest_v
                .first()
                .ok_or("apply: <finding_ref> required")?;
            let p = propose(r);
            let ledger = Ledger::open_default()?;
            let res = apply(&ledger, p, !no_dry)?;
            println!("{}", serde_json::to_string(&res)?);
            Ok(())
        }
        "summary" => {
            let ledger = Ledger::open_default()?;
            let v = can_self_modify(&ledger)?;
            println!("{}", summary(&v));
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
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
        "aim-ai-self-modify — gated code self-modification framework\n\n\
USAGE:\n\
  aim-ai-self-modify can-self-modify           # JSON Verdict\n\
  aim-ai-self-modify propose <finding_ref>     # JSON Proposal\n\
  aim-ai-self-modify apply <ref> [--no-dry-run]   # JSON ApplyResult\n\
  aim-ai-self-modify summary                   # plain-text\n\n\
ENV: AI_DIAGNOSTIC_DB"
    );
}
