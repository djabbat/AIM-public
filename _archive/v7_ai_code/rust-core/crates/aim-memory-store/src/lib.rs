//! aim-memory-store — long-term cross-session memory.
//!
//! Port of `agents/memory_store.py`. Writes one Markdown file per fact
//! under `<root>/user_memories/<category>/<timestamp>_<slug>.md`, in the
//! same format the auto-memory system uses.
//!
//! Reindexing is decoupled via the [`Reindexer`] trait so tests run
//! hermetically — no `subprocess.run("aim-memory-index", …)` in core.

use std::collections::BTreeMap;
use std::path::PathBuf;

use chrono::{DateTime, Local};
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use walkdir::WalkDir;

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("walkdir error: {0}")]
    Walk(#[from] walkdir::Error),
}

pub type Result<T> = std::result::Result<T, StoreError>;

// ── slugify ─────────────────────────────────────────────────────────────────

/// Mirrors Python `_slugify`: strip non-word/dash/underscore/dot/space
/// characters, lowercase, collapse whitespace to `_`, cap at `max_len`,
/// fall back to `"memory"` if empty. Unicode word characters are kept.
pub fn slugify(text: &str, max_len: usize) -> String {
    let cleaned: String = text
        .chars()
        .filter(|c| {
            c.is_alphanumeric()
                || *c == '-'
                || *c == '_'
                || *c == '.'
                || c.is_whitespace()
        })
        .collect();
    let lower = cleaned.trim().to_lowercase();
    let ws_re = Regex::new(r"\s+").expect("whitespace regex compiles");
    let collapsed = ws_re.replace_all(&lower, "_").into_owned();
    let truncated: String = collapsed.chars().take(max_len).collect();
    if truncated.is_empty() {
        "memory".to_string()
    } else {
        truncated
    }
}

// ── reindex hook ────────────────────────────────────────────────────────────

/// Pluggable reindex trigger. Production binds it to `aim-memory-index`
/// CLI; tests bind to a `NoopReindexer`.
pub trait Reindexer: Send + Sync {
    fn reindex_incremental(&self);
}

pub struct NoopReindexer;

impl Reindexer for NoopReindexer {
    fn reindex_incremental(&self) {}
}

/// Counting stub — useful for tests that want to assert reindex was called.
pub struct CountingReindexer {
    count: parking_lot::Mutex<usize>,
}

impl CountingReindexer {
    pub fn new() -> Self {
        Self {
            count: parking_lot::Mutex::new(0),
        }
    }
    pub fn count(&self) -> usize {
        *self.count.lock()
    }
}

impl Default for CountingReindexer {
    fn default() -> Self {
        Self::new()
    }
}

impl Reindexer for CountingReindexer {
    fn reindex_incremental(&self) {
        *self.count.lock() += 1;
    }
}

// Re-export parking_lot for the CountingReindexer Mutex
pub use parking_lot;

// ── store ───────────────────────────────────────────────────────────────────

/// Pluggable clock — keeps tests deterministic.
pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Local>;
}

pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Local> {
        Local::now()
    }
}

pub struct FixedClock(pub DateTime<Local>);

impl Clock for FixedClock {
    fn now(&self) -> DateTime<Local> {
        self.0
    }
}

/// Memory store rooted at `<root>/user_memories/`.
pub struct MemoryStore<'a> {
    pub root: PathBuf,
    pub reindexer: &'a dyn Reindexer,
    pub clock: &'a dyn Clock,
}

impl<'a> MemoryStore<'a> {
    pub fn new(root: PathBuf, reindexer: &'a dyn Reindexer, clock: &'a dyn Clock) -> Self {
        Self {
            root,
            reindexer,
            clock,
        }
    }

    fn user_memories_dir(&self) -> PathBuf {
        self.root.join("user_memories")
    }

    /// Persist a single fact. Returns the file path written.
    /// `quiet=true` suppresses the reindex hook (used by bulk importers).
    pub fn remember(
        &self,
        fact: &str,
        category: &str,
        metadata: Option<&BTreeMap<String, MetaValue>>,
        quiet: bool,
    ) -> Result<PathBuf> {
        let cat_dir = self.user_memories_dir().join(category);
        std::fs::create_dir_all(&cat_dir)?;

        let ts = self.clock.now();
        let slug = slugify(fact, 60);
        let name = format!("{}_{}.md", ts.format("%Y%m%d_%H%M%S_%6f"), slug);
        let path = cat_dir.join(name);

        let mut fm_extra = String::new();
        if let Some(m) = metadata {
            for (k, v) in m {
                fm_extra.push_str(&format!("{}: {}\n", k, v.render()));
            }
        }

        let desc: String = fact.chars().take(200).collect();
        let body = format!(
            "---\nname: {slug}\ndescription: {desc}\ntype: user\ncategory: {category}\ncreated: {created}\n{fm_extra}---\n\n{fact}\n",
            slug = slug,
            desc = desc,
            category = category,
            created = ts.format("%Y-%m-%dT%H:%M:%S%:z"),
            fm_extra = fm_extra,
            fact = fact,
        );
        std::fs::write(&path, body)?;

        if !quiet {
            self.reindexer.reindex_incremental();
        }
        Ok(path)
    }

    /// Delete every user-memory file whose path contains `pattern`.
    /// Returns the count deleted; triggers reindex if any deletion occurred.
    pub fn forget(&self, pattern: &str) -> Result<usize> {
        let dir = self.user_memories_dir();
        if !dir.exists() {
            return Ok(0);
        }
        let mut n = 0usize;
        for entry in WalkDir::new(&dir).into_iter().filter_map(|e| e.ok()) {
            if !entry.file_type().is_file() {
                continue;
            }
            let name = entry.file_name().to_string_lossy().to_string();
            if name.contains(pattern) {
                std::fs::remove_file(entry.path())?;
                n += 1;
            }
        }
        if n > 0 {
            self.reindexer.reindex_incremental();
        }
        Ok(n)
    }

    /// List all stored facts (not semantic — just file enumeration).
    /// Useful for debugging / migrations / tests.
    pub fn list(&self) -> Result<Vec<StoredFact>> {
        let dir = self.user_memories_dir();
        if !dir.exists() {
            return Ok(Vec::new());
        }
        let mut out = Vec::new();
        for entry in WalkDir::new(&dir).into_iter().filter_map(|e| e.ok()) {
            if !entry.file_type().is_file() {
                continue;
            }
            if entry.path().extension().and_then(|s| s.to_str()) != Some("md") {
                continue;
            }
            let category = entry
                .path()
                .parent()
                .and_then(|p| p.file_name())
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| "general".into());
            out.push(StoredFact {
                path: entry.path().to_path_buf(),
                category,
            });
        }
        out.sort_by(|a, b| a.path.cmp(&b.path));
        Ok(out)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct StoredFact {
    pub path: PathBuf,
    pub category: String,
}

/// Lightweight value type for frontmatter metadata.
#[derive(Clone, Debug)]
pub enum MetaValue {
    Str(String),
    List(Vec<String>),
    Int(i64),
}

impl MetaValue {
    fn render(&self) -> String {
        match self {
            MetaValue::Str(s) => s.clone(),
            MetaValue::List(xs) => xs.join(","),
            MetaValue::Int(n) => n.to_string(),
        }
    }
}

impl From<&str> for MetaValue {
    fn from(s: &str) -> Self {
        MetaValue::Str(s.to_string())
    }
}

impl From<String> for MetaValue {
    fn from(s: String) -> Self {
        MetaValue::Str(s)
    }
}

impl From<Vec<String>> for MetaValue {
    fn from(v: Vec<String>) -> Self {
        MetaValue::List(v)
    }
}

impl From<i64> for MetaValue {
    fn from(n: i64) -> Self {
        MetaValue::Int(n)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn fixed_clock() -> FixedClock {
        let dt = Local
            .with_ymd_and_hms(2026, 5, 4, 21, 30, 45)
            .single()
            .unwrap();
        FixedClock(dt)
    }

    // ── slugify ─────────────────────────────────────────────────────────────

    #[test]
    fn slugify_lowercases() {
        assert_eq!(slugify("Hello World", 60), "hello_world");
    }

    #[test]
    fn slugify_strips_punctuation() {
        assert_eq!(slugify("Hello, World!", 60), "hello_world");
    }

    #[test]
    fn slugify_keeps_hyphens_and_underscores() {
        assert_eq!(slugify("foo-bar_baz", 60), "foo-bar_baz");
    }

    #[test]
    fn slugify_collapses_whitespace() {
        assert_eq!(slugify("a    b", 60), "a_b");
    }

    #[test]
    fn slugify_preserves_unicode() {
        let s = slugify("Иванов работал", 60);
        assert!(s.starts_with("иванов"));
        assert!(s.contains("работал"));
    }

    #[test]
    fn slugify_caps_at_max_len() {
        let long = "a".repeat(200);
        assert_eq!(slugify(&long, 10).chars().count(), 10);
    }

    #[test]
    fn slugify_empty_falls_back_to_memory() {
        assert_eq!(slugify("   !@#$%   ", 60), "memory");
    }

    // ── remember ────────────────────────────────────────────────────────────

    #[test]
    fn remember_writes_file_with_frontmatter() {
        let tmp = TempDir::new().unwrap();
        let reidx = CountingReindexer::new();
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        let path = store
            .remember("любимый цвет синий", "general", None, false)
            .unwrap();
        let body = std::fs::read_to_string(&path).unwrap();

        assert!(body.starts_with("---\n"));
        assert!(body.contains("type: user\n"));
        assert!(body.contains("category: general\n"));
        assert!(body.contains("description: любимый цвет синий"));
        assert!(body.ends_with("любимый цвет синий\n"));
    }

    #[test]
    fn remember_creates_category_subdir() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        let path = store
            .remember("TSU PhD контакт", "contacts", None, false)
            .unwrap();
        assert!(path
            .parent()
            .unwrap()
            .ends_with("user_memories/contacts"));
    }

    #[test]
    fn remember_filename_includes_timestamp_and_slug() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        let path = store.remember("hello world", "general", None, false).unwrap();
        let name = path.file_name().unwrap().to_string_lossy();
        assert!(name.starts_with("20260504_213045_"));
        assert!(name.contains("hello_world"));
        assert!(name.ends_with(".md"));
    }

    #[test]
    fn remember_triggers_reindex_unless_quiet() {
        let tmp = TempDir::new().unwrap();
        let reidx = CountingReindexer::new();
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        store.remember("a", "general", None, false).unwrap();
        store.remember("b", "general", None, true).unwrap();
        assert_eq!(reidx.count(), 1);
    }

    #[test]
    fn remember_with_metadata_renders_extra_frontmatter() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        let mut meta = BTreeMap::new();
        meta.insert("source".into(), MetaValue::from("import"));
        meta.insert(
            "tags".into(),
            MetaValue::from(vec!["a".to_string(), "b".to_string()]),
        );
        meta.insert("priority".into(), MetaValue::from(7i64));

        let path = store
            .remember("fact", "general", Some(&meta), false)
            .unwrap();
        let body = std::fs::read_to_string(&path).unwrap();
        assert!(body.contains("source: import\n"));
        assert!(body.contains("tags: a,b\n"));
        assert!(body.contains("priority: 7\n"));
    }

    #[test]
    fn remember_truncates_description_at_200_chars() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        let long = "x".repeat(500);
        let path = store.remember(&long, "general", None, false).unwrap();
        let body = std::fs::read_to_string(&path).unwrap();
        let desc_line = body
            .lines()
            .find(|l| l.starts_with("description: "))
            .unwrap();
        let desc = desc_line.trim_start_matches("description: ");
        assert_eq!(desc.chars().count(), 200);
    }

    // ── forget ──────────────────────────────────────────────────────────────

    #[test]
    fn forget_removes_matching_files() {
        let tmp = TempDir::new().unwrap();
        let reidx = CountingReindexer::new();
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        store.remember("колибри", "fauna", None, true).unwrap();
        store.remember("кит", "fauna", None, true).unwrap();
        store.remember("сосна", "flora", None, true).unwrap();

        let removed = store.forget("колибри").unwrap();
        assert_eq!(removed, 1);
        assert_eq!(reidx.count(), 1);
    }

    #[test]
    fn forget_nothing_matches_returns_zero() {
        let tmp = TempDir::new().unwrap();
        let reidx = CountingReindexer::new();
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        store.remember("abc", "general", None, true).unwrap();
        let removed = store.forget("zzz").unwrap();
        assert_eq!(removed, 0);
        assert_eq!(reidx.count(), 0);
    }

    #[test]
    fn forget_on_missing_dir_is_noop() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        assert_eq!(store.forget("anything").unwrap(), 0);
    }

    #[test]
    fn forget_walks_subdirs_recursively() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        store.remember("alpha", "deep_a", None, true).unwrap();
        store.remember("alpha", "deep_b", None, true).unwrap();
        let removed = store.forget("alpha").unwrap();
        assert_eq!(removed, 2);
    }

    // ── list ────────────────────────────────────────────────────────────────

    #[test]
    fn list_enumerates_facts_with_categories() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        store.remember("a", "fauna", None, true).unwrap();
        store.remember("b", "flora", None, true).unwrap();
        let facts = store.list().unwrap();
        assert_eq!(facts.len(), 2);
        assert!(facts.iter().any(|f| f.category == "fauna"));
        assert!(facts.iter().any(|f| f.category == "flora"));
    }

    #[test]
    fn list_on_missing_dir_returns_empty() {
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);
        assert!(store.list().unwrap().is_empty());
    }

    // ── filename uniqueness via microsecond timestamp ───────────────────────

    #[test]
    fn filenames_collide_under_identical_clock_unless_unique_microsecond() {
        // Documenting current behavior: with a fixed clock, two writes produce
        // identical names — the second overwrites. Production uses Local::now()
        // which advances each call. This test guards the contract.
        let tmp = TempDir::new().unwrap();
        let reidx = NoopReindexer;
        let clock = fixed_clock();
        let store = MemoryStore::new(tmp.path().to_path_buf(), &reidx, &clock);

        let p1 = store.remember("same", "x", None, true).unwrap();
        let p2 = store.remember("same", "x", None, true).unwrap();
        assert_eq!(p1, p2);
        assert_eq!(store.list().unwrap().len(), 1);
    }
}
