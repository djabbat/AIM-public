//! aim-pam CLI — administer + score PAM-13 questionnaires.
//!
//! ```text
//!   aim-pam questions [--lang ru|en]                  — print 13 questions
//!   aim-pam score 3 4 3 2 3 4 3 3 2 3 3 4 3            — 13 responses → score+level
//!   aim-pam delta <old_score> <new_score>              — clinically/individually significant?
//! ```

use std::process::ExitCode;

use std::env;
use std::path::PathBuf;

use aim_pam::{
    current_activation_level, delta_clinically_significant, delta_individually_significant,
    history, latest_delta, record_administration, PamQuestionnaire, QUESTIONS_EN, QUESTIONS_RU,
    PAM_MCID, PAM_MDC,
};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("aim-pam: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), String> {
    let (cmd, rest) = match args.split_first() {
        Some((c, r)) => (c.as_str(), r),
        None => {
            print_usage();
            return Ok(());
        }
    };
    match cmd {
        "questions" => {
            let lang = rest
                .iter()
                .position(|a| a == "--lang")
                .and_then(|i| rest.get(i + 1))
                .map(String::as_str)
                .unwrap_or("en");
            let q: &[&str] = match lang {
                "ru" => &QUESTIONS_RU,
                _ => &QUESTIONS_EN,
            };
            for (i, t) in q.iter().enumerate() {
                println!("{}. {}", i + 1, t);
            }
            println!();
            println!("Scale: 1=Disagree strongly, 2=Disagree, 3=Agree, 4=Agree strongly");
            Ok(())
        }
        "score" => {
            if rest.len() != 13 {
                return Err(format!("score needs 13 responses, got {}", rest.len()));
            }
            let responses: Vec<u8> = rest
                .iter()
                .map(|s| s.parse::<u8>().map_err(|e| format!("{s:?}: {e}")))
                .collect::<Result<_, _>>()?;
            let q = PamQuestionnaire::new(responses).map_err(|e| format!("{e}"))?;
            println!("Raw sum: {}", q.raw_sum());
            println!("Score: {:.1} / 100", q.score());
            println!("Level: {} ({})", q.level(), level_label(q.level()));
            println!();
            println!("MCID = {} pts (clinical), MDC = {} pts (individual)", PAM_MCID, PAM_MDC);
            Ok(())
        }
        "delta" => {
            let old: f64 = rest
                .first()
                .ok_or("usage: delta <old> <new>")?
                .parse()
                .map_err(|e| format!("old: {e}"))?;
            let new: f64 = rest
                .get(1)
                .ok_or("usage: delta <old> <new>")?
                .parse()
                .map_err(|e| format!("new: {e}"))?;
            let d = new - old;
            println!("Delta: {:+.1}", d);
            match delta_clinically_significant(old, new) {
                Some(true) => println!("Clinically significant: YES (|Δ| ≥ {})", PAM_MCID),
                Some(false) => println!("Clinically significant: no (|Δ| < {})", PAM_MCID),
                None => println!("Clinically significant: no change"),
            }
            if delta_individually_significant(old, new) {
                println!("Individually significant: YES (|Δ| ≥ {})", PAM_MDC);
            } else {
                println!("Individually significant: no (|Δ| < {})", PAM_MDC);
            }
            Ok(())
        }
        "record" => {
            // record <patient_id> r1..r13 [--patients-dir D]
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let dir = take_patients_dir(&mut rest_v);
            let pid = rest_v.first().ok_or("record: <patient_id> required")?.to_string();
            let resp_strs: Vec<&str> = rest_v.iter().skip(1).copied().collect();
            if resp_strs.len() != 13 {
                return Err(format!("record: 13 responses required, got {}", resp_strs.len()));
            }
            let responses: Vec<u8> = resp_strs
                .iter()
                .map(|s| s.parse::<u8>().map_err(|e| format!("{s:?}: {e}")))
                .collect::<Result<_, _>>()?;
            let p = record_administration(&dir, &pid, responses, None)
                .map_err(|e| format!("{e}"))?;
            println!("{}", serde_json::to_string(&p).map_err(|e| format!("{e}"))?);
            Ok(())
        }
        "history" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let dir = take_patients_dir(&mut rest_v);
            let pid = rest_v.first().ok_or("history: <patient_id> required")?.to_string();
            for p in history(&dir, &pid).map_err(|e| format!("{e}"))? {
                println!("{}", serde_json::to_string(&p).map_err(|e| format!("{e}"))?);
            }
            Ok(())
        }
        "level" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let dir = take_patients_dir(&mut rest_v);
            let pid = rest_v.first().ok_or("level: <patient_id> required")?.to_string();
            let l = current_activation_level(&dir, &pid).map_err(|e| format!("{e}"))?;
            println!("{l}");
            Ok(())
        }
        "latest-delta" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let dir = take_patients_dir(&mut rest_v);
            let pid = rest_v.first().ok_or("latest-delta: <patient_id> required")?.to_string();
            let (label, delta) = latest_delta(&dir, &pid).map_err(|e| format!("{e}"))?;
            let v = serde_json::json!({"label": label, "delta": delta});
            println!("{}", serde_json::to_string(&v).map_err(|e| format!("{e}"))?);
            Ok(())
        }
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help")),
    }
}

fn take_patients_dir(rest: &mut Vec<&str>) -> PathBuf {
    if let Some(i) = rest.iter().position(|a| *a == "--patients-dir") {
        if i + 1 < rest.len() {
            let v = rest[i + 1].to_string();
            rest.remove(i + 1);
            rest.remove(i);
            return PathBuf::from(v);
        }
    }
    PathBuf::from(env::var("AIM_PATIENTS_DIR").unwrap_or_else(|_| "Patients".to_string()))
}

fn level_label(l: u8) -> &'static str {
    match l {
        1 => "disengaged and overwhelmed",
        2 => "becoming aware but still struggling",
        3 => "taking action and gaining control",
        4 => "maintaining behaviors and pushing further",
        _ => "?",
    }
}

fn print_usage() {
    println!(
        "aim-pam — Patient Activation Measure (PAM-13) administration & scoring\n\n\
USAGE:\n\
  aim-pam questions [--lang en|ru]\n\
  aim-pam score r1 r2 r3 r4 r5 r6 r7 r8 r9 r10 r11 r12 r13\n\
  aim-pam delta <old_score> <new_score>\n\
  aim-pam record <patient_id> r1..r13 [--patients-dir DIR]   # score + append JSONL\n\
  aim-pam history <patient_id> [--patients-dir DIR]          # JSONL of administrations\n\
  aim-pam level <patient_id> [--patients-dir DIR]            # current level (0 if empty)\n\
  aim-pam latest-delta <patient_id> [--patients-dir DIR]     # {{label, delta}}\n\n\
ENV: AIM_PATIENTS_DIR (default: ./Patients)\n\n\
LICENSE NOTE: This crate uses a research-grade linear approximation of\n\
the proprietary Insignia Health Rasch calibration. Clinical use requires\n\
a licensed scoring service from Insignia Health."
    );
}
