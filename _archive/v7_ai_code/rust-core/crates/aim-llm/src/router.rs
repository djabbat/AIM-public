use crate::providers::{Provider, ProviderId};
use aim_common::{ApiError, ApiResult};
use aim_llm_router::{AcquireResult, CircuitBreaker, Clock as RouterClock, TokenBucket};
use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

/// Wall-clock clock for `aim_llm_router::CircuitBreaker`. Production
/// callers use this; tests can swap a `ManualClock`.
struct WallClock;

impl RouterClock for WallClock {
    fn now_secs(&self) -> f64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0)
    }
}

#[derive(Clone)]
pub struct RouterState {
    pub providers: Arc<Vec<Box<dyn Provider>>>,
    pub cache: crate::cache::PromptCache,
    /// Per-provider circuit breakers — opens after N consecutive
    /// failures, recovers after `recovery_secs`. Defaults match the
    /// Python `llm.py` constants (DS=5/30s, Groq=3/30s, Anthropic=3/60s,
    /// Gemini=3/120s, Ollama=2/15s).
    pub breakers: Arc<HashMap<ProviderId, CircuitBreaker>>,
    /// Per-provider token-bucket rate limiters (RPM, capacity).
    /// Defaults match Python `llm.py` (Ollama unlimited so capacity is
    /// large; Anthropic conservative since paid + tight RPM; Gemini
    /// has a daily 50/request free tier so we throttle aggressively).
    pub limiters: Arc<HashMap<ProviderId, TokenBucket>>,
}

fn default_breakers() -> HashMap<ProviderId, CircuitBreaker> {
    let mut m = HashMap::new();
    m.insert(ProviderId::DeepSeek, CircuitBreaker::new(5, 30.0));
    m.insert(ProviderId::Groq, CircuitBreaker::new(3, 30.0));
    m.insert(ProviderId::Anthropic, CircuitBreaker::new(3, 60.0));
    m.insert(ProviderId::Gemini, CircuitBreaker::new(3, 120.0));
    m.insert(ProviderId::Ollama, CircuitBreaker::new(2, 15.0));
    m
}

fn default_limiters(clock: &dyn RouterClock) -> HashMap<ProviderId, TokenBucket> {
    // (RPM, burst capacity) per provider.
    let configs: &[(ProviderId, u32, u32)] = &[
        (ProviderId::DeepSeek, 600, 60),    // generous; DeepSeek is paid
        (ProviderId::Groq, 30, 5),          // free tier 30/min
        (ProviderId::Anthropic, 50, 10),    // tight RPM; paid Opus
        (ProviderId::Gemini, 50, 5),        // free 50/day total — burst small
        (ProviderId::Ollama, 10000, 1000),  // local, effectively unlimited
    ];
    let mut m = HashMap::new();
    for (pid, rpm, cap) in configs {
        m.insert(*pid, TokenBucket::new(*rpm, *cap, clock));
    }
    m
}

impl RouterState {
    pub fn from_env() -> Self {
        let providers = crate::providers::load_from_env();
        let clock = WallClock;
        Self {
            providers: Arc::new(providers),
            cache: crate::cache::PromptCache::from_env(),
            breakers: Arc::new(default_breakers()),
            limiters: Arc::new(default_limiters(&clock)),
        }
    }

    pub fn provider_by_id(&self, id: ProviderId) -> Option<&dyn Provider> {
        self.providers.iter().find(|p| p.id() == id).map(|b| b.as_ref())
    }

    pub fn first_ready(&self) -> Option<&dyn Provider> {
        self.providers.iter().find(|p| p.is_ready()).map(|b| b.as_ref())
    }
}

#[derive(Serialize)]
pub struct ProviderInfo {
    pub id: ProviderId,
    pub ready: bool,
    pub default_model: &'static str,
}

pub async fn list_providers(State(state): State<RouterState>) -> Json<Vec<ProviderInfo>> {
    let infos = state.providers.iter().map(|p| ProviderInfo {
        id: p.id(),
        ready: p.is_ready(),
        default_model: p.default_model(),
    }).collect();
    Json(infos)
}

#[derive(Deserialize)]
pub struct ChatRequest {
    pub messages: Vec<ChatMessage>,
    /// Model identifier; we infer the provider from its prefix.
    pub model_hint: Option<String>,
    /// Force a specific provider; overrides model_hint inference.
    pub provider: Option<ProviderId>,
    /// Tier name (per CLAUDE.md): critical / deep / long / default / fast.
    pub tier: Option<String>,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Serialize)]
pub struct ChatResponse {
    pub reply: String,
    pub provider: ProviderId,
    pub model: String,
    pub attempts: Vec<Attempt>,
}

#[derive(Serialize, Clone)]
pub struct Attempt {
    pub provider: ProviderId,
    pub model: String,
    pub ok: bool,
    pub error: Option<String>,
}

/// Map a model name (or hint) to its provider when possible.
pub fn provider_for_model(model: &str) -> Option<ProviderId> {
    let m = model.to_lowercase();
    if m.starts_with("deepseek") { return Some(ProviderId::DeepSeek); }
    if m.starts_with("claude")   { return Some(ProviderId::Anthropic); }
    if m.starts_with("gemini")   { return Some(ProviderId::Gemini); }
    if m.starts_with("llama")    { return Some(ProviderId::Groq); }
    if m.starts_with("qwen") || m.starts_with("phi") || m.contains(":") {
        // Ollama models often look "llama3.2" / "qwen2.5:7b"
        return Some(ProviderId::Ollama);
    }
    None
}

/// Tier → ordered chain of (provider, model) per CLAUDE.md.
pub fn tier_chain(tier: &str) -> Vec<(ProviderId, &'static str)> {
    match tier {
        "critical" => vec![
            (ProviderId::Anthropic, "claude-opus-4-7"),
            (ProviderId::Gemini,    "gemini-2.5-pro"),
            (ProviderId::DeepSeek,  "deepseek-reasoner"),
            (ProviderId::Ollama,    "deepseek-r1"),
        ],
        "deep" => vec![
            (ProviderId::DeepSeek,  "deepseek-reasoner"),
            (ProviderId::Anthropic, "claude-opus-4-7"),
            (ProviderId::Gemini,    "gemini-2.5-pro"),
            (ProviderId::Ollama,    "deepseek-r1"),
        ],
        "long" => vec![
            (ProviderId::DeepSeek,  "deepseek-chat"),
            (ProviderId::Gemini,    "gemini-2.5-pro"),
            (ProviderId::Ollama,    "qwen2.5:7b"),
        ],
        "fast" => vec![
            (ProviderId::Groq,      "llama-3.1-8b-instant"),
            (ProviderId::DeepSeek,  "deepseek-chat"),
            (ProviderId::Ollama,    "qwen2.5:3b"),
        ],
        // "default" or anything else
        _ => vec![
            (ProviderId::DeepSeek,  "deepseek-chat"),
            (ProviderId::Gemini,    "gemini-2.5-flash"),
            (ProviderId::Ollama,    "qwen2.5:7b"),
        ],
    }
}

pub async fn chat(
    State(state): State<RouterState>,
    Json(req): Json<ChatRequest>,
) -> ApiResult<Json<ChatResponse>> {
    if req.messages.is_empty() {
        return Err(ApiError::BadRequest("messages cannot be empty".into()));
    }

    // Build the chain. Priority:
    //  1. Explicit provider field.
    //  2. model_hint (try inferred provider first, then fall back to others).
    //  3. tier name.
    //  4. first ready provider with its default model.
    let chain: Vec<(ProviderId, String)> = if let Some(pid) = req.provider {
        let model = req.model_hint.unwrap_or_else(|| {
            state.provider_by_id(pid).map(|p| p.default_model().to_string()).unwrap_or_default()
        });
        vec![(pid, model)]
    } else if let Some(model) = &req.model_hint {
        let mut v = Vec::new();
        if let Some(inferred) = provider_for_model(model) {
            v.push((inferred, model.clone()));
        }
        // After explicit, allow tier-style fallback to default.
        for (p, m) in tier_chain(req.tier.as_deref().unwrap_or("default")) {
            if !v.iter().any(|(pp, _)| *pp == p) {
                v.push((p, m.into()));
            }
        }
        v
    } else if let Some(tier) = &req.tier {
        tier_chain(tier).into_iter().map(|(p, m)| (p, m.into())).collect()
    } else if let Some(p) = state.first_ready() {
        vec![(p.id(), p.default_model().to_string())]
    } else {
        return Err(ApiError::Upstream("no ready provider".into()));
    };

    let mut attempts = Vec::new();
    let max_retries_per_step: u32 = std::env::var("AIM_LLM_RETRIES").ok()
        .and_then(|s| s.parse().ok()).unwrap_or(2);

    let clock = WallClock;
    for (pid, model) in &chain {
        let Some(provider) = state.provider_by_id(*pid) else {
            attempts.push(Attempt {
                provider: *pid, model: model.clone(),
                ok: false, error: Some("provider not loaded".into()),
            });
            continue;
        };
        if !provider.is_ready() {
            attempts.push(Attempt {
                provider: *pid, model: model.clone(),
                ok: false, error: Some("not ready (no API key?)".into()),
            });
            continue;
        }
        // Circuit-breaker gate (per provider) — skip the provider if the
        // breaker is OPEN and within recovery window. Lets the next
        // provider in the chain take over without piling on more
        // failures to the upstream that's clearly down.
        if let Some(breaker) = state.breakers.get(pid) {
            if let Err(e) = breaker.before_call(&clock) {
                attempts.push(Attempt {
                    provider: *pid,
                    model: model.clone(),
                    ok: false,
                    error: Some(format!("circuit open; retry in {:.1}s", e.wait_secs)),
                });
                aim_common::upstream_inc("aim-llm", &format!("{:?}", pid).to_lowercase(), "circuit_open");
                continue;
            }
        }
        // Rate-limit gate — block calls that exceed the per-provider
        // RPM budget. Skip the provider (don't sleep blocking) so the
        // next provider in the chain can serve immediately.
        if let Some(limiter) = state.limiters.get(pid) {
            match limiter.try_acquire(1, &clock) {
                AcquireResult::Granted => {}
                AcquireResult::WaitFor { secs } => {
                    attempts.push(Attempt {
                        provider: *pid,
                        model: model.clone(),
                        ok: false,
                        error: Some(format!("rate-limited; retry in {:.1}s", secs)),
                    });
                    aim_common::upstream_inc("aim-llm", &format!("{:?}", pid).to_lowercase(), "rate_limited");
                    continue;
                }
            }
        }

        // Cache check (per provider+model combination).
        let cache_key = if state.cache.enabled() {
            let msgs_json = serde_json::to_string(&req.messages).unwrap_or_default();
            let composite = format!("{:?}/{model}", pid);
            Some(crate::cache::PromptCache::key(&composite, &msgs_json))
        } else { None };

        if let Some(key) = cache_key.as_deref() {
            if let Some(cached) = state.cache.get(key) {
                attempts.push(Attempt { provider: *pid, model: model.clone(), ok: true, error: Some("cache_hit".into()) });
                aim_common::req_inc("aim-llm", "/v1/chat", "cache_hit");
                return Ok(Json(ChatResponse {
                    reply: cached, provider: *pid, model: model.clone(), attempts,
                }));
            }
        }

        let mut last_err: Option<String> = None;
        for attempt in 0..=max_retries_per_step {
            let provider_label = format!("{:?}", pid).to_lowercase();
            match provider.complete(&req.messages, model).await {
                Ok(reply) => {
                    if let Some(breaker) = state.breakers.get(pid) {
                        breaker.on_success();
                    }
                    attempts.push(Attempt { provider: *pid, model: model.clone(), ok: true, error: None });
                    aim_common::upstream_inc("aim-llm", &provider_label, "ok");
                    aim_common::req_inc("aim-llm", "/v1/chat", "ok");
                    if let Some(key) = cache_key.as_deref() {
                        state.cache.put(key, key, &reply, model);
                    }
                    return Ok(Json(ChatResponse {
                        reply, provider: *pid, model: model.clone(), attempts,
                    }));
                }
                Err(e) => {
                    let msg = e.to_string();
                    if attempt < max_retries_per_step && is_transient(&msg) {
                        aim_common::upstream_inc("aim-llm", &provider_label, "retry");
                        let delay = std::time::Duration::from_millis(200 * (1 << attempt));
                        tokio::time::sleep(delay).await;
                        last_err = Some(msg);
                        continue;
                    }
                    aim_common::upstream_inc("aim-llm", &provider_label, "fail");
                    if let Some(breaker) = state.breakers.get(pid) {
                        breaker.on_failure(&clock);
                    }
                    last_err = Some(msg);
                    break;
                }
            }
        }
        attempts.push(Attempt {
            provider: *pid, model: model.clone(),
            ok: false, error: last_err,
        });
    }

    let summary = attempts.iter()
        .map(|a| format!("{:?}/{}: {}", a.provider, a.model,
            a.error.clone().unwrap_or_else(|| "?".into())))
        .collect::<Vec<_>>()
        .join("; ");
    aim_common::req_inc("aim-llm", "/v1/chat", "all_failed");
    Err(ApiError::Upstream(format!("all providers failed: {summary}")))
}

fn is_transient(err: &str) -> bool {
    let e = err.to_lowercase();
    e.contains("timeout") || e.contains("timed out")
        || e.contains("503") || e.contains("502") || e.contains("504")
        || e.contains("connection") || e.contains("dns")
        || e.contains("rate limit") || e.contains("429")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::ProviderId;

    // ── provider_for_model ────────────────────────────────────────────────

    #[test]
    fn provider_for_model_deepseek_prefix() {
        assert_eq!(
            provider_for_model("deepseek-chat"),
            Some(ProviderId::DeepSeek)
        );
        assert_eq!(
            provider_for_model("deepseek-reasoner"),
            Some(ProviderId::DeepSeek)
        );
    }

    #[test]
    fn provider_for_model_anthropic_prefix() {
        assert_eq!(
            provider_for_model("claude-opus-4-7"),
            Some(ProviderId::Anthropic)
        );
        assert_eq!(
            provider_for_model("claude-haiku-4-5-20251001"),
            Some(ProviderId::Anthropic)
        );
    }

    #[test]
    fn provider_for_model_gemini_prefix() {
        assert_eq!(
            provider_for_model("gemini-2.5-pro"),
            Some(ProviderId::Gemini)
        );
        assert_eq!(
            provider_for_model("gemini-2.5-flash"),
            Some(ProviderId::Gemini)
        );
    }

    #[test]
    fn provider_for_model_groq_prefix() {
        assert_eq!(
            provider_for_model("llama-3.1-8b-instant"),
            Some(ProviderId::Groq)
        );
        assert_eq!(
            provider_for_model("llama-3.3-70b-versatile"),
            Some(ProviderId::Groq)
        );
    }

    #[test]
    fn provider_for_model_ollama_for_qwen_phi() {
        assert_eq!(
            provider_for_model("qwen2.5:7b"),
            Some(ProviderId::Ollama)
        );
        assert_eq!(provider_for_model("phi-3"), Some(ProviderId::Ollama));
    }

    #[test]
    fn provider_for_model_unknown_returns_none() {
        assert_eq!(provider_for_model("gpt-4-turbo"), None);
        assert_eq!(provider_for_model("mistral-7b"), None);
    }

    #[test]
    fn provider_for_model_case_insensitive() {
        assert_eq!(
            provider_for_model("CLAUDE-Opus-4.7"),
            Some(ProviderId::Anthropic)
        );
        assert_eq!(
            provider_for_model("DeepSeek-Chat"),
            Some(ProviderId::DeepSeek)
        );
    }

    // ── tier_chain ────────────────────────────────────────────────────────

    #[test]
    fn tier_chain_critical_starts_with_anthropic() {
        let chain = tier_chain("critical");
        assert!(!chain.is_empty());
        assert_eq!(chain[0].0, ProviderId::Anthropic);
        assert!(chain[0].1.starts_with("claude"));
    }

    #[test]
    fn tier_chain_fast_starts_with_groq() {
        let chain = tier_chain("fast");
        assert_eq!(chain[0].0, ProviderId::Groq);
        assert!(chain[0].1.contains("llama"));
    }

    #[test]
    fn tier_chain_long_uses_long_context_models() {
        let chain = tier_chain("long");
        // Long-context tier MUST start with DeepSeek-chat (1M ctx) or
        // a comparable long-context model.
        assert_eq!(chain[0].0, ProviderId::DeepSeek);
    }

    #[test]
    fn tier_chain_unknown_returns_default() {
        let unknown = tier_chain("nonsense");
        let default = tier_chain("default");
        // Both should produce identical chains so callers get a safe fallback.
        let unknown_ids: Vec<_> = unknown.iter().map(|(p, _)| *p).collect();
        let default_ids: Vec<_> = default.iter().map(|(p, _)| *p).collect();
        assert_eq!(unknown_ids, default_ids);
    }

    #[test]
    fn tier_chain_all_have_ollama_fallback() {
        // Every production tier (except long which already truncates) must
        // include Ollama as a local fallback so the system stays responsive
        // when every cloud provider is down.
        for tier in &["critical", "deep", "long", "default", "fast"] {
            let chain = tier_chain(tier);
            let has_ollama = chain.iter().any(|(p, _)| *p == ProviderId::Ollama);
            assert!(has_ollama, "tier {tier} missing Ollama fallback");
        }
    }

    // ── is_transient ──────────────────────────────────────────────────────

    #[test]
    fn is_transient_recognises_timeouts_and_5xx() {
        assert!(is_transient("request timed out"));
        assert!(is_transient("HTTP status 503 Service Unavailable"));
        assert!(is_transient("502 Bad Gateway"));
        assert!(is_transient("connection refused"));
        assert!(is_transient("rate limit exceeded"));
        assert!(is_transient("429 Too Many Requests"));
    }

    #[test]
    fn is_transient_not_transient_4xx_or_validation() {
        assert!(!is_transient("400 Bad Request"));
        assert!(!is_transient("401 Unauthorized"));
        assert!(!is_transient("403 Forbidden"));
        assert!(!is_transient("malformed JSON"));
        assert!(!is_transient("invalid api key"));
    }

    // ── default_breakers ──────────────────────────────────────────────────

    #[test]
    fn default_breakers_covers_all_five_providers() {
        let m = default_breakers();
        for pid in &[
            ProviderId::DeepSeek,
            ProviderId::Groq,
            ProviderId::Anthropic,
            ProviderId::Gemini,
            ProviderId::Ollama,
        ] {
            assert!(m.contains_key(pid), "breaker for {pid:?} missing");
        }
    }

    #[test]
    fn default_breakers_initial_state_closed() {
        let m = default_breakers();
        for pid in &[
            ProviderId::DeepSeek,
            ProviderId::Groq,
            ProviderId::Anthropic,
            ProviderId::Gemini,
            ProviderId::Ollama,
        ] {
            let cb = m.get(pid).expect("breaker present");
            // CLOSED state means before_call returns Ok.
            let clock = WallClock;
            assert!(cb.before_call(&clock).is_ok(), "{pid:?} starts CLOSED");
        }
    }

    // ── default_limiters ──────────────────────────────────────────────────

    #[test]
    fn default_limiters_covers_all_five_providers() {
        let clock = WallClock;
        let m = default_limiters(&clock);
        for pid in &[
            ProviderId::DeepSeek,
            ProviderId::Groq,
            ProviderId::Anthropic,
            ProviderId::Gemini,
            ProviderId::Ollama,
        ] {
            assert!(m.contains_key(pid), "limiter for {pid:?} missing");
        }
    }

    #[test]
    fn default_limiters_initial_burst_allows_calls() {
        let clock = WallClock;
        let m = default_limiters(&clock);
        // Each provider should grant at least one token at startup.
        for pid in &[
            ProviderId::DeepSeek,
            ProviderId::Groq,
            ProviderId::Anthropic,
            ProviderId::Gemini,
            ProviderId::Ollama,
        ] {
            let lim = m.get(pid).expect("limiter present");
            let r = lim.try_acquire(1, &clock);
            assert!(matches!(r, AcquireResult::Granted), "{pid:?} burst rejected");
        }
    }
}
