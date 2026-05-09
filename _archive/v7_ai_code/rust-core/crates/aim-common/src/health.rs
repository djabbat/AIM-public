use axum::Json;
use serde::Serialize;

#[derive(Serialize)]
pub struct HealthInfo {
    pub service: &'static str,
    pub version: &'static str,
    pub status: &'static str,
    pub started_at: chrono::DateTime<chrono::Utc>,
}

pub async fn health_handler() -> Json<HealthInfo> {
    Json(HealthInfo {
        service: env!("CARGO_PKG_NAME"),
        version: env!("CARGO_PKG_VERSION"),
        status: "ok",
        started_at: chrono::Utc::now(),
    })
}
