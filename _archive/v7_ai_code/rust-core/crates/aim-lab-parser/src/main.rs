//! aim-lab-parser CLI: read OCR text from stdin (or file) → JSON.
//!
//! Usage:
//!   aim-lab-parser parse-file <path>
//!   aim-lab-parser parse-stdin

use std::io::Read;
use std::process::ExitCode;

use aim_lab_parser::parse;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let text = match args.first().map(String::as_str) {
        Some("parse-file") => match args.get(1) {
            Some(p) => match std::fs::read_to_string(p) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("read {p}: {e}");
                    return ExitCode::from(1);
                }
            },
            None => {
                eprintln!("usage: parse-file <path>");
                return ExitCode::from(2);
            }
        },
        Some("parse-stdin") => {
            let mut s = String::new();
            if let Err(e) = std::io::stdin().read_to_string(&mut s) {
                eprintln!("stdin: {e}");
                return ExitCode::from(1);
            }
            s
        }
        Some("--help" | "-h") | None => {
            println!("aim-lab-parser parse-file <path>");
            println!("aim-lab-parser parse-stdin");
            return ExitCode::SUCCESS;
        }
        Some(other) => {
            eprintln!("unknown subcommand: {other}");
            return ExitCode::from(2);
        }
    };

    let labs = parse(&text);
    match serde_json::to_string_pretty(&labs) {
        Ok(s) => {
            println!("{s}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("serde error: {e}");
            ExitCode::from(3)
        }
    }
}
