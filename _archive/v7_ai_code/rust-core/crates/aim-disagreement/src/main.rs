//! aim-disagreement CLI — Blumenthal-Lee 4-zone classifier.
//!
//! Output is JSON on stdout so Python shims and Phoenix LiveViews can
//! parse without a wrapper library.
//!
//! Subcommands:
//!   classify <ai_conf> <clinician_conf> <agree:true|false>
//!     [--ai-high <0..1>] [--clinician-high <0..1>]

use std::process::ExitCode;

use aim_disagreement::{classify_with_outcome, ZoneThresholds};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-disagreement: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-disagreement classify <ai> <clin> <agree> ...; try --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "classify" => {
            let mut rest: Vec<&str> = rest.iter().map(String::as_str).collect();
            let ai_high = take_opt(&mut rest, "--ai-high")
                .map(|s| s.parse::<f64>())
                .transpose()?;
            let cl_high = take_opt(&mut rest, "--clinician-high")
                .map(|s| s.parse::<f64>())
                .transpose()?;
            let mut th = ZoneThresholds::default();
            if let Some(v) = ai_high {
                th.ai_high = v;
            }
            if let Some(v) = cl_high {
                th.clinician_high = v;
            }
            let ai: f64 = rest.first().ok_or("ai_conf required")?.parse()?;
            let cl: f64 = rest.get(1).ok_or("clinician_conf required")?.parse()?;
            let agree = match rest.get(2).copied().unwrap_or("") {
                "true" | "1" | "yes" => true,
                "false" | "0" | "no" => false,
                other => return Err(format!("agree expects true|false, got {other:?}").into()),
            };
            let out = classify_with_outcome(ai, cl, agree, th)?;
            println!("{}", serde_json::to_string(&out)?);
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
        "aim-disagreement — Blumenthal-Lee 4-zone HCI classifier\n\n\
USAGE:\n\
  aim-disagreement classify <ai_conf> <clinician_conf> <true|false> [--ai-high X] [--clinician-high Y]\n\n\
EXAMPLE:\n\
  aim-disagreement classify 0.95 0.40 true\n\
  → {{\"zone\": \"ai_leads\", \"ui_action\": \"show_evidence_confirm\", ...}}"
    );
}
