//! aim-ai-skill-standard CLI — Phase 9 Tier 3 #19 (2026-05-07).
//!
//! Replaces `AI/ai/skill_standard.py` (HV4).
//!
//! Subcommands:
//!   to-agentskills        # stdin: AIM skill JSON → stdout: external JSON
//!   from-agentskills      # stdin: external JSON → stdout: AIM JSON
//!   round-trip            # stdin: AIM → AIM (verifies idempotent fields)
//!   export-dir <src> <dst> [--overwrite]  # JSON {"written": N}
//!   import-dir <src> <dst> [--overwrite]  # JSON {"written": N}
//!   summary               # plain-text

use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use aim_ai_skill_standard::{export_dir, from_agentskills, import_dir, round_trip_aim, to_agentskills};
use serde_json::Value;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-skill-standard: {e}");
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
        "to-agentskills" => {
            let v: Value = read_stdin_json()?;
            let out = to_agentskills(&v)?;
            println!("{}", serde_json::to_string(&out)?);
            Ok(())
        }
        "from-agentskills" => {
            let v: Value = read_stdin_json()?;
            let out = from_agentskills(&v)?;
            println!("{}", serde_json::to_string(&out)?);
            Ok(())
        }
        "round-trip" => {
            let v: Value = read_stdin_json()?;
            let out = round_trip_aim(&v)?;
            println!("{}", serde_json::to_string(&out)?);
            Ok(())
        }
        "export-dir" => {
            let (src, dst, overwrite) = parse_dir_args(&rest)?;
            let n = export_dir(&src, &dst, overwrite)?;
            println!("{{\"written\":{}}}", n);
            Ok(())
        }
        "import-dir" => {
            let (src, dst, overwrite) = parse_dir_args(&rest)?;
            let n = import_dir(&src, &dst, overwrite)?;
            println!("{{\"written\":{}}}", n);
            Ok(())
        }
        "summary" => {
            println!(
                "🔌 Skill standard adapter — ready.\n  to-agentskills / from-agentskills — single-skill conversion\n  export-dir <src> <dst> / import-dir <src> <dst> — batch"
            );
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn read_stdin_json() -> Result<Value, Box<dyn std::error::Error>> {
    let mut s = String::new();
    std::io::stdin().read_to_string(&mut s)?;
    Ok(serde_json::from_str(&s)?)
}

fn parse_dir_args(rest: &[&str]) -> Result<(PathBuf, PathBuf, bool), Box<dyn std::error::Error>> {
    let mut v: Vec<&str> = rest.to_vec();
    let overwrite = if let Some(i) = v.iter().position(|a| *a == "--overwrite") {
        v.remove(i);
        true
    } else {
        false
    };
    if v.len() < 2 {
        return Err("expected <src> <dst>".into());
    }
    Ok((PathBuf::from(v[0]), PathBuf::from(v[1]), overwrite))
}

fn print_usage() {
    println!(
        "aim-ai-skill-standard — agentskills.io interop\n\n\
USAGE:\n\
  aim-ai-skill-standard to-agentskills           # stdin AIM → stdout ext\n\
  aim-ai-skill-standard from-agentskills         # stdin ext → stdout AIM\n\
  aim-ai-skill-standard round-trip               # stdin AIM → AIM\n\
  aim-ai-skill-standard export-dir <src> <dst> [--overwrite]\n\
  aim-ai-skill-standard import-dir <src> <dst> [--overwrite]\n\
  aim-ai-skill-standard summary"
    );
}
