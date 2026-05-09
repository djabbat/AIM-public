//! aim-patient-events CLI — Phoenix LiveView calls this.
//!
//! Subcommands:
//!   list <id> [--limit N]           — timeline desc, JSON array
//!   add <id> --date <YYYY-MM-DD> --kind <K> --description <T> [--source S] [--payload <JSON>]
//!   add-correction <id> --of <event_id> --date <YYYY-MM-DD> --description <T>
//!   count <id>
//!
//! Env: AIM_PATIENTS_DIR (default Patients/).

use std::process::ExitCode;

use aim_patient_events::{Event, EventKind, EventSource, EventStore};
use chrono::NaiveDate;

fn usage() -> &'static str {
    "aim-patient-events — patient timeline event log\n\
     \n\
     USAGE:\n\
     aim-patient-events list <id> [--limit N]\n\
     aim-patient-events add <id> --date <YYYY-MM-DD> --kind <KIND> --description <TEXT> [--source S] [--payload <JSON>]\n\
     aim-patient-events add-correction <id> --of <event_id> --date <YYYY-MM-DD> --description <TEXT>\n\
     aim-patient-events count <id>\n\
     \n\
     KIND: complaint, diagnosis, lab, treatment, allergy_reported, visit, note, correction\n\
     SOURCE: manual (default), ocr, agent, pam, doctor, codesign, kernel\n\
     ENV: AIM_PATIENTS_DIR (default Patients/)"
}

fn parse_kind(s: &str) -> EventKind {
    match s {
        "complaint" => EventKind::Complaint,
        "diagnosis" => EventKind::Diagnosis,
        "lab" => EventKind::Lab,
        "treatment" => EventKind::Treatment,
        "allergy_reported" => EventKind::AllergyReported,
        "visit" => EventKind::Visit,
        "note" => EventKind::Note,
        "correction" => EventKind::Correction,
        other => EventKind::Custom(other.into()),
    }
}

fn parse_source(s: &str) -> EventSource {
    match s {
        "manual" | "" => EventSource::Manual,
        "ocr" => EventSource::Ocr,
        "agent" => EventSource::Agent,
        "pam" => EventSource::Pam,
        "doctor" => EventSource::Doctor,
        "codesign" => EventSource::Codesign,
        "kernel" => EventSource::Kernel,
        _ => EventSource::Manual,
    }
}

struct Flags {
    date: Option<NaiveDate>,
    kind: Option<String>,
    description: Option<String>,
    source: String,
    payload: Option<String>,
    limit: Option<usize>,
    of: Option<String>,
}

fn parse_flags(rest: Vec<String>) -> Result<Flags, String> {
    let mut f = Flags {
        date: None,
        kind: None,
        description: None,
        source: "manual".into(),
        payload: None,
        limit: None,
        of: None,
    };
    let mut iter = rest.into_iter();
    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--date" => {
                let v = iter.next().ok_or_else(|| "--date needs value".to_string())?;
                f.date = Some(
                    NaiveDate::parse_from_str(&v, "%Y-%m-%d")
                        .map_err(|e| format!("bad --date {v}: {e}"))?,
                );
            }
            "--kind" => f.kind = Some(iter.next().ok_or_else(|| "--kind".to_string())?),
            "--description" => {
                f.description = Some(iter.next().ok_or_else(|| "--description".to_string())?)
            }
            "--source" => f.source = iter.next().ok_or_else(|| "--source".to_string())?,
            "--payload" => f.payload = Some(iter.next().ok_or_else(|| "--payload".to_string())?),
            "--limit" => {
                let v = iter.next().ok_or_else(|| "--limit".to_string())?;
                f.limit = Some(v.parse::<usize>().map_err(|e| format!("--limit: {e}"))?);
            }
            "--of" => f.of = Some(iter.next().ok_or_else(|| "--of".to_string())?),
            other => return Err(format!("unknown flag: {other}")),
        }
    }
    Ok(f)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let store = EventStore::from_env();

    let sub = match args.first() {
        Some(s) => s.clone(),
        None => {
            println!("{}", usage());
            return ExitCode::SUCCESS;
        }
    };

    if sub == "--help" || sub == "-h" {
        println!("{}", usage());
        return ExitCode::SUCCESS;
    }

    let id = match args.get(1) {
        Some(s) => s.clone(),
        None => {
            eprintln!("missing patient id\n\n{}", usage());
            return ExitCode::from(2);
        }
    };

    let flags = match parse_flags(args.into_iter().skip(2).collect()) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("{e}\n\n{}", usage());
            return ExitCode::from(2);
        }
    };

    match sub.as_str() {
        "list" => {
            let limit = flags.limit.unwrap_or(500);
            match store.timeline(&id, limit) {
                Ok(events) => {
                    println!(
                        "{}",
                        serde_json::to_string_pretty(&events).unwrap_or_default()
                    );
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            }
        }
        "add" => {
            let date = match flags.date {
                Some(d) => d,
                None => {
                    eprintln!("--date is required");
                    return ExitCode::from(2);
                }
            };
            let kind = match flags.kind {
                Some(k) => parse_kind(&k),
                None => {
                    eprintln!("--kind is required");
                    return ExitCode::from(2);
                }
            };
            let desc = match flags.description {
                Some(d) => d,
                None => {
                    eprintln!("--description is required");
                    return ExitCode::from(2);
                }
            };
            let mut event = Event::new(date, kind, desc, parse_source(&flags.source));
            if let Some(p) = flags.payload {
                match serde_json::from_str::<serde_json::Value>(&p) {
                    Ok(v) => event = event.with_payload(v),
                    Err(e) => {
                        eprintln!("bad --payload JSON: {e}");
                        return ExitCode::from(2);
                    }
                }
            }
            match store.append(&id, event) {
                Ok(saved) => {
                    println!(
                        "{}",
                        serde_json::to_string_pretty(&saved).unwrap_or_default()
                    );
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            }
        }
        "add-correction" => {
            let of = match flags.of {
                Some(o) => o,
                None => {
                    eprintln!("--of <event_id> is required");
                    return ExitCode::from(2);
                }
            };
            let date = match flags.date {
                Some(d) => d,
                None => {
                    eprintln!("--date is required");
                    return ExitCode::from(2);
                }
            };
            let desc = match flags.description {
                Some(d) => d,
                None => {
                    eprintln!("--description is required");
                    return ExitCode::from(2);
                }
            };
            let event = Event::new(date, EventKind::Correction, desc, parse_source(&flags.source))
                .correcting(of);
            match store.append(&id, event) {
                Ok(saved) => {
                    println!("{}", serde_json::to_string_pretty(&saved).unwrap_or_default());
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            }
        }
        "count" => match store.count(&id) {
            Ok(n) => {
                println!("{n}");
                ExitCode::SUCCESS
            }
            Err(e) => {
                eprintln!("error: {e}");
                ExitCode::from(1)
            }
        },
        other => {
            eprintln!("unknown subcommand: {other}\n\n{}", usage());
            ExitCode::from(2)
        }
    }
}
