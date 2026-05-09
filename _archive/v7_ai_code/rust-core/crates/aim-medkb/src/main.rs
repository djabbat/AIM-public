//! aim-medkb :8772 — lab reference + drug interactions + i18n strings.
//!
//! Endpoints:
//!   GET  /health
//!   GET  /v1/lab                 — list analyte codes
//!   GET  /v1/lab/:code           — reference range for analyte
//!   GET  /v1/interactions?drugs=a,b,c — pairwise interaction screen
//!   GET  /v1/i18n/:lang/:key     — translated string (TODO; minimal stub)

use aim_common::{cors_layer, health_handler, init_tracing, ApiError, ApiResult};
use axum::{extract::{Path, Query, State}, routing::get, Json, Router};
use serde::{Deserialize, Serialize};
use std::{collections::{HashMap, HashSet}, net::SocketAddr, sync::Arc};

#[derive(Clone, Deserialize, Serialize, Debug)]
pub struct LabRange {
    pub display: String,
    pub unit: String,
    #[serde(default)] pub low: Option<f64>,
    #[serde(default)] pub high: Option<f64>,
    #[serde(default)] pub critical_low: Option<f64>,
    #[serde(default)] pub critical_high: Option<f64>,
    #[serde(default)] pub category: Option<String>,
    #[serde(default)] pub notes: Option<String>,
}

#[derive(Clone, Deserialize, Serialize, Debug)]
pub struct InteractionPair {
    pub drugs: Vec<String>,
    pub severity: String,
    pub mechanism: String,
    pub recommendation: String,
    #[serde(default)] pub source: String,
}

#[derive(Deserialize)]
struct InteractionsFile {
    pairs: Vec<InteractionPair>,
    #[serde(default)] synonyms: HashMap<String, String>,
}

#[derive(Clone)]
struct AppState {
    lab: Arc<HashMap<String, LabRange>>,
    pairs: Arc<HashMap<(String, String), InteractionPair>>,
    synonyms: Arc<HashMap<String, String>>,
}

impl AppState {
    fn new() -> anyhow::Result<Self> {
        let lab_path = std::env::var("AIM_MEDKB_LAB")
            .unwrap_or_else(|_| "crates/aim-medkb/data/lab_ranges.json".into());
        let lab: HashMap<String, LabRange> =
            serde_json::from_slice(&std::fs::read(&lab_path)?)?;

        let inter_path = std::env::var("AIM_MEDKB_INTERACTIONS")
            .unwrap_or_else(|_| "crates/aim-medkb/data/interactions.json".into());
        let inter: InteractionsFile =
            serde_json::from_slice(&std::fs::read(&inter_path)?)?;

        let mut pair_map = HashMap::new();
        for p in &inter.pairs {
            if p.drugs.len() != 2 { continue; }
            let mut k = [p.drugs[0].clone(), p.drugs[1].clone()];
            k.sort();
            pair_map.insert((k[0].clone(), k[1].clone()), p.clone());
        }

        tracing::info!(
            analytes = lab.len(),
            interactions = pair_map.len(),
            synonyms = inter.synonyms.len(),
            "medkb loaded"
        );
        Ok(Self {
            lab: Arc::new(lab),
            pairs: Arc::new(pair_map),
            synonyms: Arc::new(inter.synonyms),
        })
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing("info");
    let state = AppState::new()?;

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/metrics", get(aim_common::metrics_handler))
        .route("/v1/lab", get(list_codes))
        .route("/v1/lab/:code", get(lab_ref))
        .route("/v1/interactions", get(interactions))
        .route("/v1/i18n/:lang/:key", get(i18n))
        .with_state(state)
        .layer(cors_layer());

    let port: u16 = std::env::var("AIM_MEDKB_PORT").ok()
        .and_then(|s| s.parse().ok()).unwrap_or(8772);
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!(%addr, "aim-medkb listening");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn list_codes(State(s): State<AppState>) -> Json<Vec<String>> {
    let mut v: Vec<String> = s.lab.keys().cloned().collect();
    v.sort();
    Json(v)
}

async fn lab_ref(
    State(s): State<AppState>,
    Path(code): Path<String>,
) -> ApiResult<Json<LabRange>> {
    s.lab.get(&code)
        .cloned()
        .map(Json)
        .ok_or_else(|| ApiError::NotFound(format!("analyte not found: {code}")))
}

#[derive(Deserialize)]
struct InterQuery {
    drugs: String,
}

#[derive(Serialize)]
struct InterResp {
    queried: Vec<String>,
    canonical: Vec<String>,
    matches: Vec<InteractionPair>,
    severity_max: String,
    disclaimer: String,
}

async fn interactions(
    State(s): State<AppState>,
    Query(q): Query<InterQuery>,
) -> ApiResult<Json<InterResp>> {
    let raw: Vec<String> = q.drugs.split(',').map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty()).collect();
    if raw.len() < 2 {
        return Err(ApiError::BadRequest("need at least 2 drugs (comma-separated)".into()));
    }
    let canon: Vec<String> = raw.iter().map(|d| aim_medkb::canonicalise(d, &s.synonyms)).collect();
    let mut seen: HashSet<(String, String)> = HashSet::new();
    let mut matches: Vec<InteractionPair> = Vec::new();
    for i in 0..canon.len() {
        for j in (i + 1)..canon.len() {
            let mut k = [canon[i].clone(), canon[j].clone()];
            k.sort();
            let key = (k[0].clone(), k[1].clone());
            if !seen.insert(key.clone()) { continue; }
            if let Some(p) = s.pairs.get(&key) {
                matches.push(p.clone());
            }
        }
    }
    let severity_max = matches.iter()
        .map(|m| aim_medkb::severity_rank(&m.severity))
        .min()
        .map(aim_medkb::rank_label)
        .unwrap_or("no_known")
        .to_string();

    Ok(Json(InterResp {
        queried: raw,
        canonical: canon,
        matches,
        severity_max,
        disclaimer: "This is decision support only; clinician judgment required.".into(),
    }))
}

async fn i18n(Path((lang, key)): Path<(String, String)>) -> ApiResult<Json<serde_json::Value>> {
    Ok(Json(serde_json::json!({ "lang": lang, "key": key, "value": null,
        "note": "centralised i18n now lives in aim_web/I18n; medkb i18n is reserved for medical glossary"})))
}
