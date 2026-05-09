//! aim-async-reindex — concurrent batched memory reindex orchestrator.
//!
//! Port of `agents/async_reindex.py`. The Python version owns the
//! ThreadPoolExecutor + lancedb table writes; here we keep just the
//! deterministic batching + dispatch logic, which is the part worth
//! testing. Two pluggable traits:
//!
//! * [`Encoder`] — accepts a batch of texts, returns vectors. The
//!   `DaemonFirstEncoder` tries the daemon first and falls back to a
//!   secondary encoder on failure (mirrors the Python `_encode_batch`).
//! * [`IndexSink`] — receives encoded records and writes them to the
//!   underlying table (lancedb in prod, in-memory in tests).
//!
//! Concurrency lives in the binary; this crate uses sequential batches
//! so unit tests are deterministic. The data model and the
//! daemon-then-fallback selection logic are identical to Python's.

use std::sync::Arc;
use std::time::Instant;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

// ── records ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ChunkRecord {
    pub file: String,
    pub chunk_id: String,
    pub text: String,
    #[serde(default)]
    pub vector: Vec<f32>,
}

// ── encoder traits ─────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum EncodeError {
    #[error("encoder offline")]
    Offline,
    #[error("encode failed: {0}")]
    Failed(String),
}

pub trait Encoder: Send + Sync {
    fn encode(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, EncodeError>;
}

/// Tries `daemon` first; on `Offline` or `Failed` falls back to `local`.
/// The Python module does the same, swallowing daemon errors and
/// falling back to the in-process model.
pub struct DaemonFirstEncoder<'a> {
    pub daemon: &'a dyn Encoder,
    pub local: &'a dyn Encoder,
}

impl<'a> Encoder for DaemonFirstEncoder<'a> {
    fn encode(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, EncodeError> {
        match self.daemon.encode(texts) {
            Ok(v) => Ok(v),
            Err(_) => self.local.encode(texts),
        }
    }
}

// ── index sink ─────────────────────────────────────────────────────────────

pub trait IndexSink: Send + Sync {
    /// Drop the existing table and replace it with `records`. Mirrors
    /// the Python `db.drop_table(...)` + `db.create_table(..., data=...)`.
    fn replace(&self, records: &[ChunkRecord]) -> Result<(), String>;
}

#[derive(Default)]
pub struct InMemSink {
    pub last: Mutex<Vec<ChunkRecord>>,
    pub fail: Mutex<bool>,
}

impl InMemSink {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set_fail(&self, v: bool) {
        *self.fail.lock() = v;
    }
    pub fn snapshot(&self) -> Vec<ChunkRecord> {
        self.last.lock().clone()
    }
}

impl IndexSink for InMemSink {
    fn replace(&self, records: &[ChunkRecord]) -> Result<(), String> {
        if *self.fail.lock() {
            return Err("forced sink failure".into());
        }
        *self.last.lock() = records.to_vec();
        Ok(())
    }
}

// ── batching + dispatch ────────────────────────────────────────────────────

pub fn batch_records<'a>(records: &'a [ChunkRecord], batch_size: usize) -> Vec<&'a [ChunkRecord]> {
    if records.is_empty() {
        return vec![];
    }
    let bs = batch_size.max(1);
    let mut out = Vec::new();
    let mut i = 0;
    while i < records.len() {
        let end = (i + bs).min(records.len());
        out.push(&records[i..end]);
        i = end;
    }
    out
}

pub fn encode_batch(
    batch: &[ChunkRecord],
    encoder: &dyn Encoder,
) -> Result<Vec<ChunkRecord>, EncodeError> {
    let texts: Vec<String> = batch.iter().map(|r| r.text.clone()).collect();
    let vecs = encoder.encode(&texts)?;
    if vecs.len() != batch.len() {
        return Err(EncodeError::Failed(format!(
            "expected {} vectors, got {}",
            batch.len(),
            vecs.len()
        )));
    }
    let mut out = Vec::with_capacity(batch.len());
    for (r, v) in batch.iter().zip(vecs.into_iter()) {
        let mut rec = r.clone();
        rec.vector = v;
        out.push(rec);
    }
    Ok(out)
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ReindexReport {
    pub files: usize,
    pub chunks: usize,
    pub batches: usize,
    pub elapsed_ms: u128,
    pub failed_batches: usize,
}

pub fn reindex(
    records: &[ChunkRecord],
    encoder: &dyn Encoder,
    sink: &dyn IndexSink,
    batch_size: usize,
) -> Result<ReindexReport, String> {
    let start = Instant::now();
    if records.is_empty() {
        return Ok(ReindexReport::default());
    }
    let batches = batch_records(records, batch_size);
    let mut encoded: Vec<ChunkRecord> = Vec::with_capacity(records.len());
    let mut failed = 0usize;
    for batch in &batches {
        match encode_batch(batch, encoder) {
            Ok(mut v) => encoded.append(&mut v),
            Err(_) => {
                failed += 1;
            }
        }
    }
    sink.replace(&encoded)?;
    let files: std::collections::BTreeSet<&str> =
        encoded.iter().map(|r| r.file.as_str()).collect();
    Ok(ReindexReport {
        files: files.len(),
        chunks: encoded.len(),
        batches: batches.len(),
        elapsed_ms: start.elapsed().as_millis(),
        failed_batches: failed,
    })
}

// ── reusable test stubs ────────────────────────────────────────────────────

/// Deterministic hashing encoder for tests. Each text gets a 4-dim vec
/// derived from its bytes — repeatable, no model required.
pub struct StubEncoder {
    pub dim: usize,
}

impl StubEncoder {
    pub fn new(dim: usize) -> Self {
        Self { dim }
    }
}

impl Encoder for StubEncoder {
    fn encode(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, EncodeError> {
        let mut out = Vec::with_capacity(texts.len());
        for t in texts {
            let mut v = vec![0.0f32; self.dim];
            for (i, b) in t.bytes().enumerate() {
                v[i % self.dim] += (b as f32) / 256.0;
            }
            out.push(v);
        }
        Ok(out)
    }
}

pub struct OfflineEncoder;
impl Encoder for OfflineEncoder {
    fn encode(&self, _: &[String]) -> Result<Vec<Vec<f32>>, EncodeError> {
        Err(EncodeError::Offline)
    }
}

pub struct CountingEncoder {
    pub inner: Arc<dyn Encoder>,
    pub calls: Arc<Mutex<usize>>,
    pub total_texts: Arc<Mutex<usize>>,
}

impl CountingEncoder {
    pub fn wrap(inner: Arc<dyn Encoder>) -> Self {
        Self {
            inner,
            calls: Arc::new(Mutex::new(0)),
            total_texts: Arc::new(Mutex::new(0)),
        }
    }
}

impl Encoder for CountingEncoder {
    fn encode(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, EncodeError> {
        *self.calls.lock() += 1;
        *self.total_texts.lock() += texts.len();
        self.inner.encode(texts)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rec(file: &str, id: &str, text: &str) -> ChunkRecord {
        ChunkRecord {
            file: file.into(),
            chunk_id: id.into(),
            text: text.into(),
            vector: vec![],
        }
    }

    fn corpus(n: usize) -> Vec<ChunkRecord> {
        (0..n)
            .map(|i| rec(&format!("f{}.md", i / 3), &format!("c{}", i), &format!("text {}", i)))
            .collect()
    }

    // ── batch_records ──────────────────────────────────────────────────────

    #[test]
    fn batches_align_with_batch_size() {
        let rs = corpus(10);
        let bs = batch_records(&rs, 4);
        assert_eq!(bs.len(), 3);
        assert_eq!(bs[0].len(), 4);
        assert_eq!(bs[1].len(), 4);
        assert_eq!(bs[2].len(), 2);
    }

    #[test]
    fn batches_zero_size_treated_as_one() {
        let rs = corpus(3);
        let bs = batch_records(&rs, 0);
        assert_eq!(bs.len(), 3);
        assert_eq!(bs[0].len(), 1);
    }

    #[test]
    fn batches_empty_input() {
        let rs: Vec<ChunkRecord> = vec![];
        let bs = batch_records(&rs, 8);
        assert!(bs.is_empty());
    }

    // ── encode_batch ───────────────────────────────────────────────────────

    #[test]
    fn encode_batch_attaches_vectors() {
        let e = StubEncoder::new(4);
        let rs = corpus(3);
        let out = encode_batch(&rs, &e).unwrap();
        assert_eq!(out.len(), 3);
        for r in &out {
            assert_eq!(r.vector.len(), 4);
        }
    }

    #[test]
    fn encode_batch_offline_propagates() {
        let e = OfflineEncoder;
        let rs = corpus(2);
        let err = encode_batch(&rs, &e).unwrap_err();
        assert!(matches!(err, EncodeError::Offline));
    }

    // ── DaemonFirstEncoder ────────────────────────────────────────────────

    #[test]
    fn daemon_first_uses_daemon_when_up() {
        let daemon = StubEncoder::new(4);
        let local = StubEncoder::new(8); // different dim — proves it wasn't used
        let e = DaemonFirstEncoder {
            daemon: &daemon,
            local: &local,
        };
        let v = e.encode(&["x".into()]).unwrap();
        assert_eq!(v[0].len(), 4);
    }

    #[test]
    fn daemon_first_falls_back_when_offline() {
        let daemon = OfflineEncoder;
        let local = StubEncoder::new(8);
        let e = DaemonFirstEncoder {
            daemon: &daemon,
            local: &local,
        };
        let v = e.encode(&["x".into()]).unwrap();
        assert_eq!(v[0].len(), 8);
    }

    // ── reindex ───────────────────────────────────────────────────────────

    #[test]
    fn reindex_writes_all_records_to_sink() {
        let rs = corpus(7);
        let e = StubEncoder::new(4);
        let sink = InMemSink::new();
        let r = reindex(&rs, &e, &sink, 3).unwrap();
        assert_eq!(r.chunks, 7);
        assert_eq!(r.batches, 3); // 3+3+1
        // 3 unique files: f0 (i=0,1,2), f1 (i=3,4,5), f2 (i=6)
        assert_eq!(r.files, 3);
        assert_eq!(sink.snapshot().len(), 7);
    }

    #[test]
    fn reindex_empty_short_circuits() {
        let e = StubEncoder::new(4);
        let sink = InMemSink::new();
        let r = reindex(&[], &e, &sink, 8).unwrap();
        assert_eq!(r.chunks, 0);
        assert_eq!(r.batches, 0);
        assert!(sink.snapshot().is_empty());
    }

    #[test]
    fn reindex_records_failed_batches() {
        let rs = corpus(5);
        let e = OfflineEncoder;
        let sink = InMemSink::new();
        let r = reindex(&rs, &e, &sink, 2).unwrap();
        assert_eq!(r.failed_batches, 3);
        assert_eq!(r.chunks, 0);
    }

    #[test]
    fn reindex_propagates_sink_error() {
        let rs = corpus(2);
        let e = StubEncoder::new(4);
        let sink = InMemSink::new();
        sink.set_fail(true);
        let err = reindex(&rs, &e, &sink, 2).unwrap_err();
        assert!(err.contains("forced"));
    }

    #[test]
    fn reindex_batch_size_drives_batch_count() {
        let rs = corpus(8);
        let e = StubEncoder::new(4);
        let sink = InMemSink::new();
        let counter = CountingEncoder::wrap(Arc::new(StubEncoder::new(4)));
        let calls_handle = counter.calls.clone();
        let r = reindex(&rs, &counter, &sink, 4).unwrap();
        let _ = e; // stub above unused; avoid warnings
        assert_eq!(r.batches, 2);
        assert_eq!(*calls_handle.lock(), 2);
    }
}
