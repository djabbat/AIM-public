//! aim-cli — top-level subcommand dispatcher (port of aim_cli.py).
//!
//! Parses `aim <cmd> [args]` into a typed [`Command`] enum. The
//! actual subcommand handlers live in dedicated crates (aim-daily-brief,
//! aim-recall-cli, aim-weekly-digest, aim-auto-eval, aim-user-keys, …)
//! and the binary wires them together. This crate keeps the parser
//! deterministic and unit-testable.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "kebab-case")]
pub enum Command {
    Brief {
        project: Option<String>,
        lang: Option<String>,
    },
    Recall {
        query: String,
        k: u32,
        json: bool,
    },
    Digest,
    Followups {
        save: bool,
    },
    EvalRun {
        version: Option<String>,
        tag: Option<String>,
    },
    EvalAuto,
    EvalList,
    ProjectList,
    ProjectArchive {
        name: String,
        reason: String,
    },
    ProjectUnarchive {
        name: String,
    },
    ProjectSweep {
        apply: bool,
        idle_months: u32,
    },
    ProjectTransition {
        name: String,
        dst: String,
        reason: String,
    },
    Do {
        query: String,
    },
    SetupKey {
        providers: Vec<String>,
        status: bool,
    },
    Serve {
        once: bool,
        tick_seconds: u32,
    },
    RoutineList,
    RoutineRun {
        name: String,
    },
    Memory,
    Cost,
    Escalate,
    Health,
    Version,
}

#[derive(Debug, Error, PartialEq)]
pub enum ParseError {
    #[error("missing subcommand; usage: aim <cmd> [args]")]
    MissingSubcommand,
    #[error("unknown subcommand: {0}")]
    UnknownSubcommand(String),
    #[error("missing argument: {0}")]
    MissingArgument(&'static str),
    #[error("invalid number for {0}: {1}")]
    InvalidNumber(&'static str, String),
}

pub fn parse(args: &[String]) -> Result<Command, ParseError> {
    let mut i = 0;
    let cmd = args
        .first()
        .ok_or(ParseError::MissingSubcommand)?
        .as_str();
    i += 1;
    let rest = &args[i..];
    match cmd {
        "brief" => {
            let project = take_opt(rest, "--project");
            let lang = take_opt(rest, "--lang");
            Ok(Command::Brief { project, lang })
        }
        "recall" => {
            let query_words = collect_positional(rest);
            if query_words.is_empty() {
                return Err(ParseError::MissingArgument("query"));
            }
            let k = take_opt(rest, "--k")
                .map(|v| v.parse::<u32>().map_err(|_| ParseError::InvalidNumber("--k", v)))
                .transpose()?
                .unwrap_or(5);
            let json = has_flag(rest, "--json");
            Ok(Command::Recall {
                query: query_words.join(" "),
                k,
                json,
            })
        }
        "digest" => Ok(Command::Digest),
        "followups" => Ok(Command::Followups {
            save: has_flag(rest, "--save"),
        }),
        "eval" => parse_eval(rest),
        "project" => parse_project(rest),
        "do" => {
            let query_words = collect_positional(rest);
            if query_words.is_empty() {
                return Err(ParseError::MissingArgument("query"));
            }
            Ok(Command::Do {
                query: query_words.join(" "),
            })
        }
        "setup-key" => {
            let providers = take_multi(rest, "--provider");
            Ok(Command::SetupKey {
                providers,
                status: has_flag(rest, "--status"),
            })
        }
        "serve" => Ok(Command::Serve {
            once: has_flag(rest, "--once"),
            tick_seconds: take_opt(rest, "--tick-seconds")
                .map(|v| {
                    v.parse::<u32>()
                        .map_err(|_| ParseError::InvalidNumber("--tick-seconds", v))
                })
                .transpose()?
                .unwrap_or(30),
        }),
        "routine" => parse_routine(rest),
        "memory" => Ok(Command::Memory),
        "cost" => Ok(Command::Cost),
        "escalate" => Ok(Command::Escalate),
        "health" => Ok(Command::Health),
        "version" => Ok(Command::Version),
        other => Err(ParseError::UnknownSubcommand(other.to_string())),
    }
}

fn parse_eval(rest: &[String]) -> Result<Command, ParseError> {
    let head = rest.first().map(|s| s.as_str()).unwrap_or("run");
    match head {
        "run" => {
            let body = if !rest.is_empty() && rest[0] == "run" { &rest[1..] } else { rest };
            let version = take_opt(body, "--version");
            let tag = take_opt(body, "--tag");
            Ok(Command::EvalRun { version, tag })
        }
        "auto" => Ok(Command::EvalAuto),
        "list" => Ok(Command::EvalList),
        other => Err(ParseError::UnknownSubcommand(format!("eval {}", other))),
    }
}

fn parse_project(rest: &[String]) -> Result<Command, ParseError> {
    let head = rest
        .first()
        .ok_or(ParseError::MissingArgument("project subcommand"))?
        .as_str();
    let body = &rest[1..];
    match head {
        "list" => Ok(Command::ProjectList),
        "archive" => {
            let name = first_positional(body, "name")?;
            let reason = take_opt(body, "--reason").unwrap_or_default();
            Ok(Command::ProjectArchive { name, reason })
        }
        "unarchive" => Ok(Command::ProjectUnarchive {
            name: first_positional(body, "name")?,
        }),
        "sweep" => Ok(Command::ProjectSweep {
            apply: has_flag(body, "--apply"),
            idle_months: take_opt(body, "--idle-months")
                .map(|v| {
                    v.parse::<u32>()
                        .map_err(|_| ParseError::InvalidNumber("--idle-months", v))
                })
                .transpose()?
                .unwrap_or(6),
        }),
        "transition" => {
            let positionals = collect_positional(body);
            if positionals.len() < 2 {
                return Err(ParseError::MissingArgument("name + dst"));
            }
            let name = positionals[0].clone();
            let dst = positionals[1].clone();
            let reason = take_opt(body, "--reason").unwrap_or_default();
            Ok(Command::ProjectTransition { name, dst, reason })
        }
        other => Err(ParseError::UnknownSubcommand(format!("project {}", other))),
    }
}

fn parse_routine(rest: &[String]) -> Result<Command, ParseError> {
    let head = rest.first().map(|s| s.as_str()).unwrap_or("list");
    match head {
        "list" => Ok(Command::RoutineList),
        "run" => {
            let body = &rest[1..];
            Ok(Command::RoutineRun {
                name: first_positional(body, "name")?,
            })
        }
        other => Err(ParseError::UnknownSubcommand(format!("routine {}", other))),
    }
}

// ── tiny argv helpers ────────────────────────────────────────────────────

fn take_opt(args: &[String], flag: &str) -> Option<String> {
    let pos = args.iter().position(|a| a == flag)?;
    args.get(pos + 1).cloned()
}

fn take_multi(args: &[String], flag: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut iter = args.iter().enumerate();
    while let Some((i, a)) = iter.next() {
        if a == flag {
            if let Some(v) = args.get(i + 1) {
                out.push(v.clone());
            }
        }
    }
    out
}

fn has_flag(args: &[String], flag: &str) -> bool {
    args.iter().any(|a| a == flag)
}

fn collect_positional(args: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < args.len() {
        let a = &args[i];
        if a.starts_with("--") {
            // most --flag have a value following
            i += 2;
            continue;
        }
        out.push(a.clone());
        i += 1;
    }
    out
}

fn first_positional(args: &[String], what: &'static str) -> Result<String, ParseError> {
    collect_positional(args)
        .into_iter()
        .next()
        .ok_or(ParseError::MissingArgument(what))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn p(args: &[&str]) -> Result<Command, ParseError> {
        let v: Vec<String> = args.iter().map(|s| s.to_string()).collect();
        parse(&v)
    }

    // ── basic commands ────────────────────────────────────────────────────

    #[test]
    fn missing_subcommand() {
        assert_eq!(p(&[]).unwrap_err(), ParseError::MissingSubcommand);
    }

    #[test]
    fn unknown_subcommand() {
        let err = p(&["xyzzy"]).unwrap_err();
        assert_eq!(err, ParseError::UnknownSubcommand("xyzzy".into()));
    }

    #[test]
    fn version_health_memory() {
        assert_eq!(p(&["version"]).unwrap(), Command::Version);
        assert_eq!(p(&["health"]).unwrap(), Command::Health);
        assert_eq!(p(&["memory"]).unwrap(), Command::Memory);
    }

    // ── brief ─────────────────────────────────────────────────────────────

    #[test]
    fn brief_no_options() {
        assert_eq!(
            p(&["brief"]).unwrap(),
            Command::Brief { project: None, lang: None }
        );
    }

    #[test]
    fn brief_with_project_and_lang() {
        let cmd = p(&["brief", "--project", "FCLC", "--lang", "en"]).unwrap();
        assert_eq!(
            cmd,
            Command::Brief {
                project: Some("FCLC".into()),
                lang: Some("en".into()),
            }
        );
    }

    // ── recall ────────────────────────────────────────────────────────────

    #[test]
    fn recall_joins_query_words() {
        let cmd = p(&["recall", "FCLC", "deadline", "--k", "10"]).unwrap();
        assert_eq!(
            cmd,
            Command::Recall {
                query: "FCLC deadline".into(),
                k: 10,
                json: false,
            }
        );
    }

    #[test]
    fn recall_default_k() {
        let cmd = p(&["recall", "deadlines"]).unwrap();
        let Command::Recall { k, .. } = cmd else {
            panic!()
        };
        assert_eq!(k, 5);
    }

    #[test]
    fn recall_invalid_k() {
        assert!(matches!(
            p(&["recall", "x", "--k", "abc"]).unwrap_err(),
            ParseError::InvalidNumber("--k", _)
        ));
    }

    #[test]
    fn recall_missing_query() {
        let err = p(&["recall"]).unwrap_err();
        assert_eq!(err, ParseError::MissingArgument("query"));
    }

    // ── eval ──────────────────────────────────────────────────────────────

    #[test]
    fn eval_run_default_when_omitted() {
        // `aim eval` with no subcommand should fall to run
        let cmd = p(&["eval"]).unwrap();
        assert_eq!(
            cmd,
            Command::EvalRun {
                version: None,
                tag: None
            }
        );
    }

    #[test]
    fn eval_run_with_version_and_tag() {
        let cmd = p(&["eval", "run", "--version", "v1", "--tag", "diag"]).unwrap();
        assert_eq!(
            cmd,
            Command::EvalRun {
                version: Some("v1".into()),
                tag: Some("diag".into()),
            }
        );
    }

    #[test]
    fn eval_auto_and_list() {
        assert_eq!(p(&["eval", "auto"]).unwrap(), Command::EvalAuto);
        assert_eq!(p(&["eval", "list"]).unwrap(), Command::EvalList);
    }

    // ── project ──────────────────────────────────────────────────────────

    #[test]
    fn project_archive_with_reason() {
        let cmd = p(&["project", "archive", "Sulkalmakhi", "--reason", "dormant"]).unwrap();
        assert_eq!(
            cmd,
            Command::ProjectArchive {
                name: "Sulkalmakhi".into(),
                reason: "dormant".into(),
            }
        );
    }

    #[test]
    fn project_sweep_with_apply() {
        let cmd = p(&["project", "sweep", "--apply", "--idle-months", "12"]).unwrap();
        assert_eq!(
            cmd,
            Command::ProjectSweep {
                apply: true,
                idle_months: 12,
            }
        );
    }

    #[test]
    fn project_transition_two_positionals() {
        let cmd = p(&["project", "transition", "FCLC", "ACTIVE"]).unwrap();
        assert_eq!(
            cmd,
            Command::ProjectTransition {
                name: "FCLC".into(),
                dst: "ACTIVE".into(),
                reason: String::new(),
            }
        );
    }

    #[test]
    fn project_transition_needs_two_args() {
        let err = p(&["project", "transition", "FCLC"]).unwrap_err();
        assert_eq!(err, ParseError::MissingArgument("name + dst"));
    }

    // ── do / setup-key / serve / routine ─────────────────────────────────

    #[test]
    fn do_joins_words() {
        let cmd = p(&["do", "find", "patient", "Smith"]).unwrap();
        assert_eq!(
            cmd,
            Command::Do {
                query: "find patient Smith".into()
            }
        );
    }

    #[test]
    fn setup_key_repeated_provider() {
        let cmd = p(&["setup-key", "--provider", "deepseek", "--provider", "groq"]).unwrap();
        assert_eq!(
            cmd,
            Command::SetupKey {
                providers: vec!["deepseek".into(), "groq".into()],
                status: false,
            }
        );
    }

    #[test]
    fn setup_key_status_only() {
        let cmd = p(&["setup-key", "--status"]).unwrap();
        assert_eq!(
            cmd,
            Command::SetupKey {
                providers: vec![],
                status: true,
            }
        );
    }

    #[test]
    fn serve_once_flag() {
        let cmd = p(&["serve", "--once", "--tick-seconds", "60"]).unwrap();
        assert_eq!(
            cmd,
            Command::Serve {
                once: true,
                tick_seconds: 60,
            }
        );
    }

    #[test]
    fn routine_list_default() {
        assert_eq!(p(&["routine"]).unwrap(), Command::RoutineList);
    }

    #[test]
    fn routine_run_with_name() {
        let cmd = p(&["routine", "run", "morning_check"]).unwrap();
        assert_eq!(
            cmd,
            Command::RoutineRun {
                name: "morning_check".into()
            }
        );
    }
}
