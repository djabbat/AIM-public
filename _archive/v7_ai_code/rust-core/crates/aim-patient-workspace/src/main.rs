//! aim-patient-workspace — JSON CLI for Phoenix LiveView consumption.
//!
//! Subcommands:
//!   list                         — sorted patient ids (newline-separated)
//!   overview <id>                — full PatientView JSON to stdout
//!   core-files <id>              — only core file presence array (compact)
//!   labs <id>                    — only lab file scan array
//!
//! Env: `AIM_PATIENTS_DIR` (default `Patients`).

use std::process::ExitCode;

use aim_patient_workspace::WorkspaceBuilder;

fn usage() -> &'static str {
    "aim-patient-workspace — patient-as-project unified view CLI\n\
     \n\
     USAGE:\n\
     aim-patient-workspace list\n\
     aim-patient-workspace overview <id>\n\
     aim-patient-workspace core-files <id>\n\
     aim-patient-workspace labs <id>\n\
     \n\
     ENV:\n\
     AIM_PATIENTS_DIR  — patients root (default: Patients/)"
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let builder = WorkspaceBuilder::from_env();

    match args.first().map(String::as_str) {
        Some("list") => {
            for id in builder.list() {
                println!("{id}");
            }
            ExitCode::SUCCESS
        }
        Some("overview") => {
            let id = match args.get(1) {
                Some(s) => s,
                None => {
                    eprintln!("{}", usage());
                    return ExitCode::from(2);
                }
            };
            match builder.build(id) {
                Ok(view) => {
                    match serde_json::to_string_pretty(&view) {
                        Ok(s) => {
                            println!("{s}");
                            ExitCode::SUCCESS
                        }
                        Err(e) => {
                            eprintln!("serde error: {e}");
                            ExitCode::from(3)
                        }
                    }
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            }
        }
        Some("core-files") => {
            let id = match args.get(1) {
                Some(s) => s,
                None => {
                    eprintln!("{}", usage());
                    return ExitCode::from(2);
                }
            };
            match builder.build(id) {
                Ok(view) => {
                    println!(
                        "{}",
                        serde_json::to_string(&view.core_files).unwrap_or_default()
                    );
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            }
        }
        Some("labs") => {
            let id = match args.get(1) {
                Some(s) => s,
                None => {
                    eprintln!("{}", usage());
                    return ExitCode::from(2);
                }
            };
            match builder.build(id) {
                Ok(view) => {
                    println!(
                        "{}",
                        serde_json::to_string(&view.lab_files).unwrap_or_default()
                    );
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            }
        }
        Some("--help" | "-h") | None => {
            println!("{}", usage());
            ExitCode::SUCCESS
        }
        Some(other) => {
            eprintln!("unknown subcommand: {other}\n\n{}", usage());
            ExitCode::from(2)
        }
    }
}
