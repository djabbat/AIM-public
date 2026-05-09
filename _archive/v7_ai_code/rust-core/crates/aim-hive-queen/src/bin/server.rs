//! aim-hive-queen — Axum HTTP server.
//!
//! Endpoints (matching queen_app.py):
//!     GET  /healthz                 — health check (no auth)
//!     POST /v1/hive/contribute      — worker submits anonymized signal
//!     GET  /v1/hive/updates         — worker pulls eval-gated updates
//!     POST /v1/hive/distill         — admin trigger: scan + publish
//!     GET  /v1/hive/status          — queen state summary
//!
//! Auth: workers send `Authorization: Bearer <AIM_USER_TOKEN>` (validated
//! against the AIM hub via env-configured URL — see aim-common). Admin
//! endpoints require `Authorization: Bearer <AIM_HIVE_ADMIN_TOKEN>`.
//!
//! For the bootstrap migration, worker token validation is OPTIONAL —
//! if `AIM_HIVE_REQUIRE_AUTH=0` (default during transition), worker
//! endpoints accept anonymous traffic. Admin token is always required
//! for /distill and /status.

use std::sync::Arc;

use axum::{
    extract::{rejection::JsonRejection, DefaultBodyLimit, Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::json;
use tracing::{info, warn};

use aim_hive_queen::{
    accept_contribution, distill_candidates, list_contributions, list_updates, max_payload_bytes,
    publish_update, summary, HiveQueenError, QueenStore,
};

#[derive(Clone)]
struct AppState {
    store: Arc<QueenStore>,
    admin_token: Option<String>,
    /// If false, worker endpoints accept anonymous; if true, require Bearer.
    require_worker_auth: bool,
    /// Pre-computed SHA-256 hex hashes of accepted worker tokens.
    /// Empty = accept any non-empty bearer (legacy bootstrap).
    /// Populated from `AIM_HIVE_WORKER_TOKENS` env on startup.
    worker_token_hashes: Arc<Vec<String>>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".parse().unwrap()),
        )
        .init();

    let store = Arc::new(QueenStore::open_default()?);
    let admin_token = std::env::var("AIM_HIVE_ADMIN_TOKEN").ok();
    let require_worker_auth =
        std::env::var("AIM_HIVE_REQUIRE_AUTH").as_deref() == Ok("1");
    let worker_token_hashes = Arc::new(load_worker_token_hashes());

    if require_worker_auth && worker_token_hashes.is_empty() {
        warn!(
            "AIM_HIVE_REQUIRE_AUTH=1 but AIM_HIVE_WORKER_TOKENS empty — \
             will accept any non-empty bearer (legacy bootstrap)"
        );
    } else if !worker_token_hashes.is_empty() {
        info!(
            n_tokens = worker_token_hashes.len(),
            "loaded worker token allowlist"
        );
    }

    let state = AppState {
        store,
        admin_token,
        require_worker_auth,
        worker_token_hashes,
    };

    // P1.4: cap HTTP body size to prevent DoS via large payloads.
    // Defense in depth — accept_contribution() also checks at the lib
    // layer, but rejecting at the body-extractor is cheaper.
    let body_limit = max_payload_bytes();

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/v1/hive/contribute", post(contribute_route))
        .route("/v1/hive/updates", get(updates_route))
        .route("/v1/hive/distill", post(distill_route))
        .route("/v1/hive/status", get(status_route))
        .layer(DefaultBodyLimit::max(body_limit))
        .fallback(not_found)
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8090);
    let host = std::env::var("HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let listener = tokio::net::TcpListener::bind(format!("{host}:{port}")).await?;
    info!(%host, %port, "aim-hive-queen listening");
    axum::serve(listener, app).await?;
    Ok(())
}

// ── handlers ─────────────────────────────────────────────────────

async fn healthz() -> impl IntoResponse {
    Json(json!({
        "status": "ok",
        "ts": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
    }))
}

/// Canonical {"error","status"} 404 for unknown routes (P1.6 audit
/// 2026-05-07 — workers had to handle two error shapes).
async fn not_found() -> impl IntoResponse {
    (
        StatusCode::NOT_FOUND,
        Json(json!({"error": "not found", "status": 404})),
    )
}

async fn contribute_route(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Result<Json<serde_json::Value>, JsonRejection>,
) -> impl IntoResponse {
    if state.require_worker_auth {
        if let Err(r) = require_worker_bearer(&headers, &state) {
            return r.into_response();
        }
    }
    let payload = match body {
        Ok(Json(v)) => v,
        Err(rej) => {
            // Map axum extraction failures (bad JSON, body-too-large,
            // missing content-type) to the canonical {"error","status"}
            // shape. P1.6 audit 2026-05-07.
            let status = rej.status();
            return (
                status,
                Json(json!({
                    "error": format!("{rej}"),
                    "status": status.as_u16(),
                })),
            )
                .into_response();
        }
    };
    match accept_contribution(&state.store, payload) {
        Ok(Some(id)) => {
            info!(%id, "accepted contribution");
            (StatusCode::OK, Json(json!({"contribution_id": id}))).into_response()
        }
        Ok(None) => {
            warn!("rejected contribution");
            (
                StatusCode::BAD_REQUEST,
                Json(json!({"error":"payload rejected","status":400})),
            )
                .into_response()
        }
        Err(HiveQueenError::PayloadTooLarge { limit, actual }) => {
            warn!(actual, limit, "payload too large");
            (
                StatusCode::PAYLOAD_TOO_LARGE,
                Json(json!({
                    "error": "payload too large",
                    "status": 413,
                    "limit_bytes": limit,
                    "actual_bytes": actual,
                })),
            )
                .into_response()
        }
        Err(e) => {
            warn!(error = ?e, "store error on accept");
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error":format!("{e}"), "status":500})),
            )
                .into_response()
        }
    }
}

#[derive(Debug, Deserialize)]
struct UpdatesQuery {
    since: Option<String>,
}

async fn updates_route(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<UpdatesQuery>,
) -> impl IntoResponse {
    if state.require_worker_auth {
        if let Err(r) = require_worker_bearer(&headers, &state) {
            return r.into_response();
        }
    }
    match list_updates(&state.store, q.since.as_deref()) {
        Ok(rows) => Json(json!({"updates": rows})).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error":format!("{e}"), "status":500})),
        )
            .into_response(),
    }
}

async fn distill_route(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    if let Err(r) = require_admin_bearer(&headers, &state) {
        return r.into_response();
    }
    let cands = match distill_candidates(&state.store) {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error":format!("{e}"),"status":500})),
            )
                .into_response();
        }
    };
    let mut published = Vec::new();
    for c in cands.iter().cloned() {
        // Conservative auto-publish: only if ≥3 distinct workers supported.
        if c.source_n() >= 3 {
            if let Ok(Some(upd)) = publish_update(&state.store, c, true, None) {
                published.push(json!({
                    "id": upd.id,
                    "kind": upd.kind,
                    "source_n": upd.source_n,
                }));
            }
        }
    }
    Json(json!({
        "candidates_found": cands.len(),
        "auto_published": published.len(),
        "details": published,
    }))
    .into_response()
}

async fn status_route(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    if let Err(r) = require_admin_bearer(&headers, &state) {
        return r.into_response();
    }
    let summary_v = match summary(&state.store) {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error":format!("{e}"),"status":500})),
            )
                .into_response()
        }
    };
    let n_contribs = list_contributions(&state.store, 100000, None)
        .map(|v| v.len())
        .unwrap_or(0);
    let n_updates = list_updates(&state.store, None).map(|v| v.len()).unwrap_or(0);
    Json(json!({
        "queen_summary": summary_v,
        "n_contributions": n_contribs,
        "n_updates": n_updates,
        "ts": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
    }))
    .into_response()
}

// ── auth helpers ─────────────────────────────────────────────────

fn expected_admin(state: &AppState) -> Vec<String> {
    state
        .admin_token
        .as_ref()
        .map(|t| vec![t.clone()])
        .unwrap_or_default()
}

/// Parse `AIM_HIVE_WORKER_TOKENS` into a list of SHA-256 hex hashes.
/// Whitespace + blank lines + `#` comments are ignored. Each entry is
/// lowercased and validated to be 64 hex chars; invalid entries are
/// dropped with a warning. P1.7 audit 2026-05-07: replaces the
/// external auth backend (which crashed → 503 → no contributions).
fn load_worker_token_hashes() -> Vec<String> {
    let raw = match std::env::var("AIM_HIVE_WORKER_TOKENS") {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    let mut out = Vec::new();
    for line in raw.split(|c: char| c == '\n' || c == ',' || c == ';') {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let lower = trimmed.to_ascii_lowercase();
        if lower.len() == 64 && lower.chars().all(|c| c.is_ascii_hexdigit()) {
            out.push(lower);
        } else {
            warn!(
                token_prefix = &lower.chars().take(8).collect::<String>(),
                "ignoring malformed entry in AIM_HIVE_WORKER_TOKENS \
                 (expected 64-char SHA-256 hex)"
            );
        }
    }
    out
}

/// SHA-256 of the bearer string, hex-encoded, lowercase.
fn sha256_hex(s: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    hex::encode(h.finalize())
}

/// Validate the worker bearer for `require_worker_auth=true` mode.
/// Behaviour:
/// - No `Authorization` header → 401.
/// - Allowlist empty → accept any non-empty bearer (legacy bootstrap;
///   logged at startup).
/// - Allowlist non-empty → SHA-256 of token must match an entry.
fn require_worker_bearer(
    headers: &HeaderMap,
    state: &AppState,
) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    let auth = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    if !auth.starts_with("Bearer ") {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error":"missing bearer token","status":401})),
        ));
    }
    let raw = auth["Bearer ".len()..].trim();
    if raw.is_empty() {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error":"empty bearer token","status":401})),
        ));
    }
    if state.worker_token_hashes.is_empty() {
        return Ok(());
    }
    let h = sha256_hex(raw);
    if state.worker_token_hashes.iter().any(|expected| expected == &h) {
        Ok(())
    } else {
        Err((
            StatusCode::FORBIDDEN,
            Json(json!({"error":"bad worker token","status":403})),
        ))
    }
}

/// Admin bearer — must match `AIM_HIVE_ADMIN_TOKEN` exactly. If unset,
/// the queen replies 503 (configuration error) — never auto-grant.
fn require_admin_bearer(
    headers: &HeaderMap,
    state: &AppState,
) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    let expected = expected_admin(state);
    if expected.is_empty() {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"error":"admin token not configured","status":503})),
        ));
    }
    let auth = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    if !auth.starts_with("Bearer ") {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error":"missing admin token","status":401})),
        ));
    }
    let raw = auth["Bearer ".len()..].trim();
    if expected.iter().any(|t| t == raw) {
        Ok(())
    } else {
        Err((
            StatusCode::FORBIDDEN,
            Json(json!({"error":"bad admin token","status":403})),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set_env(key: &str, val: &str) {
        // Tests in this mod read AIM_HIVE_WORKER_TOKENS, so they're
        // serialized via #[serial_test::serial] semantics handled by
        // running with --test-threads=1 in CI; locally they're fine
        // because each test sets the env explicitly before reading.
        std::env::set_var(key, val);
    }

    #[test]
    fn load_worker_token_hashes_skips_blanks_and_comments() {
        let h1 = sha256_hex("alpha");
        let h2 = sha256_hex("beta");
        set_env(
            "AIM_HIVE_WORKER_TOKENS",
            &format!("\n{h1}\n# comment line\n\n{h2}\n"),
        );
        let v = load_worker_token_hashes();
        assert_eq!(v.len(), 2);
        assert!(v.contains(&h1));
        assert!(v.contains(&h2));
        std::env::remove_var("AIM_HIVE_WORKER_TOKENS");
    }

    #[test]
    fn load_worker_token_hashes_drops_malformed_entries() {
        let h1 = sha256_hex("good");
        // 64 hex chars = valid; "deadbeef" is too short.
        set_env(
            "AIM_HIVE_WORKER_TOKENS",
            &format!("{h1}\ndeadbeef\nnot-a-hash-at-all"),
        );
        let v = load_worker_token_hashes();
        assert_eq!(v, vec![h1]);
        std::env::remove_var("AIM_HIVE_WORKER_TOKENS");
    }

    #[test]
    fn load_worker_token_hashes_supports_csv_separator() {
        let h1 = sha256_hex("one");
        let h2 = sha256_hex("two");
        set_env("AIM_HIVE_WORKER_TOKENS", &format!("{h1},{h2}"));
        let v = load_worker_token_hashes();
        assert_eq!(v.len(), 2);
        std::env::remove_var("AIM_HIVE_WORKER_TOKENS");
    }

    #[test]
    fn sha256_hex_is_64_chars_and_lowercase() {
        let h = sha256_hex("test");
        assert_eq!(h.len(), 64);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit() && !c.is_uppercase()));
    }

    fn state_with(tokens: Vec<String>, require: bool) -> AppState {
        let dir = tempfile::tempdir().unwrap();
        let store = Arc::new(QueenStore::open(dir.path().join("q.db")).unwrap());
        // Leak the tempdir guard — test process is short-lived.
        std::mem::forget(dir);
        AppState {
            store,
            admin_token: Some("admin-secret".to_string()),
            require_worker_auth: require,
            worker_token_hashes: Arc::new(tokens),
        }
    }

    fn headers_with_bearer(tok: &str) -> HeaderMap {
        let mut h = HeaderMap::new();
        h.insert(
            axum::http::header::AUTHORIZATION,
            format!("Bearer {tok}").parse().unwrap(),
        );
        h
    }

    #[test]
    fn worker_bearer_required_missing_header() {
        let st = state_with(vec![], true);
        let h = HeaderMap::new();
        let r = require_worker_bearer(&h, &st);
        assert!(matches!(r, Err((StatusCode::UNAUTHORIZED, _))));
    }

    #[test]
    fn worker_bearer_legacy_mode_accepts_any_nonempty() {
        // Empty allowlist + require=true → bootstrap mode: any non-empty
        // bearer accepted.
        let st = state_with(vec![], true);
        let h = headers_with_bearer("anything");
        assert!(require_worker_bearer(&h, &st).is_ok());
    }

    #[test]
    fn worker_bearer_legacy_mode_rejects_empty() {
        let st = state_with(vec![], true);
        let h = headers_with_bearer("");
        let r = require_worker_bearer(&h, &st);
        assert!(matches!(r, Err((StatusCode::UNAUTHORIZED, _))));
    }

    #[test]
    fn worker_bearer_allowlist_accepts_match() {
        let raw = "secret-worker-token-42";
        let st = state_with(vec![sha256_hex(raw)], true);
        let h = headers_with_bearer(raw);
        assert!(require_worker_bearer(&h, &st).is_ok());
    }

    #[test]
    fn worker_bearer_allowlist_rejects_unknown() {
        let raw = "secret-worker-token-42";
        let st = state_with(vec![sha256_hex(raw)], true);
        let h = headers_with_bearer("wrong-token");
        let r = require_worker_bearer(&h, &st);
        assert!(matches!(r, Err((StatusCode::FORBIDDEN, _))));
    }

    #[test]
    fn admin_bearer_503_when_unconfigured() {
        let dir = tempfile::tempdir().unwrap();
        let store = Arc::new(QueenStore::open(dir.path().join("q.db")).unwrap());
        std::mem::forget(dir);
        let st = AppState {
            store,
            admin_token: None,
            require_worker_auth: false,
            worker_token_hashes: Arc::new(vec![]),
        };
        let h = headers_with_bearer("doesnt-matter");
        let r = require_admin_bearer(&h, &st);
        assert!(matches!(r, Err((StatusCode::SERVICE_UNAVAILABLE, _))));
    }

    #[test]
    fn admin_bearer_accepts_correct_token() {
        let st = state_with(vec![], false);
        let h = headers_with_bearer("admin-secret");
        assert!(require_admin_bearer(&h, &st).is_ok());
    }

    #[test]
    fn admin_bearer_rejects_wrong_token() {
        let st = state_with(vec![], false);
        let h = headers_with_bearer("not-the-admin");
        let r = require_admin_bearer(&h, &st);
        assert!(matches!(r, Err((StatusCode::FORBIDDEN, _))));
    }
}
