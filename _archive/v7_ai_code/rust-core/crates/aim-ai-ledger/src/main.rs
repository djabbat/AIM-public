//! aim-ai-ledger CLI — Phase 9 Tier 1 (2026-05-07).
//!
//! Append-only SQLite log of self-diagnostic runs. Replaces the
//! `AI/ai/diagnostic_ledger.py` Python module per the Phase 9 roadmap;
//! Python becomes a thin subprocess shim.
//!
//! Subcommands:
//!   record --model M --n-refs N --n-with-line K [--grade A] [--crit X]
//!          [--high X] [--med X] [--low X] [--retry-used] [--report-path P] [--ts T]
//!   recent [--n N]            (JSONL of rows, most recent first)
//!   all                       (JSONL of all rows, oldest first)
//!   trend                     (JSON aggregate)
//!   summary                   (plain text summary)
//!   prune-phantom [--apply]   (default dry-run; --apply actually deletes)
//!   path                      (print resolved DB path)
//!
//! Output: JSON / JSONL on stdout per subcommand; human text for
//! `summary` and `path`. Default DB: `~/.cache/aim/ai_diagnostic_ledger.sqlite`
//! or whatever `aim_ai_ledger::Ledger::default_path()` returns.
//!
//! ENV:
//!   AI_DIAGNOSTIC_DB — override DB path (passes through to lib).

use std::process::ExitCode;

use aim_ai_ledger::Ledger;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("aim-ai-ledger: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let (cmd, rest) = args
        .split_first()
        .ok_or("usage: aim-ai-ledger <record|recent|all|trend|summary|prune-phantom|path>; --help")?;

    match cmd.as_str() {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(())
        }
        "path" => {
            println!("{}", Ledger::default_path().display());
            Ok(())
        }
        "record" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let model = take_opt(&mut rest_v, "--model").ok_or("record: --model required")?;
            let n_refs: i64 = take_opt(&mut rest_v, "--n-refs")
                .ok_or("record: --n-refs required")?
                .parse()?;
            let n_with_line: i64 = take_opt(&mut rest_v, "--n-with-line")
                .ok_or("record: --n-with-line required")?
                .parse()?;
            let grade = take_opt(&mut rest_v, "--grade");
            let crit = take_opt(&mut rest_v, "--crit").map(|s| s.parse::<i64>()).transpose()?;
            let high = take_opt(&mut rest_v, "--high").map(|s| s.parse::<i64>()).transpose()?;
            let med = take_opt(&mut rest_v, "--med").map(|s| s.parse::<i64>()).transpose()?;
            let low = take_opt(&mut rest_v, "--low").map(|s| s.parse::<i64>()).transpose()?;
            let report_path = take_opt(&mut rest_v, "--report-path");
            let ts = take_opt(&mut rest_v, "--ts");
            let retry_used = take_flag(&mut rest_v, "--retry-used");

            let l = Ledger::open_default()?;
            l.record(
                &model,
                grade.as_deref(),
                n_refs,
                n_with_line,
                crit,
                high,
                med,
                low,
                retry_used,
                report_path.as_deref(),
                ts.as_deref(),
            )?;
            Ok(())
        }
        "recent" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let n: usize = take_opt(&mut rest_v, "--n")
                .map(|s| s.parse::<usize>())
                .transpose()?
                .unwrap_or(10);
            let l = Ledger::open_default()?;
            for r in l.recent(n)? {
                println!("{}", serde_json::to_string(&r)?);
            }
            Ok(())
        }
        "all" => {
            let l = Ledger::open_default()?;
            for r in l.all_rows()? {
                println!("{}", serde_json::to_string(&r)?);
            }
            Ok(())
        }
        "trend" => {
            let l = Ledger::open_default()?;
            let t = l.trend()?;
            println!("{}", serde_json::to_string(&t)?);
            Ok(())
        }
        "summary" => {
            let l = Ledger::open_default()?;
            let t = l.trend()?;
            // Plain text summary mirroring AI/ai/diagnostic_ledger.py:summary().
            let n = t.n_runs;
            if n == 0 {
                println!("ledger empty — no diagnostic runs yet");
                return Ok(());
            }
            println!("ledger summary ({} runs)", n);
            println!("  last ts:           {}", t.last_ts.as_deref().unwrap_or("?"));
            println!("  avg compliance:    {:.0}%", t.avg_compliance * 100.0);
            println!("  avg crit:          {:.1}", t.avg_crit);
            println!("  retry share:       {:.0}%", t.retry_share * 100.0);
            let dist: Vec<String> = t
                .grade_dist
                .iter()
                .map(|(g, n)| format!("{g}:{n}"))
                .collect();
            if !dist.is_empty() {
                println!("  grade distribution: {}", dist.join(", "));
            }
            Ok(())
        }
        "prune-phantom" => {
            let mut rest_v: Vec<&str> = rest.iter().map(String::as_str).collect();
            let apply = take_flag(&mut rest_v, "--apply");
            let l = Ledger::open_default()?;
            let r = l.prune_phantom(!apply)?;  // dry_run = !apply
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
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

fn take_flag(rest: &mut Vec<&str>, key: &str) -> bool {
    if let Some(i) = rest.iter().position(|a| *a == key) {
        rest.remove(i);
        return true;
    }
    false
}

fn print_usage() {
    println!(
        "aim-ai-ledger — append-only SQLite log of self-diagnostic runs\n\n\
USAGE:\n\
  aim-ai-ledger record --model M --n-refs N --n-with-line K [--grade A]\n\
                       [--crit X --high X --med X --low X]\n\
                       [--retry-used] [--report-path P] [--ts T]\n\
  aim-ai-ledger recent [--n N]              # JSONL, most recent first\n\
  aim-ai-ledger all                         # JSONL, oldest first\n\
  aim-ai-ledger trend                       # JSON aggregate\n\
  aim-ai-ledger summary                     # plain text summary\n\
  aim-ai-ledger prune-phantom [--apply]     # default dry-run\n\
  aim-ai-ledger path                        # print DB path\n\n\
ENV: AI_DIAGNOSTIC_DB overrides DB path.\n\
DEFAULT DB: ~/.cache/aim/ai_diagnostic_ledger.sqlite (per Ledger::default_path)"
    );
}
