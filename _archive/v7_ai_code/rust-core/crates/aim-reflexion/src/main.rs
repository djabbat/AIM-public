//! aim-reflexion CLI — Phase 8 (2026-05-07).
//!
//! Storage-only operations exposed for the Python shim. The
//! `on_failure` flow (which calls llm.ask_fast) intentionally stays in
//! Python because the LLM router is still Python — see PHASE_8_ROADMAP.md.
//!
//! Subcommands:
//!   classify <task>                 — print bucket key
//!   store-dir                       — print resolved storage directory
//!   save <task> <summary> [--bucket B]
//!   recent <task> [--n N] [--max-age-days D] [--bucket B]   (JSONL out)

use std::process::ExitCode;

use aim_reflexion::{classify, default_store_dir, Store};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-reflexion: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-reflexion <classify|store-dir|save|recent> ...; try --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "classify" => {
            let task = rest.first().ok_or("classify: <task> required")?;
            println!("{}", classify(task));
            Ok(())
        }
        "store-dir" => {
            println!("{}", default_store_dir().display());
            Ok(())
        }
        "save" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let bucket = take_opt(&mut rest_v, "--bucket");
            let task = rest_v.first().ok_or("save: <task> required")?.to_string();
            let summary = rest_v.get(1).ok_or("save: <summary> required")?.to_string();
            let store = Store::from_env();
            store.save_reflection(&task, &summary, bucket.as_deref())?;
            Ok(())
        }
        "recent" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let bucket = take_opt(&mut rest_v, "--bucket");
            let n = take_opt(&mut rest_v, "--n")
                .map(|s| s.parse::<usize>())
                .transpose()?
                .unwrap_or(3);
            let max_age_days = take_opt(&mut rest_v, "--max-age-days")
                .map(|s| s.parse::<i64>())
                .transpose()?
                .unwrap_or(60);
            let task = rest_v.first().ok_or("recent: <task> required")?.to_string();
            let store = Store::from_env();
            let summaries =
                store.recent_reflections(&task, n, bucket.as_deref(), max_age_days);
            for s in summaries {
                // print one summary per line (matching Python recent_reflections list[str]).
                // Strip embedded newlines so each line is a complete summary.
                let one_line = s.replace('\n', " ").replace('\r', " ");
                println!("{one_line}");
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
        "aim-reflexion — task-class reflection memory (Shinn et al. 2023)\n\n\
USAGE:\n\
  aim-reflexion classify <task>\n\
  aim-reflexion store-dir\n\
  aim-reflexion save <task> <summary> [--bucket B]\n\
  aim-reflexion recent <task> [--n N] [--max-age-days D] [--bucket B]\n\n\
OUTPUT: classify/store-dir = plain text; recent = JSONL; save = silent.\n\
ENV: HOME, XDG_DATA_HOME (Linux), LOCALAPPDATA (Windows)."
    );
}
