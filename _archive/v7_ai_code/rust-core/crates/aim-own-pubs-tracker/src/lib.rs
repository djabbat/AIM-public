//! aim-own-pubs-tracker — Crossref author watcher (PV1).
//!
//! Port of `agents/own_pubs_tracker.py`. Polls Crossref for new
//! publications under a configured author name, deduplicates against
//! `publications.md`, and surfaces NEW entries in the daily / weekly
//! digest. Never overwrites `publications.md` — only suggests.
//!
//! ## Pluggable fetcher
//! [`Fetcher`] is the trait the host wires to a real reqwest-backed
//! Crossref client; tests inject [`StubFetcher`].

use async_trait::async_trait;
use chrono::Utc;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OwnPubsError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("http: {0}")]
    Http(#[from] reqwest::Error),
    #[error("fetcher: {0}")]
    Fetcher(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct Publication {
    pub doi: String,
    pub title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub year: Option<i32>,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub journal: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub pmid: String,
}

impl Publication {
    pub fn to_line(&self) -> String {
        let title: String = self.title.chars().take(120).collect();
        let mut bits = Vec::new();
        if let Some(y) = self.year {
            bits.push(y.to_string());
        }
        if !self.journal.is_empty() {
            bits.push(self.journal.clone());
        }
        if !self.doi.is_empty() {
            bits.push(format!("doi:{}", self.doi));
        }
        format!("  • {} — {}", title, bits.join(" / "))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthorConfig {
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub orcid: Option<String>,
    pub cooldown_hours: f64,
}

impl AuthorConfig {
    pub fn from_source<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        Self {
            name: get("AIM_AUTHOR_NAME")
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "Tkemaladze".into()),
            orcid: get("AIM_AUTHOR_ORCID").filter(|s| !s.is_empty()),
            cooldown_hours: get("AIM_OWN_PUBS_COOLDOWN_HOURS")
                .and_then(|v| v.parse().ok())
                .unwrap_or(6.0),
        }
    }

    pub fn from_env() -> Self {
        Self::from_source(|k| std::env::var(k).ok())
    }
}

pub fn default_state_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("own_pubs_seen.json")
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SeenState {
    #[serde(default)]
    pub dois: Vec<String>,
    #[serde(default)]
    pub last_fetched: i64,
}

fn load_seen(path: &Path) -> SeenState {
    if !path.exists() {
        return SeenState::default();
    }
    match std::fs::read_to_string(path).ok().and_then(|s| serde_json::from_str(&s).ok()) {
        Some(s) => s,
        None => SeenState::default(),
    }
}

fn save_seen(path: &Path, state: &SeenState) -> Result<(), OwnPubsError> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let body = serde_json::to_string_pretty(state)?;
    std::fs::write(path, body)?;
    Ok(())
}

// ── publications.md DOI scan ────────────────────────────────────────────

static DOI_RE: OnceLock<Regex> = OnceLock::new();
fn doi_re() -> &'static Regex {
    DOI_RE.get_or_init(|| Regex::new(r"(?i)\b(10\.\d{4,9}/[^\s,;)]+)").unwrap())
}

pub fn extract_dois_from_files(paths: &[PathBuf]) -> HashSet<String> {
    let mut out = HashSet::new();
    for p in paths {
        if !p.exists() {
            continue;
        }
        let body = match std::fs::read_to_string(p) {
            Ok(b) => b,
            Err(_) => continue,
        };
        for cap in doi_re().captures_iter(&body) {
            if let Some(m) = cap.get(1) {
                let raw = m.as_str().trim_end_matches(|c: char| ".,;)".contains(c));
                out.insert(raw.to_lowercase());
            }
        }
    }
    out
}

pub fn default_publications_md() -> Vec<PathBuf> {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    vec![
        home.join(".claude/projects/-home-oem/memory/publications.md"),
        home.join("Desktop/PhD/publications.md"),
    ]
}

// ── Crossref fetcher ────────────────────────────────────────────────────

pub const CROSSREF_URL: &str = "https://api.crossref.org/works";

#[async_trait]
pub trait Fetcher: Send + Sync {
    async fn fetch(&self, cfg: &AuthorConfig) -> Result<Vec<Publication>, OwnPubsError>;
}

pub struct CrossrefFetcher {
    pub client: reqwest::Client,
    pub base_url: String,
}

impl CrossrefFetcher {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder()
                .user_agent("AIM/1.0 (research)")
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_else(|_| reqwest::Client::new()),
            base_url: CROSSREF_URL.into(),
        }
    }

    pub fn with_base_url(mut self, url: impl Into<String>) -> Self {
        self.base_url = url.into();
        self
    }
}

impl Default for CrossrefFetcher {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Fetcher for CrossrefFetcher {
    async fn fetch(&self, cfg: &AuthorConfig) -> Result<Vec<Publication>, OwnPubsError> {
        let mut params: Vec<(&str, String)> = vec![
            ("rows", "30".into()),
            ("sort", "issued".into()),
            ("order", "desc".into()),
            ("query.author", cfg.name.clone()),
        ];
        if let Some(orcid) = &cfg.orcid {
            params.push(("filter", format!("orcid:{orcid}")));
        }
        let r = self
            .client
            .get(&self.base_url)
            .query(&params)
            .send()
            .await?
            .error_for_status()?;
        let raw: serde_json::Value = r.json().await?;
        let items = raw
            .get("message")
            .and_then(|m| m.get("items"))
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        Ok(parse_crossref(&items))
    }
}

fn parse_crossref(items: &[serde_json::Value]) -> Vec<Publication> {
    let mut out = Vec::new();
    for it in items {
        let doi = it.get("DOI").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
        if doi.is_empty() {
            continue;
        }
        let title = it
            .get("title")
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|v| v.as_str())
            .unwrap_or("(no title)")
            .trim();
        let title: String = title.chars().take(300).collect();
        let journal = it
            .get("container-title")
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        let journal: String = journal.chars().take(120).collect();
        let year = it
            .get("issued")
            .and_then(|v| v.get("date-parts"))
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|v| v.as_i64())
            .map(|n| n as i32);
        out.push(Publication {
            doi,
            title,
            year,
            journal,
            pmid: String::new(),
        });
    }
    out
}

// ── tracker ─────────────────────────────────────────────────────────────

pub struct Tracker {
    pub state_path: PathBuf,
    pub publications_md: Vec<PathBuf>,
    pub config: AuthorConfig,
    /// Test seam — explicit "now" overrides `Utc::now().timestamp()`.
    pub now_override: Option<i64>,
}

impl Tracker {
    pub fn new(
        state_path: impl Into<PathBuf>,
        publications_md: Vec<PathBuf>,
        config: AuthorConfig,
    ) -> Self {
        Self {
            state_path: state_path.into(),
            publications_md,
            config,
            now_override: None,
        }
    }

    pub fn with_now(mut self, now: i64) -> Self {
        self.now_override = Some(now);
        self
    }

    fn now(&self) -> i64 {
        self.now_override.unwrap_or_else(|| Utc::now().timestamp())
    }

    pub async fn new_pubs(&self, fetcher: &dyn Fetcher) -> Result<Vec<Publication>, OwnPubsError> {
        let mut state = load_seen(&self.state_path);
        let cooldown_secs = (self.config.cooldown_hours * 3600.0) as i64;
        let now = self.now();
        if now - state.last_fetched < cooldown_secs {
            return Ok(Vec::new());
        }

        let pubs = fetcher.fetch(&self.config).await?;
        let own = extract_dois_from_files(&self.publications_md);
        let seen_set: HashSet<String> = state.dois.iter().cloned().collect();
        let new: Vec<Publication> = pubs
            .iter()
            .filter(|p| !own.contains(&p.doi) && !seen_set.contains(&p.doi))
            .cloned()
            .collect();

        let mut updated: BTreeSet<String> = seen_set.into_iter().collect();
        for p in &pubs {
            updated.insert(p.doi.clone());
        }
        let mut sorted: Vec<String> = updated.into_iter().collect();
        if sorted.len() > 500 {
            sorted = sorted.split_off(sorted.len() - 500);
        }
        state.dois = sorted;
        state.last_fetched = now;
        save_seen(&self.state_path, &state)?;
        Ok(new)
    }

    pub async fn summary(&self, fetcher: &dyn Fetcher) -> Result<String, OwnPubsError> {
        let new = self.new_pubs(fetcher).await?;
        if new.is_empty() {
            return Ok("(no new own publications since last poll)".into());
        }
        let mut parts = vec![format!(
            "📄 New publications ({}) for author={:?}",
            new.len(),
            self.config.name
        )];
        for p in new.iter().take(8) {
            parts.push(p.to_line());
        }
        Ok(parts.join("\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    struct StubFetcher {
        responses: parking_lot::Mutex<Vec<Vec<Publication>>>,
    }

    impl StubFetcher {
        fn new(responses: Vec<Vec<Publication>>) -> Self {
            Self {
                responses: parking_lot::Mutex::new(responses),
            }
        }
    }

    #[async_trait]
    impl Fetcher for StubFetcher {
        async fn fetch(&self, _cfg: &AuthorConfig) -> Result<Vec<Publication>, OwnPubsError> {
            let mut q = self.responses.lock();
            if q.is_empty() {
                return Ok(vec![]);
            }
            Ok(q.remove(0))
        }
    }

    fn pub_(doi: &str, title: &str, year: i32) -> Publication {
        Publication {
            doi: doi.into(),
            title: title.into(),
            year: Some(year),
            journal: "Nat".into(),
            pmid: String::new(),
        }
    }

    fn make_paths(dir: &TempDir, md_body: Option<&str>) -> (PathBuf, Vec<PathBuf>) {
        let state = dir.path().join("seen.json");
        let md = dir.path().join("publications.md");
        if let Some(body) = md_body {
            std::fs::write(&md, body).unwrap();
        }
        (state, vec![md])
    }

    fn cfg() -> AuthorConfig {
        AuthorConfig {
            name: "Tkemaladze".into(),
            orcid: None,
            cooldown_hours: 6.0,
        }
    }

    #[test]
    fn pub_to_line_formats_metadata() {
        let p = pub_("10.1000/abc", "A title", 2026);
        let s = p.to_line();
        assert!(s.contains("A title"));
        assert!(s.contains("2026"));
        assert!(s.contains("Nat"));
        assert!(s.contains("doi:10.1000/abc"));
    }

    #[test]
    fn extract_dois_from_files_lowercases_and_strips_punct() {
        let dir = TempDir::new().unwrap();
        let p = dir.path().join("publications.md");
        std::fs::write(
            &p,
            "Tkemaladze, J. 2023, doi: 10.1234/ABCD.\nSee 10.5555/foo;bar.",
        )
        .unwrap();
        let dois = extract_dois_from_files(&[p]);
        assert!(dois.contains("10.1234/abcd"));
        assert!(dois.contains("10.5555/foo"));
    }

    #[test]
    fn extract_dois_handles_missing_files() {
        let dois = extract_dois_from_files(&[PathBuf::from("/nonexistent/file.md")]);
        assert!(dois.is_empty());
    }

    #[test]
    fn config_from_source_defaults() {
        let cfg = AuthorConfig::from_source(|_| None);
        assert_eq!(cfg.name, "Tkemaladze");
        assert!(cfg.orcid.is_none());
        assert_eq!(cfg.cooldown_hours, 6.0);
    }

    #[test]
    fn config_from_source_overrides() {
        let env: std::collections::HashMap<&str, &str> = [
            ("AIM_AUTHOR_NAME", "Smith"),
            ("AIM_AUTHOR_ORCID", "0000-0001-2345-6789"),
            ("AIM_OWN_PUBS_COOLDOWN_HOURS", "24"),
        ]
        .into_iter()
        .collect();
        let cfg = AuthorConfig::from_source(|k| env.get(k).map(|s| s.to_string()));
        assert_eq!(cfg.name, "Smith");
        assert_eq!(cfg.orcid.as_deref(), Some("0000-0001-2345-6789"));
        assert_eq!(cfg.cooldown_hours, 24.0);
    }

    #[test]
    fn parse_crossref_pulls_doi_title_journal_year() {
        let items = vec![json!({
            "DOI": "10.1234/abc",
            "title": ["Centriole-driven longevity"],
            "container-title": ["Nature Aging"],
            "issued": {"date-parts": [[2026, 4]]}
        })];
        let pubs = parse_crossref(&items);
        assert_eq!(pubs.len(), 1);
        assert_eq!(pubs[0].doi, "10.1234/abc");
        assert_eq!(pubs[0].title, "Centriole-driven longevity");
        assert_eq!(pubs[0].journal, "Nature Aging");
        assert_eq!(pubs[0].year, Some(2026));
    }

    #[test]
    fn parse_crossref_skips_doi_less_items() {
        let items = vec![json!({"title": ["No DOI here"]})];
        assert!(parse_crossref(&items).is_empty());
    }

    #[tokio::test]
    async fn new_pubs_drops_known_dois() {
        let dir = TempDir::new().unwrap();
        // publications.md already lists 10.1000/old
        let (state_path, mds) =
            make_paths(&dir, Some("Tkemaladze, J. 2024 — doi: 10.1000/OLD"));
        let stub = StubFetcher::new(vec![vec![
            pub_("10.1000/old", "old paper", 2024),
            pub_("10.1000/new", "new paper", 2026),
        ]]);
        let tracker = Tracker::new(state_path, mds, cfg()).with_now(1_000_000);
        let new = tracker.new_pubs(&stub).await.unwrap();
        assert_eq!(new.len(), 1);
        assert_eq!(new[0].doi, "10.1000/new");
    }

    #[tokio::test]
    async fn cooldown_blocks_second_call() {
        let dir = TempDir::new().unwrap();
        let (state_path, mds) = make_paths(&dir, None);
        let stub = StubFetcher::new(vec![
            vec![pub_("10.1000/a", "a", 2026)],
            vec![pub_("10.1000/b", "b", 2026)],
        ]);
        let tracker =
            Tracker::new(state_path, mds, cfg()).with_now(1_000_000);
        let r1 = tracker.new_pubs(&stub).await.unwrap();
        assert_eq!(r1.len(), 1);
        // Second call within 6h cooldown — must short-circuit, not consume queue
        let r2 = tracker.new_pubs(&stub).await.unwrap();
        assert!(r2.is_empty());
    }

    #[tokio::test]
    async fn cooldown_expires_after_window() {
        let dir = TempDir::new().unwrap();
        let (state_path, mds) = make_paths(&dir, None);
        let stub = StubFetcher::new(vec![
            vec![pub_("10.1000/a", "a", 2026)],
            vec![pub_("10.1000/b", "b", 2026)],
        ]);
        let t1 = Tracker::new(state_path.clone(), mds.clone(), cfg())
            .with_now(1_000_000);
        let _ = t1.new_pubs(&stub).await.unwrap();
        // 7 hours later
        let t2 = Tracker::new(state_path, mds, cfg()).with_now(1_000_000 + 7 * 3600);
        let r = t2.new_pubs(&stub).await.unwrap();
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].doi, "10.1000/b");
    }

    #[tokio::test]
    async fn second_run_dedups_against_seen_set() {
        let dir = TempDir::new().unwrap();
        let (state_path, mds) = make_paths(&dir, None);
        // Stub returns the SAME paper on both calls; second call should
        // see it in seen set and return empty.
        let stub = StubFetcher::new(vec![
            vec![pub_("10.1000/a", "a", 2026)],
            vec![pub_("10.1000/a", "a", 2026)],
        ]);
        let t1 = Tracker::new(state_path.clone(), mds.clone(), cfg())
            .with_now(1_000_000);
        let r1 = t1.new_pubs(&stub).await.unwrap();
        assert_eq!(r1.len(), 1);
        let t2 = Tracker::new(state_path, mds, cfg()).with_now(1_000_000 + 7 * 3600);
        let r2 = t2.new_pubs(&stub).await.unwrap();
        assert!(r2.is_empty());
    }

    #[tokio::test]
    async fn summary_lists_new_or_says_none() {
        let dir = TempDir::new().unwrap();
        let (state_path, mds) = make_paths(&dir, None);
        let stub = StubFetcher::new(vec![vec![pub_("10.1000/a", "Pretty title", 2026)]]);
        let tracker = Tracker::new(state_path, mds, cfg()).with_now(1_000_000);
        let s = tracker.summary(&stub).await.unwrap();
        assert!(s.contains("New publications"));
        assert!(s.contains("Pretty title"));
    }

    #[tokio::test]
    async fn summary_empty_message_when_nothing_new() {
        let dir = TempDir::new().unwrap();
        let (state_path, mds) = make_paths(&dir, None);
        let stub = StubFetcher::new(vec![vec![]]);
        let tracker = Tracker::new(state_path, mds, cfg()).with_now(1_000_000);
        let s = tracker.summary(&stub).await.unwrap();
        assert!(s.contains("no new own publications"));
    }
}
