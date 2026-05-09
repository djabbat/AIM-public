//! aim-ai-reflexion CLI — Phase 9 Tier 3 #21 (2026-05-07).
//!
//! Replaces the clustering core of `AI/ai/reflexion_cluster.py` (S10).
//! Memory-source loading (feedback_*.md + reflexion buckets) stays in
//! Python because both sources are Python-side conventions.
//!
//! Subcommands:
//!   cluster [--threshold F]   # stdin: notes (one/line) → JSONL Cluster

use std::io::Read;
use std::process::ExitCode;

use aim_ai_reflexion::cluster;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-reflexion: {e}");
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
        "cluster" => {
            let mut v = rest;
            let threshold: f64 = take_opt(&mut v, "--threshold")
                .map(|s| s.parse::<f64>())
                .transpose()?
                .unwrap_or(0.25);
            // Notes come as JSON-encoded strings, one per line, so
            // newline-rich text doesn't get split into multiple notes.
            let mut s = String::new();
            std::io::stdin().read_to_string(&mut s)?;
            let notes: Vec<String> = s
                .lines()
                .map(str::trim)
                .filter(|l| !l.is_empty())
                .filter_map(|l| serde_json::from_str::<String>(l).ok())
                .collect();
            let clusters = cluster(notes, threshold);
            for c in clusters {
                let suggestion = c.suggestion();
                let j = serde_json::json!({
                    "notes": c.notes,
                    "theme": c.theme,
                    "representative": c.representative,
                    "suggestion": suggestion,
                });
                println!("{}", serde_json::to_string(&j)?);
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
        "aim-ai-reflexion — Jaccard cluster reflexion notes\n\n\
USAGE:\n\
  aim-ai-reflexion cluster [--threshold F]\n\
      stdin: one JSON-encoded note string per line\n\
      stdout: one JSON Cluster per line"
    );
}
