//! aim-experiment-owner CLI (Phase B bridge, 2026-05-06).

use std::process::ExitCode;

use aim_experiment_owner::{experiments_dir, ExperimentOwner};
use aim_mcp_lab_runner::LabRunnerConfig;
use chrono::NaiveDate;
use std::path::PathBuf;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-experiment-owner: {msg}");
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
    let owner = ExperimentOwner::new(experiments_dir());
    match cmd {
        "list" => {
            for n in owner.list_experiments() {
                println!("{n}");
            }
            Ok(())
        }
        "brief" => {
            let id = rest
                .first()
                .ok_or_else(|| "usage: brief <name> [<YYYY-MM-DD>]".to_string())?;
            let today = parse_today_or_now(rest.get(1).map(String::as_str))?;
            let b = owner.morning_brief(id, today).map_err(|e| format!("{e}"))?;
            println!("{b}");
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
                .ok_or_else(|| "usage: phase <name>".to_string())?;
            let s = owner.load(id).map_err(|e| format!("{e}"))?;
            println!("{}", s.phase);
            Ok(())
        }
        "mcp-config" => {
            // Generate ~/.aim/mcp/<name>.toml from experiment YAML.
            // Uses experiment.canonical as project_root for Claude-Code
            // worker. Optional second arg: explicit output dir.
            let id = rest
                .first()
                .ok_or_else(|| "usage: mcp-config <name> [<out_dir>]".to_string())?;
            let state = owner.load(id).map_err(|e| format!("{e}"))?;
            let project_root = if state.canonical.is_empty() {
                PathBuf::from(".")
            } else {
                PathBuf::from(&state.canonical)
            };
            let cfg = LabRunnerConfig::claude_code_default(&state.name, &project_root);
            let dir = match rest.get(1) {
                Some(d) => PathBuf::from(d),
                None => LabRunnerConfig::default_dir(),
            };
            let p = cfg.write_to_dir(&dir).map_err(|e| format!("{e}"))?;
            println!("wrote MCP config: {}", p.display());
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
        "aim-experiment-owner — experiment lifecycle CLI\n\n\
USAGE:\n\
  aim-experiment-owner list\n\
  aim-experiment-owner brief <name> [<YYYY-MM-DD>]\n\
  aim-experiment-owner all [<YYYY-MM-DD>]\n\
  aim-experiment-owner phase <name>\n\
  aim-experiment-owner mcp-config <name> [<out_dir>]\n\n\
ENV:\n\
  AIM_EXPERIMENTS_DIR  — experiments YAML root (default: USER/experiments/)"
    );
}
