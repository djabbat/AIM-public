//! aim-hive-consumer CLI — closes the Hive cycle worker-side.
//!
//! Subcommands:
//!   pull   [--queen-url U] [--since TS] [--dry-run] [--json]
//!                                        # one-shot pull + apply
//!   loop   [--queen-url U] [--interval S] [--dry-run]
//!                                        # long-poll (Ctrl-C to stop)
//!   status [--json]                      # sync_state from local DB
//!   opt-out  --kind K --pattern P
//!   opt-in   --kind K --pattern P
//!
//! ENV: AIM_HIVE_QUEEN_URL, AIM_USER_TOKEN, AIM_HIVE_STATE_DB,
//!      AIM_HIVE_POLL_INTERVAL_S (default 300), AIM_EVAL_CASES_DIR.

use std::process::ExitCode;
use std::time::Duration;

use aim_hive_consumer::{apply, pull, ApplyOpts, ConsumerState};

#[tokio::main]
async fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(args).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-hive-consumer: {e}");
            ExitCode::FAILURE
        }
    }
}

async fn cli(args: Vec<String>) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("--help");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "pull" => cmd_pull(rest).await,
        "loop" => cmd_loop(rest).await,
        "status" => cmd_status(rest),
        "opt-out" => cmd_opt(rest, true),
        "opt-in" => cmd_opt(rest, false),
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

async fn cmd_pull(mut rest: Vec<&str>) -> Result<(), Box<dyn std::error::Error>> {
    let dry_run = take_flag(&mut rest, "--dry-run");
    let json_out = take_flag(&mut rest, "--json");
    let queen_url = take_opt(&mut rest, "--queen-url");
    let since = take_opt(&mut rest, "--since");

    let state = ConsumerState::open_default()?;
    let updates = pull(queen_url.as_deref(), since.as_deref(), &state).await?;

    let mut results = Vec::with_capacity(updates.len());
    for u in &updates {
        let r = apply(
            u,
            &state,
            &ApplyOpts {
                dry_run,
                ..Default::default()
            },
        )?;
        results.push(r);
    }

    if json_out {
        println!("{}", serde_json::to_string(&results)?);
    } else {
        let n_inst = results.iter().filter(|r| r.installed).count();
        let n_skip = results.iter().filter(|r| r.skipped).count();
        let n_dry = results.iter().filter(|r| !r.installed && !r.skipped).count();
        println!(
            "pulled {} update(s): installed={} skipped={} dry={}",
            updates.len(),
            n_inst,
            n_skip,
            n_dry
        );
        for r in &results {
            let tag = if r.installed {
                "INSTALL"
            } else if r.skipped {
                "SKIP"
            } else {
                "DRY"
            };
            let why = r.skipped_reason.as_deref().unwrap_or("");
            println!("  {tag:<7} {} {}", r.update_id, why);
        }
    }
    Ok(())
}

async fn cmd_loop(mut rest: Vec<&str>) -> Result<(), Box<dyn std::error::Error>> {
    let dry_run = take_flag(&mut rest, "--dry-run");
    let queen_url = take_opt(&mut rest, "--queen-url");
    let interval_s = take_opt(&mut rest, "--interval")
        .map(|s| s.parse::<u64>())
        .transpose()?
        .or_else(|| {
            std::env::var("AIM_HIVE_POLL_INTERVAL_S")
                .ok()
                .and_then(|s| s.parse::<u64>().ok())
        })
        .unwrap_or(300);

    let state = ConsumerState::open_default()?;
    eprintln!(
        "aim-hive-consumer loop: interval={interval_s}s queen={} dry_run={dry_run}",
        queen_url
            .as_deref()
            .or(option_env!("AIM_HIVE_QUEEN_URL"))
            .unwrap_or("(env)")
    );

    loop {
        let tick_started = chrono::Utc::now();
        match pull(queen_url.as_deref(), None, &state).await {
            Ok(updates) => {
                let mut n_inst = 0u32;
                let mut n_skip = 0u32;
                for u in &updates {
                    match apply(
                        u,
                        &state,
                        &ApplyOpts {
                            dry_run,
                            ..Default::default()
                        },
                    ) {
                        Ok(r) => {
                            if r.installed {
                                n_inst += 1;
                            } else if r.skipped {
                                n_skip += 1;
                            }
                        }
                        Err(e) => eprintln!("apply error on {}: {e}", u.id),
                    }
                }
                if !updates.is_empty() {
                    eprintln!(
                        "[{}] tick: {} update(s) installed={} skipped={}",
                        tick_started.format("%Y-%m-%dT%H:%M:%SZ"),
                        updates.len(),
                        n_inst,
                        n_skip
                    );
                }
            }
            Err(e) => eprintln!(
                "[{}] pull error: {e}",
                tick_started.format("%Y-%m-%dT%H:%M:%SZ")
            ),
        }
        tokio::time::sleep(Duration::from_secs(interval_s)).await;
    }
}

fn cmd_status(mut rest: Vec<&str>) -> Result<(), Box<dyn std::error::Error>> {
    let json_out = take_flag(&mut rest, "--json");
    let state = ConsumerState::open_default()?;
    let s = state.sync_state()?;
    if json_out {
        println!("{}", serde_json::to_string(&s)?);
    } else {
        println!(
            "installed={} skipped={} last_pull_ts={} last_seen_id={}",
            s.n_installed,
            s.n_skipped,
            s.last_pull_ts.as_deref().unwrap_or("(never)"),
            s.last_seen_id.as_deref().unwrap_or("(none)")
        );
    }
    Ok(())
}

fn cmd_opt(mut rest: Vec<&str>, opt_out: bool) -> Result<(), Box<dyn std::error::Error>> {
    let kind = take_opt(&mut rest, "--kind")
        .ok_or("--kind <K> required")?;
    let pattern = take_opt(&mut rest, "--pattern")
        .ok_or("--pattern <P> required (use '*' for all)")?;
    let state = ConsumerState::open_default()?;
    if opt_out {
        state.opt_out(&kind, &pattern)?;
        println!("opted-out: kind={kind} pattern={pattern}");
    } else {
        let removed = state.opt_in(&kind, &pattern)?;
        if removed {
            println!("opted-in: kind={kind} pattern={pattern}");
        } else {
            println!("no matching opt-out: kind={kind} pattern={pattern}");
        }
    }
    Ok(())
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
        "aim-hive-consumer — pull eval-gated updates from the queen\n\n\
USAGE:\n  \
aim-hive-consumer pull   [--queen-url U] [--since TS] [--dry-run] [--json]\n  \
aim-hive-consumer loop   [--queen-url U] [--interval S] [--dry-run]\n  \
aim-hive-consumer status [--json]\n  \
aim-hive-consumer opt-out --kind K --pattern P\n  \
aim-hive-consumer opt-in  --kind K --pattern P\n\n\
ENV: AIM_HIVE_QUEEN_URL, AIM_USER_TOKEN, AIM_HIVE_STATE_DB,\n     \
AIM_HIVE_POLL_INTERVAL_S (default 300), AIM_EVAL_CASES_DIR"
    );
}
