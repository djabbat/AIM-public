//! aim-evals — Eval harness foundation (S1, port of `agents/evals.py`).
//!
//! The keystone of closed-loop self-improvement: nothing automatic in S2-S7
//! is allowed to ship without a measured improvement on this harness.
//!
//! ## Anatomy
//! - [`EvalCase`] — a single task with input + scoring rubric (regex/JSON/
//!   keyword/exact). Stored as YAML in `tests/evals/cases/`.
//! - [`score_case`] — runs rubric set against an output, returns float [0,1].
//! - [`Harness::run_case`] — invokes a callable with the case input, scores,
//!   logs latency + cost.
//! - [`Harness::run_all`] — runs every case, returns [`EvalRun`].
//! - [`Harness::compare`] — version-vs-version delta with verdict
//!   (`improved`/`regressed`/`neutral`).
//!
//! The harness deliberately knows nothing about LLMs — it takes a closure
//! `Fn(&str) -> Result<String, _>`. S3 (prompt patches), S5 (router A/B),
//! S2 (synthesised tools) plug in by passing different closures.

use chrono::Utc;
use parking_lot::Mutex;
use regex::Regex;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;
use std::time::Instant;

#[derive(Debug, Error)]
pub enum EvalError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvalCase {
    pub id: String,
    pub task: String,
    #[serde(default)]
    pub rubrics: BTreeMap<String, serde_yaml::Value>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default = "one")]
    pub weight: f64,
}

fn one() -> f64 {
    1.0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseResult {
    pub case_id: String,
    pub score: f64,
    pub latency_ms: u64,
    pub cost_usd: f64,
    pub output: String,
    pub rubric_scores: BTreeMap<String, f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvalRun {
    pub version: String,
    pub run_at: String,
    pub cases: Vec<CaseResult>,
}

impl EvalRun {
    pub fn aggregate_score(&self) -> f64 {
        if self.cases.is_empty() {
            return 0.0;
        }
        let s: f64 = self.cases.iter().map(|c| c.score).sum();
        s / self.cases.len() as f64
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Compare {
    pub a: f64,
    pub b: f64,
    pub delta: f64,
    pub verdict: String,
}

// ── case loading ──────────────────────────────────────────────────────────

pub fn default_cases_dir() -> PathBuf {
    if let Ok(v) = std::env::var("AIM_EVAL_CASES_DIR") {
        let v = v.trim();
        if !v.is_empty() {
            return expand_tilde(v);
        }
    }
    // No "AIM home" — caller decides.
    PathBuf::from("tests/evals/cases")
}

pub fn default_db_path() -> PathBuf {
    if let Ok(v) = std::env::var("AIM_EVAL_DB") {
        let v = v.trim();
        if !v.is_empty() {
            return expand_tilde(v);
        }
    }
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::var("HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(".cache")
                .join("aim")
        });
    base.join("eval_runs.db")
}

fn expand_tilde(p: &str) -> PathBuf {
    if let Some(rest) = p.strip_prefix("~/") {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        home.join(rest)
    } else if p == "~" {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
    } else {
        PathBuf::from(p)
    }
}

pub fn load_cases(dir: &Path) -> Result<Vec<EvalCase>, EvalError> {
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut paths: Vec<PathBuf> = std::fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "yaml" || x == "yml").unwrap_or(false))
        .collect();
    paths.sort();
    let mut out = Vec::new();
    for p in paths {
        let raw = match std::fs::read_to_string(&p) {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!("skip {}: {e}", p.display());
                continue;
            }
        };
        match serde_yaml::from_str::<serde_yaml::Value>(&raw) {
            Ok(serde_yaml::Value::Mapping(_)) => {}
            Ok(_) => {
                tracing::warn!("skip {}: not a mapping", p.display());
                continue;
            }
            Err(e) => {
                tracing::warn!("skip {}: {e}", p.display());
                continue;
            }
        }
        let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("case").to_string();
        match serde_yaml::from_str::<EvalCase>(&raw) {
            Ok(mut c) => {
                if c.id.is_empty() {
                    c.id = stem;
                }
                out.push(c);
            }
            Err(e) => tracing::warn!("skip {}: {e}", p.display()),
        }
    }
    Ok(out)
}

// ── rubrics ──────────────────────────────────────────────────────────────

fn as_str_list(v: &serde_yaml::Value) -> Vec<String> {
    match v {
        serde_yaml::Value::Sequence(s) => s
            .iter()
            .map(|x| match x {
                serde_yaml::Value::String(s) => s.clone(),
                other => serde_yaml::to_string(other).unwrap_or_default().trim().to_string(),
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn score_regex(output: &str, v: &serde_yaml::Value) -> f64 {
    let pat = match v.as_str() {
        Some(s) => s,
        None => return 0.0,
    };
    match Regex::new(pat) {
        Ok(re) => {
            if re.is_match(output) {
                1.0
            } else {
                0.0
            }
        }
        Err(_) => 0.0,
    }
}

fn score_contains_all(output: &str, v: &serde_yaml::Value) -> f64 {
    let terms = as_str_list(v);
    if terms.is_empty() {
        return 1.0;
    }
    let lo = output.to_lowercase();
    let hits = terms.iter().filter(|t| lo.contains(&t.to_lowercase())).count();
    hits as f64 / terms.len() as f64
}

fn score_contains_any(output: &str, v: &serde_yaml::Value) -> f64 {
    let terms = as_str_list(v);
    if terms.is_empty() {
        return 1.0;
    }
    let lo = output.to_lowercase();
    if terms.iter().any(|t| lo.contains(&t.to_lowercase())) {
        1.0
    } else {
        0.0
    }
}

fn score_forbids(output: &str, v: &serde_yaml::Value) -> f64 {
    let terms = as_str_list(v);
    if terms.is_empty() {
        return 1.0;
    }
    let lo = output.to_lowercase();
    if terms.iter().any(|t| lo.contains(&t.to_lowercase())) {
        0.0
    } else {
        1.0
    }
}

fn score_exact(output: &str, v: &serde_yaml::Value) -> f64 {
    let expected = match v.as_str() {
        Some(s) => s,
        None => return 0.0,
    };
    if output.trim() == expected.trim() {
        1.0
    } else {
        0.0
    }
}

fn score_json_keys(output: &str, v: &serde_yaml::Value) -> f64 {
    let keys = as_str_list(v);
    if keys.is_empty() {
        return 1.0;
    }
    let obj: serde_json::Value = match serde_json::from_str(output) {
        Ok(o) => o,
        Err(_) => return 0.0,
    };
    let hits = keys
        .iter()
        .filter(|k| {
            let mut cur = &obj;
            for part in k.split('.') {
                match cur.get(part) {
                    Some(v) => cur = v,
                    None => return false,
                }
            }
            true
        })
        .count();
    hits as f64 / keys.len() as f64
}

fn score_min_length(output: &str, v: &serde_yaml::Value) -> f64 {
    let n = v.as_i64().unwrap_or(0) as usize;
    if output.len() >= n {
        1.0
    } else {
        0.0
    }
}

fn score_max_length(output: &str, v: &serde_yaml::Value) -> f64 {
    let n = v.as_i64().unwrap_or(0) as usize;
    if output.len() <= n {
        1.0
    } else {
        0.0
    }
}

pub fn score_case(
    output: &str,
    rubrics: &BTreeMap<String, serde_yaml::Value>,
) -> (f64, BTreeMap<String, f64>) {
    if rubrics.is_empty() {
        return (1.0, BTreeMap::new());
    }
    let mut per: BTreeMap<String, f64> = BTreeMap::new();
    for (name, val) in rubrics {
        let f = match name.as_str() {
            "regex" => score_regex,
            "contains_all" => score_contains_all,
            "contains_any" => score_contains_any,
            "forbids" => score_forbids,
            "exact" => score_exact,
            "json_keys" => score_json_keys,
            "min_length" => score_min_length,
            "max_length" => score_max_length,
            _ => {
                tracing::warn!("unknown rubric {:?} — ignored", name);
                continue;
            }
        };
        per.insert(name.clone(), f(output, val));
    }
    if per.is_empty() {
        return (1.0, per);
    }
    let sum: f64 = per.values().sum();
    (sum / per.len() as f64, per)
}

// ── DB / harness ──────────────────────────────────────────────────────────

pub struct Harness {
    cases_dir: PathBuf,
    conn: Arc<Mutex<Connection>>,
}

impl Harness {
    pub fn new(cases_dir: impl Into<PathBuf>, db_path: impl AsRef<Path>) -> Result<Self, EvalError> {
        let db = db_path.as_ref();
        if let Some(parent) = db.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let conn = Connection::open(db)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS eval_runs (\
                id INTEGER PRIMARY KEY AUTOINCREMENT,\
                version TEXT NOT NULL,\
                run_at TEXT NOT NULL,\
                case_id TEXT NOT NULL,\
                score REAL NOT NULL,\
                latency_ms INTEGER NOT NULL,\
                cost_usd REAL NOT NULL DEFAULT 0,\
                error TEXT,\
                rubric_scores TEXT\
            );\
            CREATE INDEX IF NOT EXISTS idx_eval_version ON eval_runs(version, run_at);",
        )?;
        Ok(Self {
            cases_dir: cases_dir.into(),
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub fn cases_dir(&self) -> &Path {
        &self.cases_dir
    }

    pub fn load_cases(&self) -> Result<Vec<EvalCase>, EvalError> {
        load_cases(&self.cases_dir)
    }

    pub fn run_case<F>(&self, case: &EvalCase, mut fn_: F, cost_per_call: f64) -> CaseResult
    where
        F: FnMut(&str) -> Result<String, String>,
    {
        let t0 = Instant::now();
        let (out, err) = match fn_(&case.task) {
            Ok(s) => (s, None),
            Err(e) => (String::new(), Some(e)),
        };
        let latency_ms = t0.elapsed().as_millis() as u64;
        let (score, per) = if err.is_some() {
            (0.0, BTreeMap::new())
        } else {
            score_case(&out, &case.rubrics)
        };
        let mut output = out;
        if output.len() > 4000 {
            output.truncate(4000);
        }
        CaseResult {
            case_id: case.id.clone(),
            score,
            latency_ms,
            cost_usd: cost_per_call,
            output,
            rubric_scores: per,
            error: err,
        }
    }

    pub fn run_all<F>(
        &self,
        mut fn_: F,
        version: &str,
        cost_per_call: f64,
        persist: bool,
        tag_filter: Option<&str>,
    ) -> Result<EvalRun, EvalError>
    where
        F: FnMut(&str) -> Result<String, String>,
    {
        let cases = self.load_cases()?;
        let cases: Vec<EvalCase> = match tag_filter {
            Some(tag) => cases
                .into_iter()
                .filter(|c| c.tags.iter().any(|t| t == tag))
                .collect(),
            None => cases,
        };
        let results: Vec<CaseResult> = cases
            .iter()
            .map(|c| self.run_case(c, &mut fn_, cost_per_call))
            .collect();
        let run = EvalRun {
            version: version.to_string(),
            run_at: Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
            cases: results,
        };
        if persist {
            self.persist(&run)?;
        }
        Ok(run)
    }

    pub fn persist(&self, run: &EvalRun) -> Result<(), EvalError> {
        let con = self.conn.lock();
        let tx = con.unchecked_transaction()?;
        for c in &run.cases {
            let rubric_scores = serde_json::to_string(&c.rubric_scores)?;
            tx.execute(
                "INSERT INTO eval_runs(version, run_at, case_id, score, latency_ms, cost_usd, error, rubric_scores) \
                 VALUES (?,?,?,?,?,?,?,?)",
                params![
                    run.version,
                    run.run_at,
                    c.case_id,
                    c.score,
                    c.latency_ms as i64,
                    c.cost_usd,
                    c.error,
                    rubric_scores,
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn latest_score(&self, version: &str) -> Result<Option<f64>, EvalError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT AVG(score) FROM eval_runs WHERE version=? AND run_at=(SELECT MAX(run_at) FROM eval_runs WHERE version=?)",
        )?;
        let s: Option<f64> = stmt.query_row(params![version, version], |r| r.get(0)).unwrap_or(None);
        Ok(s)
    }

    pub fn compare(&self, version_a: &str, version_b: &str) -> Result<Compare, EvalError> {
        let a = self.latest_score(version_a)?.unwrap_or(0.0);
        let b = self.latest_score(version_b)?.unwrap_or(0.0);
        let delta = b - a;
        let verdict = if delta > 0.01 {
            "improved"
        } else if delta < -0.01 {
            "regressed"
        } else {
            "neutral"
        };
        Ok(Compare {
            a,
            b,
            delta,
            verdict: verdict.into(),
        })
    }
}

// ── builtin starter case ──────────────────────────────────────────────────

pub const BUILTIN_SMOKE_GREETING_YAML: &str = "id: smoke-greeting\n\
task: \"Say hello in one short sentence.\"\n\
tags: [smoke, sanity]\n\
rubrics:\n\
  contains_any: [\"hello\", \"привет\", \"hi\", \"hey\"]\n\
  max_length: 200\n";

pub fn ensure_starter_cases(dir: &Path) -> Result<(), EvalError> {
    if dir.exists() {
        let any_yaml = std::fs::read_dir(dir)?
            .filter_map(|e| e.ok())
            .any(|e| e.path().extension().map(|x| x == "yaml" || x == "yml").unwrap_or(false));
        if any_yaml {
            return Ok(());
        }
    }
    std::fs::create_dir_all(dir)?;
    std::fs::write(dir.join("smoke-greeting.yaml"), BUILTIN_SMOKE_GREETING_YAML)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make_rubrics(pairs: &[(&str, serde_yaml::Value)]) -> BTreeMap<String, serde_yaml::Value> {
        let mut m = BTreeMap::new();
        for (k, v) in pairs {
            m.insert((*k).to_string(), v.clone());
        }
        m
    }

    #[test]
    fn score_contains_any_partial_credit_does_not_apply() {
        let r = make_rubrics(&[("contains_any", serde_yaml::from_str("[hello, привет]").unwrap())]);
        let (s, per) = score_case("HELLO, world", &r);
        assert_eq!(s, 1.0);
        assert!((per["contains_any"] - 1.0).abs() < 1e-9);
    }

    #[test]
    fn score_contains_all_partial_credit() {
        let r = make_rubrics(&[("contains_all", serde_yaml::from_str("[a, b, c]").unwrap())]);
        let (s, _) = score_case("a and b only", &r);
        assert!((s - 2.0 / 3.0).abs() < 1e-9);
    }

    #[test]
    fn score_forbids_blocks() {
        let r = make_rubrics(&[("forbids", serde_yaml::from_str("[\"as an AI\"]").unwrap())]);
        let (s, _) = score_case("As an AI language model, I cannot...", &r);
        assert_eq!(s, 0.0);
    }

    #[test]
    fn score_regex() {
        let r = make_rubrics(&[("regex", serde_yaml::Value::String("^hello".into()))]);
        let (s, _) = score_case("hello world", &r);
        assert_eq!(s, 1.0);
        let (s2, _) = score_case("world hello", &r);
        assert_eq!(s2, 0.0);
    }

    #[test]
    fn score_json_keys_dotted() {
        let r = make_rubrics(&[("json_keys", serde_yaml::from_str("[a, b.c]").unwrap())]);
        let (s, _) = score_case("{\"a\": 1, \"b\": {\"c\": 2}}", &r);
        assert_eq!(s, 1.0);
        let (s2, _) = score_case("{\"a\": 1}", &r);
        assert_eq!(s2, 0.5);
    }

    #[test]
    fn score_min_max_length() {
        let r1 = make_rubrics(&[("min_length", serde_yaml::Value::Number(10.into()))]);
        let (s1, _) = score_case("short", &r1);
        assert_eq!(s1, 0.0);
        let r2 = make_rubrics(&[("max_length", serde_yaml::Value::Number(3.into()))]);
        let (s2, _) = score_case("12345", &r2);
        assert_eq!(s2, 0.0);
    }

    #[test]
    fn score_exact() {
        let r = make_rubrics(&[("exact", serde_yaml::Value::String("yes".into()))]);
        let (s, _) = score_case("  yes  ", &r);
        assert_eq!(s, 1.0);
        let (s2, _) = score_case("no", &r);
        assert_eq!(s2, 0.0);
    }

    #[test]
    fn aggregate_score_average() {
        let cases = vec![
            CaseResult {
                case_id: "a".into(),
                score: 1.0,
                latency_ms: 1,
                cost_usd: 0.0,
                output: "".into(),
                rubric_scores: BTreeMap::new(),
                error: None,
            },
            CaseResult {
                case_id: "b".into(),
                score: 0.0,
                latency_ms: 1,
                cost_usd: 0.0,
                output: "".into(),
                rubric_scores: BTreeMap::new(),
                error: None,
            },
        ];
        let run = EvalRun { version: "v".into(), run_at: "x".into(), cases };
        assert!((run.aggregate_score() - 0.5).abs() < 1e-9);
    }

    #[test]
    fn ensure_starter_creates_yaml() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        ensure_starter_cases(&cases).unwrap();
        assert!(cases.join("smoke-greeting.yaml").exists());
        // Idempotent
        ensure_starter_cases(&cases).unwrap();
        let n = std::fs::read_dir(&cases).unwrap().count();
        assert_eq!(n, 1);
    }

    #[test]
    fn load_cases_reads_yaml() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        ensure_starter_cases(&cases).unwrap();
        let loaded = load_cases(&cases).unwrap();
        assert_eq!(loaded.len(), 1);
        assert_eq!(loaded[0].id, "smoke-greeting");
        assert_eq!(loaded[0].tags, vec!["smoke", "sanity"]);
    }

    #[test]
    fn run_case_records_latency_and_score() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        let db = dir.path().join("eval.db");
        ensure_starter_cases(&cases).unwrap();
        let h = Harness::new(&cases, &db).unwrap();
        let case = h.load_cases().unwrap().into_iter().next().unwrap();
        let r = h.run_case(&case, |t| Ok(format!("hello — you said: {t}")), 0.0);
        assert_eq!(r.case_id, "smoke-greeting");
        assert_eq!(r.score, 1.0);
        assert!(r.error.is_none());
    }

    #[test]
    fn run_case_handles_callable_error() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        let db = dir.path().join("eval.db");
        ensure_starter_cases(&cases).unwrap();
        let h = Harness::new(&cases, &db).unwrap();
        let case = h.load_cases().unwrap().into_iter().next().unwrap();
        let r = h.run_case(&case, |_| Err("boom".to_string()), 0.0);
        assert_eq!(r.score, 0.0);
        assert_eq!(r.error.as_deref(), Some("boom"));
    }

    #[test]
    fn run_all_filters_by_tag() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        let db = dir.path().join("eval.db");
        std::fs::create_dir_all(&cases).unwrap();
        std::fs::write(
            cases.join("a.yaml"),
            "id: a\ntask: \"x\"\ntags: [smoke]\nrubrics: {}\n",
        )
        .unwrap();
        std::fs::write(
            cases.join("b.yaml"),
            "id: b\ntask: \"x\"\ntags: [hard]\nrubrics: {}\n",
        )
        .unwrap();
        let h = Harness::new(&cases, &db).unwrap();
        let run = h.run_all(|_| Ok("ok".into()), "v1", 0.0, false, Some("smoke")).unwrap();
        assert_eq!(run.cases.len(), 1);
        assert_eq!(run.cases[0].case_id, "a");
    }

    #[test]
    fn persist_and_compare_versions() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        let db = dir.path().join("eval.db");
        std::fs::create_dir_all(&cases).unwrap();
        std::fs::write(
            cases.join("a.yaml"),
            "id: a\ntask: \"task A\"\ntags: []\nrubrics:\n  contains_any: [hello]\n",
        )
        .unwrap();
        let h = Harness::new(&cases, &db).unwrap();
        // v1: bad answer → 0.0
        h.run_all(|_| Ok("nope".into()), "v1", 0.0, true, None).unwrap();
        // v2: good answer → 1.0
        h.run_all(|_| Ok("hello world".into()), "v2", 0.0, true, None).unwrap();
        let cmp = h.compare("v1", "v2").unwrap();
        assert_eq!(cmp.verdict, "improved");
        assert!(cmp.delta > 0.5);
    }

    #[test]
    fn compare_neutral_when_no_data() {
        let dir = TempDir::new().unwrap();
        let cases = dir.path().join("cases");
        let db = dir.path().join("eval.db");
        std::fs::create_dir_all(&cases).unwrap();
        let h = Harness::new(&cases, &db).unwrap();
        let cmp = h.compare("absent-a", "absent-b").unwrap();
        assert_eq!(cmp.verdict, "neutral");
        assert_eq!(cmp.a, 0.0);
        assert_eq!(cmp.b, 0.0);
    }
}
