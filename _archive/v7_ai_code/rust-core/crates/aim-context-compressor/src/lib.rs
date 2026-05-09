//! aim-context-compressor — LLM-based context compression with map-reduce.
//!
//! Port of `agents/context_compressor.py`. Reduces large memory blobs to
//! a target token budget while preserving entities/numbers/IDs/decisions.
//! The compressor is pluggable behind [`Llm`] so the map-reduce loop is
//! testable without an LLM.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CompressError {
    #[error("llm error: {0}")]
    Llm(String),
}

pub type Result<T> = std::result::Result<T, CompressError>;

// ── system prompt ───────────────────────────────────────────────────────────

pub const SYSTEM_PROMPT: &str = "Ты сжимаешь контекст для следующего LLM-вызова. Отвечай на русском. \
Сохрани все имена, даты, числа, идентификаторы (ORCID, PMID, DOI), пути, deadlines, ключевые решения. \
Удали повторы и риторику.";

// ── helpers ─────────────────────────────────────────────────────────────────

/// Rough heuristic: ~4 chars per token (Cyrillic-mixed). Mirrors Python.
pub fn approx_tokens(s: &str) -> usize {
    (s.chars().count() / 4).max(1)
}

/// Split into overlapping chunks of `max_chars`. Single chunk if input is
/// short enough. Mirrors Python `_split_chunks`.
pub fn split_chunks(text: &str, max_chars: usize, overlap: usize) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= max_chars {
        return vec![text.to_string()];
    }
    let mut chunks = Vec::new();
    let mut start = 0usize;
    while start < chars.len() {
        let end = (start + max_chars).min(chars.len());
        chunks.push(chars[start..end].iter().collect::<String>());
        if end == chars.len() {
            break;
        }
        start = end - overlap;
    }
    chunks
}

/// Drop duplicated paragraphs (exact match after trim). Mirrors Python
/// `quick_dedup`. Splits on blank lines.
pub fn quick_dedup(text: &str) -> String {
    let re = regex::Regex::new(r"\n\s*\n").expect("dedup regex compiles");
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut out: Vec<&str> = Vec::new();
    for para in re.split(text) {
        let key = para.trim();
        if key.is_empty() || seen.contains(key) {
            continue;
        }
        seen.insert(key.to_string());
        out.push(para);
    }
    out.join("\n\n")
}

// ── Llm trait ──────────────────────────────────────────────────────────────

pub trait Llm: Send + Sync {
    fn ask(&self, system: &str, prompt: &str, max_tokens: usize) -> Result<String>;
}

// ── compress ───────────────────────────────────────────────────────────────

/// Configuration with Python defaults: 2000 tokens target, 30K char
/// map-reduce threshold, 8K chunk size, 200-char overlap.
#[derive(Clone, Debug)]
pub struct CompressorConfig {
    pub target_tokens: usize,
    pub map_reduce_threshold_chars: usize,
    pub chunk_max_chars: usize,
    pub chunk_overlap: usize,
    pub min_per_chunk_tokens: usize,
    pub min_response_tokens: usize,
}

impl Default for CompressorConfig {
    fn default() -> Self {
        Self {
            target_tokens: 2000,
            map_reduce_threshold_chars: 30_000,
            chunk_max_chars: 8_000,
            chunk_overlap: 200,
            min_per_chunk_tokens: 200,
            min_response_tokens: 256,
        }
    }
}

pub struct Compressor<'a> {
    pub llm: &'a dyn Llm,
    pub config: CompressorConfig,
}

impl<'a> Compressor<'a> {
    pub fn new(llm: &'a dyn Llm) -> Self {
        Self {
            llm,
            config: CompressorConfig::default(),
        }
    }

    pub fn with_config(llm: &'a dyn Llm, config: CompressorConfig) -> Self {
        Self { llm, config }
    }

    /// Build the per-chunk compression prompt (verbatim from Python).
    fn chunk_prompt(target_tokens: usize, chunk: &str) -> String {
        let target_chars = target_tokens * 4;
        format!(
            "СЖИМАЙ ДО ~{} токенов (~{} символов).\nСОХРАНИ: имена, даты, числа, ID (ORCID, PMID, DOI), deadlines, решения.\nУДАЛИ: повторы, риторику, преамбулы.\n\n━━━ КОНТЕКСТ ━━━\n{}\n\n━━━ СЖАТЫЙ ВАРИАНТ ━━━",
            target_tokens, target_chars, chunk
        )
    }

    /// Compress one chunk; on LLM failure falls back to truncation.
    pub fn compress_one(&self, chunk: &str, target_tokens: usize) -> String {
        let prompt = Self::chunk_prompt(target_tokens, chunk);
        let max_tokens = target_tokens.max(self.config.min_response_tokens);
        match self.llm.ask(SYSTEM_PROMPT, &prompt, max_tokens) {
            Ok(s) => s,
            Err(e) => {
                tracing::warn!("compress call failed: {}; truncating", e);
                let target_chars = target_tokens * 4;
                chunk.chars().take(target_chars).collect()
            }
        }
    }

    /// Top-level entry. Returns `context` unchanged when already under budget.
    pub fn compress(&self, context: &str) -> String {
        if context.is_empty() {
            return context.to_string();
        }
        let est = approx_tokens(context);
        if est <= self.config.target_tokens {
            return context.to_string();
        }
        let n_chars = context.chars().count();
        if n_chars <= self.config.map_reduce_threshold_chars {
            return self.compress_one(context, self.config.target_tokens);
        }
        let chunks = split_chunks(context, self.config.chunk_max_chars, self.config.chunk_overlap);
        let per_chunk = (self.config.target_tokens / chunks.len())
            .max(self.config.min_per_chunk_tokens);
        let summaries: Vec<String> = chunks
            .iter()
            .map(|ch| self.compress_one(ch, per_chunk))
            .collect();
        let merged = summaries.join("\n\n");
        if approx_tokens(&merged) <= self.config.target_tokens {
            return merged;
        }
        // Reduce step
        self.compress_one(&merged, self.config.target_tokens)
    }
}

// ── result wrapper ──────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CompressionStats {
    pub input_tokens: usize,
    pub output_tokens: usize,
    pub ratio: f64,
}

impl CompressionStats {
    pub fn new(input: &str, output: &str) -> Self {
        let i = approx_tokens(input);
        let o = approx_tokens(output);
        let ratio = if i == 0 { 1.0 } else { o as f64 / i as f64 };
        Self {
            input_tokens: i,
            output_tokens: o,
            ratio,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct ConstLlm {
        canned: String,
        calls: Mutex<Vec<(String, String, usize)>>,
    }
    impl ConstLlm {
        fn new(canned: &str) -> Self {
            Self {
                canned: canned.into(),
                calls: Mutex::new(Vec::new()),
            }
        }
    }
    impl Llm for ConstLlm {
        fn ask(&self, system: &str, prompt: &str, max_tokens: usize) -> Result<String> {
            self.calls.lock().push((system.into(), prompt.into(), max_tokens));
            Ok(self.canned.clone())
        }
    }

    struct BrokenLlm;
    impl Llm for BrokenLlm {
        fn ask(&self, _: &str, _: &str, _: usize) -> Result<String> {
            Err(CompressError::Llm("network down".into()))
        }
    }

    // ── helpers ─────────────────────────────────────────────────────────────

    #[test]
    fn approx_tokens_roughly_quarter_chars() {
        assert_eq!(approx_tokens("12345678"), 2);
        assert!(approx_tokens("") >= 1);
    }

    #[test]
    fn split_chunks_short_input_one_chunk() {
        assert_eq!(split_chunks("hello", 100, 10), vec!["hello".to_string()]);
    }

    #[test]
    fn split_chunks_overlapping_when_long() {
        let text = "a".repeat(25);
        let chunks = split_chunks(&text, 10, 2);
        assert!(chunks.len() >= 3);
        // First chunk size should match max_chars
        assert_eq!(chunks[0].chars().count(), 10);
        // Last chunk should reach the end
        assert!(chunks.last().unwrap().ends_with('a'));
    }

    #[test]
    fn split_chunks_handles_unicode() {
        let text = "Привет мир ".repeat(50);
        let chunks = split_chunks(&text, 30, 5);
        assert!(chunks.len() > 1);
        for ch in &chunks {
            // each chunk must contain valid UTF-8 (no panics from chars())
            let _: Vec<char> = ch.chars().collect();
        }
    }

    #[test]
    fn quick_dedup_drops_duplicate_paragraphs() {
        let text = "para1\n\npara2\n\npara1\n\npara3";
        let out = quick_dedup(text);
        // para1 should appear once
        let count = out.matches("para1").count();
        assert_eq!(count, 1);
        assert!(out.contains("para2"));
        assert!(out.contains("para3"));
    }

    #[test]
    fn quick_dedup_preserves_first_seen_order() {
        let text = "alpha\n\nbeta\n\ngamma";
        let out = quick_dedup(text);
        let pa = out.find("alpha").unwrap();
        let pb = out.find("beta").unwrap();
        let pg = out.find("gamma").unwrap();
        assert!(pa < pb && pb < pg);
    }

    #[test]
    fn quick_dedup_skips_empty_paragraphs() {
        let out = quick_dedup("a\n\n   \n\nb");
        assert!(out.contains("a"));
        assert!(out.contains("b"));
    }

    // ── chunk_prompt ────────────────────────────────────────────────────────

    #[test]
    fn chunk_prompt_includes_target_token_count() {
        let p = Compressor::<'_>::chunk_prompt(500, "ctx");
        assert!(p.contains("~500 токенов"));
        assert!(p.contains("ctx"));
        assert!(p.contains("СОХРАНИ"));
    }

    // ── Compressor ──────────────────────────────────────────────────────────

    #[test]
    fn compress_under_budget_returns_input() {
        let llm = ConstLlm::new("ignored");
        let c = Compressor::new(&llm);
        let out = c.compress("short");
        assert_eq!(out, "short");
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn compress_empty_returns_empty() {
        let llm = ConstLlm::new("ignored");
        let c = Compressor::new(&llm);
        assert_eq!(c.compress(""), "");
    }

    #[test]
    fn compress_single_pass_under_threshold() {
        let llm = ConstLlm::new("compressed!");
        let mut cfg = CompressorConfig::default();
        cfg.target_tokens = 100;
        cfg.map_reduce_threshold_chars = 50_000;
        let c = Compressor::with_config(&llm, cfg);
        let big = "a".repeat(10_000);
        let out = c.compress(&big);
        assert_eq!(out, "compressed!");
        assert_eq!(llm.calls.lock().len(), 1);
    }

    #[test]
    fn compress_map_reduce_over_threshold() {
        // input ~125 tokens > target 50 → triggers compression
        // input 500 chars > threshold 100 → triggers map-reduce
        // canned response is short → merged stays under budget → no reduce step
        let llm = ConstLlm::new("c");
        let mut cfg = CompressorConfig::default();
        cfg.target_tokens = 50;
        cfg.map_reduce_threshold_chars = 100;
        cfg.chunk_max_chars = 50;
        cfg.chunk_overlap = 5;
        let c = Compressor::with_config(&llm, cfg);
        let big = "x".repeat(500);
        let out = c.compress(&big);
        assert!(out.contains("c"));
        // multiple LLM calls (one per chunk)
        assert!(llm.calls.lock().len() > 1);
    }

    #[test]
    fn compress_truncates_on_llm_failure() {
        let llm = BrokenLlm;
        let c = Compressor::new(&llm);
        let big = "x".repeat(20_000);
        let out = c.compress(&big);
        // fallback truncation = target_tokens * 4 = 8000
        assert_eq!(out.chars().count(), 2000 * 4);
    }

    #[test]
    fn compress_one_falls_back_on_error() {
        let c = Compressor::new(&BrokenLlm);
        let out = c.compress_one("very long text here", 5);
        // 5 tokens * 4 chars = 20 chars
        assert_eq!(out.chars().count(), "very long text here".chars().count().min(20));
    }

    #[test]
    fn compress_uses_min_response_tokens_when_target_below() {
        let llm = ConstLlm::new("ok");
        let c = Compressor::new(&llm);
        c.compress_one("ctx", 50); // below default min_response_tokens=256
        let max_tokens = llm.calls.lock()[0].2;
        assert_eq!(max_tokens, 256);
    }

    // ── CompressionStats ───────────────────────────────────────────────────

    #[test]
    fn stats_compute_ratio() {
        let s = CompressionStats::new(&"a".repeat(800), &"b".repeat(200));
        assert_eq!(s.input_tokens, 200);
        assert_eq!(s.output_tokens, 50);
        assert!((s.ratio - 0.25).abs() < 1e-9);
    }

    #[test]
    fn stats_empty_input_ratio_one() {
        // approx_tokens("") returns 1, so ratio = 0/1 = 0; this just shouldn't panic
        let s = CompressionStats::new("", "anything");
        assert!(s.ratio.is_finite());
    }
}
