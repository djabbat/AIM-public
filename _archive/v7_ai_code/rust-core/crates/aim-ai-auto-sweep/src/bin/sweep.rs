//! `aim-ai-sweep` — run periodic AIM/AI maintenance.
//!     aim-ai-sweep                 → live, prints summary
//!     aim-ai-sweep --dry-run       → print plan, no writes
//!     aim-ai-sweep --json          → JSON SweepResult

fn main() {
    let dry_run = std::env::args().any(|a| a == "--dry-run");
    let json = std::env::args().any(|a| a == "--json");
    let r = aim_ai_auto_sweep::sweep(dry_run);
    if json {
        println!("{}", serde_json::to_string_pretty(&r).unwrap());
    } else {
        println!("{}", aim_ai_auto_sweep::summary(&r, dry_run));
    }
}
