//! aim-speculative — draft+target speculative decoding.
//!
//! Port of `agents/speculative.py`. Uses a fast model (Groq) as the
//! **draft** to produce a quick candidate, then a stronger **target**
//! (DeepSeek-reasoner / Claude Opus) to validate or refine. Falls back to
//! a single-model call when the draft path fails.
//!
//! Trade-off: 1.5–2× speedup on long answers when the draft agrees with
//! the target's direction; otherwise overhead. Use when latency matters
//! more than nuance (interactive UI).
//!
//! ## Pluggable models
//! Both draft and target are [`Llm`] trait impls — production wires real
//! HTTP clients, tests inject [`StubLlm`].

use async_trait::async_trait;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SpeculativeError {
    #[error("target llm: {0}")]
    Target(String),
}

#[async_trait]
pub trait Llm: Send + Sync {
    async fn ask(&self, prompt: &str, system: &str) -> Result<String, String>;
}

/// Build the verification prompt that wraps the original prompt + draft
/// candidate. Exposed as a free function so callers / tests can assert
/// on its exact shape.
pub fn build_verify_prompt(prompt: &str, draft: &str) -> String {
    format!(
        "ЗАДАЧА:\n{prompt}\n\n━━━ DRAFT (от быстрой модели; может быть неточным) ━━━\n{draft}\n\n━━━ ИНСТРУКЦИЯ ━━━\nЕсли draft точен и полон — повтори его без изменений.\nЕсли есть мелкие неточности — исправь, сохранив структуру.\nЕсли draft принципиально неверный — напиши с нуля.\nВерни ТОЛЬКО окончательный ответ, без мета-комментариев."
    )
}

#[derive(Debug, Clone, Copy)]
pub struct SpeculativeOpts {
    pub draft_max_tokens: u32,
    pub target_max_tokens: u32,
}

impl Default for SpeculativeOpts {
    fn default() -> Self {
        Self {
            draft_max_tokens: 200,
            target_max_tokens: 4096,
        }
    }
}

/// Run draft → target. If the draft fails (network / quota / etc.), fall
/// back to a direct target call. Returns the **target's** answer (never
/// the raw draft) so callers always get target-quality output.
///
/// `draft` may be `None` to skip speculative decoding entirely (matches
/// the Python "no Groq key" path).
pub async fn speculative_generate(
    prompt: &str,
    system: &str,
    draft: Option<&dyn Llm>,
    target: &dyn Llm,
    _opts: &SpeculativeOpts,
) -> Result<String, SpeculativeError> {
    let Some(draft_llm) = draft else {
        return target
            .ask(prompt, system)
            .await
            .map_err(SpeculativeError::Target);
    };
    let draft_text = match draft_llm.ask(prompt, system).await {
        Ok(t) => t,
        Err(e) => {
            tracing::warn!("draft failed ({e}); fallback to direct target");
            return target
                .ask(prompt, system)
                .await
                .map_err(SpeculativeError::Target);
        }
    };
    let verify_prompt = build_verify_prompt(prompt, &draft_text);
    target
        .ask(&verify_prompt, system)
        .await
        .map_err(SpeculativeError::Target)
}

/// Test-friendly LLM stub backed by a response queue.
pub struct StubLlm {
    pub queue: parking_lot::Mutex<Vec<Result<String, String>>>,
    pub calls: parking_lot::Mutex<Vec<(String, String)>>,
}

impl StubLlm {
    pub fn new() -> Self {
        Self {
            queue: parking_lot::Mutex::new(Vec::new()),
            calls: parking_lot::Mutex::new(Vec::new()),
        }
    }
    pub fn push_ok(self, s: &str) -> Self {
        self.queue.lock().push(Ok(s.to_string()));
        self
    }
    pub fn push_err(self, e: &str) -> Self {
        self.queue.lock().push(Err(e.to_string()));
        self
    }
    pub fn calls(&self) -> Vec<(String, String)> {
        self.calls.lock().clone()
    }
}

impl Default for StubLlm {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Llm for StubLlm {
    async fn ask(&self, prompt: &str, system: &str) -> Result<String, String> {
        self.calls
            .lock()
            .push((prompt.to_string(), system.to_string()));
        let mut q = self.queue.lock();
        if q.is_empty() {
            return Err("stub queue exhausted".into());
        }
        q.remove(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn no_draft_falls_through_to_target() {
        let target = StubLlm::new().push_ok("target answer");
        let r = speculative_generate(
            "Q?",
            "",
            None,
            &target,
            &SpeculativeOpts::default(),
        )
        .await
        .unwrap();
        assert_eq!(r, "target answer");
        assert_eq!(target.calls().len(), 1);
        assert_eq!(target.calls()[0].0, "Q?", "no verify wrapper without draft");
    }

    #[tokio::test]
    async fn draft_then_target_verify() {
        let draft = StubLlm::new().push_ok("DRAFT TEXT");
        let target = StubLlm::new().push_ok("FINAL");
        let r = speculative_generate(
            "Compare A and B",
            "system_prompt",
            Some(&draft),
            &target,
            &SpeculativeOpts::default(),
        )
        .await
        .unwrap();
        assert_eq!(r, "FINAL");
        // Draft was called with the original prompt
        let dcalls = draft.calls();
        assert_eq!(dcalls[0].0, "Compare A and B");
        assert_eq!(dcalls[0].1, "system_prompt");
        // Target was called with the verify-wrapper that contains both
        // the original prompt and the draft text.
        let tcalls = target.calls();
        assert!(tcalls[0].0.contains("ЗАДАЧА:"));
        assert!(tcalls[0].0.contains("Compare A and B"));
        assert!(tcalls[0].0.contains("DRAFT TEXT"));
        assert_eq!(tcalls[0].1, "system_prompt");
    }

    #[tokio::test]
    async fn draft_failure_falls_back_to_direct_target() {
        let draft = StubLlm::new().push_err("groq 503");
        let target = StubLlm::new().push_ok("direct answer");
        let r = speculative_generate(
            "Q?",
            "",
            Some(&draft),
            &target,
            &SpeculativeOpts::default(),
        )
        .await
        .unwrap();
        assert_eq!(r, "direct answer");
        // Target got the *raw* prompt, not the verify wrapper
        let tcalls = target.calls();
        assert_eq!(tcalls[0].0, "Q?");
    }

    #[tokio::test]
    async fn target_failure_propagates() {
        let target = StubLlm::new().push_err("deepseek down");
        let r = speculative_generate("Q?", "", None, &target, &SpeculativeOpts::default()).await;
        assert!(matches!(r, Err(SpeculativeError::Target(_))));
    }

    #[tokio::test]
    async fn target_failure_after_draft_propagates() {
        let draft = StubLlm::new().push_ok("draft text");
        let target = StubLlm::new().push_err("deepseek down");
        let r = speculative_generate(
            "Q?",
            "",
            Some(&draft),
            &target,
            &SpeculativeOpts::default(),
        )
        .await;
        assert!(matches!(r, Err(SpeculativeError::Target(_))));
    }

    #[test]
    fn build_verify_prompt_shape() {
        let p = build_verify_prompt("solve X", "rough draft Y");
        assert!(p.contains("ЗАДАЧА:\nsolve X"));
        assert!(p.contains("DRAFT (от быстрой модели"));
        assert!(p.contains("rough draft Y"));
        assert!(p.contains("Верни ТОЛЬКО окончательный ответ"));
    }

    #[test]
    fn build_verify_prompt_handles_empty_draft() {
        let p = build_verify_prompt("X", "");
        assert!(p.contains("ЗАДАЧА:\nX"));
    }
}
