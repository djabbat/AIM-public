//! aim-literature-watch — PubMed RSS dedup + new-paper digest (L2).
//!
//! Port of `agents/literature_watch.py`. Runs daily/weekly. For each
//! configured query (in `USER/preferences/literature.yaml`), pulls the
//! PubMed esearch + esummary endpoint, deduplicates against:
//! - already-seen PMIDs (`~/.cache/aim/literature_seen.json`)
//! - the user's own publications.md (so we don't surface own work)
//!
//! Then produces a short digest of NEW papers. Watch list is small (20–50
//! items) so we don't hammer NCBI; default cooldown 6h between
//! identical-query refreshes.
//!
//! ## Schema (`USER/preferences/literature.yaml`)
//!
//! ```yaml
//! queries:
//!   - name: centriole-aging
//!     term: 'centriole AND aging'
//!     max_results: 10
//!   - name: longevity-biomarkers
//!     term: 'longevity biomarker[Title]'
//!     max_results: 8
//! cooldown_hours: 6
//! ```
//!
//! ## Public API
//! - [`Watch`] — top-level handle (env-overridable paths, injectable fetcher)
//! - [`Query`] / [`Paper`] — data
//! - [`Watch::queries`] — read prefs YAML
//! - [`Watch::new_for`] — dedup'd new papers for one query
//! - [`Watch::summary`] — digest across all queries

use async_trait::async_trait;
use chrono::Utc;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::path::PathBuf;
use thiserror::Error;
use std::sync::OnceLock;

#[derive(Debug, Error)]
pub enum LitError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("http: {0}")]
    Http(#[from] reqwest::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Query {
    pub name: String,
    pub term: String,
    #[serde(default = "ten")]
    pub max_results: u32,
}

fn ten() -> u32 {
    10
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Paper {
    pub pmid: String,
    pub title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub year: Option<i32>,
    #[serde(default)]
    pub journal: String,
    #[serde(default)]
    pub first_author: String,
}

impl Paper {
    pub fn to_line(&self) -> String {
        let title: String = self.title.chars().take(120).collect();
        let mut bits: Vec<String> = vec![self.pmid.clone()];
        if let Some(y) = self.year {
            bits.push(y.to_string());
        }
        if !self.first_author.is_empty() {
            bits.push(format!("{} et al.", self.first_author));
        }
        if !self.journal.is_empty() {
            bits.push(self.journal.clone());
        }
        format!("  • {} — {}", title, bits.join(" / "))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Bucket {
    #[serde(default)]
    pmids: Vec<String>,
    #[serde(default)]
    last_fetched: i64,
}

impl Default for Bucket {
    fn default() -> Self {
        Self {
            pmids: Vec::new(),
            last_fetched: 0,
        }
    }
}

#[async_trait]
pub trait Fetcher: Send + Sync {
    async fn fetch(&self, query: &Query) -> Result<Vec<Paper>, LitError>;
}

pub struct PubMedFetcher {
    http: reqwest::Client,
    base_url: String,
}

impl PubMedFetcher {
    pub fn new() -> Self {
        Self {
            http: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(20))
                .build()
                .unwrap_or_else(|_| reqwest::Client::new()),
            base_url: "https://eutils.ncbi.nlm.nih.gov/entrez/eutils".into(),
        }
    }

    pub fn with_base_url(mut self, url: impl Into<String>) -> Self {
        self.base_url = url.into();
        self
    }
}

impl Default for PubMedFetcher {
    fn default() -> Self {
        Self::new()
    }
}

static YEAR_RE: OnceLock<Regex> = OnceLock::new();
fn year_re() -> &'static Regex {
    YEAR_RE.get_or_init(|| Regex::new(r"^(\d{4})").expect("year regex"))
}

static PMID_RE: OnceLock<Regex> = OnceLock::new();
fn pmid_re() -> &'static Regex {
    PMID_RE.get_or_init(|| Regex::new(r"(?i)\bPMID[:\s]*([0-9]{4,9})").expect("pmid regex"))
}

#[async_trait]
impl Fetcher for PubMedFetcher {
    async fn fetch(&self, query: &Query) -> Result<Vec<Paper>, LitError> {
        let esearch = format!("{}/esearch.fcgi", self.base_url);
        let r = self
            .http
            .get(&esearch)
            .query(&[
                ("db", "pubmed"),
                ("term", query.term.as_str()),
                ("retmode", "json"),
                ("retmax", &query.max_results.to_string()),
            ])
            .send()
            .await?
            .error_for_status()?;
        let raw: serde_json::Value = r.json().await?;
        let ids: Vec<String> = raw
            .get("esearchresult")
            .and_then(|v| v.get("idlist"))
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|x| x.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        if ids.is_empty() {
            return Ok(Vec::new());
        }

        let esummary = format!("{}/esummary.fcgi", self.base_url);
        let r = self
            .http
            .get(&esummary)
            .query(&[
                ("db", "pubmed"),
                ("id", ids.join(",").as_str()),
                ("retmode", "json"),
            ])
            .send()
            .await?
            .error_for_status()?;
        let summ: serde_json::Value = r.json().await?;
        let result = summ.get("result").cloned().unwrap_or(serde_json::Value::Null);
        Ok(parse_summary(&ids, &result))
    }
}

fn parse_summary(ids: &[String], result: &serde_json::Value) -> Vec<Paper> {
    let mut out = Vec::new();
    for pmid in ids {
        let rec = match result.get(pmid) {
            Some(v) if v.is_object() => v,
            _ => continue,
        };
        let title = rec
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let journal = rec
            .get("fulljournalname")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let date_str = rec
            .get("pubdate")
            .and_then(|v| v.as_str())
            .or_else(|| rec.get("epubdate").and_then(|v| v.as_str()))
            .unwrap_or("");
        let year = year_re()
            .captures(date_str)
            .and_then(|c| c.get(1))
            .and_then(|m| m.as_str().parse::<i32>().ok());
        let first_author = rec
            .get("authors")
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|x| x.get("name"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        out.push(Paper {
            pmid: pmid.clone(),
            title,
            year,
            journal,
            first_author,
        });
    }
    out
}

// ── Watch ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct WatchPaths {
    pub prefs: PathBuf,
    pub seen: PathBuf,
    /// Files to scan for own-PMID exclusion (publications lists).
    pub own_publications: Vec<PathBuf>,
}

impl WatchPaths {
    pub fn from_env() -> Self {
        let prefs = std::env::var("AIM_LITERATURE_PREFS")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(|s| expand_tilde(&s))
            .unwrap_or_else(|| PathBuf::from("USER/preferences/literature.yaml"));
        let aim_home = std::env::var("AIM_HOME")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(|s| expand_tilde(&s))
            .unwrap_or_else(|| {
                let home = std::env::var("HOME")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| PathBuf::from("."));
                home.join(".cache").join("aim")
            });
        let seen = aim_home.join("literature_seen.json");
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        let own_publications = vec![
            home.join(".claude/projects/-home-oem/memory/publications.md"),
            home.join("Desktop/PhD/publications.md"),
        ];
        Self {
            prefs,
            seen,
            own_publications,
        }
    }
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

pub struct Watch {
    paths: WatchPaths,
    fetcher: Box<dyn Fetcher>,
    /// Override for `chrono::Utc::now().timestamp()` so cooldown can be
    /// exercised deterministically in tests.
    now_override: Option<i64>,
}

impl Watch {
    pub fn new(paths: WatchPaths, fetcher: Box<dyn Fetcher>) -> Self {
        Self {
            paths,
            fetcher,
            now_override: None,
        }
    }

    pub fn with_now(mut self, ts: i64) -> Self {
        self.now_override = Some(ts);
        self
    }

    fn now(&self) -> i64 {
        self.now_override.unwrap_or_else(|| Utc::now().timestamp())
    }

    pub fn queries(&self) -> Result<Vec<Query>, LitError> {
        if !self.paths.prefs.exists() {
            return Ok(Vec::new());
        }
        let raw = std::fs::read_to_string(&self.paths.prefs)?;
        let parsed: serde_yaml::Value = match serde_yaml::from_str(&raw) {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!("literature prefs parse failed: {e}");
                return Ok(Vec::new());
            }
        };
        let map = match parsed.as_mapping() {
            Some(m) => m,
            None => return Ok(Vec::new()),
        };
        let queries = map
            .get("queries")
            .and_then(|v| v.as_sequence())
            .cloned()
            .unwrap_or_default();
        let mut out = Vec::new();
        for q in queries {
            let m = match q.as_mapping() {
                Some(m) => m,
                None => continue,
            };
            let term = m
                .get("term")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            if term.is_empty() {
                continue;
            }
            let name = m
                .get("name")
                .and_then(|v| v.as_str())
                .map(String::from)
                .unwrap_or_else(|| term.chars().take(30).collect());
            let max_results = m
                .get("max_results")
                .and_then(|v| v.as_u64())
                .map(|n| n as u32)
                .unwrap_or(10);
            out.push(Query {
                name,
                term,
                max_results,
            });
        }
        Ok(out)
    }

    pub fn cooldown_hours(&self) -> f64 {
        if !self.paths.prefs.exists() {
            return 6.0;
        }
        let raw = match std::fs::read_to_string(&self.paths.prefs) {
            Ok(r) => r,
            Err(_) => return 6.0,
        };
        let parsed: serde_yaml::Value = match serde_yaml::from_str(&raw) {
            Ok(v) => v,
            Err(_) => return 6.0,
        };
        parsed
            .as_mapping()
            .and_then(|m| m.get("cooldown_hours"))
            .and_then(|v| v.as_f64().or_else(|| v.as_i64().map(|n| n as f64)))
            .unwrap_or(6.0)
    }

    fn load_seen(&self) -> BTreeMap<String, Bucket> {
        if !self.paths.seen.exists() {
            return BTreeMap::new();
        }
        let raw = match std::fs::read_to_string(&self.paths.seen) {
            Ok(s) => s,
            Err(_) => return BTreeMap::new(),
        };
        serde_json::from_str(&raw).unwrap_or_default()
    }

    fn save_seen(&self, state: &BTreeMap<String, Bucket>) -> Result<(), LitError> {
        if let Some(parent) = self.paths.seen.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let raw = serde_json::to_string_pretty(state)?;
        std::fs::write(&self.paths.seen, raw)?;
        Ok(())
    }

    fn own_pmids(&self) -> HashSet<String> {
        let mut out = HashSet::new();
        for p in &self.paths.own_publications {
            if !p.exists() {
                continue;
            }
            let raw = match std::fs::read_to_string(p) {
                Ok(s) => s,
                Err(_) => continue,
            };
            for cap in pmid_re().captures_iter(&raw) {
                if let Some(m) = cap.get(1) {
                    out.insert(m.as_str().to_string());
                }
            }
        }
        out
    }

    pub async fn new_for(&self, query: &Query) -> Result<Vec<Paper>, LitError> {
        let mut seen = self.load_seen();
        let bucket = seen.entry(query.name.clone()).or_default();
        let now = self.now();
        let cooldown_secs = (self.cooldown_hours() * 3600.0) as i64;
        if now - bucket.last_fetched < cooldown_secs {
            return Ok(Vec::new());
        }

        let papers = self.fetcher.fetch(query).await?;
        let own = self.own_pmids();
        let seen_set: HashSet<String> = bucket.pmids.iter().cloned().collect();
        let new_papers: Vec<Paper> = papers
            .iter()
            .filter(|p| !seen_set.contains(&p.pmid) && !own.contains(&p.pmid))
            .cloned()
            .collect();

        let mut updated: HashSet<String> = seen_set;
        for p in &papers {
            updated.insert(p.pmid.clone());
        }
        let mut sorted: Vec<String> = updated.into_iter().collect();
        sorted.sort();
        // Cap to most recent 500 (PMIDs are numeric — last 500 by lexicographic
        // order of zero-padded numerics is stable enough for an audit trail).
        if sorted.len() > 500 {
            sorted = sorted.split_off(sorted.len() - 500);
        }
        bucket.pmids = sorted;
        bucket.last_fetched = now;
        self.save_seen(&seen)?;
        Ok(new_papers)
    }

    pub async fn summary(&self, today: chrono::NaiveDate) -> Result<String, LitError> {
        let qs = self.queries()?;
        if qs.is_empty() {
            return Ok("(no literature queries configured)".into());
        }
        let mut parts = vec![format!("📚 Literature watch — {}", today)];
        let mut any_new = false;
        for q in qs {
            let new = self.new_for(&q).await?;
            if new.is_empty() {
                continue;
            }
            any_new = true;
            parts.push(format!("  «{}» — {} new", q.name, new.len()));
            for p in new.iter().take(5) {
                parts.push(p.to_line());
            }
        }
        if !any_new {
            parts.push("  (no new papers across watched queries)".into());
        }
        Ok(parts.join("\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use tempfile::TempDir;

    struct StubFetcher {
        responses: Mutex<Vec<Vec<Paper>>>,
    }

    impl StubFetcher {
        fn new(responses: Vec<Vec<Paper>>) -> Self {
            Self {
                responses: Mutex::new(responses),
            }
        }
    }

    #[async_trait]
    impl Fetcher for StubFetcher {
        async fn fetch(&self, _q: &Query) -> Result<Vec<Paper>, LitError> {
            let mut r = self.responses.lock().unwrap();
            if r.is_empty() {
                return Ok(Vec::new());
            }
            Ok(r.remove(0))
        }
    }

    fn paper(pmid: &str, title: &str) -> Paper {
        Paper {
            pmid: pmid.into(),
            title: title.into(),
            year: Some(2026),
            journal: "Nat Aging".into(),
            first_author: "Doe J".into(),
        }
    }

    fn make_paths(dir: &TempDir, prefs_yaml: Option<&str>) -> WatchPaths {
        let prefs = dir.path().join("literature.yaml");
        if let Some(y) = prefs_yaml {
            std::fs::write(&prefs, y).unwrap();
        }
        WatchPaths {
            prefs,
            seen: dir.path().join("seen.json"),
            own_publications: vec![dir.path().join("publications.md")],
        }
    }

    #[test]
    fn paper_to_line_formats_all_fields() {
        let p = paper("123", "A short title");
        let line = p.to_line();
        assert!(line.contains("123"));
        assert!(line.contains("2026"));
        assert!(line.contains("Doe J et al."));
        assert!(line.contains("Nat Aging"));
        assert!(line.starts_with("  • "));
    }

    #[test]
    fn queries_parses_yaml() {
        let dir = TempDir::new().unwrap();
        let yaml = r#"queries:
  - name: a
    term: aging
    max_results: 5
  - name: b
    term: longevity biomarker[Title]
  - term: ''
"#;
        let paths = make_paths(&dir, Some(yaml));
        let w = Watch::new(paths, Box::new(StubFetcher::new(vec![])));
        let qs = w.queries().unwrap();
        assert_eq!(qs.len(), 2);
        assert_eq!(qs[0].name, "a");
        assert_eq!(qs[0].max_results, 5);
        assert_eq!(qs[1].name, "b");
        assert_eq!(qs[1].max_results, 10);
    }

    #[test]
    fn cooldown_default_when_missing() {
        let dir = TempDir::new().unwrap();
        let paths = make_paths(&dir, None);
        let w = Watch::new(paths, Box::new(StubFetcher::new(vec![])));
        assert_eq!(w.cooldown_hours(), 6.0);
    }

    #[test]
    fn cooldown_read_from_yaml() {
        let dir = TempDir::new().unwrap();
        let paths = make_paths(&dir, Some("queries: []\ncooldown_hours: 24\n"));
        let w = Watch::new(paths, Box::new(StubFetcher::new(vec![])));
        assert_eq!(w.cooldown_hours(), 24.0);
    }

    #[test]
    fn own_pmids_extracted_from_publications() {
        let dir = TempDir::new().unwrap();
        let paths = make_paths(&dir, None);
        std::fs::write(
            &paths.own_publications[0],
            "Tkemaladze, J. et al. PMID: 12345678 — title.\n\nPMID 87654321\n",
        )
        .unwrap();
        let w = Watch::new(paths, Box::new(StubFetcher::new(vec![])));
        let own = w.own_pmids();
        assert!(own.contains("12345678"));
        assert!(own.contains("87654321"));
    }

    #[tokio::test]
    async fn new_for_dedups_against_own_pmids() {
        let dir = TempDir::new().unwrap();
        let yaml = r#"queries:
  - name: aging
    term: aging
    max_results: 10
"#;
        let paths = make_paths(&dir, Some(yaml));
        std::fs::write(&paths.own_publications[0], "PMID: 12345678").unwrap();
        let stub = StubFetcher::new(vec![vec![
            paper("12345678", "own work"),
            paper("99999999", "fresh paper"),
        ]]);
        let w = Watch::new(paths, Box::new(stub));
        let q = Query {
            name: "aging".into(),
            term: "aging".into(),
            max_results: 10,
        };
        let new = w.new_for(&q).await.unwrap();
        assert_eq!(new.len(), 1);
        assert_eq!(new[0].pmid, "99999999");
    }

    #[tokio::test]
    async fn cooldown_blocks_second_call() {
        let dir = TempDir::new().unwrap();
        let yaml = r#"queries:
  - name: aging
    term: aging
cooldown_hours: 6
"#;
        let paths = make_paths(&dir, Some(yaml));
        let stub = StubFetcher::new(vec![
            vec![paper("11", "first")],
            vec![paper("22", "second")],
        ]);
        let w = Watch::new(paths, Box::new(stub)).with_now(1_000_000);
        let q = Query {
            name: "aging".into(),
            term: "aging".into(),
            max_results: 10,
        };
        let first = w.new_for(&q).await.unwrap();
        assert_eq!(first.len(), 1);
        // Same instant, cooldown blocks
        let second = w.new_for(&q).await.unwrap();
        assert_eq!(second.len(), 0);
    }

    #[tokio::test]
    async fn cooldown_lifts_after_window() {
        let dir = TempDir::new().unwrap();
        let yaml = "queries: []\ncooldown_hours: 1\n";
        let paths = make_paths(&dir, Some(yaml));
        let stub = StubFetcher::new(vec![
            vec![paper("11", "first")],
            vec![paper("22", "second")],
        ]);
        let q = Query {
            name: "aging".into(),
            term: "aging".into(),
            max_results: 10,
        };
        let w1 = Watch::new(paths.clone(), Box::new(stub)).with_now(1_000_000);
        let _ = w1.new_for(&q).await.unwrap();
        // Re-open with same on-disk seen file but past the cooldown window.
        let stub2 = StubFetcher::new(vec![vec![paper("22", "second")]]);
        let w2 = Watch::new(paths, Box::new(stub2)).with_now(1_000_000 + 7200);
        let new = w2.new_for(&q).await.unwrap();
        assert_eq!(new.len(), 1);
        assert_eq!(new[0].pmid, "22");
    }

    #[tokio::test]
    async fn summary_when_no_queries_returns_placeholder() {
        let dir = TempDir::new().unwrap();
        let paths = make_paths(&dir, None);
        let w = Watch::new(paths, Box::new(StubFetcher::new(vec![])));
        let s = w.summary(chrono::NaiveDate::from_ymd_opt(2026, 5, 4).unwrap()).await.unwrap();
        assert!(s.contains("no literature queries configured"));
    }

    #[tokio::test]
    async fn summary_renders_new_papers() {
        let dir = TempDir::new().unwrap();
        let yaml = r#"queries:
  - name: aging
    term: aging
"#;
        let paths = make_paths(&dir, Some(yaml));
        let stub = StubFetcher::new(vec![vec![paper("777", "Recent finding")]]);
        let w = Watch::new(paths, Box::new(stub)).with_now(2_000_000);
        let s = w
            .summary(chrono::NaiveDate::from_ymd_opt(2026, 5, 4).unwrap())
            .await
            .unwrap();
        assert!(s.contains("Literature watch"));
        assert!(s.contains("«aging» — 1 new"));
        assert!(s.contains("777"));
    }

    #[test]
    fn parse_summary_extracts_year_and_author() {
        let ids = vec!["123".to_string()];
        let result = serde_json::json!({
            "123": {
                "title": "  A title with whitespace  ",
                "fulljournalname": "Nat Aging",
                "pubdate": "2026 Apr 12",
                "authors": [
                    {"name": "Doe J"}, {"name": "Smith A"}
                ]
            }
        });
        let papers = parse_summary(&ids, &result);
        assert_eq!(papers.len(), 1);
        assert_eq!(papers[0].title, "A title with whitespace");
        assert_eq!(papers[0].year, Some(2026));
        assert_eq!(papers[0].first_author, "Doe J");
    }

    #[test]
    fn parse_summary_skips_missing_records() {
        let ids = vec!["123".to_string(), "456".to_string()];
        let result = serde_json::json!({
            "123": {"title": "ok"}
        });
        let papers = parse_summary(&ids, &result);
        assert_eq!(papers.len(), 1);
        assert_eq!(papers[0].pmid, "123");
    }
}
