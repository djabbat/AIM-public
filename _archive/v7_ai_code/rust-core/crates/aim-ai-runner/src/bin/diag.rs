//! `aim-ai-diag` — run the self-diagnostic against DeepSeek.
//!
//!     aim-ai-diag                  → reasoner, save, compliance retry on
//!     aim-ai-diag --model X        → override model
//!     aim-ai-diag --no-save        → don't write artifact
//!     aim-ai-diag --force          → bypass safety gate
//!     aim-ai-diag --quiet          → minimal stdout

use aim_ai_runner::{run, DeepSeekClient, RunOpts, RunnerError};

#[tokio::main]
async fn main() -> Result<(), RunnerError> {
    let mut opts = RunOpts::default();
    let args: Vec<String> = std::env::args().collect();
    let mut quiet = false;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--model" => {
                if let Some(v) = args.get(i + 1) {
                    opts.model = v.clone();
                    i += 1;
                }
            }
            "--no-save" => opts.save = false,
            "--force" => opts.skip_safety_gate = true,
            "--quiet" => quiet = true,
            "--no-retry" => opts.compliance_retry = false,
            _ => {}
        }
        i += 1;
    }
    if !quiet {
        eprintln!("[aim-ai-diag] model: {}", opts.model);
        eprintln!("[aim-ai-diag] querying DeepSeek (this may take several minutes)…");
    }
    let client = DeepSeekClient::from_env()?;
    let res = run(&client, &opts).await?;
    if !quiet {
        eprintln!(
            "[aim-ai-diag] grade={:?} refs={} compliance={:.0}% retry={} elapsed={:.1}s",
            res.grade, res.n_findings, res.line_compliance * 100.0, res.retry_used, res.elapsed_secs
        );
        if let Some(p) = &res.report_path {
            eprintln!("[aim-ai-diag] saved → {}", p.display());
        }
    }
    println!("{}", res.report);
    Ok(())
}
