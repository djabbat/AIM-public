//! aim-project-owner CLI (2026-05-06).
//!
//! Mirrors the API surface of `aim-patient-owner` and
//! `aim-experiment-owner` so all three lifecycles speak the same CLI:
//!
//! ```text
//!   aim-project-owner list                        — sorted project ids
//!   aim-project-owner brief <id> [<YYYY-MM-DD>]   — morning brief
//!   aim-project-owner all   [<YYYY-MM-DD>]        — concat for all projects
//!   aim-project-owner phase <id>                  — current phase
//! ```

use std::process::ExitCode;

use aim_project_owner::{list_projects, load, morning_brief, projects_dir, BriefExtras};
use chrono::NaiveDate;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-project-owner: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), String> {
    let dir = resolve_relative(projects_dir());
    let (cmd, rest) = match args.split_first() {
        Some((c, r)) => (c.as_str(), r),
        None => {
            print_usage();
            return Ok(());
        }
    };
    match cmd {
        "list" => {
            for n in list_projects(&dir) {
                println!("{n}");
            }
            Ok(())
        }
        "brief" => {
            let id = rest
                .first()
                .ok_or_else(|| "usage: brief <id> [<YYYY-MM-DD>]".to_string())?;
            let today = parse_today_or_now(rest.get(1).map(String::as_str))?;
            let state = load(&dir, id).map_err(|e| format!("{e}"))?;
            let extras = BriefExtras::default();
            println!("{}", morning_brief(&state, today, &extras));
            Ok(())
        }
        "all" => {
            let today = parse_today_or_now(rest.first().map(String::as_str))?;
            let names = list_projects(&dir);
            if names.is_empty() {
                println!("(no projects configured)");
                return Ok(());
            }
            let mut blocks: Vec<String> = Vec::new();
            for n in names {
                match load(&dir, &n) {
                    Ok(s) => blocks.push(morning_brief(&s, today, &BriefExtras::default())),
                    Err(e) => blocks.push(format!("❌ {n}: {e}")),
                }
            }
            println!("{}", blocks.join("\n\n———\n\n"));
            Ok(())
        }
        "phase" => {
            let id = rest
                .first()
                .ok_or_else(|| "usage: phase <id>".to_string())?;
            let s = load(&dir, id).map_err(|e| format!("{e}"))?;
            println!("{}", s.phase);
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

fn resolve_relative(p: std::path::PathBuf) -> std::path::PathBuf {
    if p.is_absolute() {
        return p;
    }
    if let Ok(c) = std::env::current_dir() {
        let cand = c.join(&p);
        if cand.exists() {
            return cand;
        }
    }
    if let Ok(root) = std::env::var("AIM_ROOT") {
        let cand = std::path::PathBuf::from(root).join(&p);
        if cand.exists() {
            return cand;
        }
    }
    let home = std::env::var("HOME").unwrap_or_default();
    std::path::PathBuf::from(home)
        .join("Desktop/LongevityCommon/AIM")
        .join(&p)
}

fn print_usage() {
    println!(
        "aim-project-owner — project lifecycle CLI\n\n\
USAGE:\n\
  aim-project-owner list\n\
  aim-project-owner brief <id> [<YYYY-MM-DD>]\n\
  aim-project-owner all [<YYYY-MM-DD>]\n\
  aim-project-owner phase <id>\n\n\
ENV:\n\
  AIM_PROJECTS_DIR  — projects YAML root (default: USER/projects/)\n\
  AIM_ROOT          — repo root for relative-path resolution"
    );
}
