//! aim-fs-http — Axum REST wrapper around AIM_FS for non-Phoenix clients.
//!
//! Endpoints (all JSON in/out, Bearer-token auth):
//!
//!   POST /v1/propose
//!   POST /v1/approve            { tenant_id, proposal_id, actor }
//!   POST /v1/reject             { tenant_id, proposal_id, actor, reason? }
//!   GET  /v1/inbox?tenant_id&limit
//!   POST /v1/search             { tenant_id, query, scope?, limit? }
//!   GET  /v1/projects?user_id
//!   GET  /v1/patients?doctor_id
//!   GET  /v1/disputes?tenant_id
//!   POST /v1/disputes/resolve   { tenant_id, winner_id, loser_id, actor }
//!   POST /v1/links/add          { tenant_id, source_id, target_id, link_type }
//!   GET  /v1/links/outgoing?tenant_id&source_id
//!   POST /v1/sweep
//!   GET  /healthz
//!
//! Auth: every non-/healthz request must carry `Authorization: Bearer <token>`
//! where token matches `AIM_FS_HTTP_TOKEN` env (must be set; refuse to start
//! without it).
//!
//! Defaults: bind 127.0.0.1:8770; override with `--bind 0.0.0.0:8770`.
//!
//! Native systemd, no Docker (per AIM `feedback_no_docker`):
//!   ExecStart=/usr/local/bin/aim-fs-http
//!   Environment=AIM_FS_HTTP_TOKEN=<32-hex>
//!   Environment=AIM_FS_ROOT=%h/.aim_fs
use aim_fs::search::SearchScope;
use aim_fs::{Actor, AimFs, ApprovalPolicy, LinkType, NewEntity};
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::Value;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

#[derive(Clone)]
struct AppState {
    fs: Arc<AimFs>,
    token: Arc<String>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut bind = "127.0.0.1:8770".to_string();
    let mut aim_root: Option<PathBuf> = None;
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!(
                    "aim-fs-http [--bind 127.0.0.1:8770] [--aim-root <path>]\n\
                     Required env: AIM_FS_HTTP_TOKEN"
                );
                return Ok(());
            }
            "--bind" => {
                bind = argv[i + 1].clone();
                i += 2;
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }
    let aim_root = aim_root
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .or_else(|| {
            std::env::var("HOME")
                .ok()
                .map(|h| PathBuf::from(h).join(".aim_fs"))
        })
        .ok_or_else(|| anyhow::anyhow!("AIM_FS_ROOT required"))?;
    let token = std::env::var("AIM_FS_HTTP_TOKEN")
        .map_err(|_| anyhow::anyhow!("AIM_FS_HTTP_TOKEN env var required (refusing to start)"))?;
    if token.len() < 16 {
        anyhow::bail!("AIM_FS_HTTP_TOKEN too short — use ≥ 16 chars");
    }

    let fs = Arc::new(AimFs::open(&aim_root)?);
    let state = AppState {
        fs,
        token: Arc::new(token),
    };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/v1/propose", post(propose))
        .route("/v1/approve", post(approve))
        .route("/v1/reject", post(reject))
        .route("/v1/inbox", get(inbox))
        .route("/v1/search", post(search))
        .route("/v1/projects", get(projects))
        .route("/v1/patients", get(patients))
        .route("/v1/disputes", get(disputes))
        .route("/v1/disputes/resolve", post(resolve_dispute))
        .route("/v1/links/add", post(add_link))
        .route("/v1/links/outgoing", get(outgoing_links))
        .route("/v1/sweep", post(sweep))
        .with_state(state);

    let addr: SocketAddr = bind.parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    println!("aim-fs-http listening on {}", addr);
    axum::serve(listener, app).await?;
    Ok(())
}

/// Authorisation: accepts either
///   1. legacy shared Bearer token (== `AIM_FS_HTTP_TOKEN` env), OR
///   2. HS256 JWT issued by `aim-fs-jwt` (signed with `AIM_FS_JWT_SECRET`).
///
/// Returns the validated tenant_id when JWT auth is used (so the handler
/// can cross-check it against the request body's `tenant_id` field), or
/// `None` for legacy shared-token mode.
///
/// Phase B Hub-mode H.1.  RS256 + per-tenant scope enforcement is the
/// next step (see `HUB_MODE.md` §3.1).
fn check_auth(headers: &HeaderMap, expected: &str) -> Result<Option<String>, StatusCode> {
    let auth = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    let tok = match auth.strip_prefix("Bearer ") {
        Some(t) => t,
        None => return Err(StatusCode::UNAUTHORIZED),
    };
    // Legacy shared-token path.
    if subtle_eq(tok.as_bytes(), expected.as_bytes()) {
        return Ok(None);
    }
    // JWT path — try to verify against AIM_FS_JWT_SECRET.
    if let Some(tenant) = verify_jwt(tok) {
        return Ok(Some(tenant));
    }
    Err(StatusCode::UNAUTHORIZED)
}

#[cfg(feature = "http")]
fn verify_jwt(token: &str) -> Option<String> {
    let secret = std::env::var("AIM_FS_JWT_SECRET").ok()?;
    let secret_bytes = hex::decode(secret.trim()).ok()?;
    use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
    #[derive(serde::Deserialize)]
    struct Claims {
        sub: String,
    }
    let mut validation = Validation::new(Algorithm::HS256);
    validation.set_issuer(&["aim-fs-jwt"]);
    decode::<Claims>(token, &DecodingKey::from_secret(&secret_bytes), &validation)
        .ok()
        .map(|d| d.claims.sub)
}

#[cfg(not(feature = "http"))]
fn verify_jwt(_: &str) -> Option<String> {
    None
}

fn subtle_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for i in 0..a.len() {
        diff |= a[i] ^ b[i];
    }
    diff == 0
}

async fn healthz() -> &'static str {
    "ok"
}

#[derive(Deserialize)]
struct ProposeBody {
    tenant_id: String,
    new: NewEntity,
    rationale: Option<String>,
    idempotency_key: Option<String>,
    policy: ApprovalPolicy,
}

async fn propose(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ProposeBody>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.propose(
        &body.tenant_id,
        body.new,
        body.rationale.as_deref(),
        body.idempotency_key.as_deref(),
        &body.policy,
    )
    .map(|v| Json(serde_json::to_value(v).unwrap()))
    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct ApproveBody {
    tenant_id: String,
    proposal_id: String,
    actor: Actor,
}

async fn approve(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ApproveBody>,
) -> Result<&'static str, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.approve_proposal(&body.tenant_id, &body.proposal_id, &body.actor)
        .map(|_| "ok")
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct RejectBody {
    tenant_id: String,
    proposal_id: String,
    actor: Actor,
    reason: Option<String>,
}

async fn reject(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<RejectBody>,
) -> Result<&'static str, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.reject_proposal(
        &body.tenant_id,
        &body.proposal_id,
        &body.actor,
        body.reason.as_deref(),
    )
    .map(|_| "ok")
    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct InboxQuery {
    tenant_id: String,
    limit: Option<i64>,
}
async fn inbox(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<InboxQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.list_pending(&q.tenant_id, q.limit.unwrap_or(50))
        .map(|v| Json(serde_json::to_value(v).unwrap()))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct SearchBody {
    tenant_id: String,
    query: String,
    scope: Option<SearchScope>,
    limit: Option<i64>,
}

async fn search(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<SearchBody>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.search(
        &body.tenant_id,
        &body.query,
        &body.scope.unwrap_or_default(),
        body.limit.unwrap_or(20),
    )
    .map(|v| Json(serde_json::to_value(v).unwrap()))
    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct ProjectsQuery {
    user_id: String,
}
async fn projects(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ProjectsQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.list_projects(&q.user_id)
        .map(|v| Json(serde_json::to_value(v).unwrap()))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct PatientsQuery {
    doctor_id: String,
}
async fn patients(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<PatientsQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.list_patients(&q.doctor_id)
        .map(|v| Json(serde_json::to_value(v).unwrap()))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct DisputesQuery {
    tenant_id: String,
}
async fn disputes(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<DisputesQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.list_disputes(&q.tenant_id)
        .map(|v| Json(serde_json::to_value(v).unwrap()))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct ResolveDisputeBody {
    tenant_id: String,
    winner_id: String,
    loser_id: String,
    actor: Actor,
}
async fn resolve_dispute(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ResolveDisputeBody>,
) -> Result<&'static str, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.resolve_dispute(&body.tenant_id, &body.winner_id, &body.loser_id, &body.actor)
        .map(|_| "ok")
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct AddLinkBody {
    tenant_id: String,
    source_id: String,
    target_id: String,
    link_type: LinkType,
}
async fn add_link(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<AddLinkBody>,
) -> Result<&'static str, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.add_link(&body.tenant_id, &body.source_id, &body.target_id, body.link_type)
        .map(|_| "ok")
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct LinksOutgoingQuery {
    tenant_id: String,
    source_id: String,
}
async fn outgoing_links(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<LinksOutgoingQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    s.fs.list_outgoing_links(&q.tenant_id, &q.source_id)
        .map(|v| {
            Json(serde_json::Value::Array(
                v.into_iter()
                    .map(|(tgt, lt)| {
                        serde_json::json!({"target_id": tgt, "link_type": lt})
                    })
                    .collect(),
            ))
        })
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

async fn sweep(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, String)> {
    let _auth = check_auth(&headers, &s.token).map_err(|c| (c, "unauthorised".into()))?;
    let pool = aim_fs::db::open_pool(
        &s.fs.root().join("_service").join("db").join("aim_fs.db"),
    )
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    let n = aim_fs::sweeper::sweep_once(&pool)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(serde_json::json!({"changed": n})))
}
