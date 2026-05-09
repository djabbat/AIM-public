//! aim-hive-queen — bee-and-queen aggregator.
//!
//! Workers POST anonymized contributions; queen stores them, distills
//! cross-worker patterns into candidate updates, gates each candidate
//! through an eval suite, publishes approved updates back to a feed
//! workers pull from.
//!
//! This is the core library. The binary `aim-hive-queen` (in `bin/`)
//! wraps it in an Axum HTTP server matching `queen_app.py` endpoints.
//!
//! Rust port of `AI/ai/hive_queen.py`.

pub mod store;
pub mod distill;

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use thiserror::Error;

pub use store::{QueenStore, QueenError};

/// Default upper bound for the serialized JSON payload accepted from
/// a worker. Set in 2026-05-07 audit (DoS mitigation). Override via
/// `AIM_HIVE_MAX_PAYLOAD_BYTES`.
pub const MAX_PAYLOAD_BYTES_DEFAULT: usize = 1_048_576; // 1 MiB

/// Effective payload-size cap for the current process.
pub fn max_payload_bytes() -> usize {
    std::env::var("AIM_HIVE_MAX_PAYLOAD_BYTES")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .map(|n| n.max(1024)) // never less than 1 KiB
        .unwrap_or(MAX_PAYLOAD_BYTES_DEFAULT)
}

#[derive(Debug, Error)]
pub enum HiveQueenError {
    #[error("store: {0}")]
    Store(#[from] QueenError),
    #[error("rejected: {0}")]
    Rejected(String),
    #[error("payload too large: {actual} > {limit} bytes")]
    PayloadTooLarge { limit: usize, actual: usize },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contribution {
    pub id: String,
    pub ts: String,
    pub worker_id: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Candidate {
    /// "skill" | "prompt_patch" | "eval_case"
    pub kind: String,
    pub body: serde_json::Value,
    /// Workers whose payloads supported this candidate.
    pub source_workers: BTreeSet<String>,
    pub rationale: String,
}

impl Candidate {
    pub fn source_n(&self) -> usize {
        self.source_workers.len()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Update {
    pub id: String,
    pub ts: String,
    pub kind: String,
    pub body: serde_json::Value,
    pub source_n: u32,
    pub eval_delta: Option<f64>,
    pub signature: String,
}

/// Validate + persist a worker contribution. Returns the new ID,
/// or `None` if the payload was rejected.
pub fn accept_contribution(
    store: &QueenStore,
    payload: serde_json::Value,
) -> Result<Option<String>, HiveQueenError> {
    if !payload.is_object() {
        tracing::warn!("rejected non-object payload");
        return Ok(None);
    }
    if payload.get("v").and_then(|v| v.as_u64()) != Some(1) {
        tracing::warn!(v = ?payload.get("v"), "rejected payload with bad v");
        return Ok(None);
    }
    let worker_id = match payload.get("worker_id").and_then(|w| w.as_str()) {
        Some(w) if w.len() >= 8 => w.to_string(),
        _ => {
            tracing::warn!("rejected payload with missing/short worker_id");
            return Ok(None);
        }
    };
    let id = uuid::Uuid::new_v4().to_string();
    let ts = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
    let blob = serde_json::to_string(&payload).expect("payload serialises");
    let limit = max_payload_bytes();
    if blob.len() > limit {
        tracing::warn!(actual = blob.len(), limit, "rejected oversize payload");
        return Err(HiveQueenError::PayloadTooLarge {
            limit,
            actual: blob.len(),
        });
    }
    store.insert_contribution(&id, &ts, &worker_id, &blob)?;
    Ok(Some(id))
}

pub fn list_contributions(
    store: &QueenStore,
    limit: i64,
    worker_id: Option<&str>,
) -> Result<Vec<Contribution>, HiveQueenError> {
    Ok(store.list_contributions(limit, worker_id)?)
}

pub fn distill_candidates(store: &QueenStore) -> Result<Vec<Candidate>, HiveQueenError> {
    let contribs = list_contributions(store, 1000, None)?;
    Ok(distill::distill(&contribs))
}

/// Convert a candidate into a published update. The eval gate is the
/// caller's responsibility — pass `eval_pass=false` to refuse.
pub fn publish_update(
    store: &QueenStore,
    candidate: Candidate,
    eval_pass: bool,
    eval_delta: Option<f64>,
) -> Result<Option<Update>, HiveQueenError> {
    if !eval_pass {
        tracing::info!(kind = %candidate.kind, "eval gate refused candidate");
        return Ok(None);
    }
    let id = uuid::Uuid::new_v4().to_string();
    let ts = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
    let body_blob = serde_json::to_string(&candidate.body).expect("serialise");
    let sig = signature(&candidate.body);
    let source_n = candidate.source_n() as u32;
    store.insert_update(
        &id,
        &ts,
        &candidate.kind,
        &body_blob,
        source_n,
        eval_delta,
        &sig,
    )?;
    Ok(Some(Update {
        id,
        ts,
        kind: candidate.kind,
        body: candidate.body,
        source_n,
        eval_delta,
        signature: sig,
    }))
}

pub fn list_updates(
    store: &QueenStore,
    since: Option<&str>,
) -> Result<Vec<Update>, HiveQueenError> {
    Ok(store.list_updates(since)?)
}

pub fn summary(store: &QueenStore) -> Result<serde_json::Value, HiveQueenError> {
    let n_contribs = store.count_contributions()?;
    let n_updates = list_updates(store, None)?.len();
    let cands = distill_candidates(store)?;
    Ok(serde_json::json!({
        "n_contributions": n_contribs,
        "n_updates": n_updates,
        "candidates_pending": cands.len(),
        "candidate_kinds": cands.iter().map(|c| c.kind.clone()).collect::<Vec<_>>(),
    }))
}

fn signature(body: &serde_json::Value) -> String {
    use sha2::Digest;
    let blob = serde_json::to_string(body).expect("body serialises");
    let mut h = sha2::Sha256::new();
    h.update(blob.as_bytes());
    let digest = h.finalize();
    hex::encode(&digest[..12]) // 24 hex chars to match Python's [:24]
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh_store() -> (tempfile::TempDir, QueenStore) {
        let d = tempdir().unwrap();
        let s = QueenStore::open(d.path().join("queen.db")).unwrap();
        (d, s)
    }

    #[test]
    fn accept_rejects_non_object() {
        let (_d, s) = fresh_store();
        let r = accept_contribution(&s, serde_json::json!([1, 2])).unwrap();
        assert!(r.is_none());
    }

    #[test]
    fn accept_rejects_bad_version() {
        let (_d, s) = fresh_store();
        let r = accept_contribution(&s, serde_json::json!({"v": 0, "worker_id":"a".repeat(16)}))
            .unwrap();
        assert!(r.is_none());
    }

    #[test]
    fn accept_rejects_short_worker_id() {
        let (_d, s) = fresh_store();
        let r = accept_contribution(&s, serde_json::json!({"v":1, "worker_id":"abc"})).unwrap();
        assert!(r.is_none());
    }

    #[test]
    fn accept_returns_id_for_valid() {
        let (_d, s) = fresh_store();
        let p = serde_json::json!({"v":1, "worker_id":"a".repeat(16)});
        let r = accept_contribution(&s, p).unwrap();
        assert!(r.is_some());
        assert!(uuid::Uuid::parse_str(&r.unwrap()).is_ok());
    }

    #[test]
    fn list_contributions_round_trip() {
        let (_d, s) = fresh_store();
        let p = serde_json::json!({
            "v":1,
            "worker_id":"a".repeat(16),
            "ledger":{"n_runs":5,"avg_compliance":0.4}
        });
        accept_contribution(&s, p).unwrap();
        let rows = list_contributions(&s, 10, None).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].payload["ledger"]["n_runs"].as_u64(), Some(5));
    }

    #[test]
    fn publish_refuses_when_eval_fails() {
        let (_d, s) = fresh_store();
        let c = Candidate {
            kind: "skill".to_string(),
            body: serde_json::json!({"x":1}),
            source_workers: ["w1".to_string()].into_iter().collect(),
            rationale: "test".to_string(),
        };
        let r = publish_update(&s, c, false, None).unwrap();
        assert!(r.is_none());
    }

    #[test]
    fn publish_accepts_when_eval_passes() {
        let (_d, s) = fresh_store();
        let c = Candidate {
            kind: "skill".to_string(),
            body: serde_json::json!({"x":1}),
            source_workers: ["w1".to_string(), "w2".to_string()].into_iter().collect(),
            rationale: "test".to_string(),
        };
        let r = publish_update(&s, c, true, Some(0.07)).unwrap().unwrap();
        assert_eq!(r.kind, "skill");
        assert_eq!(r.source_n, 2);
        assert_eq!(r.signature.len(), 24);
        // List sees it
        let updates = list_updates(&s, None).unwrap();
        assert_eq!(updates.len(), 1);
        assert_eq!(updates[0].id, r.id);
    }

    #[test]
    fn signature_is_deterministic() {
        let body = serde_json::json!({"a":1,"b":[1,2,3]});
        let a = signature(&body);
        let b = signature(&body);
        assert_eq!(a, b);
        assert_eq!(a.len(), 24);
    }

    #[test]
    fn accept_rejects_oversized_payload() {
        let (_d, s) = fresh_store();
        // 2 MiB random-ish blob, well above the 1 MiB default.
        let big = "x".repeat(2 * 1024 * 1024);
        let p = serde_json::json!({
            "v": 1,
            "worker_id": "a".repeat(16),
            "blob": big,
        });
        let r = accept_contribution(&s, p);
        match r {
            Err(HiveQueenError::PayloadTooLarge { limit, actual }) => {
                assert_eq!(limit, MAX_PAYLOAD_BYTES_DEFAULT);
                assert!(actual > limit);
            }
            other => panic!("expected PayloadTooLarge, got {other:?}"),
        }
    }

    #[test]
    fn accept_passes_payload_just_under_cap() {
        let (_d, s) = fresh_store();
        // 600 KiB — well under 1 MiB cap.
        let p = serde_json::json!({
            "v": 1,
            "worker_id": "a".repeat(16),
            "blob": "x".repeat(600 * 1024),
        });
        let r = accept_contribution(&s, p).unwrap();
        assert!(r.is_some());
    }

    #[test]
    fn max_payload_bytes_default_is_1mib() {
        std::env::remove_var("AIM_HIVE_MAX_PAYLOAD_BYTES");
        assert_eq!(max_payload_bytes(), MAX_PAYLOAD_BYTES_DEFAULT);
        assert_eq!(MAX_PAYLOAD_BYTES_DEFAULT, 1_048_576);
    }

    #[test]
    fn summary_reports_counts() {
        let (_d, s) = fresh_store();
        for _ in 0..3 {
            accept_contribution(
                &s,
                serde_json::json!({"v":1,"worker_id":"a".repeat(16)}),
            )
            .unwrap();
        }
        let v = summary(&s).unwrap();
        assert_eq!(v["n_contributions"].as_u64(), Some(3));
    }
}
