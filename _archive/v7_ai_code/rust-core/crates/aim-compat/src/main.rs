//! aim-compat — CLI for unified compatibility checks.
//!
//! Subcommands:
//!   check-new <drug> [--age N] [--pregnant] [--allergy A]... [--cond C]... [--existing M]...
//!   check-regimen <drug1,drug2,...> [same flags]
//!
//! Output: JSON `Vec<Conflict>` to stdout, sorted by severity (worst first).
//! Exit 0 even when conflicts exist (clinical decision belongs to caller);
//! exit 2 for usage error, exit 3 for serialisation failure.

use std::process::ExitCode;

use aim_compat::{check_new_drug, check_regimen, PatientCtx};

fn usage() -> &'static str {
    "aim-compat — unified medication compatibility checker (v0.1)\n\
     \n\
     USAGE:\n\
     aim-compat check-new <drug> [flags]\n\
     aim-compat check-regimen <drug1,drug2,...> [flags]\n\
     \n\
     FLAGS (repeatable where applicable):\n\
     --age <years>         patient age\n\
     --sex <M|F>           patient sex\n\
     --pregnant            mark patient pregnant\n\
     --breastfeeding       mark patient breastfeeding\n\
     --allergy <name>      add an allergy (repeatable)\n\
     --cond <text>         add a condition (repeatable)\n\
     --existing <drug>     add an existing medication (repeatable)\n\
     \n\
     OUTPUT:\n\
     JSON array of Conflict, sorted by severity (worst first).\n\
     Empty array `[]` = no flags fired."
}

#[derive(Default)]
struct Args {
    sub: Option<String>,
    target: Option<String>,
    ctx: PatientCtx,
}

fn parse_args() -> Result<Args, String> {
    let mut a = Args::default();
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut iter = raw.into_iter();
    a.sub = iter.next();
    a.target = iter.next();

    while let Some(flag) = iter.next() {
        match flag.as_str() {
            "--age" => {
                let v = iter.next().ok_or_else(|| "--age needs value".to_string())?;
                a.ctx.age_years =
                    Some(v.parse::<u32>().map_err(|e| format!("bad --age: {e}"))?);
            }
            "--sex" => {
                a.ctx.sex = Some(iter.next().ok_or_else(|| "--sex needs value".to_string())?);
            }
            "--pregnant" => a.ctx.pregnant = true,
            "--breastfeeding" => a.ctx.breastfeeding = true,
            "--allergy" => {
                a.ctx
                    .allergies
                    .push(iter.next().ok_or_else(|| "--allergy needs value".to_string())?);
            }
            "--cond" => {
                a.ctx
                    .conditions
                    .push(iter.next().ok_or_else(|| "--cond needs value".to_string())?);
            }
            "--existing" => {
                a.ctx
                    .existing_meds
                    .push(iter.next().ok_or_else(|| "--existing needs value".to_string())?);
            }
            other => return Err(format!("unknown flag: {other}")),
        }
    }
    Ok(a)
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}\n\n{}", usage());
            return ExitCode::from(2);
        }
    };

    let conflicts = match (args.sub.as_deref(), args.target.as_deref()) {
        (Some("check-new"), Some(drug)) => check_new_drug(drug, &args.ctx),
        (Some("check-regimen"), Some(list)) => {
            let drugs: Vec<String> = list.split(',').map(|s| s.trim().to_string()).collect();
            check_regimen(&drugs, &args.ctx)
        }
        (Some("--help" | "-h"), _) | (None, _) => {
            println!("{}", usage());
            return ExitCode::SUCCESS;
        }
        _ => {
            eprintln!("usage: see --help\n\n{}", usage());
            return ExitCode::from(2);
        }
    };

    match serde_json::to_string_pretty(&conflicts) {
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
