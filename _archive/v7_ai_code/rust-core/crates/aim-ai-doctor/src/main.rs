//! aim-ai-doctor CLI — Phase 9 Tier 3 #11 (2026-05-07).
//!
//! Replaces the non-Python part of `AI/ai/doctor.py`. Python keeps
//! the modules-import probe (no Rust equivalent for `import`) and the
//! DEEPSEEK_API_KEY probe; this binary owns the structural ones.
//!
//! Subcommands:
//!   diagnose [--repo-root PATH]      # JSONL of Probe (one per line)
//!   summary  [--repo-root PATH]      # plain-text

use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_doctor::{diagnose, summary, Severity};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-doctor: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("summary");
    let mut rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    let repo_root = take_opt(&mut rest, "--repo-root")
        .map(PathBuf::from)
        .unwrap_or_else(default_repo_root);
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "diagnose" => {
            let probes = diagnose(&repo_root);
            for p in probes {
                let sev = match p.severity {
                    Severity::Info => "info",
                    Severity::Warn => "warn",
                    Severity::Crit => "crit",
                };
                let j = serde_json::json!({
                    "name": p.name,
                    "ok": p.ok,
                    "detail": p.detail,
                    "severity": sev,
                });
                println!("{}", serde_json::to_string(&j)?);
            }
            Ok(())
        }
        "summary" => {
            let probes = diagnose(&repo_root);
            println!("{}", summary(&probes));
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn default_repo_root() -> PathBuf {
    // Best guess: walk up from CWD until we see AIM/rust-core.
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let mut p = cwd.as_path();
    while let Some(parent) = p.parent() {
        if parent.join("AIM").join("rust-core").join("Cargo.toml").exists() {
            return parent.to_path_buf();
        }
        if p.join("AIM").join("rust-core").join("Cargo.toml").exists() {
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
        "aim-ai-doctor — wiring smoke test for AI subproject\n\n\
USAGE:\n\
  aim-ai-doctor diagnose [--repo-root PATH]   # JSONL Probe rows\n\
  aim-ai-doctor summary  [--repo-root PATH]   # plain-text\n\n\
ENV: AI_DIAGNOSTIC_DB"
    );
}
