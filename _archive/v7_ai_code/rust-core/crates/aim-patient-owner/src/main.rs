//! aim-patient-owner CLI (Phase A bridge, 2026-05-06).
//!
//! Minimal stdout-only CLI so Python `scripts/daily_brief.py` can
//! call the Rust patient brief without re-implementing the parser in
//! Python. No clap dep — std::env::args is enough for 4 subcommands.
//!
//! ```text
//!   aim-patient-owner list                       — sorted patient ids (one per line)
//!   aim-patient-owner brief <id> [<YYYY-MM-DD>]  — single patient brief
//!   aim-patient-owner all [<YYYY-MM-DD>]         — concat all patient briefs
//!   aim-patient-owner phase <id>                 — current phase
//! ```
//!
//! The patients root is read from `AIM_PATIENTS_DIR` (or `Patients`
//! relative to CWD). All errors print to stderr with exit code 1.

use std::process::ExitCode;

use aim_patient_owner::{patients_dir, PatientOwner};
use chrono::NaiveDate;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-patient-owner: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), String> {
    let (cmd, rest) = match args.split_first() {
        Some((c, r)) => (c.as_str(), r),
        None => {
            print_usage();
            return Ok(());
        }
    };

    let owner = PatientOwner::new(patients_dir());

    match cmd {
        "list" => {
            for name in owner.list_patients() {
                println!("{name}");
            }
            Ok(())
        }
        "brief" => {
            let id = rest
                .first()
                .ok_or_else(|| "usage: brief <id> [<YYYY-MM-DD>]".to_string())?;
            let today = parse_today_or_now(rest.get(1).map(String::as_str))?;
            let brief = owner
                .morning_brief(id, today)
                .map_err(|e| format!("{e}"))?;
            println!("{brief}");
            Ok(())
        }
        "all" => {
            let today = parse_today_or_now(rest.first().map(String::as_str))?;
            println!("{}", owner.all_briefs(today));
            Ok(())
        }
        "phase" => {
            let id = rest
                .first()
                .ok_or_else(|| "usage: phase <id>".to_string())?;
            let mem = owner.load(id).map_err(|e| format!("{e}"))?;
            println!("{}", mem.phase);
            Ok(())
        }
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help")),
    }
}

fn parse_today_or_now(s: Option<&str>) -> Result<NaiveDate, String> {
    match s {
        Some(s) => NaiveDate::parse_from_str(s, "%Y-%m-%d")
            .map_err(|e| format!("bad date {s:?}: {e}")),
        None => Ok(chrono::Local::now().date_naive()),
    }
}

fn print_usage() {
    println!(
        "aim-patient-owner — patient lifecycle brief CLI\n\n\
USAGE:\n\
  aim-patient-owner list\n\
  aim-patient-owner brief <id> [<YYYY-MM-DD>]\n\
  aim-patient-owner all [<YYYY-MM-DD>]\n\
  aim-patient-owner phase <id>\n\n\
ENV:\n\
  AIM_PATIENTS_DIR  — patients root (default: Patients/)"
    );
}
