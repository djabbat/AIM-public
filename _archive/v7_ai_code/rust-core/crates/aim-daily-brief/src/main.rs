//! aim-daily-brief CLI (Rust port of `scripts/daily_brief.py`, 2026-05-06).
//!
//! Composes the morning brief by aggregating project + patient +
//! experiment lifecycles via the `aim-lifecycle` trait, then routes to
//! Telegram (or stdout in dry-run). No subprocess hops — direct Rust
//! library calls.
//!
//! Replaces the Python script that previously shelled out to three
//! separate Rust binaries via `subprocess.run`. Eliminates ~3-5×
//! subprocess startup overhead per brief.
//!
//! ```text
//!   aim-daily-brief                  # render to stdout
//!   aim-daily-brief --date 2026-05-06
//!   aim-daily-brief --json           # machine-readable BriefSections
//! ```
//!
//! Telegram delivery is left to the user — we keep CLI scope to
//! composing+rendering. Pipe stdout to `notify` / `telegram-bot-cli` /
//! existing Python `agents/notify.py` for delivery.

use std::path::PathBuf;
use std::process::ExitCode;

use aim_daily_brief::{
    chunk_for_telegram, render_brief, BriefSections, DeliveryDecision, DeliveryPrefs,
    Telegram,
};
use aim_experiment_owner::ExperimentOwner;
use aim_patient_owner::PatientOwner;
use chrono::NaiveDate;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-daily-brief: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), String> {
    let mut today: Option<NaiveDate> = None;
    let mut json_mode = false;
    let mut telegram_mode = false;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--date" => {
                let v = args.get(i + 1).ok_or("--date needs YYYY-MM-DD")?;
                today = Some(
                    NaiveDate::parse_from_str(v, "%Y-%m-%d")
                        .map_err(|e| format!("bad --date {v:?}: {e}"))?,
                );
                i += 2;
            }
            "--json" => {
                json_mode = true;
                i += 1;
            }
            "--telegram" => {
                telegram_mode = true;
                i += 1;
            }
            "--help" | "-h" => {
                print_usage();
                return Ok(());
            }
            other => return Err(format!("unknown flag {other:?}")),
        }
    }
    let today = today.unwrap_or_else(|| chrono::Local::now().date_naive());

    let sections = compose(today)?;
    let body = render_brief(today, &sections);

    if json_mode {
        let v = serde_json::json!({
            "today": today.format("%Y-%m-%d").to_string(),
            "head": sections.head,
            "all_briefs": sections.all_briefs,
            "deadlines": sections.deadlines,
        });
        println!("{}", serde_json::to_string_pretty(&v).unwrap());
        return Ok(());
    }

    if telegram_mode {
        let token = std::env::var("TELEGRAM_BOT_TOKEN")
            .or_else(|_| std::env::var("AIM_TG_BOT_TOKEN"))
            .map_err(|_| {
                "TELEGRAM_BOT_TOKEN (or AIM_TG_BOT_TOKEN) not set".to_string()
            })?;
        let chat = std::env::var("AIM_TELEGRAM_CHAT_ID")
            .map_err(|_| "AIM_TELEGRAM_CHAT_ID not set".to_string())?;
        let dry_run = std::env::var("AIM_TG_DRYRUN")
            .map(|v| v == "1")
            .unwrap_or(false);
        let prefs = DeliveryPrefs {
            quiet_hours: false,
            dry_run,
            channels: vec!["telegram".into()],
        };
        let tg = TelegramClient { token, chat };
        let decision = aim_daily_brief::decide_delivery(&prefs);
        match decision {
            DeliveryDecision::Suppress => {
                eprintln!("(suppressed by quiet_hours)");
            }
            DeliveryDecision::Stdout => {
                println!("{body}");
            }
            DeliveryDecision::Telegram => {
                let chunks = chunk_for_telegram(&body);
                for c in &chunks {
                    if let Err(e) = tg.post(c) {
                        return Err(format!("telegram delivery failed: {e}"));
                    }
                }
                eprintln!(
                    "delivered {} chunks ({} chars total)",
                    chunks.len(),
                    body.len()
                );
            }
        }
        return Ok(());
    }

    println!("{body}");
    Ok(())
}

/// Telegram trait implementation using `reqwest::blocking`.
struct TelegramClient {
    token: String,
    chat: String,
}

impl Telegram for TelegramClient {
    fn post(&self, body: &str) -> Result<(), String> {
        let url = format!(
            "https://api.telegram.org/bot{}/sendMessage",
            self.token
        );
        let payload = serde_json::json!({
            "chat_id": self.chat,
            "text": body,
            "disable_web_page_preview": true,
        });
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .map_err(|e| format!("client init: {e}"))?;
        let resp = client
            .post(&url)
            .json(&payload)
            .send()
            .map_err(|e| format!("send: {e}"))?;
        if !resp.status().is_success() {
            let st = resp.status();
            let txt = resp.text().unwrap_or_default();
            return Err(format!("telegram {st}: {}", &txt[..txt.len().min(200)]));
        }
        Ok(())
    }
}

/// Aggregate project + patient + experiment briefs into one [`BriefSections`].
///
/// Each block is gracefully skipped when its source is missing
/// (root dir absent, no entities, etc.) — the brief still renders.
fn compose(today: NaiveDate) -> Result<BriefSections, String> {
    let mut blocks: Vec<String> = Vec::new();

    // 1. Projects (existing aim-project-owner free functions)
    let proj_root = aim_project_owner::projects_dir();
    let proj_root = resolve_relative(proj_root);
    let project_names = aim_project_owner::list_projects(&proj_root);
    if !project_names.is_empty() {
        let mut proj_block: Vec<String> = Vec::new();
        for name in &project_names {
            match aim_project_owner::load(&proj_root, name) {
                Ok(state) => {
                    let extras = aim_project_owner::BriefExtras::default();
                    proj_block.push(aim_project_owner::morning_brief(
                        &state, today, &extras,
                    ));
                }
                Err(e) => {
                    proj_block.push(format!("❌ {name}: {e}"));
                }
            }
        }
        blocks.push(proj_block.join("\n\n———\n\n"));
    }

    // 2. Patients
    let pat_root = aim_patient_owner::patients_dir();
    let pat_root = resolve_relative(pat_root);
    let patient_owner = PatientOwner::new(pat_root);
    let patient_block = patient_owner.all_briefs(today);
    if !patient_block.contains("(no patients") {
        blocks.push(patient_block);
    }

    // 3. Experiments
    let exp_root = aim_experiment_owner::experiments_dir();
    let exp_root = resolve_relative(exp_root);
    let experiment_owner = ExperimentOwner::new(exp_root);
    let exp_block = experiment_owner.all_briefs(today);
    if !exp_block.contains("(no experiments") {
        blocks.push(exp_block);
    }

    let all_briefs = if blocks.is_empty() {
        "(no managed entities found)".to_string()
    } else {
        blocks.join("\n\n———\n\n")
    };

    // Deadlines section is currently rendered by the Python deadline
    // scanner — no Rust port yet. We leave a placeholder header so the
    // shape matches the Python output.
    let deadlines = format!(
        "(deadlines section: invoke `python -m agents.deadline_scanner` for cross-source roll-up; \
         not yet ported to Rust)"
    );

    // Render AIM_FS inbox digest if the binary is present. Always non-fatal —
    // the brief should work even before AIM_FS is adopted.
    let aim_fs_inbox = render_aim_fs_block();

    Ok(BriefSections {
        head: None,
        all_briefs,
        deadlines,
        aim_fs_inbox,
    })
}

/// Best-effort AIM_FS digest. Returns empty string if the binary or root is
/// unavailable; callers should not block the brief on this.
fn render_aim_fs_block() -> String {
    let binary = std::env::var("AIM_FS_BIN").unwrap_or_else(|_| "aim-fs".to_string());
    let aim_root = std::env::var("AIM_FS_ROOT").unwrap_or_else(|_| {
        std::env::var("HOME")
            .map(|h| format!("{h}/.aim_fs"))
            .unwrap_or_else(|_| "/var/lib/aim_fs".to_string())
    });
    let tenant = std::env::var("AIM_FS_TENANT").unwrap_or_else(|_| "djabbat".to_string());
    aim_daily_brief::aim_fs::render_inbox_block(&tenant, &binary, &aim_root, 5)
        .unwrap_or_default()
}

/// Resolve a path that may be relative ("USER/projects") to a sensible
/// absolute one. We try CWD first, then `$AIM_ROOT`, then a hardcoded
/// development path.
fn resolve_relative(p: PathBuf) -> PathBuf {
    if p.is_absolute() {
        return p;
    }
    let cwd_candidate = std::env::current_dir().ok().map(|c| c.join(&p));
    if let Some(c) = cwd_candidate {
        if c.exists() {
            return c;
        }
    }
    if let Ok(root) = std::env::var("AIM_ROOT") {
        let c = PathBuf::from(root).join(&p);
        if c.exists() {
            return c;
        }
    }
    // Final fallback — dev box layout
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home)
        .join("Desktop/LongevityCommon/AIM")
        .join(&p)
}

fn print_usage() {
    println!(
        "aim-daily-brief — unified morning brief renderer\n\n\
USAGE:\n\
  aim-daily-brief\n\
  aim-daily-brief --date <YYYY-MM-DD>\n\
  aim-daily-brief --json\n\
  aim-daily-brief --telegram      # deliver to Telegram (requires env vars)\n\n\
ENV:\n\
  AIM_PROJECTS_DIR     — projects YAML root (default: USER/projects/)\n\
  AIM_PATIENTS_DIR     — patient MEMORY.md root (default: Patients/)\n\
  AIM_EXPERIMENTS_DIR  — experiments YAML root (default: USER/experiments/)\n\
  AIM_ROOT             — repo root for relative path resolution\n\n\
TELEGRAM (with --telegram):\n\
  TELEGRAM_BOT_TOKEN   — bot token from BotFather\n\
  AIM_TELEGRAM_CHAT_ID — target chat id\n\
  AIM_TG_DRYRUN=1      — print to stdout instead of posting (debug)"
    );
}
