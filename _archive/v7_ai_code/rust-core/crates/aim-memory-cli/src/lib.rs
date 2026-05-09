//! aim-memory-cli — orchestration for AIM's `aim-memory` subcommands.
//!
//! Port of `agents/memory_cli.py`. This crate is a *library* of
//! stateless command handlers + a [`Backend`] trait that abstracts every
//! external dependency (vector index, graph store, dedup, versioning,
//! backup). Argument parsing (clap) lives in the Phase-4 binary; the
//! handlers here are testable in isolation.
//!
//! Subcommands (mirroring Python):
//!   add | search | delete | stats | backup | snapshot | rollback | diff | dedup

use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CliError {
    #[error("backend error: {0}")]
    Backend(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("cancelled by user")]
    Cancelled,
}

pub type Result<T> = std::result::Result<T, CliError>;

// ── data types ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Priority {
    Critical,
    High,
    Normal,
    Low,
    Ephemeral,
}

impl Priority {
    pub fn parse(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "critical" => Some(Self::Critical),
            "high" => Some(Self::High),
            "normal" => Some(Self::Normal),
            "low" => Some(Self::Low),
            "ephemeral" => Some(Self::Ephemeral),
            _ => None,
        }
    }
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Normal => "normal",
            Self::Low => "low",
            Self::Ephemeral => "ephemeral",
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AddArgs {
    pub fact: String,
    pub category: String,
    pub tags: Vec<String>,
    pub priority: Option<Priority>,
    pub ttl_hours: Option<i64>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SearchArgs {
    pub query: String,
    pub limit: usize,
    pub graph: bool,
    pub hops: usize,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Hit {
    pub file: PathBuf,
    pub text: String,
    pub distance: f64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct StatsReport {
    pub index: BTreeMap<String, String>,
    pub graph_nodes: Option<usize>,
    pub graph_edges: Option<usize>,
    pub user_memories: Option<usize>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DiffSummary {
    pub added: usize,
    pub removed: usize,
    pub first_added: Vec<String>,
    pub first_removed: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DedupReport {
    pub pairs_found: usize,
    pub preview: Vec<DedupPair>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DedupPair {
    pub a: PathBuf,
    pub b: PathBuf,
    pub score: f64,
}

// ── backend trait ───────────────────────────────────────────────────────────

/// Pluggable surface for all external services. Production binds each
/// method to the corresponding crate (`aim-memory-store`, future
/// `aim-memory-index`, `aim-memory-versioning`, `aim-memory-deduplicate`,
/// etc). Tests use a stub.
pub trait Backend: Send + Sync {
    fn add(&self, args: &AddArgs) -> Result<PathBuf>;
    fn search_flat(&self, query: &str, k: usize) -> Result<Vec<Hit>>;
    fn search_graph(&self, query: &str, k: usize, hops: usize) -> Result<Vec<Hit>>;
    fn delete(&self, pattern: &str) -> Result<usize>;
    fn stats(&self) -> Result<StatsReport>;
    fn backup(&self, dest: &std::path::Path) -> Result<PathBuf>;
    fn snapshot(&self, description: &str) -> Result<String>;
    fn rollback(&self, version_id: &str) -> Result<()>;
    fn diff(&self, a: &str, b: &str) -> Result<DiffSummary>;
    fn dedup(&self, threshold: f64, dry_run: bool) -> Result<DedupReport>;
}

// ── confirmation prompt (pluggable for tests) ───────────────────────────────

pub trait Confirm: Send + Sync {
    fn confirm(&self, prompt: &str) -> bool;
}

pub struct AlwaysYes;
impl Confirm for AlwaysYes {
    fn confirm(&self, _prompt: &str) -> bool {
        true
    }
}

pub struct AlwaysNo;
impl Confirm for AlwaysNo {
    fn confirm(&self, _prompt: &str) -> bool {
        false
    }
}

// ── handlers ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum CommandResult {
    Added { path: PathBuf },
    Searched { hits: Vec<Hit> },
    Deleted { count: usize },
    Stats(StatsReport),
    BackedUp { path: PathBuf },
    Snapshotted { version_id: String },
    RolledBack,
    Diffed(DiffSummary),
    Deduped(DedupReport),
}

pub struct MemoryCli<'a> {
    pub backend: &'a dyn Backend,
}

impl<'a> MemoryCli<'a> {
    pub fn new(backend: &'a dyn Backend) -> Self {
        Self { backend }
    }

    pub fn add(&self, args: &AddArgs) -> Result<CommandResult> {
        let path = self.backend.add(args)?;
        Ok(CommandResult::Added { path })
    }

    pub fn search(&self, args: &SearchArgs) -> Result<CommandResult> {
        let hits = if args.graph {
            self.backend.search_graph(&args.query, args.limit, args.hops)?
        } else {
            self.backend.search_flat(&args.query, args.limit)?
        };
        Ok(CommandResult::Searched { hits })
    }

    pub fn delete(&self, pattern: &str, force: bool, confirm: &dyn Confirm) -> Result<CommandResult> {
        if !force && !confirm.confirm(pattern) {
            return Err(CliError::Cancelled);
        }
        let count = self.backend.delete(pattern)?;
        Ok(CommandResult::Deleted { count })
    }

    pub fn stats(&self) -> Result<CommandResult> {
        Ok(CommandResult::Stats(self.backend.stats()?))
    }

    pub fn backup(&self, dest_root: &std::path::Path, ts: &str) -> Result<CommandResult> {
        let dest = dest_root.join(format!("memory_backup_{}", ts));
        let path = self.backend.backup(&dest)?;
        Ok(CommandResult::BackedUp { path })
    }

    pub fn snapshot(&self, description: &str) -> Result<CommandResult> {
        let version_id = self.backend.snapshot(description)?;
        Ok(CommandResult::Snapshotted { version_id })
    }

    pub fn rollback(&self, version_id: &str) -> Result<CommandResult> {
        self.backend.rollback(version_id)?;
        Ok(CommandResult::RolledBack)
    }

    pub fn diff(&self, a: &str, b: &str) -> Result<CommandResult> {
        Ok(CommandResult::Diffed(self.backend.diff(a, b)?))
    }

    pub fn dedup(&self, threshold: f64, dry_run: bool) -> Result<CommandResult> {
        Ok(CommandResult::Deduped(self.backend.dedup(threshold, dry_run)?))
    }
}

// ── arg parsing helpers (no clap dep) ───────────────────────────────────────

/// Parse `--tags a,b,c` into trimmed non-empty entries.
pub fn parse_tags(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stub backend ────────────────────────────────────────────────────────

    #[derive(Default)]
    struct StubBackend {
        adds: Mutex<Vec<AddArgs>>,
        deletes: Mutex<Vec<String>>,
        rollbacks: Mutex<Vec<String>>,
        snapshots: Mutex<Vec<String>>,
        flat_searches: Mutex<Vec<(String, usize)>>,
        graph_searches: Mutex<Vec<(String, usize, usize)>>,
    }

    impl Backend for StubBackend {
        fn add(&self, args: &AddArgs) -> Result<PathBuf> {
            self.adds.lock().push(args.clone());
            Ok(PathBuf::from(format!("/tmp/{}.md", args.fact.len())))
        }
        fn search_flat(&self, q: &str, k: usize) -> Result<Vec<Hit>> {
            self.flat_searches.lock().push((q.into(), k));
            Ok(vec![Hit {
                file: "/tmp/x.md".into(),
                text: format!("flat:{}", q),
                distance: 0.5,
            }])
        }
        fn search_graph(&self, q: &str, k: usize, hops: usize) -> Result<Vec<Hit>> {
            self.graph_searches.lock().push((q.into(), k, hops));
            Ok(vec![Hit {
                file: "/tmp/y.md".into(),
                text: format!("graph:{}:{}", q, hops),
                distance: 0.7,
            }])
        }
        fn delete(&self, pattern: &str) -> Result<usize> {
            self.deletes.lock().push(pattern.into());
            Ok(3)
        }
        fn stats(&self) -> Result<StatsReport> {
            let mut r = StatsReport::default();
            r.index.insert("rows".into(), "10".into());
            r.user_memories = Some(7);
            Ok(r)
        }
        fn backup(&self, dest: &std::path::Path) -> Result<PathBuf> {
            std::fs::create_dir_all(dest)?;
            Ok(dest.to_path_buf())
        }
        fn snapshot(&self, description: &str) -> Result<String> {
            self.snapshots.lock().push(description.into());
            Ok(format!("v_{}", description.len()))
        }
        fn rollback(&self, vid: &str) -> Result<()> {
            self.rollbacks.lock().push(vid.into());
            Ok(())
        }
        fn diff(&self, _a: &str, _b: &str) -> Result<DiffSummary> {
            Ok(DiffSummary {
                added: 2,
                removed: 1,
                first_added: vec!["a".into(), "b".into()],
                first_removed: vec!["c".into()],
            })
        }
        fn dedup(&self, _threshold: f64, _dry_run: bool) -> Result<DedupReport> {
            Ok(DedupReport {
                pairs_found: 1,
                preview: vec![DedupPair {
                    a: "/tmp/a.md".into(),
                    b: "/tmp/b.md".into(),
                    score: 0.92,
                }],
            })
        }
    }

    // ── Priority ────────────────────────────────────────────────────────────

    #[test]
    fn priority_round_trips() {
        for p in [
            Priority::Critical,
            Priority::High,
            Priority::Normal,
            Priority::Low,
            Priority::Ephemeral,
        ] {
            assert_eq!(Priority::parse(p.as_str()), Some(p));
        }
    }

    #[test]
    fn priority_case_insensitive() {
        assert_eq!(Priority::parse("CRITICAL"), Some(Priority::Critical));
        assert_eq!(Priority::parse("High"), Some(Priority::High));
    }

    #[test]
    fn priority_unknown_returns_none() {
        assert!(Priority::parse("urgent").is_none());
    }

    // ── parse_tags ───────────────────────────────────────────────────────────

    #[test]
    fn parse_tags_trims_and_filters_empty() {
        assert_eq!(
            parse_tags(" a, b ,, c , "),
            vec!["a".to_string(), "b".to_string(), "c".to_string()]
        );
    }

    #[test]
    fn parse_tags_empty_string_returns_empty_vec() {
        assert!(parse_tags("").is_empty());
        assert!(parse_tags(",,").is_empty());
    }

    // ── add ─────────────────────────────────────────────────────────────────

    #[test]
    fn add_passes_args_to_backend() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        let args = AddArgs {
            fact: "hello".into(),
            category: "general".into(),
            tags: vec!["a".into(), "b".into()],
            priority: Some(Priority::High),
            ttl_hours: Some(48),
        };
        let r = cli.add(&args).unwrap();
        assert!(matches!(r, CommandResult::Added { .. }));
        let recorded = b.adds.lock();
        assert_eq!(recorded.len(), 1);
        assert_eq!(recorded[0].fact, "hello");
        assert_eq!(recorded[0].tags, vec!["a", "b"]);
        assert_eq!(recorded[0].priority, Some(Priority::High));
        assert_eq!(recorded[0].ttl_hours, Some(48));
    }

    // ── search ──────────────────────────────────────────────────────────────

    #[test]
    fn search_flat_when_graph_false() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        let args = SearchArgs {
            query: "foo".into(),
            limit: 10,
            graph: false,
            hops: 1,
        };
        let r = cli.search(&args).unwrap();
        if let CommandResult::Searched { hits } = r {
            assert_eq!(hits[0].text, "flat:foo");
        } else {
            panic!("expected Searched");
        }
        assert_eq!(b.flat_searches.lock().len(), 1);
        assert_eq!(b.graph_searches.lock().len(), 0);
    }

    #[test]
    fn search_graph_when_graph_true() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        let args = SearchArgs {
            query: "bar".into(),
            limit: 5,
            graph: true,
            hops: 2,
        };
        let r = cli.search(&args).unwrap();
        if let CommandResult::Searched { hits } = r {
            assert_eq!(hits[0].text, "graph:bar:2");
        } else {
            panic!("expected Searched");
        }
        assert_eq!(b.flat_searches.lock().len(), 0);
        let g = b.graph_searches.lock();
        assert_eq!(g[0], ("bar".into(), 5, 2));
    }

    // ── delete ──────────────────────────────────────────────────────────────

    #[test]
    fn delete_force_skips_confirm() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        let r = cli.delete("xyz", true, &AlwaysNo).unwrap();
        assert!(matches!(r, CommandResult::Deleted { count: 3 }));
        assert_eq!(b.deletes.lock()[0], "xyz");
    }

    #[test]
    fn delete_no_force_yes_confirm_proceeds() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        let r = cli.delete("xyz", false, &AlwaysYes).unwrap();
        assert!(matches!(r, CommandResult::Deleted { count: 3 }));
    }

    #[test]
    fn delete_no_force_no_confirm_returns_cancelled() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        let err = cli.delete("xyz", false, &AlwaysNo).unwrap_err();
        assert!(matches!(err, CliError::Cancelled));
        assert!(b.deletes.lock().is_empty());
    }

    // ── stats ───────────────────────────────────────────────────────────────

    #[test]
    fn stats_returns_backend_report() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        if let CommandResult::Stats(s) = cli.stats().unwrap() {
            assert_eq!(s.index.get("rows").unwrap(), "10");
            assert_eq!(s.user_memories, Some(7));
        } else {
            panic!("expected Stats");
        }
    }

    // ── backup ──────────────────────────────────────────────────────────────

    #[test]
    fn backup_creates_timestamped_dir() {
        let tmp = tempfile::TempDir::new().unwrap();
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        if let CommandResult::BackedUp { path } = cli.backup(tmp.path(), "20260504_213045").unwrap() {
            assert!(path.ends_with("memory_backup_20260504_213045"));
            assert!(path.exists());
        } else {
            panic!("expected BackedUp");
        }
    }

    // ── snapshot / rollback / diff ──────────────────────────────────────────

    #[test]
    fn snapshot_passes_description() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        if let CommandResult::Snapshotted { version_id } = cli.snapshot("manual save").unwrap() {
            assert_eq!(version_id, "v_11");
        } else {
            panic!();
        }
        assert_eq!(b.snapshots.lock()[0], "manual save");
    }

    #[test]
    fn rollback_passes_version_id() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        cli.rollback("v_42").unwrap();
        assert_eq!(b.rollbacks.lock()[0], "v_42");
    }

    #[test]
    fn diff_returns_summary() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        if let CommandResult::Diffed(s) = cli.diff("v1", "v2").unwrap() {
            assert_eq!(s.added, 2);
            assert_eq!(s.removed, 1);
            assert_eq!(s.first_added, vec!["a".to_string(), "b".to_string()]);
        } else {
            panic!();
        }
    }

    // ── dedup ───────────────────────────────────────────────────────────────

    #[test]
    fn dedup_returns_pairs() {
        let b = StubBackend::default();
        let cli = MemoryCli::new(&b);
        if let CommandResult::Deduped(r) = cli.dedup(0.85, true).unwrap() {
            assert_eq!(r.pairs_found, 1);
            assert_eq!(r.preview[0].score, 0.92);
        } else {
            panic!();
        }
    }
}
