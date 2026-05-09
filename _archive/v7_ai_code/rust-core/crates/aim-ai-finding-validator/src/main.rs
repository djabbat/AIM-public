//! aim-ai-finding-validator CLI — Phase 9 Tier 3 #17 (2026-05-07).
//!
//! Replaces `AI/ai/finding_validator.py` (FV1).
//!
//! Subcommands:
//!   classify --file F            # stdin: claim text → JSON Verdict
//!   audit-report [--repo-root R] # stdin: report markdown → JSON AuditReport
//!   summary      [--repo-root R] # stdin: report markdown → plain-text

use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_finding_validator::{audit_report, classify, Status};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-finding-validator: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("--help");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "classify" => {
            let mut v = rest;
            let file = take_opt(&mut v, "--file").ok_or("classify: --file required")?;
            let claim = read_stdin_string()?;
            let verdict = classify(&claim, std::path::Path::new(&file));
            println!("{}", serde_json::to_string(&verdict)?);
            Ok(())
        }
        "audit-report" => {
            let mut v = rest;
            let repo_root = take_opt(&mut v, "--repo-root")
                .map(PathBuf::from)
                .unwrap_or_else(default_repo_root);
            let report = read_stdin_string()?;
            let r = audit_report(&report, &repo_root);
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        "summary" => {
            let mut v = rest;
            let repo_root = take_opt(&mut v, "--repo-root")
                .map(PathBuf::from)
                .unwrap_or_else(default_repo_root);
            let report = read_stdin_string()?;
            let a = audit_report(&report, &repo_root);
            if a.n_findings == 0 {
                println!("(no severity-tagged findings in report)");
                return Ok(());
            }
            println!("🔍 Finding validator — {} findings", a.n_findings);
            println!("  ❌ false positive: {}", a.n_false);
            println!("  ❓ unverified:     {}", a.n_unverified);
            println!("  ✅ true:           {}", a.n_true);
            if a.n_false > 0 {
                println!("\n False-positive examples:");
                let mut shown = 0;
                for au in a.audits.iter() {
                    if matches!(au.verdict.status, Status::FalsePositive) {
                        let r = au.file_ref.clone().unwrap_or_default();
                        println!("  • [{}] {}: {}", r, au.verdict.rule, au.verdict.evidence);
                        shown += 1;
                        if shown >= 5 {
                            break;
                        }
                    }
                }
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn read_stdin_string() -> Result<String, Box<dyn std::error::Error>> {
    let mut s = String::new();
    std::io::stdin().read_to_string(&mut s)?;
    Ok(s)
}

fn default_repo_root() -> PathBuf {
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let mut p = cwd.as_path();
    while let Some(parent) = p.parent() {
        if p.join("rust-core").join("Cargo.toml").exists() {
            return p.to_path_buf();
        }
        p = parent;
    }
    PathBuf::from(".")
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
        "aim-ai-finding-validator — heuristic auto-validator for diagnostic findings\n\n\
USAGE:\n\
  aim-ai-finding-validator classify --file F             # stdin claim → JSON\n\
  aim-ai-finding-validator audit-report [--repo-root R]  # stdin md → JSON\n\
  aim-ai-finding-validator summary      [--repo-root R]  # stdin md → text"
    );
}
