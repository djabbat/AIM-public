//! aim-doctor :8773 — diagnosis pipeline with case storage.
//!
//! Endpoints:
//!   GET  /health
//!   POST /v1/intake     — { complaint, language? } -> { case_id, structured, raw }
//!   POST /v1/diagnose   — { case_id?, intake?, cbc?, system? } -> { differentials, syndromes, plan, errors }
//!   GET  /v1/cases/:id  — fetch stored case
//!   GET  /v1/cases      — list case ids (debug)

use aim_common::{cors_layer, health_handler, init_tracing, ApiError, ApiResult};
use axum::{extract::{Path, State}, routing::{get, post}, Json, Router};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::HashMap, net::SocketAddr, sync::Arc};

#[derive(Clone)]
struct DoctorState {
    upstream: Upstream,
    client: reqwest::Client,
    cases: Arc<Mutex<HashMap<String, Case>>>,
}

#[derive(Clone, Serialize)]
struct Case {
    id: String,
    structured: Value,
    raw: String,
    created_at: String,
}

#[derive(Clone)]
struct Upstream {
    llm: String,
    diffdx: String,
    ssa: String,
}

impl Upstream {
    fn from_env() -> Self {
        Self {
            llm:    env_or("AIM_LLM_URL",    "http://127.0.0.1:8770"),
            diffdx: env_or("AIM_DIFFDX_URL", "http://127.0.0.1:8765"),
            ssa:    env_or("AIM_SSA_URL",    "http://127.0.0.1:8766"),
        }
    }
}

fn env_or(k: &str, d: &str) -> String {
    std::env::var(k).unwrap_or_else(|_| d.to_string())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing("info");
    let state = DoctorState {
        upstream: Upstream::from_env(),
        client: reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(180))
            .build()?,
        cases: Arc::new(Mutex::new(HashMap::new())),
    };

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/metrics", get(aim_common::metrics_handler))
        .route("/v1/intake", post(intake))
        .route("/v1/diagnose", post(diagnose))
        .route("/v1/cases/:id", get(get_case))
        .route("/v1/cases", get(list_cases))
        .with_state(state)
        .layer(cors_layer());

    let port: u16 = std::env::var("AIM_DOCTOR_PORT").ok()
        .and_then(|s| s.parse().ok()).unwrap_or(8773);
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!(%addr, "aim-doctor listening");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

#[derive(Deserialize)]
struct IntakeReq {
    complaint: String,
    #[serde(default)] language: Option<String>,
}

#[derive(Serialize)]
struct IntakeResp {
    case_id: String,
    structured: Value,
    raw: String,
}

const INTAKE_SYSTEM: &str = r#"You convert free-form patient complaints into a structured JSON intake.
Reply ONLY with a JSON object of this shape, no prose:
{
  "chief_complaint": string,
  "duration": string|null,
  "severity": "mild"|"moderate"|"severe"|null,
  "associated_symptoms": [string],
  "red_flags": [string],
  "system": "cardio"|"resp"|"gi"|"neuro"|"endo"|"renal"|"heme"|"musc"|"other"|null,
  "suggested_workup": [string]
}"#;

async fn intake(
    State(s): State<DoctorState>,
    Json(req): Json<IntakeReq>,
) -> ApiResult<Json<IntakeResp>> {
    let user = match req.language.as_deref() {
        Some(lang) if !lang.is_empty() => format!("[language: {lang}]\n{}", req.complaint),
        _ => req.complaint.clone(),
    };

    let llm_resp: Value = s.client.post(format!("{}/v1/chat", s.upstream.llm))
        .json(&json!({
            "messages": [
                { "role": "system", "content": INTAKE_SYSTEM },
                { "role": "user",   "content": user }
            ]
        }))
        .send().await.map_err(|e| ApiError::Upstream(format!("aim-llm send: {e}")))?
        .error_for_status().map_err(|e| ApiError::Upstream(format!("aim-llm status: {e}")))?
        .json().await.map_err(|e| ApiError::Upstream(format!("aim-llm parse: {e}")))?;

    let raw = llm_resp.get("reply").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let structured = aim_doctor::extract_json(&raw).unwrap_or_else(|| json!({ "chief_complaint": req.complaint }));

    let case_id = uuid::Uuid::new_v4().to_string();
    let case = Case {
        id: case_id.clone(),
        structured: structured.clone(),
        raw: raw.clone(),
        created_at: chrono::Utc::now().to_rfc3339(),
    };
    s.cases.lock().insert(case_id.clone(), case);

    Ok(Json(IntakeResp { case_id, structured, raw }))
}

#[derive(Deserialize)]
struct DiagnoseReq {
    #[serde(default)] case_id: Option<String>,
    #[serde(default)] intake: Option<Value>,
    #[serde(default)] cbc: Option<Value>,
    #[serde(default)] system: Option<String>,
}

#[derive(Serialize, Default)]
struct DiagnoseResp {
    differentials: Value,
    syndromes: Option<Value>,
    plan: String,
    errors: Vec<String>,
}

const PLAN_SYSTEM: &str = r#"You are a careful clinician. Given an intake, candidate diagnoses, and CBC syndromes,
produce a concise plan in plain language: 1) most likely working diagnosis, 2) red flags to rule out,
3) immediate workup, 4) follow-up. Be specific, cite labs by name, do not invent numbers."#;

async fn diagnose(
    State(s): State<DoctorState>,
    Json(req): Json<DiagnoseReq>,
) -> ApiResult<Json<DiagnoseResp>> {
    let intake_val: Value = if let Some(case_id) = &req.case_id {
        let case = s.cases.lock().get(case_id).cloned()
            .ok_or_else(|| ApiError::NotFound(format!("case {case_id} not found")))?;
        case.structured
    } else if let Some(i) = req.intake {
        i
    } else {
        return Err(ApiError::BadRequest("either case_id or intake is required".into()));
    };

    let mut errors: Vec<String> = Vec::new();

    // 1. DiffDx ranking.
    let diff_body = json!({
        "presenting_complaint": intake_val.get("chief_complaint")
            .and_then(|v| v.as_str()).unwrap_or(""),
        "system": req.system.clone()
            .or_else(|| intake_val.get("system").and_then(|v| v.as_str()).map(String::from))
            .unwrap_or_else(|| "other".into())
    });

    let differentials: Value = match s.client.post(format!("{}/api/v1/diff", s.upstream.diffdx))
        .json(&diff_body).send().await
    {
        Ok(r) => match r.error_for_status() {
            Ok(r2) => r2.json::<Value>().await.unwrap_or_else(|e| {
                errors.push(format!("diffdx parse: {e}"));
                json!({})
            }),
            Err(e) => { errors.push(format!("diffdx status: {e}")); json!({}) }
        },
        Err(e) => { errors.push(format!("diffdx send: {e}")); json!({}) }
    };

    // 2. SSA syndromes.
    let syndromes = if let Some(cbc) = &req.cbc {
        match s.client.post(format!("{}/api/v1/syndromes", s.upstream.ssa))
            .json(cbc).send().await
        {
            Ok(r) => match r.error_for_status() {
                Ok(r2) => match r2.json::<Value>().await {
                    Ok(v) => Some(v),
                    Err(e) => { errors.push(format!("ssa parse: {e}")); None }
                },
                Err(e) => { errors.push(format!("ssa status: {e}")); None }
            },
            Err(e) => { errors.push(format!("ssa send: {e}")); None }
        }
    } else { None };

    // 3. LLM synthesis plan.
    let mut context = json!({
        "intake": intake_val,
        "differentials": differentials,
        "syndromes": syndromes,
    });
    if !errors.is_empty() {
        context["upstream_errors"] = json!(errors.clone());
    }

    let plan = match s.client.post(format!("{}/v1/chat", s.upstream.llm))
        .json(&json!({
            "messages": [
                { "role": "system", "content": PLAN_SYSTEM },
                { "role": "user",   "content": context.to_string() }
            ]
        }))
        .send().await
    {
        Ok(r) => match r.error_for_status() {
            Ok(r2) => match r2.json::<Value>().await {
                Ok(v) => v.get("reply").and_then(|s| s.as_str()).unwrap_or("").to_string(),
                Err(e) => { errors.push(format!("llm parse: {e}")); String::new() }
            },
            Err(e) => { errors.push(format!("llm status: {e}")); String::new() }
        },
        Err(e) => { errors.push(format!("llm send: {e}")); String::new() }
    };

    Ok(Json(DiagnoseResp { differentials, syndromes, plan, errors }))
}

async fn get_case(
    State(s): State<DoctorState>,
    Path(id): Path<String>,
) -> ApiResult<Json<Case>> {
    s.cases.lock().get(&id).cloned()
        .map(Json)
        .ok_or_else(|| ApiError::NotFound(format!("case {id}")))
}

async fn list_cases(State(s): State<DoctorState>) -> Json<Vec<String>> {
    let ids: Vec<String> = s.cases.lock().keys().cloned().collect();
    Json(ids)
}

