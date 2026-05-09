//! aim-ai-runner — actually RUN the self-diagnostic.
//!
//! Where `aim-ai-self-diagnostic` only emits the prompt for human
//! pasting, this crate posts it to DeepSeek, saves the resulting
//! audit report under `AIM/AI/artifacts/`, and records a row into
//! the ledger.
//!
//! Compliance retry: if the first response has < `min_compliance`
//! line-refs carrying `:line`, append a corrective suffix and retry
//! once. If retry compliance doesn't improve, keep the first reply.
//!
//! Safety gate: when not skipped, `aim-ai-safety-gate::can_run` blocks
//! on cooldown / daily-budget breach.
//!
//! Rust port of `AI/ai/run_self_diagnostic.py`.

use aim_ai_ledger::Ledger;
use aim_ai_meta_evaluator::parse_report;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::Duration;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RunnerError {
    #[error("safety gate blocked diagnostic run: {0}")]
    SafetyBlocked(String),
    #[error("DEEPSEEK_API_KEY not found in env or ~/.aim_env")]
    NoApiKey,
    #[error("transport: {0}")]
    Transport(#[from] reqwest::Error),
    #[error("upstream HTTP {status}: {body}")]
    Http { status: u16, body: String },
    #[error("self-diagnostic: {0}")]
    SelfDiag(#[from] aim_ai_self_diagnostic::SelfDiagError),
    #[error("safety gate: {0}")]
    Safety(#[from] aim_ai_safety_gate::SafetyError),
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunResult {
    pub report: String,
    pub report_path: Option<PathBuf>,
    pub model_used: String,
    pub elapsed_secs: f64,
    pub retry_used: bool,
    pub line_compliance: f64,
    pub n_findings: u32,
    pub grade: Option<String>,
}

#[derive(Debug, Clone)]
pub struct RunOpts {
    pub model: String,
    pub save: bool,
    pub compliance_retry: bool,
    pub min_compliance: f64,
    pub skip_safety_gate: bool,
    pub repo_root: PathBuf,
}

impl Default for RunOpts {
    fn default() -> Self {
        Self {
            model: "deepseek-reasoner".into(),
            save: true,
            compliance_retry: true,
            min_compliance: 0.5,
            skip_safety_gate: false,
            repo_root: aim_ai_self_diagnostic::project_root(),
        }
    }
}

/// Trait so tests inject deterministic stubs without hitting DeepSeek.
#[async_trait::async_trait]
pub trait LlmClient: Send + Sync {
    async fn chat(&self, prompt: &str, model: &str) -> Result<String, RunnerError>;
}

/// Default DeepSeek client: POST /v1/chat/completions.
pub struct DeepSeekClient {
    pub api_key: String,
    pub timeout: Duration,
    pub base_url: String,
}

impl DeepSeekClient {
    pub fn from_env() -> Result<Self, RunnerError> {
        let key = resolve_api_key().ok_or(RunnerError::NoApiKey)?;
        Ok(Self {
            api_key: key,
            timeout: Duration::from_secs(600),
            base_url: std::env::var("DEEPSEEK_BASE_URL")
                .unwrap_or_else(|_| "https://api.deepseek.com".into()),
        })
    }
}

#[async_trait::async_trait]
impl LlmClient for DeepSeekClient {
    async fn chat(&self, prompt: &str, model: &str) -> Result<String, RunnerError> {
        let body = serde_json::json!({
            "model": model,
            "messages": [
                {"role": "system",
                 "content": "You are an adversarial code auditor. Find defects, do not confirm health. Every finding must reference path:line. Fabrications fail L_VERIFIABILITY. Return one markdown report with all 9 phases."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 16000,
        });
        let url = format!("{}/v1/chat/completions", self.base_url.trim_end_matches('/'));
        let client = reqwest::Client::builder().timeout(self.timeout).build()?;
        let resp = client
            .post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(RunnerError::Http {
                status: status.as_u16(),
                body,
            });
        }
        let v: serde_json::Value = resp.json().await?;
        let content = v
            .get("choices")
            .and_then(|c| c.get(0))
            .and_then(|c| c.get("message"))
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or("")
            .to_string();
        Ok(content)
    }
}

fn resolve_api_key() -> Option<String> {
    if let Ok(v) = std::env::var("DEEPSEEK_API_KEY") {
        if !v.is_empty() {
            return Some(v);
        }
    }
    let home = std::env::var("HOME").ok()?;
    let aim_env = PathBuf::from(home).join(".aim_env");
    let text = std::fs::read_to_string(&aim_env).ok()?;
    for line in text.lines() {
        let line = line.trim();
        for prefix in ["DEEPSEEK_API_KEY=", "export DEEPSEEK_API_KEY="] {
            if let Some(rest) = line.strip_prefix(prefix) {
                let v = rest.trim().trim_matches(|c| c == '\'' || c == '"');
                if !v.is_empty() {
                    return Some(v.to_string());
                }
            }
        }
    }
    None
}

const COMPLIANCE_RETRY_SUFFIX: &str = "\n\n---\n\n**CRITICAL — REPEATED INSTRUCTION:** Your previous response had {prev}% line-compliance ({n_with}/{n_total} findings carried a `:line` ref). The diagnostic spec REQUIRES `path:line` (e.g. `AIM/AI/ai/distillation_tracker.py:42`) on every finding. Re-emit the ENTIRE 9-phase report with at least 80% line compliance. Findings without `:line` will be discarded post-hoc.";

fn compliance_of(report: &str) -> (f64, u32, u32) {
    let p = parse_report(report);
    let n_total = p.findings.len() as u32;
    let n_with = p
        .findings
        .iter()
        .filter(|r| {
            if let Some((_, tail)) = r.rsplit_once(':') {
                tail.chars().all(|c| c.is_ascii_digit())
            } else {
                false
            }
        })
        .count() as u32;
    (p.line_compliance(), n_with, n_total)
}

/// Today-dated artifact path: `<repo>/AIM/AI/artifacts/self_diag_<YYYY-MM-DD>.md`.
pub fn output_path(repo_root: &Path, today: chrono::NaiveDate) -> PathBuf {
    aim_ai_self_diagnostic::ai_root(repo_root)
        .join("artifacts")
        .join(format!("self_diag_{}.md", today.format("%Y-%m-%d")))
}

/// Build prompt → call LLM → save → record. Returns RunResult.
pub async fn run<C: LlmClient>(
    client: &C,
    opts: &RunOpts,
) -> Result<RunResult, RunnerError> {
    // Safety gate
    if !opts.skip_safety_gate {
        let ledger = Ledger::open_default()?;
        let v = aim_ai_safety_gate::can_run(&ledger)?;
        if !v.allowed {
            return Err(RunnerError::SafetyBlocked(v.reasons.join("; ")));
        }
    }

    let prompt = aim_ai_self_diagnostic::build_prompt(&opts.repo_root)?;
    let t0 = std::time::Instant::now();

    // First call (with chat fallback if reasoner fails)
    let primary_model = opts.model.clone();
    let report = match client.chat(&prompt, &primary_model).await {
        Ok(s) => s,
        Err(e) if primary_model == "deepseek-reasoner" => {
            tracing::info!(error = ?e, "reasoner failed; falling back to deepseek-chat");
            client.chat(&prompt, "deepseek-chat").await?
        }
        Err(e) => return Err(e),
    };

    // Compliance retry
    let mut final_report = report;
    let mut retry_used = false;
    if opts.compliance_retry {
        let (comp, n_with, n_total) = compliance_of(&final_report);
        if n_total > 0 && comp < opts.min_compliance {
            let retry_prompt = format!(
                "{}{}",
                prompt,
                COMPLIANCE_RETRY_SUFFIX
                    .replace("{prev}", &format!("{:.0}", comp * 100.0))
                    .replace("{n_with}", &n_with.to_string())
                    .replace("{n_total}", &n_total.to_string())
            );
            match client.chat(&retry_prompt, &opts.model).await {
                Ok(retry) => {
                    let (retry_comp, _, _) = compliance_of(&retry);
                    if retry_comp > comp {
                        final_report = retry;
                        retry_used = true;
                    }
                }
                Err(e) => tracing::warn!(error = ?e, "compliance retry failed; keeping first response"),
            }
        }
    }

    let elapsed = t0.elapsed().as_secs_f64();
    let parsed = parse_report(&final_report);
    let line_compliance = parsed.line_compliance();
    let n_findings = parsed.findings.len() as u32;
    let grade = parsed.grade.clone();

    let report_path = if opts.save {
        let today = chrono::Utc::now().date_naive();
        let out = output_path(&opts.repo_root, today);
        if let Some(p) = out.parent() {
            std::fs::create_dir_all(p)?;
        }
        std::fs::write(&out, &final_report)?;

        // Ledger record
        if let Ok(ledger) = Ledger::open_default() {
            let n_refs = parsed.findings.len() as i64;
            let n_with_line = parsed
                .findings
                .iter()
                .filter(|r| {
                    if let Some((_, tail)) = r.rsplit_once(':') {
                        tail.chars().all(|c| c.is_ascii_digit())
                    } else {
                        false
                    }
                })
                .count() as i64;
            let crit = parsed.totals.get("crit").copied();
            let high = parsed.totals.get("high").copied();
            let med = parsed.totals.get("med").copied();
            let low = parsed.totals.get("low").copied();
            let _ = ledger.record(
                &opts.model,
                grade.as_deref(),
                n_refs,
                n_with_line,
                crit,
                high,
                med,
                low,
                retry_used,
                Some(out.to_string_lossy().as_ref()),
                None,
            );
        }
        // Prompt fingerprint
        if let Ok(store) = aim_ai_prompt_versions::PromptStore::open_default() {
            let _ = store.record_current(None, None);
        }
        Some(out)
    } else {
        None
    };

    Ok(RunResult {
        report: final_report,
        report_path,
        model_used: primary_model,
        elapsed_secs: elapsed,
        retry_used,
        line_compliance,
        n_findings,
        grade,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use tempfile::tempdir;

    struct StubClient {
        responses: Mutex<Vec<String>>,
    }

    #[async_trait::async_trait]
    impl LlmClient for StubClient {
        async fn chat(&self, _prompt: &str, _model: &str) -> Result<String, RunnerError> {
            let mut q = self.responses.lock().unwrap();
            Ok(q.pop()
                .unwrap_or_else(|| "Grade: A\nagents/x.py:1".to_string()))
        }
    }

    fn fixture(repo: &Path) {
        let docs = repo.join("AIM").join("AI").join("docs");
        std::fs::create_dir_all(&docs).unwrap();
        std::fs::write(docs.join("SELF_DIAGNOSTIC_PROMPT.md"), "Audit\n").unwrap();
    }

    #[tokio::test]
    async fn run_happy_path_records_ledger() {
        let d = tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        fixture(d.path());
        let stub = StubClient {
            responses: Mutex::new(vec![
                "Grade: A\nagents/x.py:1 and agents/y.py:2".to_string(),
            ]),
        };
        let opts = RunOpts {
            repo_root: d.path().to_path_buf(),
            skip_safety_gate: true,
            compliance_retry: false,
            ..Default::default()
        };
        let res = run(&stub, &opts).await.unwrap();
        assert_eq!(res.grade.as_deref(), Some("A"));
        assert_eq!(res.n_findings, 2);
        assert!(!res.retry_used);
        assert!(res.report_path.is_some());
        assert!(res.report_path.unwrap().exists());
    }

    #[tokio::test]
    async fn run_compliance_retry_when_below_threshold() {
        let d = tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        fixture(d.path());
        // First response: low compliance (no :line); retry: better
        let stub = StubClient {
            responses: Mutex::new(vec![
                "Grade: B\nagents/a.py:1 and agents/b.py:2".to_string(), // retry
                "Grade: B\nagents/a.py and agents/b.py".to_string(),     // first
            ]),
        };
        let opts = RunOpts {
            repo_root: d.path().to_path_buf(),
            skip_safety_gate: true,
            compliance_retry: true,
            min_compliance: 0.5,
            save: false,
            ..Default::default()
        };
        let res = run(&stub, &opts).await.unwrap();
        assert!(res.retry_used);
        assert!(res.line_compliance > 0.5);
    }

    #[tokio::test]
    async fn run_no_save_no_artifacts() {
        let d = tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        fixture(d.path());
        let stub = StubClient {
            responses: Mutex::new(vec!["Grade: A\nagents/a.py:1".into()]),
        };
        let opts = RunOpts {
            repo_root: d.path().to_path_buf(),
            skip_safety_gate: true,
            compliance_retry: false,
            save: false,
            ..Default::default()
        };
        let res = run(&stub, &opts).await.unwrap();
        assert!(res.report_path.is_none());
    }

    #[test]
    fn output_path_uses_today_date() {
        let d = tempdir().unwrap();
        let p = output_path(d.path(), chrono::NaiveDate::from_ymd_opt(2026, 5, 4).unwrap());
        let s = p.to_string_lossy().to_string();
        assert!(s.contains("self_diag_2026-05-04.md"));
    }

    #[test]
    fn compliance_of_counts_line_refs() {
        let (c, w, t) = compliance_of("Grade: B\nagents/a.py:1 and agents/b.py:2 and agents/c.py");
        assert_eq!(t, 3);
        assert_eq!(w, 2);
        assert!((c - 2.0 / 3.0).abs() < 1e-9);
    }

    #[test]
    fn compliance_of_empty_report() {
        let (c, w, t) = compliance_of("(no findings)");
        assert_eq!(t, 0);
        assert_eq!(w, 0);
        assert_eq!(c, 0.0);
    }
}
