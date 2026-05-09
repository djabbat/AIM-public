//! aim-config — global config + model IDs + endpoints + kernel weights.
//!
//! Port of `config.py`. Pure data + env-driven loaders. The actual
//! `~/.aim_env` parser stays in the binary; this crate exposes
//! `from_env(get)` which accepts a `Fn(&str) -> Option<String>`.

use serde::{Deserialize, Serialize};

pub const VERSION: &str = "7.0.0";
pub const APP_NAME: &str = "AIM — Assistant of Integrative Medicine";

pub const SUPPORTED_LANGS: &[&str] = &[
    "ru", "en", "fr", "es", "ar", "zh", "ka", "kz", "da",
];
pub const DEFAULT_LANG: &str = "ru";

pub const REASONING_KEYWORDS: &[&str] = &[
    "диагноз",
    "diagnosis",
    "дифференциальный",
    "differential",
    "анализ",
    "analysis",
    "причина",
    "cause",
    "почему",
    "why",
    "объясни механизм",
    "explain mechanism",
    "патогенез",
    "pathogenesis",
];

// ── models ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Models {
    pub ds_chat: String,
    pub ds_reasoner: String,
    pub ds_chat_legacy: String,
    pub ds_reasoner_legacy: String,
    pub groq_llama: String,
    pub groq_llama_fast: String,
    pub groq_mixtral: String,
    pub ollama_chat: String,
    pub ollama_fast: String,
    pub ollama_reasoner: String,
    pub claude_opus: String,
    pub claude_sonnet: String,
    pub claude_haiku: String,
    pub gemini_pro: String,
    pub gemini_flash: String,
    pub gemini_flash_lite: String,
}

impl Default for Models {
    fn default() -> Self {
        Self {
            ds_chat: "deepseek-v4-flash".into(),
            ds_reasoner: "deepseek-v4-pro".into(),
            ds_chat_legacy: "deepseek-chat".into(),
            ds_reasoner_legacy: "deepseek-reasoner".into(),
            groq_llama: "llama-3.3-70b-versatile".into(),
            groq_llama_fast: "llama-3.1-8b-instant".into(),
            groq_mixtral: "mixtral-8x7b-32768".into(),
            ollama_chat: "qwen2.5:7b-instruct".into(),
            ollama_fast: "qwen2.5:3b-instruct".into(),
            ollama_reasoner: "deepseek-r1:7b".into(),
            claude_opus: "claude-opus-4-7".into(),
            claude_sonnet: "claude-sonnet-4-6".into(),
            claude_haiku: "claude-haiku-4-5-20251001".into(),
            gemini_pro: "gemini-2.5-pro".into(),
            gemini_flash: "gemini-2.5-flash".into(),
            gemini_flash_lite: "gemini-2.5-flash-lite".into(),
        }
    }
}

impl Models {
    pub fn from_env<F: Fn(&str) -> Option<String>>(get: F) -> Self {
        let mut m = Self::default();
        if let Some(v) = get("AIM_DS_CHAT_MODEL") { m.ds_chat = v; }
        if let Some(v) = get("AIM_DS_REASONER_MODEL") { m.ds_reasoner = v; }
        if let Some(v) = get("AIM_OLLAMA_CHAT_MODEL") { m.ollama_chat = v; }
        if let Some(v) = get("AIM_OLLAMA_FAST_MODEL") { m.ollama_fast = v; }
        if let Some(v) = get("AIM_OLLAMA_REASONER_MODEL") { m.ollama_reasoner = v; }
        if let Some(v) = get("AIM_CLAUDE_OPUS_MODEL") { m.claude_opus = v; }
        if let Some(v) = get("AIM_CLAUDE_SONNET_MODEL") { m.claude_sonnet = v; }
        if let Some(v) = get("AIM_CLAUDE_HAIKU_MODEL") { m.claude_haiku = v; }
        if let Some(v) = get("AIM_GEMINI_PRO_MODEL") { m.gemini_pro = v; }
        if let Some(v) = get("AIM_GEMINI_FLASH_MODEL") { m.gemini_flash = v; }
        if let Some(v) = get("AIM_GEMINI_FLASH_LITE_MODEL") { m.gemini_flash_lite = v; }
        m
    }
}

// ── endpoints ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Endpoints {
    pub deepseek: String,
    pub groq: String,
    pub ollama: String,
    pub anthropic: String,
    pub gemini: String,
}

impl Default for Endpoints {
    fn default() -> Self {
        Self {
            deepseek: "https://api.deepseek.com/v1".into(),
            groq: "https://api.groq.com/openai/v1".into(),
            ollama: "http://127.0.0.1:11434/v1".into(),
            anthropic: "https://api.anthropic.com/v1".into(),
            gemini: "https://generativelanguage.googleapis.com/v1beta/openai".into(),
        }
    }
}

impl Endpoints {
    pub fn from_env<F: Fn(&str) -> Option<String>>(get: F) -> Self {
        let mut e = Self::default();
        if let Some(v) = get("AIM_OLLAMA_URL") {
            e.ollama = v;
        }
        e
    }
}

// ── llm params ────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct LlmParams {
    pub temperature: f32,
    pub max_tokens: u32,
    pub max_tokens_long: u32,
    pub timeout_secs: f64,
    pub connect_timeout_secs: f64,
}

impl Default for LlmParams {
    fn default() -> Self {
        Self {
            temperature: 0.3,
            max_tokens: 16_384,
            max_tokens_long: 131_072,
            timeout_secs: 180.0,
            connect_timeout_secs: 10.0,
        }
    }
}

impl LlmParams {
    pub fn from_env<F: Fn(&str) -> Option<String>>(get: F) -> Self {
        let mut p = Self::default();
        if let Some(v) = get("AIM_LLM_MAX_TOKENS").and_then(|s| s.parse().ok()) {
            p.max_tokens = v;
        }
        if let Some(v) = get("AIM_LLM_MAX_TOKENS_LONG").and_then(|s| s.parse().ok()) {
            p.max_tokens_long = v;
        }
        if let Some(v) = get("AIM_LLM_TIMEOUT").and_then(|s| s.parse().ok()) {
            p.timeout_secs = v;
        }
        if let Some(v) = get("AIM_LLM_CONNECT_TIMEOUT").and_then(|s| s.parse().ok()) {
            p.connect_timeout_secs = v;
        }
        p
    }
}

// ── kernel weights ────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct KernelWeights {
    pub alpha: f64,
    pub beta: f64,
    pub gamma: f64,
    pub ethics_ze: f64,
    pub ethics_auto: f64,
    pub ethics_benef: f64,
    pub ethics_nonmal: f64,
    pub ethics_justice: f64,
    pub clarify_impedance_threshold: f64,
}

impl Default for KernelWeights {
    fn default() -> Self {
        Self {
            alpha: 0.2,
            beta: 0.4,
            gamma: 0.4,
            ethics_ze: 0.40,
            ethics_auto: 0.15,
            ethics_benef: 0.15,
            ethics_nonmal: 0.15,
            ethics_justice: 0.15,
            clarify_impedance_threshold: 0.7,
        }
    }
}

impl KernelWeights {
    pub fn from_env<F: Fn(&str) -> Option<String>>(get: F) -> Self {
        let mut k = Self::default();
        if let Some(v) = get("AIM_KERNEL_ALPHA").and_then(|s| s.parse().ok()) {
            k.alpha = v;
        }
        if let Some(v) = get("AIM_KERNEL_BETA").and_then(|s| s.parse().ok()) {
            k.beta = v;
        }
        if let Some(v) = get("AIM_KERNEL_GAMMA").and_then(|s| s.parse().ok()) {
            k.gamma = v;
        }
        k
    }

    pub fn preset(name: &str) -> Option<KernelWeights> {
        let (a, b, g) = match name {
            "conservative" => (0.1, 0.3, 0.6),
            "balanced" => (0.2, 0.4, 0.4),
            "aggressive" => (0.3, 0.6, 0.1),
            _ => return None,
        };
        let mut k = KernelWeights::default();
        k.alpha = a;
        k.beta = b;
        k.gamma = g;
        Some(k)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supported_langs_count_nine() {
        assert_eq!(SUPPORTED_LANGS.len(), 9);
        assert!(SUPPORTED_LANGS.contains(&"ru"));
        assert!(SUPPORTED_LANGS.contains(&"ka"));
        assert!(SUPPORTED_LANGS.contains(&"kz"));
        assert!(SUPPORTED_LANGS.contains(&"da"));
    }

    #[test]
    fn default_models_match_python_defaults() {
        let m = Models::default();
        assert_eq!(m.ds_chat, "deepseek-v4-flash");
        assert_eq!(m.ds_reasoner, "deepseek-v4-pro");
        assert_eq!(m.claude_opus, "claude-opus-4-7");
    }

    #[test]
    fn models_from_env_overrides() {
        let m = Models::from_env(|k| {
            if k == "AIM_DS_CHAT_MODEL" { Some("custom-flash".into()) } else { None }
        });
        assert_eq!(m.ds_chat, "custom-flash");
        assert_eq!(m.ds_reasoner, "deepseek-v4-pro"); // unchanged
    }

    #[test]
    fn endpoints_default() {
        let e = Endpoints::default();
        assert!(e.deepseek.starts_with("https://"));
        assert!(e.ollama.starts_with("http://127.0.0.1"));
    }

    #[test]
    fn endpoints_ollama_override() {
        let e = Endpoints::from_env(|k| {
            if k == "AIM_OLLAMA_URL" { Some("http://server:11434/v1".into()) } else { None }
        });
        assert_eq!(e.ollama, "http://server:11434/v1");
    }

    #[test]
    fn llm_params_defaults() {
        let p = LlmParams::default();
        assert_eq!(p.max_tokens, 16_384);
        assert_eq!(p.max_tokens_long, 131_072);
    }

    #[test]
    fn llm_params_from_env_int_parsing() {
        let p = LlmParams::from_env(|k| match k {
            "AIM_LLM_MAX_TOKENS" => Some("8192".into()),
            "AIM_LLM_TIMEOUT" => Some("60".into()),
            _ => None,
        });
        assert_eq!(p.max_tokens, 8_192);
        assert_eq!(p.timeout_secs, 60.0);
    }

    #[test]
    fn kernel_weights_default_balanced() {
        let k = KernelWeights::default();
        assert!((k.alpha + k.beta + k.gamma - 1.0).abs() < 1e-9);
    }

    #[test]
    fn kernel_preset_conservative_increases_gamma() {
        let k = KernelWeights::preset("conservative").unwrap();
        assert_eq!(k.gamma, 0.6);
    }

    #[test]
    fn kernel_preset_unknown_is_none() {
        assert!(KernelWeights::preset("xyzzy").is_none());
    }

    #[test]
    fn reasoning_keywords_bilingual() {
        assert!(REASONING_KEYWORDS.contains(&"диагноз"));
        assert!(REASONING_KEYWORDS.contains(&"diagnosis"));
    }
}
