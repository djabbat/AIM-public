//! aim-ai-gap-detector CLI — Phase 9 Tier 3 #20 (2026-05-07).
//!
//! Replaces `AI/ai/gap_detector.py` (S11). The library doesn't filter
//! by `window_days` — Python shim post-filters by ts before calling
//! `gaps`. CLI exposes:
//!   surrenders                     # JSONL Surrender (no window filter)
//!   gaps [--threshold F]           # stdin: JSONL Surrender → JSONL Gap
//!   summary [--threshold F] [--window-days D]   # plain-text

use std::io::Read;
use std::process::ExitCode;

use aim_ai_gap_detector::{gaps, surrenders, surrenders_in_dir, Surrender};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-gap-detector: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("summary");
    let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "surrenders" => {
            let mut v = rest;
            let dir_opt = take_opt(&mut v, "--dir");
            let s = match dir_opt {
                Some(d) => surrenders_in_dir(std::path::Path::new(&d)),
                None => surrenders(),
            };
            for x in s {
                println!("{}", serde_json::to_string(&x)?);
            }
            Ok(())
        }
        "gaps" => {
            let mut v = rest;
            let threshold: f64 = take_opt(&mut v, "--threshold")
                .map(|s| s.parse::<f64>())
                .transpose()?
                .unwrap_or(0.20);
            let surr = read_stdin_surrenders()?;
            for g in gaps(&surr, threshold) {
                println!("{}", serde_json::to_string(&g)?);
            }
            Ok(())
        }
        "summary" => {
            let mut v = rest;
            let threshold: f64 = take_opt(&mut v, "--threshold")
                .map(|s| s.parse::<f64>())
                .transpose()?
                .unwrap_or(0.20);
            let window_days: i64 = take_opt(&mut v, "--window-days")
                .map(|s| s.parse::<i64>())
                .transpose()?
                .unwrap_or(14);
            let dir_opt = take_opt(&mut v, "--dir");
            let raw = match dir_opt {
                Some(d) => surrenders_in_dir(std::path::Path::new(&d)),
                None => surrenders(),
            };
            let cutoff = chrono::Utc::now() - chrono::Duration::days(window_days);
            let filtered: Vec<Surrender> = raw
                .into_iter()
                .filter(|s| {
                    let Some(ts) = s.ts.as_deref() else {
                        return true;
                    };
                    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(ts) {
                        dt.with_timezone(&chrono::Utc) >= cutoff
                    } else {
                        true
                    }
                })
                .collect();
            let g = gaps(&filtered, threshold);
            if g.is_empty() {
                println!("(no capability gaps detected over last {window_days}d)");
                return Ok(());
            }
            let total: usize = g.iter().map(|x| x.n()).sum();
            println!(
                "🕳 Capability gaps — {} clusters / {} surrenders / last {}d",
                g.len(),
                total,
                window_days
            );
            for cluster in g.iter().take(8) {
                let theme = if cluster.theme.is_empty() {
                    "(no theme)".to_string()
                } else {
                    cluster
                        .theme
                        .iter()
                        .take(4)
                        .cloned()
                        .collect::<Vec<_>>()
                        .join(", ")
                };
                println!("  • [{} surrenders] {}", cluster.n(), theme);
                let preview: String = cluster.suggestion.chars().take(140).collect();
                println!("      → {}", preview);
            }
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn read_stdin_surrenders() -> Result<Vec<Surrender>, Box<dyn std::error::Error>> {
    let mut s = String::new();
    std::io::stdin().read_to_string(&mut s)?;
    let mut out: Vec<Surrender> = Vec::new();
    for line in s.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let parsed: Surrender = serde_json::from_str(line)?;
        out.push(parsed);
    }
    Ok(out)
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
        "aim-ai-gap-detector — capability-gap clustering from session surrenders\n\n\
USAGE:\n\
  aim-ai-gap-detector surrenders [--dir D]                # JSONL\n\
  aim-ai-gap-detector gaps [--threshold F]                # stdin → JSONL\n\
  aim-ai-gap-detector summary [--threshold F] [--window-days D] [--dir D]\n\n\
ENV: AIM_SESSIONS_DIR (default ~/.cache/aim/sessions)"
    );
}
