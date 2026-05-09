//! aim-memory-index — semantic memory chunking + retrieval surface.
//!
//! Port of the deterministic core of `agents/memory_index.py`. The
//! Python original embeds via `sentence-transformers` and stores in
//! LanceDB; the Rust port keeps:
//!
//! - `split_chunks` — windowed chunker with overlap
//! - `enumerate_files` — auto-memory dir + Desktop project core .md walk
//! - `Embedder` + `VectorStore` traits — production wires real backends
//!   (e.g. an embed-daemon over Unix-domain socket + `lance` crate)
//! - `IndexState` snapshot for incremental reindex (mtime tracking)
//!
//! Actual ANN/cosine math and persistence are deferred to the binary
//! that consumes this crate.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum IndexError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("embed error: {0}")]
    Embed(String),
    #[error("store error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, IndexError>;

// ── chunking ───────────────────────────────────────────────────────────────

pub const CHUNK_CHARS: usize = 1500;
pub const CHUNK_OVERLAP: usize = 200;

/// Split a text into overlapping char-windows. Mirrors Python
/// `_split_chunks`. The cuts are by `char` count (not byte) so multi-byte
/// scripts (Cyrillic / Georgian / CJK) are safe.
pub fn split_chunks(text: &str) -> Vec<String> {
    split_chunks_with(text, CHUNK_CHARS, CHUNK_OVERLAP)
}

pub fn split_chunks_with(text: &str, chunk_chars: usize, overlap: usize) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= chunk_chars {
        return vec![text.to_string()];
    }
    let mut out = Vec::new();
    let mut start = 0usize;
    while start < chars.len() {
        let end = (start + chunk_chars).min(chars.len());
        out.push(chars[start..end].iter().collect::<String>());
        if end == chars.len() {
            break;
        }
        start = end - overlap;
    }
    out
}

// ── file enumeration ───────────────────────────────────────────────────────

/// Core .md filenames the indexer considers under `Desktop/<project>/`.
pub const CORE_MD_NAMES: &[&str] = &[
    "CONCEPT.md",
    "STATE.md",
    "THEORY.md",
    "DESIGN.md",
    "EVIDENCE.md",
    "PARAMETERS.md",
    "OPEN_PROBLEMS.md",
    "MEMORY.md",
    "README.md",
];

/// Project subtree names walked when `index_desktop` is true.
pub const DESKTOP_PROJECT_NAMES: &[&str] = &[
    "LongevityCommon",
    "FCLC",
    "MCOA",
    "Ze",
    "BioSense",
    "CDATA",
    "AIM",
    "Annals",
    "PhD",
    "Books",
    "GLA",
];

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct FileRecord {
    pub path: PathBuf,
    pub label: String,
    pub mtime_secs: i64,
}

/// Enumerate the auto-memory directory + (optionally) project core files.
/// Skips files unreadable or missing. Sorted by path for deterministic
/// reindex ordering.
pub fn enumerate_files(
    auto_memory_dir: &Path,
    desktop_root: Option<&Path>,
) -> Result<Vec<FileRecord>> {
    let mut seen: std::collections::BTreeSet<PathBuf> = std::collections::BTreeSet::new();
    let mut out: Vec<FileRecord> = Vec::new();

    if auto_memory_dir.exists() {
        let mut paths: Vec<PathBuf> = std::fs::read_dir(auto_memory_dir)?
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("md"))
            .collect();
        paths.sort();
        for p in paths {
            if seen.insert(p.clone()) {
                let mtime = mtime_secs(&p)?;
                out.push(FileRecord {
                    path: p,
                    label: "auto_memory".into(),
                    mtime_secs: mtime,
                });
            }
        }
    }

    if let Some(desktop) = desktop_root {
        for project in DESKTOP_PROJECT_NAMES {
            let project_dir = desktop.join(project);
            if !project_dir.exists() {
                continue;
            }
            for core in CORE_MD_NAMES {
                let p = project_dir.join(core);
                if p.exists() && seen.insert(p.clone()) {
                    let mtime = mtime_secs(&p)?;
                    out.push(FileRecord {
                        path: p,
                        label: format!("desktop:{}", project),
                        mtime_secs: mtime,
                    });
                }
            }
        }
    }

    Ok(out)
}

fn mtime_secs(p: &Path) -> Result<i64> {
    let meta = std::fs::metadata(p)?;
    let modified = meta.modified()?;
    let secs = modified
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    Ok(secs)
}

// ── records / chunking pipeline ────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ChunkRecord {
    pub file: String,
    pub chunk_id: usize,
    pub text: String,
    pub mtime_secs: i64,
    pub label: String,
}

/// Read each file record and emit a `ChunkRecord` per chunk. Mirrors
/// Python `_enumerate_records` minus the deduplication-on-Path detail
/// (already handled by [`enumerate_files`]).
pub fn enumerate_records(files: &[FileRecord]) -> Result<Vec<ChunkRecord>> {
    let mut out: Vec<ChunkRecord> = Vec::new();
    for f in files {
        let text = std::fs::read_to_string(&f.path)?;
        let name = f
            .path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();
        for (i, chunk) in split_chunks(&text).into_iter().enumerate() {
            out.push(ChunkRecord {
                file: name.clone(),
                chunk_id: i,
                text: chunk,
                mtime_secs: f.mtime_secs,
                label: f.label.clone(),
            });
        }
    }
    Ok(out)
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait Embedder: Send + Sync {
    /// Return a vector per input text. Implementations may panic on length
    /// mismatch in production; tests use deterministic stubs.
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
}

pub trait VectorStore: Send + Sync {
    fn upsert(&self, records: &[StoredRecord]) -> Result<()>;
    fn search(&self, query_embedding: &[f32], k: usize) -> Result<Vec<Hit>>;
    fn delete_by_file(&self, file: &str) -> Result<()>;
    fn count(&self) -> Result<usize>;
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct StoredRecord {
    pub file: String,
    pub chunk_id: usize,
    pub text: String,
    pub embedding: Vec<f32>,
    pub mtime_secs: i64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Hit {
    pub file: String,
    pub chunk_id: usize,
    pub text: String,
    pub distance: f64,
}

// ── incremental state ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct IndexState {
    pub mtimes: BTreeMap<PathBuf, i64>,
}

impl IndexState {
    pub fn changed_or_new(&self, files: &[FileRecord]) -> Vec<FileRecord> {
        files
            .iter()
            .filter(|f| {
                self.mtimes
                    .get(&f.path)
                    .map(|&m| m < f.mtime_secs)
                    .unwrap_or(true)
            })
            .cloned()
            .collect()
    }

    pub fn record(&mut self, files: &[FileRecord]) {
        for f in files {
            self.mtimes.insert(f.path.clone(), f.mtime_secs);
        }
    }

    /// Files in `mtimes` that are no longer present in `files` (deleted).
    pub fn deleted_paths(&self, files: &[FileRecord]) -> Vec<PathBuf> {
        let live: std::collections::BTreeSet<&PathBuf> =
            files.iter().map(|f| &f.path).collect();
        self.mtimes
            .keys()
            .filter(|p| !live.contains(p))
            .cloned()
            .collect()
    }
}

// ── reindex orchestrator ───────────────────────────────────────────────────

pub struct Indexer<'a> {
    pub embedder: &'a dyn Embedder,
    pub store: &'a dyn VectorStore,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ReindexReport {
    pub upserted: usize,
    pub deleted_files: usize,
    pub touched_files: usize,
}

impl<'a> Indexer<'a> {
    pub fn new(embedder: &'a dyn Embedder, store: &'a dyn VectorStore) -> Self {
        Self { embedder, store }
    }

    pub fn reindex_incremental(
        &self,
        files: &[FileRecord],
        state: &mut IndexState,
    ) -> Result<ReindexReport> {
        let changed = state.changed_or_new(files);
        let deleted = state.deleted_paths(files);
        for path in &deleted {
            if let Some(name) = path.file_name().and_then(|s| s.to_str()) {
                self.store.delete_by_file(name)?;
            }
        }
        let chunks = enumerate_records(&changed)?;
        let texts: Vec<String> = chunks.iter().map(|c| c.text.clone()).collect();
        let embeddings = if texts.is_empty() {
            Vec::new()
        } else {
            self.embedder.embed(&texts)?
        };
        let stored: Vec<StoredRecord> = chunks
            .iter()
            .zip(embeddings.into_iter())
            .map(|(c, embedding)| StoredRecord {
                file: c.file.clone(),
                chunk_id: c.chunk_id,
                text: c.text.clone(),
                embedding,
                mtime_secs: c.mtime_secs,
            })
            .collect();
        if !stored.is_empty() {
            self.store.upsert(&stored)?;
        }
        state.record(&changed);
        // Drop deleted entries from state
        for p in &deleted {
            state.mtimes.remove(p);
        }
        Ok(ReindexReport {
            upserted: stored.len(),
            deleted_files: deleted.len(),
            touched_files: changed.len(),
        })
    }

    /// Top-K hits for `query`. Embeds the query first and delegates to
    /// the vector store.
    pub fn retrieve(&self, query: &str, k: usize) -> Result<Vec<Hit>> {
        let embedding = self.embedder.embed(&[query.to_string()])?;
        let v = embedding.into_iter().next().ok_or_else(|| {
            IndexError::Embed("embedder returned empty vector".into())
        })?;
        self.store.search(&v, k)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use tempfile::TempDir;

    // ── split_chunks ───────────────────────────────────────────────────────

    #[test]
    fn split_chunks_short_input_returns_single_chunk() {
        let v = split_chunks("hello");
        assert_eq!(v, vec!["hello".to_string()]);
    }

    #[test]
    fn split_chunks_with_overlap_covers_full_text() {
        let text = "x".repeat(3000);
        let v = split_chunks_with(&text, 1000, 100);
        // chunks: 0-999, 900-1899, 1800-2799, 2700-2999 → 4 chunks
        assert_eq!(v.len(), 4);
        // each chunk ≤ 1000 chars
        for c in &v {
            assert!(c.chars().count() <= 1000);
        }
    }

    #[test]
    fn split_chunks_unicode_safe() {
        let text = "Привет мир ".repeat(500); // multi-byte chars
        let v = split_chunks_with(&text, 100, 10);
        assert!(v.len() > 1);
        for c in &v {
            // each chunk re-decodes cleanly
            let _: Vec<char> = c.chars().collect();
        }
    }

    // ── enumerate_files ────────────────────────────────────────────────────

    #[test]
    fn enumerate_auto_memory_dir() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("a.md"), "alpha").unwrap();
        std::fs::write(tmp.path().join("b.md"), "beta").unwrap();
        std::fs::write(tmp.path().join("ignored.txt"), "x").unwrap();
        let files = enumerate_files(tmp.path(), None).unwrap();
        assert_eq!(files.len(), 2);
        assert!(files.iter().all(|f| f.label == "auto_memory"));
    }

    #[test]
    fn enumerate_includes_desktop_project_core() {
        let tmp = TempDir::new().unwrap();
        let memory_dir = tmp.path().join("memory");
        std::fs::create_dir_all(&memory_dir).unwrap();
        let desktop = tmp.path().join("Desktop");
        let project_dir = desktop.join("AIM");
        std::fs::create_dir_all(&project_dir).unwrap();
        std::fs::write(project_dir.join("CONCEPT.md"), "concept").unwrap();
        std::fs::write(project_dir.join("README.md"), "readme").unwrap();
        std::fs::write(project_dir.join("notes.md"), "skipped").unwrap(); // not in CORE_MD_NAMES

        let files = enumerate_files(&memory_dir, Some(&desktop)).unwrap();
        let names: Vec<&str> = files
            .iter()
            .map(|f| f.path.file_name().unwrap().to_str().unwrap())
            .collect();
        assert!(names.contains(&"CONCEPT.md"));
        assert!(names.contains(&"README.md"));
        assert!(!names.contains(&"notes.md"));
    }

    #[test]
    fn enumerate_skips_unknown_projects() {
        let tmp = TempDir::new().unwrap();
        let memory_dir = tmp.path().join("memory");
        let desktop = tmp.path().join("Desktop");
        let unknown = desktop.join("UnknownProject");
        std::fs::create_dir_all(&unknown).unwrap();
        std::fs::write(unknown.join("CONCEPT.md"), "x").unwrap();
        let files = enumerate_files(&memory_dir, Some(&desktop)).unwrap();
        assert!(files.is_empty());
    }

    #[test]
    fn enumerate_dedupes_path() {
        let tmp = TempDir::new().unwrap();
        let memory_dir = tmp.path().join("memory");
        std::fs::create_dir_all(&memory_dir).unwrap();
        let desktop = tmp.path().join("Desktop");
        // same path appears in both auto_memory and desktop scope
        let aim = desktop.join("AIM");
        std::fs::create_dir_all(&aim).unwrap();
        std::fs::write(aim.join("MEMORY.md"), "x").unwrap();
        // also drop a copy in memory_dir
        std::fs::write(memory_dir.join("MEMORY.md"), "x").unwrap();
        let files = enumerate_files(&memory_dir, Some(&desktop)).unwrap();
        // both files exist as distinct paths → both included
        assert_eq!(files.len(), 2);
    }

    // ── enumerate_records ──────────────────────────────────────────────────

    #[test]
    fn enumerate_records_chunks_each_file() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("big.md");
        let big = "y".repeat(5000);
        std::fs::write(&p, &big).unwrap();
        let mtime = mtime_secs(&p).unwrap();
        let recs = enumerate_records(&[FileRecord {
            path: p.clone(),
            label: "auto_memory".into(),
            mtime_secs: mtime,
        }])
        .unwrap();
        assert!(recs.len() > 1);
        assert!(recs.iter().all(|r| r.file == "big.md"));
        assert_eq!(recs[0].chunk_id, 0);
        assert_eq!(recs[1].chunk_id, 1);
    }

    // ── IndexState ─────────────────────────────────────────────────────────

    fn fr(path: &str, mtime: i64) -> FileRecord {
        FileRecord {
            path: PathBuf::from(path),
            label: "auto_memory".into(),
            mtime_secs: mtime,
        }
    }

    #[test]
    fn changed_or_new_returns_all_when_state_empty() {
        let state = IndexState::default();
        let files = vec![fr("a", 1), fr("b", 2)];
        let v = state.changed_or_new(&files);
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn changed_or_new_returns_only_modified() {
        let mut state = IndexState::default();
        state.record(&[fr("a", 1), fr("b", 2)]);
        let after = vec![fr("a", 1), fr("b", 5), fr("c", 3)];
        let changed = state.changed_or_new(&after);
        let names: Vec<String> = changed
            .iter()
            .map(|f| f.path.to_string_lossy().to_string())
            .collect();
        assert!(names.contains(&"b".to_string()));
        assert!(names.contains(&"c".to_string()));
        assert!(!names.contains(&"a".to_string()));
    }

    #[test]
    fn deleted_paths_finds_removed_files() {
        let mut state = IndexState::default();
        state.record(&[fr("a", 1), fr("b", 2)]);
        let after = vec![fr("a", 1)];
        let deleted = state.deleted_paths(&after);
        assert_eq!(deleted, vec![PathBuf::from("b")]);
    }

    // ── Indexer ────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct ConstantEmbedder;
    impl Embedder for ConstantEmbedder {
        fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
            Ok(texts.iter().map(|_| vec![0.0_f32; 8]).collect())
        }
    }

    #[derive(Default)]
    struct InMemStore {
        upserts: Mutex<Vec<StoredRecord>>,
        deletes: Mutex<Vec<String>>,
    }
    impl VectorStore for InMemStore {
        fn upsert(&self, recs: &[StoredRecord]) -> Result<()> {
            self.upserts.lock().extend(recs.iter().cloned());
            Ok(())
        }
        fn search(&self, _: &[f32], k: usize) -> Result<Vec<Hit>> {
            Ok(self
                .upserts
                .lock()
                .iter()
                .take(k)
                .map(|r| Hit {
                    file: r.file.clone(),
                    chunk_id: r.chunk_id,
                    text: r.text.clone(),
                    distance: 0.0,
                })
                .collect())
        }
        fn delete_by_file(&self, file: &str) -> Result<()> {
            self.deletes.lock().push(file.to_string());
            Ok(())
        }
        fn count(&self) -> Result<usize> {
            Ok(self.upserts.lock().len())
        }
    }

    #[test]
    fn reindex_incremental_upserts_changed_files() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(&p, "hello").unwrap();
        let f = FileRecord {
            path: p,
            label: "auto_memory".into(),
            mtime_secs: 1,
        };
        let emb = ConstantEmbedder;
        let store = InMemStore::default();
        let idx = Indexer::new(&emb, &store);
        let mut state = IndexState::default();
        let r = idx.reindex_incremental(&[f.clone()], &mut state).unwrap();
        assert_eq!(r.upserted, 1);
        assert_eq!(r.touched_files, 1);
        assert_eq!(store.count().unwrap(), 1);
    }

    #[test]
    fn reindex_incremental_skips_unchanged_files_on_second_run() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(&p, "hello").unwrap();
        let f = FileRecord {
            path: p,
            label: "auto_memory".into(),
            mtime_secs: 1,
        };
        let emb = ConstantEmbedder;
        let store = InMemStore::default();
        let idx = Indexer::new(&emb, &store);
        let mut state = IndexState::default();
        idx.reindex_incremental(&[f.clone()], &mut state).unwrap();
        let r = idx.reindex_incremental(&[f], &mut state).unwrap();
        assert_eq!(r.upserted, 0);
    }

    #[test]
    fn reindex_incremental_deletes_removed_files() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(&p, "hello").unwrap();
        let f = FileRecord {
            path: p,
            label: "auto_memory".into(),
            mtime_secs: 1,
        };
        let emb = ConstantEmbedder;
        let store = InMemStore::default();
        let idx = Indexer::new(&emb, &store);
        let mut state = IndexState::default();
        idx.reindex_incremental(&[f], &mut state).unwrap();
        let r = idx.reindex_incremental(&[], &mut state).unwrap();
        assert_eq!(r.deleted_files, 1);
        assert_eq!(store.deletes.lock().len(), 1);
    }

    #[test]
    fn retrieve_returns_top_k_hits() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(&p, "hello").unwrap();
        let f = FileRecord {
            path: p,
            label: "auto_memory".into(),
            mtime_secs: 1,
        };
        let emb = ConstantEmbedder;
        let store = InMemStore::default();
        let idx = Indexer::new(&emb, &store);
        let mut state = IndexState::default();
        idx.reindex_incremental(&[f], &mut state).unwrap();
        let hits = idx.retrieve("anything", 5).unwrap();
        assert_eq!(hits.len(), 1);
    }
}
