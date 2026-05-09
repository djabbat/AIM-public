//! aim-interactions CLI — Phase 8 Week 2 (2026-05-07).
//!
//! Drug-drug interaction lookup. The static table (~30 pairs with PMIDs
//! / mechanisms / recommendations) lives in the lib (`aim_interactions`);
//! this binary exposes it as JSON-on-stdout subcommands so the Python
//! shim (`agents/interactions.py`) becomes a thin subprocess wrapper.
//!
//! Subcommands:
//!   check <drug_a> <drug_b>          — JSON Interaction
//!   regimen <drug1> <drug2> ...      — JSONL of pairs
//!   format <drug1> <drug2> ... [--lang en|ru] [--include-no-known]
//!   known-drugs                      — newline-separated canonical names
//!   canon <name>                     — print canonical key

use std::process::ExitCode;

use aim_interactions::{
    canon, check_interaction, check_regimen, dump_table, format_regimen_report, known_drugs,
    DISCLAIMER,
};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-interactions: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-interactions <check|regimen|format|known-drugs|canon> ...; try --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "check" => {
            let a = rest.first().ok_or("check: <drug_a> required")?;
            let b = rest.get(1).ok_or("check: <drug_b> required")?;
            let i = check_interaction(a, b);
            println!("{}", serde_json::to_string(&i)?);
            Ok(())
        }
        "regimen" => {
            let drugs: Vec<String> = rest.iter().cloned().collect();
            for ix in check_regimen(&drugs) {
                println!("{}", serde_json::to_string(&ix)?);
            }
            Ok(())
        }
        "format" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let lang = take_opt(&mut rest_v, "--lang").unwrap_or_else(|| "en".to_string());
            let include_no_known = take_flag(&mut rest_v, "--include-no-known");
            let drugs: Vec<String> = rest_v.iter().map(|s| s.to_string()).collect();
            let interactions = check_regimen(&drugs);
            let report = format_regimen_report(&interactions, &lang, include_no_known);
            print!("{report}");
            Ok(())
        }
        "known-drugs" => {
            for d in known_drugs() {
                println!("{d}");
            }
            Ok(())
        }
        "canon" => {
            let name = rest.first().ok_or("canon: <name> required")?;
            println!("{}", canon(name));
            Ok(())
        }
        "dump-table" => {
            for ix in dump_table() {
                println!("{}", serde_json::to_string(&ix)?);
            }
            Ok(())
        }
        "disclaimer" => {
            println!("{DISCLAIMER}");
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

fn take_flag(rest: &mut Vec<&str>, key: &str) -> bool {
    if let Some(i) = rest.iter().position(|a| *a == key) {
        rest.remove(i);
        return true;
    }
    false
}

fn print_usage() {
    println!(
        "aim-interactions — drug-drug interaction lookup (~30 pairs)\n\n\
USAGE:\n\
  aim-interactions check <drug_a> <drug_b>\n\
  aim-interactions regimen <drug1> <drug2> ...\n\
  aim-interactions format <drug1> <drug2> ... [--lang en|ru] [--include-no-known]\n\
  aim-interactions known-drugs\n\
  aim-interactions canon <name>\n\n\
OUTPUT: JSON for check/regimen, plain text for format/known-drugs/canon."
    );
}
