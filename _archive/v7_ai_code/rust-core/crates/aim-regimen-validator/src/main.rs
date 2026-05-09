//! aim-regimen-validator CLI — Phase 8 Week 2 (2026-05-07).
//!
//! Wires `aim-regimen-validator`'s `validate` against
//! `aim-interactions::check_regimen` (the static drug-pair table) so
//! the Python shim (`agents/regimen_validator.py`) can subprocess into
//! Rust for clinical safety screening.
//!
//! Subcommands:
//!   validate <drug1> <drug2> ... [--physician-override]
//!   validate-or-raise <drug1> <drug2> ... [--physician-override]
//!   annotate <draft_text> -- <drug1> <drug2> ... [--physician-override]
//!
//! Output: JSON Validation on stdout for validate/validate-or-raise;
//! plain text annotated draft for annotate. validate-or-raise exits
//! non-zero with the error message on stderr if the regimen is refused.

use std::process::ExitCode;

use aim_interactions::{check_regimen, Interaction as RawInteraction, Severity as RawSeverity};
use aim_regimen_validator::{
    annotate as annotate_lib, validate as validate_lib, validate_or_raise as validate_or_raise_lib,
    Interaction, InteractionLookup, Severity,
};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-regimen-validator: {e}");
            ExitCode::FAILURE
        }
    }
}

/// Bridge between `aim-interactions::Interaction` (rich, with mechanism &
/// source) and `aim-regimen-validator::Interaction` (just the bucket-relevant
/// fields). The validator only needs drug names + severity + recommendation.
struct InteractionsCrateLookup;

impl InteractionLookup for InteractionsCrateLookup {
    fn lookup(&self, drugs: &[&str]) -> Vec<Interaction> {
        let drugs_vec: Vec<String> = drugs.iter().map(|s| s.to_string()).collect();
        check_regimen(&drugs_vec)
            .into_iter()
            .map(map_interaction)
            .collect()
    }
}

fn map_interaction(ix: RawInteraction) -> Interaction {
    let severity = match ix.severity {
        RawSeverity::Contraindicated => Severity::Contraindicated,
        RawSeverity::Major => Severity::Major,
        RawSeverity::Moderate => Severity::Moderate,
        RawSeverity::Minor => Severity::Minor,
        RawSeverity::NoKnown => Severity::NoKnown,
    };
    Interaction {
        drug_a: ix.drug_a,
        drug_b: ix.drug_b,
        severity,
        recommendation: ix.recommendation,
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-regimen-validator <validate|validate-or-raise|annotate> ...; --help")?;
    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "validate" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let physician_override = take_flag(&mut rest_v, "--physician-override");
            let drugs: Vec<String> = rest_v.iter().map(|s| s.to_string()).collect();
            let drug_refs: Vec<&str> = drugs.iter().map(|s| s.as_str()).collect();
            let v = validate_lib(&drug_refs, &InteractionsCrateLookup, physician_override);
            println!("{}", serde_json::to_string(&v)?);
            Ok(())
        }
        "validate-or-raise" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let physician_override = take_flag(&mut rest_v, "--physician-override");
            let drugs: Vec<String> = rest_v.iter().map(|s| s.to_string()).collect();
            let drug_refs: Vec<&str> = drugs.iter().map(|s| s.as_str()).collect();
            match validate_or_raise_lib(&drug_refs, &InteractionsCrateLookup, physician_override) {
                Ok(v) => {
                    println!("{}", serde_json::to_string(&v)?);
                    Ok(())
                }
                Err(e) => Err(format!("{e}").into()),
            }
        }
        "annotate" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let physician_override = take_flag(&mut rest_v, "--physician-override");
            // Format: <draft_text> -- <drug1> <drug2> ...
            let sep_idx = rest_v
                .iter()
                .position(|s| *s == "--")
                .ok_or("annotate: expected '<draft_text> -- <drug1> <drug2> ...'")?;
            let draft = rest_v[..sep_idx].join(" ");
            let drugs: Vec<String> = rest_v[sep_idx + 1..]
                .iter()
                .map(|s| s.to_string())
                .collect();
            let drug_refs: Vec<&str> = drugs.iter().map(|s| s.as_str()).collect();
            let out = annotate_lib(&draft, &drug_refs, &InteractionsCrateLookup, physician_override);
            print!("{out}");
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn take_flag(rest: &mut Vec<&str>, key: &str) -> bool {
    if let Some(i) = rest.iter().position(|a| *a == key) {
        rest.remove(i);
        return true;
    }
    false
}

fn print_usage() {
    println!(
        "aim-regimen-validator — clinical-safety regimen screen\n\n\
USAGE:\n\
  aim-regimen-validator validate <drug1> <drug2> ... [--physician-override]\n\
  aim-regimen-validator validate-or-raise <drug1> <drug2> ... [--physician-override]\n\
  aim-regimen-validator annotate <draft_text> -- <drug1> <drug2> ... [--physician-override]\n\n\
OUTPUT: JSON Validation for validate/validate-or-raise; plain text for annotate.\n\
validate-or-raise exits non-zero with stderr message on hard refusal."
    );
}
