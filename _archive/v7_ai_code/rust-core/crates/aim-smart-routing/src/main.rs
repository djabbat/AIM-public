//! aim-smart-routing CLI — Phase 8 Week 1 (2026-05-07).
//!
//! All logic lives in the lib (`aim_smart_routing`); this binary exposes
//! the operations as JSON-on-stdout subcommands so the Python shim
//! (`agents/smart_routing.py`) becomes a thin subprocess wrapper.
//!
//! Subcommands:
//!   classify <prompt> [--force-model M]
//!   route    <prompt> [--force-model M] [--assume-output N] [--db PATH]
//!   estimate-cost <model> <in_tokens> [<out_tokens>]
//!   stats [--db PATH]
//!
//! ENV: AIM_SMART_ROUTING=1 enables DB logging in `route` (default off).
//!      `--db PATH` overrides the default `~/.claude/smart_routing.db`.

use std::path::PathBuf;
use std::process::ExitCode;

use aim_smart_routing::{
    classify, default_db_path, default_prices, estimate_cost, Router,
};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-smart-routing: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-smart-routing <classify|route|estimate-cost|stats> ...; try --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "classify" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let force_model = take_opt(&mut rest_v, "--force-model");
            let prompt = rest_v.first().ok_or("classify: <prompt> required")?.to_string();
            let info = classify(&prompt, force_model.as_deref());
            println!("{}", serde_json::to_string(&info)?);
            Ok(())
        }
        "route" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let force_model = take_opt(&mut rest_v, "--force-model");
            let assume_output = take_opt(&mut rest_v, "--assume-output")
                .map(|s| s.parse::<u64>())
                .transpose()?
                .unwrap_or(500);
            let db_path = take_opt(&mut rest_v, "--db")
                .map(PathBuf::from)
                .unwrap_or_else(default_db_path);
            let prompt = rest_v.first().ok_or("route: <prompt> required")?.to_string();
            let enabled = std::env::var("AIM_SMART_ROUTING")
                .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
                .unwrap_or(false);
            let mut router = Router::new(default_prices(), enabled, Some(&db_path))?;
            router.assume_output_tokens = assume_output;
            let info = router.route(&prompt, force_model.as_deref())?;
            println!("{}", serde_json::to_string(&info)?);
            Ok(())
        }
        "estimate-cost" => {
            let model = rest.first().ok_or("estimate-cost: <model> required")?;
            let in_tok: u64 = rest
                .get(1)
                .ok_or("estimate-cost: <in_tokens> required")?
                .parse()?;
            let out_tok: u64 = rest
                .get(2)
                .map(|s| s.parse::<u64>())
                .transpose()?
                .unwrap_or(0);
            let prices = default_prices();
            let cost = estimate_cost(&prices, model, in_tok, out_tok);
            let v = serde_json::json!({
                "model": model,
                "in_tokens": in_tok,
                "out_tokens": out_tok,
                "cost_usd": cost,
            });
            println!("{}", serde_json::to_string(&v)?);
            Ok(())
        }
        "stats" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let db_path = take_opt(&mut rest_v, "--db")
                .map(PathBuf::from)
                .unwrap_or_else(default_db_path);
            let enabled = std::env::var("AIM_SMART_ROUTING")
                .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
                .unwrap_or(false);
            let router = Router::new(default_prices(), enabled, Some(&db_path))?;
            let s = router.stats()?;
            println!("{}", serde_json::to_string(&s)?);
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
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
        "aim-smart-routing — LLM tier classification + cost-aware routing\n\n\
USAGE:\n\
  aim-smart-routing classify <prompt> [--force-model M]\n\
  aim-smart-routing route    <prompt> [--force-model M] [--assume-output N] [--db PATH]\n\
  aim-smart-routing estimate-cost <model> <in_tokens> [<out_tokens>]\n\
  aim-smart-routing stats [--db PATH]\n\n\
OUTPUT: JSON on stdout. Default DB: ~/.claude/smart_routing.db\n\
ENV: AIM_SMART_ROUTING=1 enables DB logging in `route`."
    );
}
