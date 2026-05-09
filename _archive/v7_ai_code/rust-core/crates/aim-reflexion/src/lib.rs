//! aim-reflexion — verbal-reflection memory for the generalist.
//!
//! Reflexion (Shinn et al., 2023; refined 2025) — when a run fails or the
//! self-critique finds material flaws, generate a brief verbal reflection
//! ("what went wrong, what to try differently") and persist it. On the
//! NEXT run with a similar task class, retrieve recent reflections and
//! inject them as a hint.
//!
//! Cheap (no fine-tuning), one of the highest-ROI non-RLHF techniques
//! for tool-using agents (+10–15% on ReAct-style tasks).
//!
//! Port of `agents/reflexion.py`. Storage layout matches the Python
//! module (`<store_dir>/<bucket>.jsonl`).

use async_trait::async_trait;
use chrono::Utc;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ReflexionError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("llm: {0}")]
    Llm(String),
}

/// Coarse keyword bucket. Matches `agents/reflexion.py` literally.
const BUCKETS: &[(&str, &[&str])] = &[
    (
        "code_edit",
        &[
            "edit", "refactor", "fix", "patch", "bug", "пофикси", "исправь", "рефактор",
        ],
    ),
    (
        "research",
        &[
            "research",
            "find papers",
            "literature",
            "pubmed",
            "pmid",
            "doi",
            "literature review",
            "обзор",
            "литератур",
        ],
    ),
    (
        "writing",
        &[
            "write",
            "draft",
            "peer review",
            "manuscript",
            "article",
            "редакт",
            "напиши",
            "статья",
            "рецензир",
        ],
    ),
    (
        "diagnosis",
        &[
            "diagnose", "diagnos", "treatment", "symptoms", "patient", "диагноз", "лечен",
            "пациент", "симптом",
        ],
    ),
    (
        "ops",
        &["deploy", "build", "push", "commit", "git", "test"],
    ),
    (
        "email",
        &["email", "send", "draft email", "напиши письмо"],
    ),
];

/// Classify a task into one of the buckets above. Falls back to `"general"`
/// when no keyword matches.
pub fn classify(task: &str) -> &'static str {
    let lc = task.to_lowercase();
    for (bucket, kws) in BUCKETS {
        if kws.iter().any(|k| lc.contains(k)) {
            return bucket;
        }
    }
    "general"
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Reflection {
    pub ts: i64,
    pub task_excerpt: String,
    pub summary: String,
}

/// Resolve the storage dir: matches the cross-platform Python rule
/// (Windows `%LOCALAPPDATA%\aim\reflexion`, macOS `~/Library/Application
/// Support/aim/reflexion`, Linux `${XDG_DATA_HOME:-~/.local/share}/aim/reflexion`).
pub fn default_store_dir() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    if cfg!(target_os = "windows") {
        let base = std::env::var("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home.join("AppData").join("Local"));
        base.join("aim").join("reflexion")
    } else if cfg!(target_os = "macos") {
        home.join("Library").join("Application Support").join("aim").join("reflexion")
    } else {
        let base = std::env::var("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home.join(".local").join("share"));
        base.join("aim").join("reflexion")
    }
}

static SAFE_NAME: OnceLock<Regex> = OnceLock::new();
fn safe_name_re() -> &'static Regex {
    SAFE_NAME.get_or_init(|| Regex::new(r"[^a-z0-9_]").unwrap())
}

fn safe_bucket(b: &str) -> String {
    let lc = b.to_lowercase();
    let s = safe_name_re().replace_all(&lc, "_").to_string();
    s.chars().take(40).collect()
}

/// Pluggable LLM caller for `on_failure`. Tests inject [`StubLlm`].
#[async_trait]
pub trait Llm: Send + Sync {
    async fn ask_fast(&self, prompt: &str) -> Result<String, ReflexionError>;
}

pub struct StubLlm {
    pub canned: parking_lot::Mutex<Vec<String>>,
}

impl StubLlm {
    pub fn new(canned: Vec<&str>) -> Self {
        Self {
            canned: parking_lot::Mutex::new(canned.into_iter().map(String::from).collect()),
        }
    }
}

#[async_trait]
impl Llm for StubLlm {
    async fn ask_fast(&self, _prompt: &str) -> Result<String, ReflexionError> {
        let mut q = self.canned.lock();
        if q.is_empty() {
            Err(ReflexionError::Llm("stub queue exhausted".into()))
        } else {
            Ok(q.remove(0))
        }
    }
}

pub struct Store {
    dir: PathBuf,
}

impl Store {
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        Self { dir: dir.into() }
    }

    pub fn from_env() -> Self {
        Self::new(default_store_dir())
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    fn bucket_path(&self, bucket: &str) -> PathBuf {
        self.dir.join(format!("{}.jsonl", safe_bucket(bucket)))
    }

    pub fn save_reflection(
        &self,
        task: &str,
        summary: &str,
        bucket: Option<&str>,
    ) -> Result<(), ReflexionError> {
        let bucket = bucket.unwrap_or(classify(task));
        std::fs::create_dir_all(&self.dir)?;
        let path = self.bucket_path(bucket);
        let task_excerpt: String = task.chars().take(200).collect();
        let summary_excerpt: String = summary.chars().take(1000).collect();
        let rec = Reflection {
            ts: Utc::now().timestamp(),
            task_excerpt,
            summary: summary_excerpt,
        };
        let line = serde_json::to_string(&rec)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    pub fn recent_reflections(
        &self,
        task: &str,
        n: usize,
        bucket: Option<&str>,
        max_age_days: i64,
    ) -> Vec<String> {
        self.recent_reflections_with_now(task, n, bucket, max_age_days, Utc::now().timestamp())
    }

    /// Test seam — explicit `now` to drive the cutoff deterministically.
    pub fn recent_reflections_with_now(
        &self,
        task: &str,
        n: usize,
        bucket: Option<&str>,
        max_age_days: i64,
        now_secs: i64,
    ) -> Vec<String> {
        let bucket = bucket.unwrap_or(classify(task));
        let path = self.bucket_path(bucket);
        if !path.exists() {
            return Vec::new();
        }
        let raw = match std::fs::read_to_string(&path) {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        let cutoff = now_secs - max_age_days * 86_400;
        let mut entries: Vec<Reflection> = Vec::new();
        for line in raw.lines() {
            if line.trim().is_empty() {
                continue;
            }
            if let Ok(rec) = serde_json::from_str::<Reflection>(line) {
                if rec.ts >= cutoff {
                    entries.push(rec);
                }
            }
        }
        let total = entries.len();
        entries
            .into_iter()
            .skip(total.saturating_sub(n))
            .map(|r| r.summary)
            .collect()
    }

    /// Build the prompt the LLM receives for [`on_failure`]. Exposed so
    /// tests can assert on its contents without invoking the LLM.
    pub fn build_failure_prompt(task: &str, error_excerpt: &str) -> String {
        let task_excerpt: String = task.chars().take(600).collect();
        let err_excerpt: String = error_excerpt.chars().take(1500).collect();
        format!(
            "You are writing a one-paragraph (≤80 words) Reflexion entry.\n\
            An AI agent just FAILED at the task below. Identify the proximate \
            cause and ONE concrete change of strategy to try next time. Be \
            concrete, not generic.\n\n\
            === TASK ===\n{task_excerpt}\n\n\
            === FAILURE EVIDENCE ===\n{err_excerpt}\n\
            === Your reflection: ===",
        )
    }

    /// Generate a Reflexion summary via the supplied LLM and persist it.
    /// Empty / whitespace-only LLM replies are silently skipped (matches
    /// Python — the agent shouldn't fail because reflection capture didn't
    /// produce useful text).
    pub async fn on_failure(
        &self,
        task: &str,
        error_excerpt: &str,
        llm: &dyn Llm,
    ) -> Result<(), ReflexionError> {
        let prompt = Self::build_failure_prompt(task, error_excerpt);
        let summary = llm.ask_fast(&prompt).await?;
        if summary.trim().is_empty() {
            return Ok(());
        }
        self.save_reflection(task, &summary, None)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn fresh() -> (TempDir, Store) {
        let dir = TempDir::new().unwrap();
        let store = Store::new(dir.path().to_path_buf());
        (dir, store)
    }

    #[test]
    fn classify_buckets() {
        assert_eq!(classify("Fix the bug in kernel.py"), "code_edit");
        assert_eq!(classify("Find papers about centriole aging"), "research");
        assert_eq!(classify("Write a peer review"), "writing");
        assert_eq!(classify("Diagnose patient with cough"), "diagnosis");
        assert_eq!(classify("git push origin main"), "ops");
        assert_eq!(classify("Send an email to Dzidziguri"), "email");
        assert_eq!(classify("Just say hello"), "general");
    }

    #[test]
    fn classify_handles_cyrillic() {
        // "напиши" matches the writing bucket FIRST (matches Python's
        // insertion-order dict iteration — writing is declared before
        // email, and "напиши письмо" contains "напиши").
        assert_eq!(classify("напиши письмо коллеге"), "writing");
        assert_eq!(classify("исправь баг в kernel"), "code_edit");
        assert_eq!(classify("обзор литературы по PMID"), "research");
    }

    #[test]
    fn save_then_recent_returns_in_chronological_order() {
        let (_d, s) = fresh();
        s.save_reflection("write peer review", "tip 1", None).unwrap();
        s.save_reflection("write peer review", "tip 2", None).unwrap();
        s.save_reflection("write peer review", "tip 3", None).unwrap();
        let recent = s.recent_reflections("write peer review", 2, None, 60);
        // Last 2 entries (most recent at end)
        assert_eq!(recent, vec!["tip 2".to_string(), "tip 3".to_string()]);
    }

    #[test]
    fn recent_filters_by_age() {
        let (_d, s) = fresh();
        // Hand-write old + new entries to simulate age
        let bucket_path = s.bucket_path("writing");
        std::fs::create_dir_all(s.dir()).unwrap();
        let now = 1_700_000_000_i64;
        let old = Reflection {
            ts: now - 90 * 86_400,
            task_excerpt: "write".into(),
            summary: "old tip".into(),
        };
        let fresh_rec = Reflection {
            ts: now - 5 * 86_400,
            task_excerpt: "write".into(),
            summary: "fresh tip".into(),
        };
        let mut body = String::new();
        body.push_str(&serde_json::to_string(&old).unwrap());
        body.push('\n');
        body.push_str(&serde_json::to_string(&fresh_rec).unwrap());
        body.push('\n');
        std::fs::write(&bucket_path, body).unwrap();

        let recent = s.recent_reflections_with_now("write peer review", 5, None, 60, now);
        assert_eq!(recent, vec!["fresh tip".to_string()]);
    }

    #[test]
    fn recent_returns_empty_when_no_file() {
        let (_d, s) = fresh();
        assert!(s.recent_reflections("anything", 3, None, 60).is_empty());
    }

    #[test]
    fn save_truncates_long_excerpts() {
        let (_d, s) = fresh();
        let task = "x".repeat(500);
        let summary = "y".repeat(2000);
        s.save_reflection(&task, &summary, Some("general")).unwrap();
        let raw = std::fs::read_to_string(s.bucket_path("general")).unwrap();
        let rec: Reflection = serde_json::from_str(raw.trim()).unwrap();
        assert_eq!(rec.task_excerpt.len(), 200);
        assert_eq!(rec.summary.len(), 1000);
    }

    #[test]
    fn explicit_bucket_overrides_classify() {
        let (_d, s) = fresh();
        s.save_reflection("Generic note", "manual override", Some("ops")).unwrap();
        // Should land in ops.jsonl, not general.jsonl
        assert!(s.bucket_path("ops").exists());
        assert!(!s.bucket_path("general").exists());
    }

    #[test]
    fn safe_bucket_strips_unsafe_chars() {
        assert_eq!(safe_bucket("Code-Edit"), "code_edit");
        assert_eq!(safe_bucket("WEIRD!@#"), "weird___");
        assert!(safe_bucket(&"x".repeat(60)).len() <= 40);
    }

    #[test]
    fn build_failure_prompt_truncates_inputs() {
        let task = "T".repeat(700);
        let err = "E".repeat(2000);
        let p = Store::build_failure_prompt(&task, &err);
        // Task max 600, err max 1500
        assert!(p.contains(&"T".repeat(600)));
        assert!(p.contains(&"E".repeat(1500)));
        assert!(!p.contains(&"T".repeat(601)));
        assert!(!p.contains(&"E".repeat(1501)));
    }

    #[tokio::test]
    async fn on_failure_persists_summary() {
        let (_d, s) = fresh();
        let llm = StubLlm::new(vec!["Tip: cache the regex outside the loop."]);
        s.on_failure("Fix the bug", "TypeError at line 42", &llm).await.unwrap();
        let recent = s.recent_reflections("Fix the bug", 5, None, 60);
        assert_eq!(recent.len(), 1);
        assert!(recent[0].contains("cache the regex"));
    }

    #[tokio::test]
    async fn on_failure_skips_empty_summary() {
        let (_d, s) = fresh();
        let llm = StubLlm::new(vec!["   \t  "]);
        s.on_failure("task", "err", &llm).await.unwrap();
        let bucket = s.bucket_path(classify("task"));
        assert!(!bucket.exists());
    }

    #[tokio::test]
    async fn on_failure_propagates_llm_err() {
        let (_d, s) = fresh();
        let llm = StubLlm::new(vec![]); // queue empty → Err
        let r = s.on_failure("task", "err", &llm).await;
        assert!(matches!(r, Err(ReflexionError::Llm(_))));
    }
}
