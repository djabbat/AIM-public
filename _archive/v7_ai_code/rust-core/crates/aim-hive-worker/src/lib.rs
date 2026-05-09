//! aim-hive-worker — AIM Hive worker side.
//!
//! Each AIM worker periodically packages an *anonymized* signal about
//! its operation and POSTs it to the queen for cross-worker
//! aggregation. The L_PRIVACY contract is enforced in two layers:
//!
//! 1. [`scrub`] — every string in the payload tree must NOT match any
//!    PII pattern (email, phone, file path, name, PMID, DOI). A match
//!    aborts the contribute call with an error.
//!
//! 2. [`aim_dp::DpAccountant::spend`] — every contribute call debits
//!    `eps_per_round` from a fixed ε-budget. When the budget is
//!    exhausted, the worker switches to *read-only*: pulls updates,
//!    stops sending.
//!
//! What the worker SENDS:
//! - aggregate counters (run count, retry rate, score)
//! - hashed prompt fingerprint (sha256, never body)
//! - reflexion theme labels (category words only)
//! - skill usage frequencies (skill_id + count, no body)
//! - eval pass/fail counts per case_id
//! - compliance metric (numeric)
//!
//! What the worker NEVER sends: phone, email, name, file path, project
//! name, patient data, prompt/response bodies, finding text.
//!
//! Public API:
//! - [`contribution`] — build the payload (read-only, applies scrub)
//! - [`preview`] — pretty-printed JSON, nothing transmitted
//! - [`contribute`] — build, scrub, DP-spend, POST
//!
//! Rust port of `AI/ai/hive_telemetry.py`.

pub mod scrub;
pub mod payload;
pub mod worker_id;

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub use payload::Payload;
pub use scrub::{scrub_value, ScrubError};
pub use worker_id::worker_id;

#[derive(Debug, Error)]
pub enum HiveError {
    #[error("L_PRIVACY blocked: {0}")]
    Privacy(#[from] ScrubError),

    #[error("DP budget: {0}")]
    Dp(#[from] aim_dp::DpError),

    #[error("transport: {0}")]
    Transport(#[from] reqwest::Error),

    #[error("queen rejected: status {status}, body {body}")]
    Queen { status: u16, body: String },

    #[error("config: {0}")]
    Config(String),

    #[error("io: {0}")]
    Io(#[from] std::io::Error),

    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

/// Outcome of [`contribute`].
#[derive(Debug, Serialize, Deserialize)]
pub struct ContributionResult {
    pub sent: bool,
    pub payload: serde_json::Value,
    pub queen_response: Option<serde_json::Value>,
    pub notes: Vec<String>,
}

/// Build the anonymized payload, ready for transport. Applies the
/// L_PRIVACY scrub before returning.
pub fn contribution(state_root: Option<&PathBuf>) -> Result<serde_json::Value, HiveError> {
    let p = payload::build(state_root)?;
    let v = serde_json::to_value(&p)?;
    let scrubbed = scrub::scrub_value(v)?;
    Ok(scrubbed)
}

/// Pretty-printed JSON of what would be sent. Nothing is transmitted.
pub fn preview(state_root: Option<&PathBuf>) -> Result<String, HiveError> {
    let v = contribution(state_root)?;
    Ok(serde_json::to_string_pretty(&v)?)
}

/// Options for [`contribute`].
#[derive(Debug, Default)]
pub struct ContributeOpts {
    /// If true, build + scrub but do not POST. Default false.
    pub dry_run: bool,
    /// Override the queen URL (defaults to `AIM_HIVE_QUEEN_URL`).
    pub queen_url: Option<String>,
    /// Override per-round ε cost (defaults to `aim_dp::default_eps_per_round`).
    pub eps_per_round: Option<f64>,
    /// Override AIM state root (where ledger DB and other state live).
    /// Defaults to `~/.aim/`.
    pub state_root: Option<PathBuf>,
}

/// Build → scrub → DP-spend → POST. Returns a [`ContributionResult`].
pub async fn contribute(opts: ContributeOpts) -> Result<ContributionResult, HiveError> {
    let mut notes = Vec::new();

    // 1. Build + scrub.
    let payload = match contribution(opts.state_root.as_ref()) {
        Ok(v) => v,
        Err(HiveError::Privacy(e)) => {
            return Ok(ContributionResult {
                sent: false,
                payload: serde_json::Value::Null,
                queen_response: None,
                notes: vec![format!("L_PRIVACY blocked: {e}")],
            });
        }
        Err(e) => return Err(e),
    };

    if opts.dry_run {
        notes.push("dry_run — not transmitted".to_string());
        return Ok(ContributionResult {
            sent: false,
            payload,
            queen_response: None,
            notes,
        });
    }

    // 2. DP gate.
    let mut acc = aim_dp::DpAccountant::from_env()?;
    let eps = opts.eps_per_round.unwrap_or_else(aim_dp::default_eps_per_round);
    if let Err(e) = acc.spend(eps) {
        notes.push(format!(
            "DP budget gate: {e}. Worker is now read-only (still pulls, no sends)."
        ));
        return Ok(ContributionResult {
            sent: false,
            payload,
            queen_response: None,
            notes,
        });
    }
    notes.push(format!(
        "DP: spent {:.4}, remaining {:.4} / {:.4}",
        eps,
        acc.remaining(),
        acc.budget()
    ));

    // 3. POST.
    let url = opts
        .queen_url
        .or_else(|| std::env::var("AIM_HIVE_QUEEN_URL").ok())
        .ok_or_else(|| HiveError::Config("AIM_HIVE_QUEEN_URL not set".to_string()))?;
    let endpoint = format!("{}/v1/hive/contribute", url.trim_end_matches('/'));

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;

    // Optional bearer token from AIM_USER_TOKEN.
    let mut req = client.post(&endpoint).json(&payload);
    if let Ok(tok) = std::env::var("AIM_USER_TOKEN") {
        req = req.bearer_auth(tok);
    }

    let resp = req.send().await?;
    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(HiveError::Queen {
            status: status.as_u16(),
            body,
        });
    }
    let body: serde_json::Value = resp.json().await?;
    Ok(ContributionResult {
        sent: true,
        payload,
        queen_response: Some(body),
        notes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn contribution_dry_does_not_panic_on_empty_state() {
        let v = contribution(Some(&std::env::temp_dir().join("aim-hive-test-empty")))
            .expect("empty state must produce a valid envelope");
        assert!(v.is_object());
        assert!(v.get("worker_id").is_some());
    }

    #[tokio::test]
    async fn contribute_dry_run_returns_payload_no_post() {
        let res = contribute(ContributeOpts {
            dry_run: true,
            state_root: Some(std::env::temp_dir().join("aim-hive-test-empty2")),
            ..Default::default()
        })
        .await
        .unwrap();
        assert!(!res.sent);
        assert!(res.payload.is_object());
        assert!(res.queen_response.is_none());
    }
}
