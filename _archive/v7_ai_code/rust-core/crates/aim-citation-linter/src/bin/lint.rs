//! `aim-citation-linter` — repo-wide citation lint CLI.
//!
//!     aim-citation-linter [path]              → text summary
//!     aim-citation-linter [path] --json       → JSON Report
//!     aim-citation-linter [path] --strict     → exit non-zero on any issue
//!
//! By default uses the `AlwaysUnresolved` verifier — every PMID/DOI is
//! reported as unresolved. Wire a real `Verifier` impl by linking this
//! library into a host binary.

use aim_citation_guard::AlwaysUnresolved;
use aim_citation_linter::{LintOpts, Linter};
use std::path::PathBuf;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut root = PathBuf::from(".");
    let mut as_json = false;
    let mut strict = false;
    let mut ignore: Vec<String> = Vec::new();
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--json" => as_json = true,
            "--strict" => strict = true,
            "--ignore" => {
                if let Some(v) = args.get(i + 1) {
                    ignore.push(v.clone());
                    i += 1;
                }
            }
            arg if !arg.starts_with("--") => root = PathBuf::from(arg),
            _ => {}
        }
        i += 1;
    }
    let opts = LintOpts { ignore_globs: ignore };
    let linter = Linter::new(AlwaysUnresolved);
    let report = linter.lint(&root, &opts);
    if as_json {
        match serde_json::to_string_pretty(&report) {
            Ok(s) => println!("{s}"),
            Err(e) => {
                eprintln!("[aim-citation-linter] json serialise failed: {e}");
                std::process::exit(2);
            }
        }
    } else {
        println!("{}", report.summary());
    }
    if strict && report.has_problems() {
        std::process::exit(1);
    }
}
