//! aim-check-docs-consistency — drift checker between code and docs.
//!
//! Port of `scripts/check_docs_consistency.py`. Four checks:
//!
//!   * every `~/.local/bin/aim-*` CLI wrapper is mentioned in at least
//!     one architecture doc,
//!   * every `agents/<module>.py` is mentioned (bare name or
//!     `agents/<name>` form),
//!   * every `AIM_*` env var read in code is documented and v.v.
//!     (with a few documented-but-external exceptions),
//!   * every `@app.get(...)` / `@router.post(...)` etc. route in
//!     `web/api.py` and `web/webhooks.py` shows up in a doc.
//!
//! Pure functions over inputs (Vec<String> of CLI / agent names, raw
//! Python source for env vars + routes, doc text). The binary is
//! responsible for filesystem walks.

use std::collections::BTreeSet;

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};

// ── env-var documented-but-external whitelist ─────────────────────────────

const ALLOWED_DOC_ONLY: &[&str] = &["AIM_PROFILE", "AIM_THREAD_ID"];

// ── individual checks ─────────────────────────────────────────────────────

pub fn check_cli_wrappers(docs: &str, cli_names: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for name in cli_names {
        if name == "aim-code-auto" {
            continue; // internal helper, not user-facing
        }
        if !docs.contains(name.as_str()) {
            out.push(format!("CLI '{}' not mentioned in any doc", name));
        }
    }
    out
}

pub fn check_agent_modules(docs: &str, module_stems: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for stem in module_stems {
        if stem == "__init__" {
            continue;
        }
        let prefixed = format!("agents/{}", stem);
        if !docs.contains(stem.as_str()) && !docs.contains(prefixed.as_str()) {
            out.push(format!("agent module 'agents/{}.py' not in docs", stem));
        }
    }
    out
}

static GETENV_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"os\.getenv\(\s*["'](AIM_[A-Z0-9_]+)["']"#).expect("GETENV_RE")
});
static ENVIRON_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"environ\[?["'](AIM_[A-Z0-9_]+)["']"#).expect("ENVIRON_RE")
});
static DOC_VAR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\bAIM_[A-Z0-9_]+\b").expect("DOC_VAR_RE"));

pub fn extract_code_env_vars(code: &str) -> BTreeSet<String> {
    let mut out: BTreeSet<String> = BTreeSet::new();
    for c in GETENV_RE.captures_iter(code) {
        if let Some(v) = c.get(1) {
            out.insert(v.as_str().to_string());
        }
    }
    for c in ENVIRON_RE.captures_iter(code) {
        if let Some(v) = c.get(1) {
            out.insert(v.as_str().to_string());
        }
    }
    out
}

pub fn extract_doc_env_vars(docs: &str) -> BTreeSet<String> {
    DOC_VAR_RE
        .find_iter(docs)
        .map(|m| m.as_str().to_string())
        .collect()
}

pub fn check_env_vars(docs: &str, code: &str) -> Vec<String> {
    let code_vars = extract_code_env_vars(code);
    let doc_vars = extract_doc_env_vars(docs);
    let mut issues = Vec::new();
    let only_in_code: Vec<&String> = code_vars.difference(&doc_vars).collect();
    let only_in_doc: Vec<&String> = doc_vars.difference(&code_vars).collect();
    for v in only_in_code {
        issues.push(format!("env var {:?} read in code but not documented", v));
    }
    for v in only_in_doc {
        if ALLOWED_DOC_ONLY.contains(&v.as_str()) {
            continue;
        }
        issues.push(format!("env var {:?} documented but not read in code", v));
    }
    issues
}

static ROUTE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r#"@(?:app|router)\.(?:get|post|websocket|put|delete|patch)\(\s*["']([^"']+)["']"#,
    )
    .expect("ROUTE_RE")
});

pub fn extract_routes(api_source: &str) -> BTreeSet<String> {
    ROUTE_RE
        .captures_iter(api_source)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect()
}

pub fn check_web_routes(docs: &str, api_source: &str) -> Vec<String> {
    let routes = extract_routes(api_source);
    let mut out = Vec::new();
    for r in &routes {
        let bare = r.replace("{task_id}", "{task}");
        if !docs.contains(r.as_str()) && !docs.contains(bare.as_str()) {
            out.push(format!("web route {:?} not in docs", r));
        }
    }
    out
}

// ── runner ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Inputs {
    pub docs: String,
    pub cli_names: Vec<String>,
    pub agent_stems: Vec<String>,
    pub code: String,
    pub api_source: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CheckResult {
    pub count: usize,
    pub issues: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Report {
    pub cli: CheckResult,
    pub agents: CheckResult,
    pub env: CheckResult,
    pub routes: CheckResult,
    pub total_issues: usize,
}

pub fn run(inputs: &Inputs) -> Report {
    let cli_issues = check_cli_wrappers(&inputs.docs, &inputs.cli_names);
    let agent_issues = check_agent_modules(&inputs.docs, &inputs.agent_stems);
    let env_issues = check_env_vars(&inputs.docs, &inputs.code);
    let route_issues = check_web_routes(&inputs.docs, &inputs.api_source);
    let total = cli_issues.len() + agent_issues.len() + env_issues.len() + route_issues.len();
    Report {
        cli: CheckResult {
            count: cli_issues.len(),
            issues: cli_issues,
        },
        agents: CheckResult {
            count: agent_issues.len(),
            issues: agent_issues,
        },
        env: CheckResult {
            count: env_issues.len(),
            issues: env_issues,
        },
        routes: CheckResult {
            count: route_issues.len(),
            issues: route_issues,
        },
        total_issues: total,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── CLI ───────────────────────────────────────────────────────────────

    #[test]
    fn cli_flags_missing_wrappers() {
        let docs = "We have aim-do and aim-recall.";
        let cli = vec!["aim-do".into(), "aim-recall".into(), "aim-mystery".into()];
        let issues = check_cli_wrappers(docs, &cli);
        assert_eq!(issues.len(), 1);
        assert!(issues[0].contains("aim-mystery"));
    }

    #[test]
    fn cli_skips_aim_code_auto() {
        let docs = "";
        let cli = vec!["aim-code-auto".into()];
        assert!(check_cli_wrappers(docs, &cli).is_empty());
    }

    // ── agents ────────────────────────────────────────────────────────────

    #[test]
    fn agents_accepts_either_name_form() {
        let docs = "We mention writer and agents/researcher.py";
        let stems = vec!["writer".into(), "researcher".into(), "ghost".into()];
        let issues = check_agent_modules(docs, &stems);
        assert_eq!(issues.len(), 1);
        assert!(issues[0].contains("ghost"));
    }

    #[test]
    fn agents_skips_init() {
        let docs = "";
        assert!(check_agent_modules(docs, &["__init__".into()]).is_empty());
    }

    // ── env vars ──────────────────────────────────────────────────────────

    #[test]
    fn env_extracts_from_getenv_and_environ() {
        let code = r#"
            x = os.getenv("AIM_HOME")
            y = os.environ["AIM_LOGLEVEL"]
            z = os.environ.get('AIM_PROFILE')
        "#;
        let vars = extract_code_env_vars(code);
        assert!(vars.contains("AIM_HOME"));
        assert!(vars.contains("AIM_LOGLEVEL"));
        // os.environ.get is not matched by either regex, mirroring Python
    }

    #[test]
    fn env_extracts_from_docs() {
        let docs = "Set AIM_HUB_URL and AIM_USER_TOKEN; reads AIM_LOGLEVEL too.";
        let vars = extract_doc_env_vars(docs);
        assert_eq!(vars.len(), 3);
        assert!(vars.contains("AIM_HUB_URL"));
    }

    #[test]
    fn env_flags_only_in_code_and_only_in_doc() {
        let code = r#"os.getenv("AIM_HOME"); os.getenv("AIM_LOGLEVEL")"#;
        let docs = "Document AIM_HOME and AIM_OFFLINE_GRACE";
        let issues = check_env_vars(docs, code);
        let only_code: Vec<&String> = issues
            .iter()
            .filter(|s| s.contains("read in code but not"))
            .collect();
        let only_docs: Vec<&String> = issues
            .iter()
            .filter(|s| s.contains("documented but not"))
            .collect();
        assert_eq!(only_code.len(), 1);
        assert!(only_code[0].contains("AIM_LOGLEVEL"));
        assert_eq!(only_docs.len(), 1);
        assert!(only_docs[0].contains("AIM_OFFLINE_GRACE"));
    }

    #[test]
    fn env_whitelists_aim_profile_aim_thread_id() {
        let docs = "AIM_PROFILE and AIM_THREAD_ID are set externally.";
        let code = "";
        let issues = check_env_vars(docs, code);
        assert!(issues.is_empty());
    }

    // ── routes ────────────────────────────────────────────────────────────

    #[test]
    fn routes_extracts_all_decorators() {
        let api = r#"
            @app.get("/health")
            @router.post("/api/auth/validate-token")
            @app.websocket("/ws/chat/{task_id}")
        "#;
        let routes = extract_routes(api);
        assert_eq!(routes.len(), 3);
        assert!(routes.contains("/health"));
    }

    #[test]
    fn routes_normalises_task_id_placeholder() {
        let api = r#"@app.websocket("/ws/chat/{task_id}")"#;
        let docs = "We document /ws/chat/{task} as the chat WS.";
        let issues = check_web_routes(docs, api);
        assert!(issues.is_empty());
    }

    #[test]
    fn routes_flags_undocumented() {
        let api = r#"@app.get("/health"); @app.post("/api/secret")"#;
        let docs = "Mentions only /health.";
        let issues = check_web_routes(docs, api);
        assert_eq!(issues.len(), 1);
        assert!(issues[0].contains("/api/secret"));
    }

    // ── runner ────────────────────────────────────────────────────────────

    #[test]
    fn run_reports_zero_issues_when_all_clean() {
        let inputs = Inputs {
            docs: "aim-do, agents/writer, AIM_HOME, /health".into(),
            cli_names: vec!["aim-do".into()],
            agent_stems: vec!["writer".into()],
            code: r#"os.getenv("AIM_HOME")"#.into(),
            api_source: r#"@app.get("/health")"#.into(),
        };
        let report = run(&inputs);
        assert_eq!(report.total_issues, 0);
    }

    #[test]
    fn run_aggregates_per_check_count() {
        let inputs = Inputs {
            docs: "(no mentions)".into(),
            cli_names: vec!["aim-mystery".into()],
            agent_stems: vec!["ghost".into()],
            code: r#"os.getenv("AIM_NEW")"#.into(),
            api_source: r#"@app.post("/api/secret")"#.into(),
        };
        let report = run(&inputs);
        assert_eq!(report.cli.count, 1);
        assert_eq!(report.agents.count, 1);
        assert!(report.env.count >= 1);
        assert_eq!(report.routes.count, 1);
        assert_eq!(report.total_issues, report.cli.count + report.agents.count + report.env.count + report.routes.count);
    }
}
