//! aim-import-claude-memory — bulk import Claude Code memory into AIM.
//!
//! Port of `scripts/import_claude_memory.py`. The interesting parts:
//!
//!   * frontmatter parsing (---key:value---),
//!   * category classification (frontmatter `type` first, then filename
//!     prefix, falling back to `general`),
//!   * idempotent skipping via an import-log set,
//!   * dry-run vs commit dispatch.
//!
//! The actual LanceDB write + reindex subprocess live in the binary
//! and go through pluggable [`MemoryStore`] / [`ImportLog`] traits.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

// ── frontmatter ───────────────────────────────────────────────────────────

pub fn parse_frontmatter(text: &str) -> (BTreeMap<String, String>, String) {
    let mut fm = BTreeMap::new();
    if !text.starts_with("---") {
        return (fm, text.to_string());
    }
    let after_open = match text.find('\n') {
        Some(i) => &text[i + 1..],
        None => return (fm, text.to_string()),
    };
    let close_idx = match after_open.find("\n---") {
        Some(i) => i,
        None => return (fm, text.to_string()),
    };
    let body_start = close_idx + 4;
    let body_section = &after_open[..close_idx];
    for line in body_section.lines() {
        if let Some((k, v)) = line.split_once(':') {
            fm.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    let mut rest = after_open[body_start..].to_string();
    if rest.starts_with('\n') {
        rest.remove(0);
    }
    (fm, rest)
}

// ── classification ────────────────────────────────────────────────────────

pub fn classify_category(file_name: &str, fm: &BTreeMap<String, String>) -> String {
    let n = file_name.to_lowercase();
    let fm_type = fm
        .get("type")
        .map(|s| s.to_lowercase())
        .unwrap_or_default();
    if matches!(
        fm_type.as_str(),
        "user" | "feedback" | "project" | "reference"
    ) {
        return fm_type;
    }
    for (prefix, cat) in [
        ("feedback_", "feedback"),
        ("project_", "project"),
        ("user_", "user"),
        ("contact_", "reference"),
        ("reference_", "reference"),
        ("fact_", "user"),
        ("pubmed_", "reference"),
    ] {
        if n.starts_with(prefix) {
            return cat.to_string();
        }
    }
    "general".to_string()
}

// ── traits ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct StoredFact {
    pub text: String,
    pub category: String,
    pub source: String,
    pub fm_name: String,
    pub fm_type: String,
    pub fm_description: String,
    pub imported_at: String,
}

pub trait MemoryStore: Send + Sync {
    fn remember(&self, fact: &StoredFact);
}

#[derive(Default)]
pub struct InMemStore {
    pub facts: Mutex<Vec<StoredFact>>,
}

impl InMemStore {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn snapshot(&self) -> Vec<StoredFact> {
        self.facts.lock().clone()
    }
}

impl MemoryStore for InMemStore {
    fn remember(&self, fact: &StoredFact) {
        self.facts.lock().push(fact.clone());
    }
}

pub trait ImportLog: Send + Sync {
    fn imported(&self) -> Vec<String>;
    fn add(&self, key: &str);
    fn clear(&self);
}

#[derive(Default)]
pub struct InMemLog {
    inner: Mutex<Vec<String>>,
}

impl InMemLog {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn preload(items: &[&str]) -> Self {
        let s = Self::default();
        for k in items {
            s.add(k);
        }
        s
    }
}

impl ImportLog for InMemLog {
    fn imported(&self) -> Vec<String> {
        self.inner.lock().clone()
    }
    fn add(&self, key: &str) {
        let mut g = self.inner.lock();
        if !g.iter().any(|k| k == key) {
            g.push(key.to_string());
        }
    }
    fn clear(&self) {
        self.inner.lock().clear();
    }
}

// ── runner ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InputFile {
    pub key: String,    // canonical resolved path
    pub name: String,   // basename, e.g. "feedback_x.md"
    pub content: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ImportReport {
    pub scanned: usize,
    pub skipped: usize,
    pub imported: usize,
    pub new_facts: usize,
    pub by_category: BTreeMap<String, usize>,
}

pub fn run_import(
    files: &[InputFile],
    store: &dyn MemoryStore,
    log: &dyn ImportLog,
    now: DateTime<Utc>,
    reset: bool,
    dry_run: bool,
) -> ImportReport {
    if reset {
        log.clear();
    }
    let already: Vec<String> = log.imported();
    let mut report = ImportReport::default();
    for f in files {
        // Skip the auto-generated index file from Claude itself.
        if f.name == "MEMORY.md" {
            continue;
        }
        report.scanned += 1;
        if already.contains(&f.key) {
            report.skipped += 1;
            continue;
        }
        let (fm, body) = parse_frontmatter(&f.content);
        let category = classify_category(&f.name, &fm);
        let fact_text = if !body.trim().is_empty() {
            body.trim().to_string()
        } else {
            f.content.trim().to_string()
        };
        if fact_text.is_empty() {
            continue;
        }
        let fm_description: String = fm
            .get("description")
            .cloned()
            .unwrap_or_default()
            .chars()
            .take(200)
            .collect();
        let fm_name = fm
            .get("name")
            .cloned()
            .unwrap_or_else(|| {
                f.name
                    .strip_suffix(".md")
                    .unwrap_or(f.name.as_str())
                    .to_string()
            });
        let fact = StoredFact {
            text: fact_text,
            category: category.clone(),
            source: f.name.clone(),
            fm_name,
            fm_type: fm.get("type").cloned().unwrap_or_default(),
            fm_description,
            imported_at: now.format("%Y-%m-%dT%H:%M:%S").to_string(),
        };
        if !dry_run {
            store.remember(&fact);
        }
        log.add(&f.key);
        *report.by_category.entry(category).or_insert(0) += 1;
        report.imported += 1;
        report.new_facts += 1;
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap()
    }

    fn file(key: &str, name: &str, content: &str) -> InputFile {
        InputFile {
            key: key.into(),
            name: name.into(),
            content: content.into(),
        }
    }

    // ── frontmatter ───────────────────────────────────────────────────────

    #[test]
    fn frontmatter_parses_and_returns_body() {
        let (fm, body) = parse_frontmatter("---\ntype: project\nname: x\n---\nbody here");
        assert_eq!(fm.get("type").unwrap(), "project");
        assert_eq!(fm.get("name").unwrap(), "x");
        assert_eq!(body, "body here");
    }

    #[test]
    fn frontmatter_no_delimiter_returns_full_text() {
        let (fm, body) = parse_frontmatter("plain body");
        assert!(fm.is_empty());
        assert_eq!(body, "plain body");
    }

    // ── classification ────────────────────────────────────────────────────

    #[test]
    fn classify_uses_frontmatter_type_first() {
        let mut fm = BTreeMap::new();
        fm.insert("type".into(), "Project".into());
        assert_eq!(classify_category("random.md", &fm), "project");
    }

    #[test]
    fn classify_falls_back_to_filename_prefix() {
        let fm = BTreeMap::new();
        assert_eq!(classify_category("feedback_x.md", &fm), "feedback");
        assert_eq!(classify_category("contact_x.md", &fm), "reference");
        assert_eq!(classify_category("fact_x.md", &fm), "user");
        assert_eq!(classify_category("pubmed_x.md", &fm), "reference");
    }

    #[test]
    fn classify_unknown_is_general() {
        let fm = BTreeMap::new();
        assert_eq!(classify_category("notes.md", &fm), "general");
    }

    #[test]
    fn classify_invalid_fm_type_falls_to_prefix() {
        let mut fm = BTreeMap::new();
        fm.insert("type".into(), "weird".into());
        assert_eq!(classify_category("project_a.md", &fm), "project");
    }

    // ── runner ────────────────────────────────────────────────────────────

    #[test]
    fn import_skips_already_logged() {
        let files = vec![file("/p/a.md", "project_a.md", "body a")];
        let store = InMemStore::new();
        let log = InMemLog::preload(&["/p/a.md"]);
        let r = run_import(&files, &store, &log, now(), false, false);
        assert_eq!(r.skipped, 1);
        assert_eq!(r.imported, 0);
        assert!(store.snapshot().is_empty());
    }

    #[test]
    fn import_skips_memory_md() {
        let files = vec![file("/p/MEMORY.md", "MEMORY.md", "body")];
        let store = InMemStore::new();
        let log = InMemLog::new();
        let r = run_import(&files, &store, &log, now(), false, false);
        assert_eq!(r.scanned, 0);
        assert_eq!(r.imported, 0);
    }

    #[test]
    fn import_writes_with_metadata() {
        let content = "---\ntype: feedback\nname: my-feedback\ndescription: hi\n---\nbody";
        let files = vec![file("/p/feedback_x.md", "feedback_x.md", content)];
        let store = InMemStore::new();
        let log = InMemLog::new();
        let r = run_import(&files, &store, &log, now(), false, false);
        assert_eq!(r.imported, 1);
        assert_eq!(r.new_facts, 1);
        assert_eq!(r.by_category["feedback"], 1);
        let snap = store.snapshot();
        assert_eq!(snap.len(), 1);
        assert_eq!(snap[0].text, "body");
        assert_eq!(snap[0].fm_name, "my-feedback");
        assert_eq!(snap[0].imported_at, "2026-05-05T12:00:00");
    }

    #[test]
    fn import_dry_run_does_not_write() {
        let files = vec![file("/p/project_a.md", "project_a.md", "body")];
        let store = InMemStore::new();
        let log = InMemLog::new();
        let r = run_import(&files, &store, &log, now(), false, true);
        assert_eq!(r.imported, 1);
        assert!(store.snapshot().is_empty());
        // log still records the import key (matches Python's behaviour
        // of adding to self.imported regardless of dry_run)
        assert_eq!(log.imported().len(), 1);
    }

    #[test]
    fn import_reset_clears_log_first() {
        let files = vec![file("/p/project_a.md", "project_a.md", "body")];
        let store = InMemStore::new();
        let log = InMemLog::preload(&["/p/project_a.md"]);
        let r = run_import(&files, &store, &log, now(), true, false);
        assert_eq!(r.imported, 1);
        assert_eq!(r.skipped, 0);
    }

    #[test]
    fn import_skips_empty_body() {
        let files = vec![file("/p/empty.md", "empty.md", "")];
        let store = InMemStore::new();
        let log = InMemLog::new();
        let r = run_import(&files, &store, &log, now(), false, false);
        assert_eq!(r.imported, 0);
    }

    #[test]
    fn import_falls_back_to_full_content_when_no_frontmatter_body() {
        // Frontmatter parsing returns empty body if there's nothing after ---
        let files = vec![file(
            "/p/x.md",
            "user_x.md",
            "---\ntype: user\n---\n",
        )];
        let store = InMemStore::new();
        let log = InMemLog::new();
        let r = run_import(&files, &store, &log, now(), false, false);
        assert_eq!(r.imported, 1);
        let snap = store.snapshot();
        // body was empty after frontmatter → falls back to full content
        assert!(snap[0].text.contains("type: user"));
    }

    #[test]
    fn import_truncates_description_at_200() {
        let long_desc = "x".repeat(400);
        let content = format!("---\ntype: project\ndescription: {}\n---\nbody", long_desc);
        let files = vec![file("/p/p.md", "project_a.md", &content)];
        let store = InMemStore::new();
        let log = InMemLog::new();
        run_import(&files, &store, &log, now(), false, false);
        let snap = store.snapshot();
        assert_eq!(snap[0].fm_description.chars().count(), 200);
    }
}
