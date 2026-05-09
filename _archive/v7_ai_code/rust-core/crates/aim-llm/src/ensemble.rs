//! Ensemble + self-critique. Replaces agents/ensemble.py + agents/reflexion.py
//! self-critique pass.
//!
//! `/v1/ensemble` — runs the same prompt against N providers/models in parallel,
//! computes pairwise Jaccard k-shingle agreement, and:
//!   - if max-pair agreement ≥ threshold → returns the longest answer as consensus,
//!   - else → calls an "adjudicator" model with the candidates and returns its
//!     synthesis.
//!
//! `/v1/critique` — single-shot self-critique. Given an answer + original prompt,
//! ask a (preferably stronger) model to spot fabricated facts/refs and either
//! return "ok" or a corrected version.

use crate::providers::{Provider, ProviderId};
use crate::router::{ChatMessage, RouterState};
use aim_common::{ApiError, ApiResult};
use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashSet;

#[derive(Deserialize)]
pub struct EnsembleReq {
    pub messages: Vec<ChatMessage>,
    /// Models to try in parallel. Each entry like {provider:"deepseek", model:"deepseek-reasoner"}
    /// If omitted, picks the default critical-tier chain.
    #[serde(default)] pub members: Option<Vec<Member>>,
    /// Jaccard threshold for declaring consensus (0.0..1.0). Default 0.35.
    #[serde(default)] pub threshold: Option<f32>,
}

#[derive(Deserialize, Clone)]
pub struct Member {
    pub provider: ProviderId,
    pub model: String,
}

#[derive(Serialize)]
pub struct EnsembleResp {
    pub candidates: Vec<Candidate>,
    pub max_agreement: f32,
    pub mode: String,            // "consensus" | "adjudicated"
    pub final_answer: String,
}

#[derive(Serialize, Clone)]
pub struct Candidate {
    pub provider: ProviderId,
    pub model: String,
    pub ok: bool,
    pub answer: Option<String>,
    pub error: Option<String>,
}

const ADJUDICATOR_PROMPT: &str = r#"You receive several candidate answers to the same user prompt.
Your job: synthesise ONE final answer that takes the strongest, most-supported claims from each,
flagging anything fabricated or unsupported. Be concise. If candidates fundamentally disagree on a
factual claim, say so explicitly. Output only the final answer text."#;

pub async fn ensemble(
    State(state): State<RouterState>,
    Json(req): Json<EnsembleReq>,
) -> ApiResult<Json<EnsembleResp>> {
    if req.messages.is_empty() {
        return Err(ApiError::BadRequest("messages cannot be empty".into()));
    }
    let threshold = req.threshold.unwrap_or(0.35);

    let members: Vec<Member> = req.members.unwrap_or_else(default_members);

    let futs = members.iter().map(|m| {
        let messages = req.messages.clone();
        let member = m.clone();
        let providers = state.providers.clone();
        async move {
            let provider = providers.iter().find(|p| p.id() == member.provider);
            match provider {
                None => Candidate { provider: member.provider, model: member.model.clone(),
                    ok: false, answer: None, error: Some("provider not loaded".into()) },
                Some(p) if !p.is_ready() => Candidate { provider: member.provider, model: member.model.clone(),
                    ok: false, answer: None, error: Some("not ready (no API key?)".into()) },
                Some(p) => match p.complete(&messages, &member.model).await {
                    Ok(a)  => Candidate { provider: member.provider, model: member.model, ok: true,  answer: Some(a),  error: None },
                    Err(e) => Candidate { provider: member.provider, model: member.model, ok: false, answer: None, error: Some(e.to_string()) },
                }
            }
        }
    });

    let candidates: Vec<Candidate> = futures::future::join_all(futs).await;

    let answers: Vec<&str> = candidates.iter()
        .filter_map(|c| c.answer.as_deref())
        .collect();

    if answers.is_empty() {
        return Err(ApiError::Upstream("ensemble: all members failed".into()));
    }

    let max_agreement = if answers.len() < 2 { 1.0 } else {
        let mut max = 0.0f32;
        for i in 0..answers.len() {
            for j in (i + 1)..answers.len() {
                let a = jaccard_kshingle(answers[i], answers[j], 5);
                if a > max { max = a; }
            }
        }
        max
    };

    let (mode, final_answer) = if max_agreement >= threshold {
        let longest = answers.iter().max_by_key(|s| s.len()).unwrap().to_string();
        ("consensus".to_string(), longest)
    } else {
        let mut adjud_msgs = req.messages.clone();
        let cands_text = candidates.iter().filter_map(|c| {
            c.answer.as_ref().map(|a| format!("[{:?} / {}]\n{}", c.provider, c.model, a))
        }).collect::<Vec<_>>().join("\n\n---\n\n");
        adjud_msgs.push(ChatMessage {
            role: "user".into(),
            content: format!("Candidate answers:\n\n{cands_text}\n\n{ADJUDICATOR_PROMPT}")
        });
        let adjudicator = pick_adjudicator(&state).ok_or_else(||
            ApiError::Upstream("ensemble: no adjudicator available".into()))?;
        let synth = adjudicator.complete(&adjud_msgs, adjudicator.default_model()).await
            .map_err(|e| ApiError::Upstream(format!("adjudicator: {e}")))?;
        ("adjudicated".to_string(), synth)
    };

    Ok(Json(EnsembleResp { candidates, max_agreement, mode, final_answer }))
}

#[derive(Deserialize)]
pub struct CritiqueReq {
    pub prompt: String,
    pub answer: String,
    #[serde(default)] pub provider: Option<ProviderId>,
    #[serde(default)] pub model: Option<String>,
}

#[derive(Serialize)]
pub struct CritiqueResp {
    pub ok: bool,
    pub revised_answer: String,
    pub critique: String,
}

const CRITIQUE_PROMPT: &str = r#"You are a careful adversarial reviewer. Given a prompt and a candidate answer,
identify any fabricated facts, unsupported claims, or hallucinated citations. Then either:
  - reply with the answer unchanged if it is solid, or
  - reply with a corrected version that fixes errors.
Format your reply as:
  CRITIQUE: <one paragraph>
  REVISED: <the answer text>"#;

pub async fn critique(
    State(state): State<RouterState>,
    Json(req): Json<CritiqueReq>,
) -> ApiResult<Json<CritiqueResp>> {
    let provider = match req.provider {
        Some(pid) => state.provider_by_id(pid),
        None => pick_adjudicator(&state),
    }.ok_or_else(|| ApiError::Upstream("critique: no provider".into()))?;
    let model = req.model.as_deref().unwrap_or(provider.default_model());

    let messages = vec![
        ChatMessage { role: "system".into(), content: CRITIQUE_PROMPT.into() },
        ChatMessage { role: "user".into(),
            content: format!("PROMPT:\n{}\n\nANSWER:\n{}", req.prompt, req.answer) },
    ];

    let raw = provider.complete(&messages, model).await
        .map_err(|e| ApiError::Upstream(e.to_string()))?;

    let (critique_text, revised) = parse_critique(&raw, &req.answer);
    let ok = critique_text.to_lowercase().contains("solid")
          || critique_text.to_lowercase().contains("no issues")
          || revised == req.answer;

    Ok(Json(CritiqueResp { ok, revised_answer: revised, critique: critique_text }))
}

fn parse_critique(raw: &str, fallback_answer: &str) -> (String, String) {
    let mut critique = String::new();
    let mut revised = fallback_answer.to_string();
    let mut mode = None;
    for line in raw.lines() {
        if let Some(rest) = line.strip_prefix("CRITIQUE:") {
            mode = Some("c");
            critique.push_str(rest.trim());
        } else if let Some(rest) = line.strip_prefix("REVISED:") {
            mode = Some("r");
            revised = rest.trim().to_string();
        } else {
            match mode {
                Some("c") => { critique.push('\n'); critique.push_str(line); }
                Some("r") => { revised.push('\n'); revised.push_str(line); }
                _ => {}
            }
        }
    }
    (critique.trim().to_string(), revised.trim().to_string())
}

fn pick_adjudicator(state: &RouterState) -> Option<&dyn Provider> {
    // Prefer Anthropic > Gemini > DeepSeek > others.
    for pid in [ProviderId::Anthropic, ProviderId::Gemini, ProviderId::DeepSeek, ProviderId::Groq, ProviderId::Ollama] {
        if let Some(p) = state.provider_by_id(pid) {
            if p.is_ready() { return Some(p); }
        }
    }
    state.first_ready()
}

fn default_members() -> Vec<Member> {
    vec![
        Member { provider: ProviderId::Anthropic, model: "claude-haiku-4-5-20251001".into() },
        Member { provider: ProviderId::DeepSeek,  model: "deepseek-chat".into() },
        Member { provider: ProviderId::Gemini,    model: "gemini-2.5-flash".into() },
    ]
}

/// k-shingle Jaccard similarity over lowercased word tokens.
fn jaccard_kshingle(a: &str, b: &str, k: usize) -> f32 {
    let sa = shingles(a, k);
    let sb = shingles(b, k);
    if sa.is_empty() && sb.is_empty() { return 1.0; }
    let inter: usize = sa.intersection(&sb).count();
    let union: usize = sa.union(&sb).count();
    if union == 0 { 0.0 } else { inter as f32 / union as f32 }
}

fn shingles(s: &str, k: usize) -> HashSet<Vec<String>> {
    let toks: Vec<String> = s.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|t| !t.is_empty())
        .map(String::from)
        .collect();
    if toks.len() < k { return HashSet::new(); }
    toks.windows(k).map(|w| w.to_vec()).collect()
}

#[allow(dead_code)]
fn _force_use_json() { let _ = json!({}); }

// Re-export for test suite (public so integration tests can hit it).
pub fn jaccard_for_test(a: &str, b: &str, k: usize) -> f32 { jaccard_kshingle(a, b, k) }

#[cfg(test)]
mod tests {
    use super::*;

    // ── shingles ──────────────────────────────────────────────────────────

    #[test]
    fn shingles_empty_input() {
        let s = shingles("", 3);
        assert!(s.is_empty());
    }

    #[test]
    fn shingles_too_short() {
        // "hello world" is 2 tokens; k=3 → no shingles.
        let s = shingles("hello world", 3);
        assert!(s.is_empty());
    }

    #[test]
    fn shingles_lowercases_and_strips_punct() {
        let s = shingles("Hello, World! How are you?", 2);
        // 5 tokens (hello world how are you) → 4 bigrams
        assert_eq!(s.len(), 4);
        assert!(s.contains(&vec!["hello".into(), "world".into()]));
    }

    // ── jaccard_kshingle ──────────────────────────────────────────────────

    #[test]
    fn jaccard_identical_strings() {
        let j = jaccard_kshingle("the quick brown fox", "the quick brown fox", 2);
        assert!((j - 1.0).abs() < 1e-6);
    }

    #[test]
    fn jaccard_disjoint_strings() {
        let j = jaccard_kshingle("alpha beta gamma", "delta epsilon zeta", 2);
        assert_eq!(j, 0.0);
    }

    #[test]
    fn jaccard_partial_overlap() {
        // "the quick brown fox" vs "the brown fox jumps" — share bigram (brown,fox)
        let j = jaccard_kshingle("the quick brown fox", "the brown fox jumps", 2);
        assert!(j > 0.0 && j < 1.0, "expected partial overlap, got {j}");
    }

    #[test]
    fn jaccard_both_empty_returns_one() {
        // edge case: both empty → similarity defined as 1 (per impl)
        assert_eq!(jaccard_kshingle("", "", 2), 1.0);
    }

    #[test]
    fn jaccard_one_empty_returns_zero() {
        assert_eq!(jaccard_kshingle("", "the quick brown fox jumps", 2), 0.0);
    }

    #[test]
    fn jaccard_for_test_alias_works() {
        let j = jaccard_for_test("a b c d", "a b c d", 2);
        assert!((j - 1.0).abs() < 1e-6);
    }

    // ── default_members ───────────────────────────────────────────────────

    #[test]
    fn default_members_has_three_diverse_providers() {
        let m = default_members();
        assert_eq!(m.len(), 3);
        let pids: Vec<_> = m.iter().map(|x| x.provider).collect();
        assert!(pids.contains(&ProviderId::Anthropic));
        assert!(pids.contains(&ProviderId::DeepSeek));
        assert!(pids.contains(&ProviderId::Gemini));
    }

    #[test]
    fn default_members_all_have_model_strings() {
        for m in default_members() {
            assert!(!m.model.is_empty(), "{:?} member missing model", m.provider);
        }
    }

    // ── parse_critique ────────────────────────────────────────────────────

    #[test]
    fn parse_critique_extracts_critique_and_revised() {
        let raw = "CRITIQUE: factual error in para 2\nREVISED: corrected version follows\n";
        let (c, r) = parse_critique(raw, "fallback");
        assert_eq!(c, "factual error in para 2");
        assert_eq!(r, "corrected version follows");
    }

    #[test]
    fn parse_critique_falls_back_to_original_when_no_revised() {
        let raw = "CRITIQUE: minor nit, otherwise ok";
        let (c, r) = parse_critique(raw, "the original answer");
        assert_eq!(c, "minor nit, otherwise ok");
        assert_eq!(r, "the original answer");
    }

    #[test]
    fn parse_critique_handles_multiline_blocks() {
        let raw = "CRITIQUE: line1\nline2 of critique\nREVISED: rev line1\nrev line2";
        let (c, r) = parse_critique(raw, "fb");
        assert!(c.contains("line1"));
        assert!(c.contains("line2 of critique"));
        assert!(r.contains("rev line1"));
        assert!(r.contains("rev line2"));
    }

    #[test]
    fn parse_critique_empty_raw_returns_fallback() {
        let (c, r) = parse_critique("", "fb-answer");
        assert_eq!(c, "");
        assert_eq!(r, "fb-answer");
    }

    #[test]
    fn parse_critique_unrecognised_format_returns_fallback() {
        let raw = "this is just some text without our markers";
        let (c, r) = parse_critique(raw, "fb-answer");
        assert_eq!(c, "");
        assert_eq!(r, "fb-answer");
    }
}
