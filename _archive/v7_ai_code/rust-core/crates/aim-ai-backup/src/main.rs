//! aim-ai-backup CLI — Phase 9 Tier 4 #26 (2026-05-07).
//!
//! Replaces `AI/ai/backup.py` (BK1).
//!
//! Subcommands:
//!   snapshot                 # JSON Snapshot
//!   write [--out PATH]       # write snapshot, JSON {"path": ...}
//!   restore --in PATH [--apply]   # default dry-run
//!   summary                  # plain-text inventory

use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_backup::{restore, snapshot, write_snapshot};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-backup: {e}");
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
        "snapshot" => {
            let s = snapshot()?;
            println!("{}", serde_json::to_string(&s)?);
            Ok(())
        }
        "write" => {
            let mut v = rest;
            let out_arg = take_opt(&mut v, "--out").map(PathBuf::from);
            let s = snapshot()?;
            let dest = match out_arg {
                Some(p) => p,
                None => default_out_path(),
            };
            let written = write_snapshot(&dest, &s)?;
            println!(
                "{}",
                serde_json::json!({"path": written.display().to_string()})
            );
            Ok(())
        }
        "restore" => {
            let mut v = rest;
            let in_arg = take_opt(&mut v, "--in").ok_or("restore: --in PATH required")?;
            let apply = take_flag(&mut v, "--apply");
            let r = restore(std::path::Path::new(&in_arg), !apply)?;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        "summary" => {
            let s = snapshot()?;
            println!("📦 Backup snapshot inventory");
            println!("  diagnostic_db: {}", s.diagnostic_db.path);
            for (n, rows) in &s.diagnostic_db.tables {
                println!("    • {:24} {:>5} rows", n, rows.len());
            }
            println!("  distillation_db: {}", s.distillation_db.path);
            for (n, rows) in &s.distillation_db.tables {
                println!("    • {:24} {:>5} rows", n, rows.len());
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn default_out_path() -> PathBuf {
    let ts = chrono::Utc::now().format("%Y-%m-%dT%H%M%S").to_string();
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home)
        .join(".cache")
        .join("aim")
        .join(format!("backup_{ts}.json"))
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
        "aim-ai-backup — JSON dump/restore of AIM/AI persistent DBs\n\n\
USAGE:\n\
  aim-ai-backup snapshot                          # JSON\n\
  aim-ai-backup write [--out PATH]                # write JSON file\n\
  aim-ai-backup restore --in PATH [--apply]       # default dry-run\n\
  aim-ai-backup summary                           # plain-text inventory\n\n\
ENV: AI_DIAGNOSTIC_DB"
    );
}
