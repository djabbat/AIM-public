use std::env;
use tower_http::cors::{Any, CorsLayer};

/// Strict in prod, permissive in dev. Toggle with AIM_ENV=prod.
pub fn cors_layer() -> CorsLayer {
    if env::var("AIM_ENV").as_deref() == Ok("prod") {
        let origin = env::var("AIM_CORS_ORIGIN")
            .unwrap_or_else(|_| "http://127.0.0.1:4000".into());
        CorsLayer::new()
            .allow_origin(origin.parse::<axum::http::HeaderValue>().expect("AIM_CORS_ORIGIN"))
            .allow_methods([axum::http::Method::GET, axum::http::Method::POST])
            .allow_headers([axum::http::header::CONTENT_TYPE, axum::http::header::AUTHORIZATION])
    } else {
        CorsLayer::new().allow_origin(Any).allow_methods(Any).allow_headers(Any)
    }
}
