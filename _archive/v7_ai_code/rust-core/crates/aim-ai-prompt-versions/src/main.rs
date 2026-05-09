//! aim-ai-prompt-versions CLI — Phase 9 Tier 1 #2 (2026-05-07).
//!
//! Tracks sha256/size of `SELF_DIAGNOSTIC_PROMPT.md` revisions.
//! Replaces `AI/ai/prompt_versions.py`.
//!
//! Subcommands:
//!   prompt-path                              # resolved prompt path
//!   db-path                                  # resolved ledger DB path
//!   fingerprint [<path>]                     # JSON of current fp
//!   record-current [<path>] [--ts T]         # JSON of recorded fp
//!   history                                  # JSONL of all fps
//!   drift-since-last [<path>]                # JSON Drift struct
//!   summary                                  # plain-text summary

use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_prompt_versions::{
    default_prompt_path, fingerprint_of, PromptStore,
};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-prompt-versions: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-ai-prompt-versions <prompt-path|db-path|fingerprint|record-current|history|drift-since-last|summary>; --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "prompt-path" => {
            println!("{}", default_prompt_path().display());
            Ok(())
        }
        "db-path" => {
            // Mirror lib resolution: AI_DIAGNOSTIC_DB or default cache.
            let p = std::env::var("AI_DIAGNOSTIC_DB")
                .map(PathBuf::from)
                .unwrap_or_else(|_| {
                    let home = std::env::var("HOME")
                        .map(PathBuf::from)
                        .unwrap_or_else(|_| PathBuf::from("."));
                    home.join(".cache").join("aim").join("diagnostic_ledger.db")
                });
            println!("{}", p.display());
            Ok(())
        }
        "fingerprint" => {
            let path: PathBuf = rest
                .first()
                .map(PathBuf::from)
                .unwrap_or_else(default_prompt_path);
            let fp = fingerprint_of(&path)?;
            println!("{}", serde_json::to_string(&fp)?);
            Ok(())
        }
        "record-current" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let ts = take_opt(&mut rest_v, "--ts");
            let path = rest_v.first().map(|s| PathBuf::from(*s));
            let store = PromptStore::open_default()?;
            let fp = store.record_current(path.as_deref(), ts.as_deref())?;
            println!("{}", serde_json::to_string(&fp)?);
            Ok(())
        }
        "history" => {
            let store = PromptStore::open_default()?;
            for fp in store.history()? {
                println!("{}", serde_json::to_string(&fp)?);
            }
            Ok(())
        }
        "drift-since-last" => {
            let path = rest.first().map(PathBuf::from);
            let store = PromptStore::open_default()?;
            let d = store.drift_since_last(path.as_deref())?;
            println!("{}", serde_json::to_string(&d)?);
            Ok(())
        }
        "summary" => {
            let store = PromptStore::open_default()?;
            let h = store.history()?;
            if h.is_empty() {
                println!("(no prompt fingerprints recorded)");
                return Ok(());
            }
            let last = h.last().unwrap();
            println!("📌 Prompt versions — {} fingerprints", h.len());
            println!(
                "  last ts:    {}",
                last.ts.as_deref().unwrap_or("?")
            );
            println!("  last sha:   {}", &last.sha256[..16.min(last.sha256.len())]);
            println!("  bytes:      {}", last.byte_count);
            println!("  lines:      {}", last.line_count);
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
        "aim-ai-prompt-versions — track SELF_DIAGNOSTIC_PROMPT.md revisions\n\n\
USAGE:\n\
  aim-ai-prompt-versions prompt-path\n\
  aim-ai-prompt-versions db-path\n\
  aim-ai-prompt-versions fingerprint [<path>]\n\
  aim-ai-prompt-versions record-current [<path>] [--ts T]\n\
  aim-ai-prompt-versions history\n\
  aim-ai-prompt-versions drift-since-last [<path>]\n\
  aim-ai-prompt-versions summary\n\n\
ENV: AI_DIAGNOSTIC_PROMPT, AI_DIAGNOSTIC_DB, AIM_ROOT, HOME, XDG_CACHE_HOME"
    );
}
