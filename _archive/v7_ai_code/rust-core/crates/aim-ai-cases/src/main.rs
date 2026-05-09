//! aim-ai-cases CLI — Phase 9 Tier 3 #15 (2026-05-07).
//!
//! Replaces `AI/ai/case_validator.py` (CV1).
//!
//! Subcommands:
//!   validate-one <PATH>      # JSON CaseStatus
//!   validate-dir [--dir D]   # JSON Report
//!   summary       [--dir D]  # plain-text

use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_cases::{validate_dir, validate_one};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-cases: {e}");
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
        "validate-one" => {
            let p = rest.first().ok_or("validate-one: <PATH> required")?;
            let s = validate_one(std::path::Path::new(p));
            println!("{}", serde_json::to_string(&s)?);
            Ok(())
        }
        "validate-dir" => {
            let mut v = rest;
            let dir = take_opt(&mut v, "--dir").map(PathBuf::from);
            let r = validate_dir(dir.as_deref());
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        "summary" => {
            let mut v = rest;
            let dir = take_opt(&mut v, "--dir").map(PathBuf::from);
            let r = validate_dir(dir.as_deref());
            if r.n_cases == 0 {
                println!("(no eval cases found)");
                return Ok(());
            }
            println!(
                "📋 Case validator — {} cases ({} ok / {} failed)",
                r.n_cases, r.n_ok, r.n_failed
            );
            if r.all_ok() {
                println!("  ✅ all cases pass schema check");
                return Ok(());
            }
            for s in &r.statuses {
                if s.ok {
                    continue;
                }
                let cid = s.case_id.as_deref().unwrap_or("?");
                let name = s
                    .path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("?");
                println!("  ❌ {}  ({})", name, cid);
                for i in &s.issues {
                    println!("      • {}", i);
                }
            }
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

fn print_usage() {
    println!(
        "aim-ai-cases — eval case YAML schema validator\n\n\
USAGE:\n\
  aim-ai-cases validate-one <PATH>\n\
  aim-ai-cases validate-dir [--dir D]\n\
  aim-ai-cases summary       [--dir D]\n\n\
ENV: AIM_EVAL_CASES_DIR (default ~/.cache/aim/eval_cases)"
    );
}
