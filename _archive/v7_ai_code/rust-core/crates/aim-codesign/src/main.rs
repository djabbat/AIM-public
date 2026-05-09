//! aim-codesign CLI — append + query patient co-design events.
//!
//! Output is JSON on stdout (one event per line for `events`/`filter`,
//! single line for `record`/`mark`), so Python shims and Phoenix
//! LiveViews can parse without a wrapper library.
//!
//! Subcommands:
//!   record <patient_id> <kind> <topic> [--decision-id ID] [--by patient|caregiver] [--notes "..."]
//!   events <patient_id>
//!   mark   <patient_id> <decision_id>     # prints true/false
//!   filter <patient_id> <kind1,kind2,...>
//!
//! All commands take an optional `--patients-dir <path>` (default:
//! $AIM_PATIENTS_DIR or ./Patients).

use std::env;
use std::path::PathBuf;
use std::process::ExitCode;

use aim_codesign::{
    events, filter_by_kind, mark_codesigned, record, By, CodesignError, Kind,
};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-codesign: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args.split_first().ok_or("usage: aim-codesign <cmd> ...; try --help")?;
    let mut rest: Vec<&str> = rest.iter().map(String::as_str).collect();
    let patients_dir = take_patients_dir(&mut rest);
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "record" => {
            // Take optional flags first to leave only positionals.
            let decision_id = take_opt(&mut rest, "--decision-id");
            let by_str = take_opt(&mut rest, "--by").unwrap_or_else(|| "patient".to_string());
            let notes = take_opt(&mut rest, "--notes").unwrap_or_default();
            let pid = rest.first().ok_or("record: <patient_id> required")?.to_string();
            let kind = Kind::parse(rest.get(1).ok_or("record: <kind> required")?)?;
            let topic = rest.get(2).ok_or("record: <topic> required")?.to_string();
            let by = By::parse(&by_str)?;
            let e = record(&patients_dir, &pid, kind, &topic,
                           decision_id.as_deref(), by, &notes)?;
            println!("{}", serde_json::to_string(&e)?);
            Ok(())
        }
        "events" => {
            let pid = rest.first().ok_or("events: <patient_id> required")?.to_string();
            for e in events(&patients_dir, &pid)? {
                println!("{}", serde_json::to_string(&e)?);
            }
            Ok(())
        }
        "mark" => {
            let pid = rest.first().ok_or("mark: <patient_id> required")?.to_string();
            let did = rest.get(1).ok_or("mark: <decision_id> required")?.to_string();
            let ok = mark_codesigned(&patients_dir, &pid, &did)?;
            println!("{ok}");
            Ok(())
        }
        "filter" => {
            let pid = rest.first().ok_or("filter: <patient_id> required")?.to_string();
            let kinds_str = rest.get(1).ok_or("filter: <kind1,kind2> required")?.to_string();
            let kinds: Vec<Kind> = kinds_str
                .split(',')
                .map(|k| Kind::parse(k.trim()))
                .collect::<Result<_, _>>()?;
            for e in filter_by_kind(&patients_dir, &pid, &kinds)? {
                println!("{}", serde_json::to_string(&e)?);
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn take_patients_dir(rest: &mut Vec<&str>) -> PathBuf {
    if let Some(p) = take_opt(rest, "--patients-dir") {
        PathBuf::from(p)
    } else {
        PathBuf::from(
            env::var("AIM_PATIENTS_DIR").unwrap_or_else(|_| "Patients".to_string()),
        )
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
        "aim-codesign — patient co-design event log (Patient as a Project)\n\n\
USAGE:\n\
  aim-codesign record <patient_id> <kind> <topic> [--decision-id ID] [--by patient|caregiver] [--notes \"...\"] [--patients-dir DIR]\n\
  aim-codesign events <patient_id> [--patients-dir DIR]\n\
  aim-codesign mark   <patient_id> <decision_id> [--patients-dir DIR]\n\
  aim-codesign filter <patient_id> <kind,kind,...> [--patients-dir DIR]\n\n\
KINDS: consulted | agreed | modified | refused | alternative\n\
ENV: AIM_PATIENTS_DIR (default: ./Patients)\n\n\
Output is JSON Lines on stdout."
    );
}

#[allow(dead_code)]
fn _explicit_codesign_error(_e: CodesignError) {}
