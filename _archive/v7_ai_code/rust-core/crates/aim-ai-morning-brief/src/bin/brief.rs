//! `aim-ai-brief` — print the AIM/AI morning brief.
//!     aim-ai-brief         → markdown
//!     aim-ai-brief --json  → struct as JSON

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let json = std::env::args().any(|a| a == "--json");
    let ledger = aim_ai_ledger::Ledger::open_default()?;
    if json {
        let b = aim_ai_morning_brief::render_struct(&ledger);
        println!("{}", serde_json::to_string_pretty(&b)?);
    } else {
        println!("{}", aim_ai_morning_brief::render(&ledger));
    }
    Ok(())
}
