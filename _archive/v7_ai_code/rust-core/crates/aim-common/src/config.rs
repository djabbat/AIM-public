//! Unified config loader. Reads `aim.toml` from `AIM_CONFIG_PATH` or
//! `<workspace>/aim.toml` or `../aim.toml`. Provides default values + env
//! overrides for individual fields.

use serde::Deserialize;
use std::path::PathBuf;

#[derive(Debug, Clone, Deserialize, Default)]
pub struct AimConfig {
    #[serde(default)] pub ports: Ports,
    #[serde(default)] pub upstreams: Upstreams,
    #[serde(default)] pub security: Security,
    #[serde(default)] pub llm: LlmCfg,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Ports {
    pub aim_llm: Option<u16>,
    pub aim_rag: Option<u16>,
    pub aim_medkb: Option<u16>,
    pub aim_doctor: Option<u16>,
    pub aim_generalist: Option<u16>,
    pub aim_web: Option<u16>,
    pub aim_gateway: Option<u16>,
    pub diffdx_api: Option<u16>,
    pub ssa_api: Option<u16>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Upstreams {
    pub llm: Option<String>,
    pub rag: Option<String>,
    pub medkb: Option<String>,
    pub doctor: Option<String>,
    pub diffdx: Option<String>,
    pub ssa: Option<String>,
    pub generalist: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Security {
    pub require_auth: Option<bool>,
    pub cors_origin: Option<String>,
    pub sandbox_root: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct LlmCfg {
    pub default_tier: Option<String>,
    pub retries: Option<u32>,
    pub max_tokens: Option<u32>,
    pub embed_concurrency: Option<usize>,
}

impl AimConfig {
    pub fn load() -> Self {
        Self::candidates().into_iter().find_map(|p| {
            let bytes = std::fs::read(&p).ok()?;
            let s = std::str::from_utf8(&bytes).ok()?;
            match toml::from_str::<AimConfig>(s) {
                Ok(c) => {
                    tracing::info!(path = %p.display(), "loaded aim.toml");
                    Some(c)
                }
                Err(e) => {
                    tracing::warn!(path = %p.display(), error = %e, "aim.toml parse failed");
                    None
                }
            }
        }).unwrap_or_default()
    }

    fn candidates() -> Vec<PathBuf> {
        let mut v: Vec<PathBuf> = Vec::new();
        if let Ok(p) = std::env::var("AIM_CONFIG_PATH") { v.push(p.into()); }
        v.push(PathBuf::from("aim.toml"));
        v.push(PathBuf::from("../aim.toml"));
        v.push(PathBuf::from("../../aim.toml"));
        if let Ok(home) = std::env::var("HOME") {
            v.push(PathBuf::from(format!("{home}/Desktop/LongevityCommon/AIM/aim.toml")));
        }
        v
    }
}

/// Return port for a service: ENV var > aim.toml > default.
pub fn port(env_var: &str, file_default: Option<u16>, hard_default: u16) -> u16 {
    if let Ok(s) = std::env::var(env_var) {
        if let Ok(n) = s.parse() { return n; }
    }
    file_default.unwrap_or(hard_default)
}

/// Return URL for an upstream service.
pub fn upstream_url(env_var: &str, file_default: Option<&str>, hard_default: &str) -> String {
    std::env::var(env_var)
        .ok()
        .or_else(|| file_default.map(String::from))
        .unwrap_or_else(|| hard_default.to_string())
}
