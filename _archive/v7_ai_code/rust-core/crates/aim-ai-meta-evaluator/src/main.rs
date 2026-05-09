//! aim-ai-meta-evaluator CLI — Phase 9 Tier 1 #3 (2026-05-07).
//!
//! Parse + compare diagnostic reports. Replaces `AI/ai/meta_evaluator.py`.
//!
//! Subcommands (reports passed as file paths to stay shell-friendly):
//!   parse <report.md>                 # JSON ReportFacts of one report
//!   measure <r1.md> <r2.md> [...]     # JSON Reproducibility across ≥2
//!   shared-only <r1.md> <r2.md> [...] # JSONL of findings present in ALL reports
//!   summary <r1.md> <r2.md> [...]     # plain-text summary

use std::process::ExitCode;

use aim_ai_meta_evaluator::{measure, parse_report, shared_only};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-meta-evaluator: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-ai-meta-evaluator <parse|measure|shared-only|summary> <report>...; --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "parse" => {
            let path = rest.first().ok_or("parse: <report.md> required")?;
            let text = std::fs::read_to_string(path)?;
            let facts = parse_report(&text);
            println!("{}", serde_json::to_string(&facts)?);
            Ok(())
        }
        "measure" => {
            if rest.len() < 2 {
                return Err("measure: at least 2 report paths required".into());
            }
            let texts: Vec<String> = rest
                .iter()
                .map(|p| std::fs::read_to_string(p))
                .collect::<Result<_, _>>()?;
            let refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
            let r = measure(&refs)?;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        "shared-only" => {
            if rest.len() < 2 {
                return Err("shared-only: at least 2 report paths required".into());
            }
            let texts: Vec<String> = rest
                .iter()
                .map(|p| std::fs::read_to_string(p))
                .collect::<Result<_, _>>()?;
            let refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
            let s = shared_only(&refs);
            for f in s {
                println!("{}", serde_json::to_string(&f)?);
            }
            Ok(())
        }
        "summary" => {
            if rest.len() < 2 {
                return Err("summary: at least 2 report paths required".into());
            }
            let texts: Vec<String> = rest
                .iter()
                .map(|p| std::fs::read_to_string(p))
                .collect::<Result<_, _>>()?;
            let refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
            let r = measure(&refs)?;
            println!("📊 Reproducibility across {} reports", refs.len());
            println!("  shared findings: {}", r.shared_findings.len());
            println!("  unique findings: {}", r.unique_findings.len());
            println!("  jaccard:         {:.3}", r.jaccard_findings);
            println!("  signal/noise:    {:.2}", r.signal_to_noise());
            println!("  grade variance:  {}", r.grade_variance);
            println!("  crit stddev:     {:.2}", r.crit_stddev);
            println!("  verdict:         {}", r.verdict);
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn print_usage() {
    println!(
        "aim-ai-meta-evaluator — parse + compare diagnostic reports\n\n\
USAGE:\n\
  aim-ai-meta-evaluator parse <report.md>\n\
  aim-ai-meta-evaluator measure <r1> <r2> [...]\n\
  aim-ai-meta-evaluator shared-only <r1> <r2> [...]\n\
  aim-ai-meta-evaluator summary <r1> <r2> [...]\n"
    );
}
