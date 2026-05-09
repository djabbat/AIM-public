//! aim-lab-units CLI: batch conversion via stdin JSON.
//!
//! Input (stdin): JSON array of {analyte_key, value, source_unit, target_unit}.
//! Output (stdout): JSON array of Conversion (per input).
//!
//! Example:
//!   echo '[{"analyte_key":"hemoglobin","value":13.7,"source_unit":"g/dL","target_unit":"g/L"}]' \
//!     | aim-lab-units batch

use std::io::Read;
use std::process::ExitCode;

use aim_lab_units::{convert_or_passthrough, Conversion};
use serde::Deserialize;

#[derive(Deserialize)]
struct Input {
    analyte_key: String,
    value: f64,
    source_unit: String,
    target_unit: String,
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("batch") => {
            let mut s = String::new();
            if let Err(e) = std::io::stdin().read_to_string(&mut s) {
                eprintln!("stdin read: {e}");
                return ExitCode::from(1);
            }
            let items: Vec<Input> = match serde_json::from_str(&s) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("input json: {e}");
                    return ExitCode::from(2);
                }
            };
            let out: Vec<Conversion> = items
                .iter()
                .map(|i| {
                    convert_or_passthrough(&i.analyte_key, i.value, &i.source_unit, &i.target_unit)
                })
                .collect();
            match serde_json::to_string_pretty(&out) {
                Ok(s) => {
                    println!("{s}");
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("serde: {e}");
                    ExitCode::from(3)
                }
            }
        }
        Some("--help" | "-h") | None => {
            println!(
                "aim-lab-units batch < items.json\n\n\
                 Input: JSON array of {{analyte_key, value, source_unit, target_unit}}.\n\
                 Output: JSON array of Conversion (value/source_unit_raw/target_unit/was_converted).\n"
            );
            ExitCode::SUCCESS
        }
        Some(other) => {
            eprintln!("unknown subcommand: {other}");
            ExitCode::from(2)
        }
    }
}
