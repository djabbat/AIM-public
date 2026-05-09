use aim_llm::router::{provider_for_model, tier_chain};
use aim_llm::providers::ProviderId;

#[test]
fn maps_deepseek_models() {
    assert_eq!(provider_for_model("deepseek-chat"), Some(ProviderId::DeepSeek));
    assert_eq!(provider_for_model("deepseek-reasoner"), Some(ProviderId::DeepSeek));
}

#[test]
fn maps_anthropic_models() {
    assert_eq!(provider_for_model("claude-opus-4-7"), Some(ProviderId::Anthropic));
    assert_eq!(provider_for_model("claude-haiku-4-5-20251001"), Some(ProviderId::Anthropic));
}

#[test]
fn maps_gemini_models() {
    assert_eq!(provider_for_model("gemini-2.5-pro"), Some(ProviderId::Gemini));
}

#[test]
fn maps_groq_llama() {
    assert_eq!(provider_for_model("llama-3.3-70b-versatile"), Some(ProviderId::Groq));
}

#[test]
fn ollama_models() {
    assert_eq!(provider_for_model("qwen2.5:7b"), Some(ProviderId::Ollama));
    assert_eq!(provider_for_model("phi3"), Some(ProviderId::Ollama));
}

#[test]
fn unknown_model_returns_none() {
    assert_eq!(provider_for_model("totally-unknown-xyz"), None);
}

#[test]
fn tier_chain_critical_starts_with_anthropic() {
    let c = tier_chain("critical");
    assert_eq!(c.first().map(|(p, _)| *p), Some(ProviderId::Anthropic));
    assert!(c.iter().any(|(p, _)| *p == ProviderId::Ollama), "must include local fallback");
}

#[test]
fn tier_chain_fast_starts_with_groq() {
    let c = tier_chain("fast");
    assert_eq!(c.first().map(|(p, _)| *p), Some(ProviderId::Groq));
}

#[test]
fn tier_chain_default() {
    let c = tier_chain("default");
    assert!(!c.is_empty());
    let unknown = tier_chain("xyz");
    assert_eq!(c, unknown, "unknown tier falls back to default");
}
