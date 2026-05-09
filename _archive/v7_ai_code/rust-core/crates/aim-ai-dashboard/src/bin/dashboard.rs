//! `aim-ai-dashboard` — print the consolidated AIM/AI dashboard.
//!
//!     aim-ai-dashboard            → markdown
//!     aim-ai-dashboard --json     → JSON envelope
//!     aim-ai-dashboard --compact  → 1-line-per-section (Telegram-friendly)

fn main() {
    let json = std::env::args().any(|a| a == "--json");
    let compact = std::env::args().any(|a| a == "--compact");
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&aim_ai_dashboard::render_json()).unwrap()
        );
    } else if compact {
        println!("{}", aim_ai_dashboard::render_compact());
    } else {
        print!("{}", aim_ai_dashboard::render());
    }
}
