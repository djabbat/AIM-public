//! aim-ai-suppressions CLI — Phase 9 Tier 3 #18 (2026-05-07).
//!
//! Replaces `AI/ai/finding_suppressions.py` (FS1).
//!
//! Subcommands:
//!   suppress --ref R [--reason T] [--until RFC3339]
//!   unsuppress --ref R           # exits 0/1; prints "true"/"false"
//!   is-suppressed --ref R        # exits 0/1; prints "true"/"false"
//!   active                       # JSONL of active rows
//!   all                          # JSONL of all rows (active + expired)
//!   filter                       # stdin: 1 ref/line → stdout: kept refs
//!   summary                      # plain-text
//!   prune-expired                # JSON {"removed": N}
//!
//! ENV: AI_DIAGNOSTIC_DB.

use std::io::{BufRead, Read};
use std::process::ExitCode;

use aim_ai_suppressions::SuppressionStore;
use chrono::DateTime;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(code) => code,
        Err(e) => {
            eprintln!("aim-ai-suppressions: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<ExitCode, Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("summary");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(ExitCode::SUCCESS)
        }
        "suppress" => {
            let mut v = rest;
            let r = take_opt(&mut v, "--ref").ok_or("suppress: --ref required")?;
            let reason = take_opt(&mut v, "--reason").unwrap_or_default();
            let until = match take_opt(&mut v, "--until") {
                Some(s) => Some(
                    DateTime::parse_from_rfc3339(&s)?
                        .with_timezone(&chrono::Utc),
                ),
                None => None,
            };
            let store = SuppressionStore::open_default()?;
            let s = store.suppress(&r, &reason, until)?;
            println!("{}", serde_json::to_string(&s)?);
            Ok(ExitCode::SUCCESS)
        }
        "unsuppress" => {
            let mut v = rest;
            let r = take_opt(&mut v, "--ref").ok_or("unsuppress: --ref required")?;
            let store = SuppressionStore::open_default()?;
            let removed = store.unsuppress(&r)?;
            println!("{}", removed);
            Ok(if removed { ExitCode::SUCCESS } else { ExitCode::from(1) })
        }
        "is-suppressed" => {
            let mut v = rest;
            let r = take_opt(&mut v, "--ref").ok_or("is-suppressed: --ref required")?;
            let store = SuppressionStore::open_default()?;
            let yes = store.is_suppressed(&r)?;
            println!("{}", yes);
            Ok(if yes { ExitCode::SUCCESS } else { ExitCode::from(1) })
        }
        "active" => {
            let store = SuppressionStore::open_default()?;
            for s in store.active()? {
                println!("{}", serde_json::to_string(&s)?);
            }
            Ok(ExitCode::SUCCESS)
        }
        "all" => {
            let store = SuppressionStore::open_default()?;
            for s in store.all_rows()? {
                println!("{}", serde_json::to_string(&s)?);
            }
            Ok(ExitCode::SUCCESS)
        }
        "filter" => {
            let mut s = String::new();
            std::io::stdin().read_to_string(&mut s)?;
            let store = SuppressionStore::open_default()?;
            let refs: Vec<&str> = s.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
            for kept in store.filter_findings(refs)? {
                println!("{}", kept);
            }
            Ok(ExitCode::SUCCESS)
        }
        "prune-expired" => {
            let store = SuppressionStore::open_default()?;
            let removed = store.prune_expired()?;
            println!("{{\"removed\":{}}}", removed);
            Ok(ExitCode::SUCCESS)
        }
        "summary" => {
            let store = SuppressionStore::open_default()?;
            let rows = store.all_rows()?;
            if rows.is_empty() {
                println!("(no finding suppressions)");
                return Ok(ExitCode::SUCCESS);
            }
            let act: Vec<_> = rows.iter().filter(|s| s.is_active()).collect();
            let expired: Vec<_> = rows.iter().filter(|s| !s.is_active()).collect();
            println!(
                "🔇 Finding suppressions — {} active, {} expired",
                act.len(),
                expired.len()
            );
            for s in act.iter().take(15) {
                let until = s
                    .until_ts
                    .as_deref()
                    .map(|t| format!(" (until {})", &t[..t.len().min(10)]))
                    .unwrap_or_default();
                let reason = if s.reason.is_empty() {
                    String::new()
                } else {
                    format!(" — {}", s.reason)
                };
                println!("  • {}{}{}", s.r#ref, until, reason);
            }
            if act.len() > 15 {
                println!("  (+{} more)", act.len() - 15);
            }
            Ok(ExitCode::SUCCESS)
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

#[allow(dead_code)]
fn read_lines(s: &str) -> Vec<String> {
    s.as_bytes()
        .lines()
        .filter_map(Result::ok)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn print_usage() {
    println!(
        "aim-ai-suppressions — sqlite-backed mute list for diagnostic findings\n\n\
USAGE:\n\
  aim-ai-suppressions suppress --ref R [--reason T] [--until RFC3339]\n\
  aim-ai-suppressions unsuppress --ref R\n\
  aim-ai-suppressions is-suppressed --ref R\n\
  aim-ai-suppressions active             # JSONL active rows\n\
  aim-ai-suppressions all                # JSONL all rows\n\
  aim-ai-suppressions filter             # stdin refs → stdout kept\n\
  aim-ai-suppressions prune-expired      # {{removed: N}}\n\
  aim-ai-suppressions summary            # plain-text\n\n\
ENV: AI_DIAGNOSTIC_DB"
    );
}
