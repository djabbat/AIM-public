//! aim-recall-cli — semantic memory query surface.
//!
//! Port of `agents/recall_cli.py`. The Python module is a thin layer
//! over `agents.memory_index.retrieve` plus a JSONL audit log; here
//! we abstract the retriever as the [`Retriever`] trait and the audit
//! log as [`AuditSink`], keeping the formatting / dedup / batch JSON
//! logic identical.

use std::path::Path;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Hit {
    pub file: String,
    pub text: String,
    pub distance: f32,
}

pub trait Retriever: Send + Sync {
    fn retrieve(&self, query: &str, k: usize, max_chars_per_file: usize) -> Vec<Hit>;
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct UtcClock;
impl Clock for UtcClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct ManualClock {
    inner: Mutex<DateTime<Utc>>,
}

impl ManualClock {
    pub fn new(t: DateTime<Utc>) -> Self {
        Self { inner: Mutex::new(t) }
    }
    pub fn set(&self, t: DateTime<Utc>) {
        *self.inner.lock() = t;
    }
}

impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.inner.lock()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AuditEntry {
    pub ts: String,
    pub query: String,
    pub n_hits: usize,
}

pub trait AuditSink: Send + Sync {
    fn append(&self, entry: &AuditEntry);
    fn history(&self, limit: usize) -> Vec<AuditEntry>;
}

#[derive(Default)]
pub struct InMemAudit {
    entries: Mutex<Vec<AuditEntry>>,
}

impl InMemAudit {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn len(&self) -> usize {
        self.entries.lock().len()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

impl AuditSink for InMemAudit {
    fn append(&self, entry: &AuditEntry) {
        self.entries.lock().push(entry.clone());
    }
    fn history(&self, limit: usize) -> Vec<AuditEntry> {
        let g = self.entries.lock();
        let from = g.len().saturating_sub(limit);
        g[from..].to_vec()
    }
}

// ── recall ────────────────────────────────────────────────────────────────

pub struct RecallEngine<'a> {
    pub retriever: &'a dyn Retriever,
    pub audit: &'a dyn AuditSink,
    pub clock: &'a dyn Clock,
}

impl<'a> RecallEngine<'a> {
    pub fn recall(&self, query: &str, k: usize, max_chars_per_file: usize) -> Vec<Hit> {
        let q = query.trim();
        if q.is_empty() {
            return vec![];
        }
        let hits = self.retriever.retrieve(q, k, max_chars_per_file);
        let entry = AuditEntry {
            ts: self
                .clock
                .now()
                .with_timezone(&Utc)
                .format("%Y-%m-%dT%H:%M:%S")
                .to_string(),
            query: q.to_string(),
            n_hits: hits.len(),
        };
        self.audit.append(&entry);
        hits
    }

    pub fn recall_top(&self, query: &str, k: usize, line_max: usize) -> String {
        let q = query.trim();
        let hits = self.recall(q, k, 800);
        if hits.is_empty() {
            return format!("(no recall hits for {:?})", q);
        }
        let mut out = vec![format!("💭 Recall: {:?} ({} hits)", q, hits.len())];
        for h in &hits {
            let snippet = h.text.replace('\n', " ");
            let snippet = snippet.trim();
            let name = Path::new(&h.file)
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or(&h.file);
            // Same width math as Python: line_max - len(file) - 10
            let avail = line_max
                .saturating_sub(name.chars().count())
                .saturating_sub(10);
            let snippet: String = snippet.chars().take(avail).collect();
            out.push(format!(
                "  • {}  d={:.3}  {}",
                name, h.distance, snippet
            ));
        }
        out.join("\n")
    }

    pub fn recall_json(&self, queries: &[String], k: usize) -> String {
        #[derive(Serialize)]
        struct Block<'a> {
            query: &'a str,
            hits: Vec<Hit>,
        }
        let blocks: Vec<Block> = queries
            .iter()
            .map(|q| Block {
                query: q,
                hits: self.recall(q, k, 800),
            })
            .collect();
        serde_json::to_string_pretty(&blocks).unwrap_or_else(|_| "[]".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    struct StubRetriever {
        canned: Vec<Hit>,
    }

    impl Retriever for StubRetriever {
        fn retrieve(&self, _q: &str, k: usize, _max: usize) -> Vec<Hit> {
            self.canned.iter().take(k).cloned().collect()
        }
    }

    fn make_hit(file: &str, text: &str, d: f32) -> Hit {
        Hit { file: file.into(), text: text.into(), distance: d }
    }

    fn engine_with(canned: Vec<Hit>) -> (StubRetriever, InMemAudit, ManualClock) {
        let clock = ManualClock::new(Utc.with_ymd_and_hms(2026, 5, 5, 12, 30, 45).unwrap());
        (StubRetriever { canned }, InMemAudit::new(), clock)
    }

    // ── recall ────────────────────────────────────────────────────────────

    #[test]
    fn recall_returns_hits_and_writes_audit() {
        let (r, a, c) = engine_with(vec![
            make_hit("/x/a.md", "alpha line", 0.1),
            make_hit("/x/b.md", "beta line", 0.2),
        ]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let hits = e.recall("alpha", 5, 800);
        assert_eq!(hits.len(), 2);
        assert_eq!(a.len(), 1);
        let h = a.history(10);
        assert_eq!(h[0].query, "alpha");
        assert_eq!(h[0].n_hits, 2);
        assert_eq!(h[0].ts, "2026-05-05T12:30:45");
    }

    #[test]
    fn recall_empty_query_short_circuits() {
        let (r, a, c) = engine_with(vec![make_hit("/x.md", "q", 0.0)]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let hits = e.recall("   ", 5, 800);
        assert!(hits.is_empty());
        assert_eq!(a.len(), 0);
    }

    #[test]
    fn recall_respects_k_limit() {
        let canned: Vec<Hit> = (0..10)
            .map(|i| make_hit(&format!("f{}.md", i), &format!("t{}", i), i as f32 / 10.0))
            .collect();
        let (r, a, c) = engine_with(canned);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let hits = e.recall("q", 3, 800);
        assert_eq!(hits.len(), 3);
    }

    // ── recall_top ────────────────────────────────────────────────────────

    #[test]
    fn recall_top_no_hits_message() {
        let (r, a, c) = engine_with(vec![]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let s = e.recall_top("nothing", 5, 140);
        assert!(s.starts_with("(no recall hits for"));
        assert!(s.contains("nothing"));
    }

    #[test]
    fn recall_top_formats_basename_and_distance() {
        let (r, a, c) = engine_with(vec![make_hit(
            "/abs/path/notes.md",
            "the actual text content goes here",
            0.123,
        )]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let s = e.recall_top("q", 5, 140);
        assert!(s.contains("notes.md"));
        assert!(s.contains("d=0.123"));
        assert!(!s.contains("/abs/path"));
    }

    #[test]
    fn recall_top_truncates_long_snippet() {
        let long = "x".repeat(500);
        let (r, a, c) = engine_with(vec![make_hit("/n.md", &long, 0.01)]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let s = e.recall_top("q", 5, 140);
        for line in s.lines() {
            assert!(line.chars().count() <= 200, "line too long: {} chars", line.chars().count());
        }
    }

    // ── recall_json ───────────────────────────────────────────────────────

    #[test]
    fn recall_json_round_trip() {
        let (r, a, c) = engine_with(vec![make_hit("/n.md", "t", 0.5)]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        let s = e.recall_json(&["q1".into(), "q2".into()], 5);
        let parsed: serde_json::Value = serde_json::from_str(&s).unwrap();
        let arr = parsed.as_array().unwrap();
        assert_eq!(arr.len(), 2);
        assert_eq!(arr[0]["query"], "q1");
        assert_eq!(arr[0]["hits"][0]["file"], "/n.md");
    }

    // ── audit history ─────────────────────────────────────────────────────

    #[test]
    fn audit_history_limit() {
        let (r, a, c) = engine_with(vec![make_hit("/n.md", "t", 0.0)]);
        let e = RecallEngine { retriever: &r, audit: &a, clock: &c };
        for i in 0..20 {
            e.recall(&format!("q{}", i), 5, 800);
        }
        let recent = a.history(5);
        assert_eq!(recent.len(), 5);
        assert_eq!(recent[4].query, "q19");
        assert_eq!(recent[0].query, "q15");
    }
}
