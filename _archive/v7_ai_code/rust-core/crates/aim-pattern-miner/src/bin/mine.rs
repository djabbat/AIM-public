//! `aim-pattern-miner` — session-log pattern miner CLI.
//!
//!     aim-pattern-miner               → text summary, last 7 days
//!     aim-pattern-miner --days 30     → custom window
//!     aim-pattern-miner --json        → JSON findings array

fn main() {
    let mut days: i64 = 7;
    let mut as_json = false;
    let args: Vec<String> = std::env::args().collect();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--days" => {
                if let Some(v) = args.get(i + 1).and_then(|s| s.parse().ok()) {
                    days = v;
                    i += 1;
                }
            }
            "--json" => as_json = true,
            _ => {}
        }
        i += 1;
    }
    let events = aim_pattern_miner::iter_events(None, Some(days));
    let findings = aim_pattern_miner::mine(&events, &aim_pattern_miner::MineOpts::default());
    if as_json {
        match serde_json::to_string_pretty(&findings) {
            Ok(s) => println!("{s}"),
            Err(e) => {
                eprintln!("[aim-pattern-miner] json serialise failed: {e}");
                std::process::exit(1);
            }
        }
    } else {
        println!("{}", aim_pattern_miner::summary(days, &findings));
    }
}
