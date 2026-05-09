//! aim-weekly-project-digest CLI (Rust port, 2026-05-06).

use std::process::ExitCode;

use aim_daily_brief::{chunk_for_telegram, Telegram};
use aim_weekly_project_digest::{compose, render};
use chrono::NaiveDate;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-weekly-project-digest: {msg}");
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
                        .map_err(|e| format!("bad date {v:?}: {e}"))?,
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
    let sections = compose(today);
    if json_mode {
        let v = serde_json::json!({
            "today": today.format("%Y-%m-%d").to_string(),
            "projects": sections.projects,
            "stakeholder_silence": sections.stakeholder_silence,
            "experiments": sections.experiments,
            "patient_drift": sections.patient_drift,
        });
        println!("{}", serde_json::to_string_pretty(&v).unwrap());
        return Ok(());
    }
    let body = render(today, &sections);
    if telegram_mode {
        let token = std::env::var("TELEGRAM_BOT_TOKEN")
            .or_else(|_| std::env::var("AIM_TG_BOT_TOKEN"))
            .map_err(|_| "TELEGRAM_BOT_TOKEN not set".to_string())?;
        let chat = std::env::var("AIM_TELEGRAM_CHAT_ID")
            .map_err(|_| "AIM_TELEGRAM_CHAT_ID not set".to_string())?;
        let tg = TelegramClient { token, chat };
        let chunks = chunk_for_telegram(&body);
        for c in &chunks {
            tg.post(c).map_err(|e| format!("telegram: {e}"))?;
        }
        eprintln!("delivered {} chunks ({} chars)", chunks.len(), body.len());
        return Ok(());
    }
    println!("{body}");
    Ok(())
}

/// Telegram trait impl using `reqwest::blocking`. Same shape as
/// aim-daily-brief — could be DRYed into a shared crate later.
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

fn print_usage() {
    println!(
        "aim-weekly-project-digest — outward-facing weekly digest\n\n\
USAGE:\n\
  aim-weekly-project-digest\n\
  aim-weekly-project-digest --date <YYYY-MM-DD>\n\
  aim-weekly-project-digest --json\n\
  aim-weekly-project-digest --telegram     # deliver to Telegram\n\n\
ENV:\n\
  AIM_PROJECTS_DIR / AIM_PATIENTS_DIR / AIM_EXPERIMENTS_DIR\n\
  AIM_HOME (patient_comms.db / contacts.db location)\n\
  AIM_ROOT (relative-path resolver fallback)\n\n\
TELEGRAM (with --telegram):\n\
  TELEGRAM_BOT_TOKEN, AIM_TELEGRAM_CHAT_ID"
    );
}
