//! aim-coach CLI — Phase 4 of "Patient as a Project" cornerstone.
//!
//! Subcommands:
//!   classify <utterance>             — change_talk / sustain_talk / neutral / resistance
//!   next-move <kind> <activation_level>   — pick OARS move
//!   system-prompt [--lang en|ru]     — print MI coach system prompt
//!
//! All deterministic — no LLM call. Callers (Python `agents/coach.py`
//! shim or Phoenix LiveView) feed the system-prompt + classified
//! patient utterance into `aim-llm /v1/chat`.

use std::process::ExitCode;

use aim_coach::{classify_utterance, coach_system_prompt, next_move, UtteranceKind};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-coach: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-coach <classify|next-move|system-prompt> ...; try --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "classify" => {
            let utterance = rest.first().ok_or("classify: <utterance> required")?;
            let kind = classify_utterance(utterance)?;
            println!("{}", kind_str(kind));
            Ok(())
        }
        "next-move" => {
            let kind_s = rest.first().ok_or("next-move: <kind> required")?;
            let level: u8 = rest
                .get(1)
                .ok_or("next-move: <activation_level> required")?
                .parse()?;
            let kind = parse_kind(kind_s)?;
            let m = next_move(kind, level)?;
            println!("{}", move_str(m));
            Ok(())
        }
        "system-prompt" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let lang = take_opt(&mut rest_v, "--lang").unwrap_or_else(|| "en".to_string());
            print!("{}", coach_system_prompt(&lang));
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn kind_str(k: UtteranceKind) -> &'static str {
    match k {
        UtteranceKind::ChangeTalk => "change_talk",
        UtteranceKind::SustainTalk => "sustain_talk",
        UtteranceKind::Neutral => "neutral",
        UtteranceKind::Resistance => "resistance",
    }
}

fn parse_kind(s: &str) -> Result<UtteranceKind, String> {
    Ok(match s {
        "change_talk" | "change" => UtteranceKind::ChangeTalk,
        "sustain_talk" | "sustain" => UtteranceKind::SustainTalk,
        "neutral" => UtteranceKind::Neutral,
        "resistance" => UtteranceKind::Resistance,
        other => return Err(format!("unknown kind {other:?}; expected change_talk|sustain_talk|neutral|resistance")),
    })
}

fn move_str(m: aim_coach::CoachMove) -> &'static str {
    use aim_coach::CoachMove::*;
    match m {
        OpenQuestion => "open_question",
        Affirmation => "affirmation",
        Reflection => "reflection",
        Summary => "summary",
        RollWithResistance => "roll_with_resistance",
        BuildRapport => "build_rapport",
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
        "aim-coach — motivational interviewing patterns + OARS picker\n\n\
USAGE:\n\
  aim-coach classify <utterance>\n\
  aim-coach next-move <change_talk|sustain_talk|neutral|resistance> <0..4>\n\
  aim-coach system-prompt [--lang en|ru]\n\n\
NOTE: LLM call is the caller's responsibility — pipe system-prompt +\n\
patient utterance into `aim-llm /v1/chat`."
    );
}
