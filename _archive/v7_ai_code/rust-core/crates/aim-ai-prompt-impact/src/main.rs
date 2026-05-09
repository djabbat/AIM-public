//! aim-ai-prompt-impact CLI — Phase 9 Tier 2 #4 (2026-05-07).
//!
//! Join prompt-version history with ledger runs; compute
//! before/after deltas around each revision. Replaces
//! `AI/ai/prompt_impact.py`.
//!
//! Subcommands:
//!   per-revision     # JSONL of ImpactRow per prompt revision
//!   summary          # plain-text summary

use std::process::ExitCode;

use aim_ai_ledger::Ledger;
use aim_ai_prompt_impact::{impact_per_revision, summary};
use aim_ai_prompt_versions::PromptStore;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-prompt-impact: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("per-revision");
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "per-revision" => {
            let ledger = Ledger::open_default()?;
            let prompts = PromptStore::open_default()?;
            let rows = impact_per_revision(&ledger, &prompts)?;
            for r in rows {
                println!("{}", serde_json::to_string(&r)?);
            }
            Ok(())
        }
        "summary" => {
            let ledger = Ledger::open_default()?;
            let prompts = PromptStore::open_default()?;
            let rows = impact_per_revision(&ledger, &prompts)?;
            println!("{}", summary(&rows));
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn print_usage() {
    println!(
        "aim-ai-prompt-impact — before/after deltas around prompt revisions\n\n\
USAGE:\n\
  aim-ai-prompt-impact per-revision    # JSONL\n\
  aim-ai-prompt-impact summary         # plain-text\n\n\
ENV: AI_DIAGNOSTIC_DB, AI_DIAGNOSTIC_PROMPT, AIM_ROOT"
    );
}
