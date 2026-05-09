//! aim-patient-comms CLI (Phase D bridge, 2026-05-06).
//!
//! ```text
//!   aim-patient-comms list [<patient_id>]
//!   aim-patient-comms overdue [<YYYY-MM-DD>]
//!   aim-patient-comms add-followup <pid> <topic> [<YYYY-MM-DD>]
//!   aim-patient-comms close-followup <pid> <topic>
//!   aim-patient-comms record <pid> <channel> <in|out> <body...>
//! ```

use std::process::ExitCode;

use aim_patient_comms::{default_db_path, CommsStore};
use chrono::{NaiveDate, Utc};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-patient-comms: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), String> {
    let store = CommsStore::new(default_db_path()).map_err(|e| format!("{e}"))?;
    let (cmd, rest) = match args.split_first() {
        Some((c, r)) => (c.as_str(), r),
        None => {
            print_usage();
            return Ok(());
        }
    };
    match cmd {
        "list" => {
            let pid = rest.first().map(String::as_str);
            for f in store.list_followups(pid).map_err(|e| format!("{e}"))? {
                println!(
                    "{} | {} | awaiting={} | expected={}",
                    f.patient_id,
                    f.topic,
                    f.awaiting_reply,
                    f.expected_response_by
                        .map(|d| d.format("%Y-%m-%d").to_string())
                        .unwrap_or_else(|| "—".into())
                );
            }
            Ok(())
        }
        "overdue" => {
            let today = parse_today_or_now(rest.first().map(String::as_str))?;
            for f in store.overdue_followups(today).map_err(|e| format!("{e}"))? {
                let d = f
                    .expected_response_by
                    .map(|d| (today - d).num_days())
                    .unwrap_or(0);
                println!("{} | {} | {}d past expected", f.patient_id, f.topic, d);
            }
            Ok(())
        }
        "add-followup" => {
            let pid = rest.first().ok_or("usage: add-followup <pid> <topic> [<date>]")?;
            let topic = rest.get(1).ok_or("usage: add-followup <pid> <topic> [<date>]")?;
            let date = rest.get(2).map(String::as_str);
            let exp = match date {
                Some(s) => Some(
                    NaiveDate::parse_from_str(s, "%Y-%m-%d")
                        .map_err(|e| format!("bad date {s:?}: {e}"))?,
                ),
                None => None,
            };
            store.upsert_followup(pid, topic, exp).map_err(|e| format!("{e}"))?;
            println!("ok");
            Ok(())
        }
        "close-followup" => {
            let pid = rest.first().ok_or("usage: close-followup <pid> <topic>")?;
            let topic = rest.get(1).ok_or("usage: close-followup <pid> <topic>")?;
            store.close_followup(pid, topic).map_err(|e| format!("{e}"))?;
            println!("ok");
            Ok(())
        }
        "record" => {
            let pid = rest.first().ok_or("usage: record <pid> <channel> <in|out> <body...>")?;
            let channel = rest.get(1).ok_or("usage: record <pid> <channel> <in|out> <body...>")?;
            let direction = rest.get(2).ok_or("usage: record <pid> <channel> <in|out> <body...>")?;
            let body: String = rest[3..].join(" ");
            let id = store
                .record_message(pid, channel, direction, &body, Utc::now())
                .map_err(|e| format!("{e}"))?;
            println!("recorded id={id}");
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
        "aim-patient-comms — patient communications tracker CLI\n\n\
USAGE:\n\
  aim-patient-comms list [<patient_id>]\n\
  aim-patient-comms overdue [<YYYY-MM-DD>]\n\
  aim-patient-comms add-followup <pid> <topic> [<YYYY-MM-DD>]\n\
  aim-patient-comms close-followup <pid> <topic>\n\
  aim-patient-comms record <pid> <channel> <in|out> <body...>"
    );
}
