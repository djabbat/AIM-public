//! aim-ai-findings-to-evals CLI — Phase 9 Tier 3 #16 (2026-05-07).
//!
//! Replaces `AI/ai/findings_to_evals.py` (FE1).
//!
//! Subcommands:
//!   case-from-finding <ref>     # JSON CaseSpec | "null"
//!   generate                    # stdin: refs (one/line) → JSONL CaseSpec
//!   yaml                        # stdin: refs → stdout: concat YAML docs
//!   write [--dest D] [--overwrite]   # stdin: refs → JSON {"written": [paths]}
//!   summary                     # stdin: refs → plain-text

use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_findings_to_evals::{case_from_finding, generate_cases, write_cases, yaml_dump};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-findings-to-evals: {e}");
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
        "case-from-finding" => {
            let r = rest.first().ok_or("case-from-finding: <ref> required")?;
            match case_from_finding(r) {
                Some(c) => println!("{}", serde_json::to_string(&c)?),
                None => println!("null"),
            }
            Ok(())
        }
        "generate" => {
            let refs = read_stdin_refs()?;
            for spec in generate_cases(refs.iter().map(|s| s.as_str())) {
                println!("{}", serde_json::to_string(&spec)?);
            }
            Ok(())
        }
        "yaml" => {
            let refs = read_stdin_refs()?;
            for (i, spec) in generate_cases(refs.iter().map(|s| s.as_str())).iter().enumerate() {
                if i > 0 {
                    println!("---");
                }
                print!("{}", yaml_dump(spec));
            }
            Ok(())
        }
        "write" => {
            let mut v = rest;
            let dest = take_opt(&mut v, "--dest").map(PathBuf::from);
            let overwrite = take_flag(&mut v, "--overwrite");
            let refs = read_stdin_refs()?;
            let written = write_cases(
                refs.iter().map(|s| s.as_str()),
                dest.as_deref(),
                overwrite,
            )?;
            let j = serde_json::json!({
                "written": written.iter().map(|p| p.display().to_string()).collect::<Vec<_>>(),
                "n": written.len(),
            });
            println!("{}", serde_json::to_string(&j)?);
            Ok(())
        }
        "summary" => {
            let refs = read_stdin_refs()?;
            let specs = generate_cases(refs.iter().map(|s| s.as_str()));
            if specs.is_empty() {
                println!("(no eval cases generated — refs were unparseable)");
                return Ok(());
            }
            println!("📋 Generated {} regression eval cases", specs.len());
            for s in specs.iter().take(15) {
                println!("  • {}", s.id);
            }
            if specs.len() > 15 {
                println!("  (+{} more)", specs.len() - 15);
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn read_stdin_refs() -> Result<Vec<String>, Box<dyn std::error::Error>> {
    let mut s = String::new();
    std::io::stdin().read_to_string(&mut s)?;
    Ok(s.lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect())
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
        "aim-ai-findings-to-evals — file:line findings → regression eval YAML\n\n\
USAGE:\n\
  aim-ai-findings-to-evals case-from-finding <ref>\n\
  aim-ai-findings-to-evals generate                # stdin refs → JSONL specs\n\
  aim-ai-findings-to-evals yaml                    # stdin refs → YAML\n\
  aim-ai-findings-to-evals write [--dest D] [--overwrite]\n\
  aim-ai-findings-to-evals summary                 # stdin refs → plain-text\n\n\
ENV: AIM_EVAL_CASES_DIR (default cases dir)"
    );
}
