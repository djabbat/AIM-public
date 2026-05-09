//! aim-writer — научное письмо: peer review, edit, cover letter,
//! response-to-reviewers, md→docx pipeline.
//!
//! Port of `agents/writer.py`. The Python version delegates LLM calls
//! to `llm.py` and citation checks to `tools.literature`. In Rust both
//! collaborators sit behind traits ([`Llm`] + [`CitationVerifier`]) so
//! every code path is testable without network or pandoc.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum WriterError {
    #[error("llm error: {0}")]
    Llm(String),
    #[error("converter error: {0}")]
    Converter(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, WriterError>;

// ── system prompts (verbatim from Python) ───────────────────────────────────

pub const SYSTEM_PEER_REVIEW: &str = "You are a senior scientific editor performing peer review.\n\
- Identify methodology concerns, statistical issues, missing controls.\n\
- Flag overstatements or claims not supported by data shown.\n\
- Suggest specific revisions; do NOT rewrite the paper.\n\
- Score: novelty (1-5), rigor (1-5), clarity (1-5), with one-line justification each.\n\
- Final recommendation: accept / minor revision / major revision / reject.\n\
- NEVER fabricate citations. If you reference a paper, use only ones already cited in the manuscript.";

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EditMode {
    Tighten,
    Academic,
    TranslateEn,
    Abstract,
    Polish,
}

impl EditMode {
    pub fn parse(s: &str) -> Self {
        match s {
            "academic" => Self::Academic,
            "translate-en" => Self::TranslateEn,
            "abstract" => Self::Abstract,
            "polish" => Self::Polish,
            _ => Self::Tighten,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Tighten => "tighten",
            Self::Academic => "academic",
            Self::TranslateEn => "translate-en",
            Self::Abstract => "abstract",
            Self::Polish => "polish",
        }
    }

    pub fn system_prompt(&self) -> &'static str {
        match self {
            Self::Tighten => "Tighten this prose: remove redundancy, prefer active voice, keep all facts. Do not add new claims.",
            Self::Academic => "Rewrite in formal academic English suitable for a peer-reviewed journal. Do not change meaning.",
            Self::TranslateEn => "Translate to clear academic English. Preserve technical terminology.",
            Self::Abstract => "Compress this section into a 250-word structured abstract: Background / Methods / Results / Conclusions.",
            Self::Polish => "Light copy-edit: grammar, punctuation, hyphenation. Mark every change with [CHG].",
        }
    }
}

// ── LLM tier (trait) ────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LlmTier {
    Default,
    Long,
    Deep,
}

pub trait Llm: Send + Sync {
    fn complete(
        &self,
        tier: LlmTier,
        system: &str,
        prompt: &str,
        lang: &str,
    ) -> Result<String>;
}

// ── citation verifier ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CitationReport {
    pub text: String,
    pub verified: Vec<String>,
    pub rejected: Vec<RejectedCitation>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RejectedCitation {
    pub kind: String,
    pub value: String,
}

pub trait CitationVerifier: Send + Sync {
    /// `mode` ∈ {"annotate", "strip"}; production binds to tools.literature.
    fn enforce(&self, text: &str, mode: &str) -> Result<CitationReport>;
}

/// Pass-through verifier — returns `text` unchanged with no rejected entries.
pub struct PassThroughVerifier;

impl CitationVerifier for PassThroughVerifier {
    fn enforce(&self, text: &str, _mode: &str) -> Result<CitationReport> {
        Ok(CitationReport {
            text: text.to_string(),
            ..Default::default()
        })
    }
}

// ── docx converter ──────────────────────────────────────────────────────────

pub trait DocxConverter: Send + Sync {
    fn convert(&self, md_path: &std::path::Path, docx_path: &std::path::Path) -> Result<PathBuf>;
}

// ── citation pre-check ──────────────────────────────────────────────────────

/// Cheap regex pre-check: does the text mention a PMID or DOI? Mirrors
/// Python `_strip_unverified_citations`'s gate.
pub fn has_citation_markers(text: &str) -> bool {
    let re = regex::Regex::new(r"(?i)\bPMID[:\s]*\d+|\b10\.\d{4,9}/").expect("regex compiles");
    re.is_match(text)
}

/// Annotate unverified PMID/DOI markers using the pluggable verifier. If the
/// text contains no markers, returns it unchanged. If verification fails,
/// returns the text untouched (matches Python's "skip on error" stance).
pub fn strip_unverified_citations(text: &str, verifier: &dyn CitationVerifier) -> String {
    if !has_citation_markers(text) {
        return text.to_string();
    }
    match verifier.enforce(text, "annotate") {
        Ok(rep) => rep.text,
        Err(_) => text.to_string(),
    }
}

// ── writer ──────────────────────────────────────────────────────────────────

pub struct Writer<'a> {
    pub llm: &'a dyn Llm,
    pub verifier: &'a dyn CitationVerifier,
}

impl<'a> Writer<'a> {
    pub fn new(llm: &'a dyn Llm, verifier: &'a dyn CitationVerifier) -> Self {
        Self { llm, verifier }
    }

    /// Peer review (DS-V4-pro tier).
    pub fn review(&self, text: &str, focus: &str, lang: &str) -> Result<String> {
        let prompt = format!(
            "Perform a {} of the following manuscript section. Output language: {}.\n\n=== MANUSCRIPT ===\n{}\n=== END ===",
            focus, lang, text
        );
        let out = self.llm.complete(LlmTier::Deep, SYSTEM_PEER_REVIEW, &prompt, lang)?;
        Ok(strip_unverified_citations(&out, self.verifier))
    }

    /// Stylistic edit using one of the canned modes.
    pub fn edit(&self, text: &str, mode: EditMode, lang: &str) -> Result<String> {
        let prompt = format!(
            "=== INPUT ===\n{}\n=== END ===\n\nApply: {}",
            text,
            mode.as_str()
        );
        let out = self
            .llm
            .complete(LlmTier::Default, mode.system_prompt(), &prompt, lang)?;
        Ok(strip_unverified_citations(&out, self.verifier))
    }

    /// Cover letter for journal submission. Default tier.
    pub fn cover_letter(
        &self,
        manuscript: &str,
        journal: &str,
        author: &str,
        lang: &str,
    ) -> Result<String> {
        let truncated: String = manuscript.chars().take(6000).collect();
        let sys = "You are drafting a cover letter for a journal submission. \
                   1 page max. Sections: opening salutation; one-paragraph summary \
                   of the contribution; one-paragraph fit-with-the-journal argument; \
                   competing-interests + funding statement; closing.";
        let prompt = format!(
            "Journal: {}\nAuthor: {}\n\n=== MANUSCRIPT ABSTRACT/INTRO ===\n{}\n=== END ===",
            journal, author, truncated
        );
        self.llm.complete(LlmTier::Default, sys, &prompt, lang)
    }

    /// Long-context response-to-reviewers letter.
    pub fn response_to_reviewers(&self, manuscript: &str, reviews: &str, lang: &str) -> Result<String> {
        let truncated: String = manuscript.chars().take(8000).collect();
        let sys = "You are drafting a Response-to-Reviewers letter. \
                   For each reviewer comment: quote it, then give a substantive response, \
                   then state the exact revision made (or rebut with evidence). \
                   Be respectful but firm. Do NOT promise changes you cannot ground in \
                   the manuscript text. Never fabricate new citations.";
        let prompt = format!(
            "=== MANUSCRIPT EXCERPT ===\n{}\n=== END ===\n\n=== REVIEWERS ===\n{}\n=== END ===",
            truncated, reviews
        );
        let out = self.llm.complete(LlmTier::Long, sys, &prompt, lang)?;
        Ok(strip_unverified_citations(&out, self.verifier))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct EchoLlm {
        calls: Mutex<Vec<(LlmTier, String, String, String)>>,
        canned: Mutex<Option<String>>,
    }

    impl EchoLlm {
        fn with_response(s: &str) -> Self {
            Self {
                calls: Mutex::new(Vec::new()),
                canned: Mutex::new(Some(s.to_string())),
            }
        }
    }

    impl Llm for EchoLlm {
        fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String> {
            self.calls.lock().push((
                tier,
                system.to_string(),
                prompt.to_string(),
                lang.to_string(),
            ));
            Ok(self
                .canned
                .lock()
                .clone()
                .unwrap_or_else(|| format!("ECHO[{:?},{}]: {}", tier, lang, prompt)))
        }
    }

    struct AnnotatingVerifier {
        rejected: Vec<&'static str>,
    }
    impl CitationVerifier for AnnotatingVerifier {
        fn enforce(&self, text: &str, _mode: &str) -> Result<CitationReport> {
            let mut t = text.to_string();
            let mut rej = Vec::new();
            for v in &self.rejected {
                if t.contains(v) {
                    t = t.replace(v, &format!("{} [UNVERIFIED]", v));
                    rej.push(RejectedCitation {
                        kind: "PMID".into(),
                        value: (*v).into(),
                    });
                }
            }
            Ok(CitationReport {
                text: t,
                verified: Vec::new(),
                rejected: rej,
            })
        }
    }

    // ── EditMode ─────────────────────────────────────────────────────────────

    #[test]
    fn edit_mode_parse_known_values() {
        assert_eq!(EditMode::parse("academic"), EditMode::Academic);
        assert_eq!(EditMode::parse("translate-en"), EditMode::TranslateEn);
        assert_eq!(EditMode::parse("abstract"), EditMode::Abstract);
        assert_eq!(EditMode::parse("polish"), EditMode::Polish);
        assert_eq!(EditMode::parse("tighten"), EditMode::Tighten);
    }

    #[test]
    fn edit_mode_parse_unknown_falls_back_to_tighten() {
        assert_eq!(EditMode::parse("anything"), EditMode::Tighten);
    }

    #[test]
    fn edit_mode_system_prompts_distinct() {
        let modes = [
            EditMode::Tighten,
            EditMode::Academic,
            EditMode::TranslateEn,
            EditMode::Abstract,
            EditMode::Polish,
        ];
        let mut prompts: Vec<&str> = modes.iter().map(|m| m.system_prompt()).collect();
        prompts.sort();
        prompts.dedup();
        assert_eq!(prompts.len(), 5);
    }

    // ── has_citation_markers ────────────────────────────────────────────────

    #[test]
    fn detects_pmid_marker() {
        assert!(has_citation_markers("see PMID 12345"));
        assert!(has_citation_markers("(pmid:6789)"));
    }

    #[test]
    fn detects_doi_marker() {
        assert!(has_citation_markers("ref 10.1073/pnas.123"));
        assert!(has_citation_markers("DOI 10.1038/nature01234"));
    }

    #[test]
    fn no_markers_in_plain_text() {
        assert!(!has_citation_markers("just prose here"));
    }

    // ── strip_unverified_citations ──────────────────────────────────────────

    #[test]
    fn strip_passes_through_when_no_markers() {
        let v = AnnotatingVerifier { rejected: vec![] };
        assert_eq!(strip_unverified_citations("plain text", &v), "plain text");
    }

    #[test]
    fn strip_annotates_when_verifier_marks() {
        let v = AnnotatingVerifier {
            rejected: vec!["PMID 99999"],
        };
        let out = strip_unverified_citations("see PMID 99999", &v);
        assert!(out.contains("[UNVERIFIED]"));
    }

    #[test]
    fn strip_recovers_from_verifier_error() {
        struct BrokenVerifier;
        impl CitationVerifier for BrokenVerifier {
            fn enforce(&self, _text: &str, _mode: &str) -> Result<CitationReport> {
                Err(WriterError::Llm("boom".into()))
            }
        }
        let out = strip_unverified_citations("PMID 12345", &BrokenVerifier);
        assert_eq!(out, "PMID 12345");
    }

    // ── review ──────────────────────────────────────────────────────────────

    #[test]
    fn review_uses_deep_tier_and_peer_review_system() {
        let llm = EchoLlm::with_response("Novelty: 4");
        let v = PassThroughVerifier;
        let w = Writer::new(&llm, &v);
        let _ = w.review("manuscript text", "peer-review", "en").unwrap();
        let calls = llm.calls.lock();
        assert_eq!(calls[0].0, LlmTier::Deep);
        assert_eq!(calls[0].1, SYSTEM_PEER_REVIEW);
        assert!(calls[0].2.contains("=== MANUSCRIPT ==="));
        assert_eq!(calls[0].3, "en");
    }

    #[test]
    fn review_propagates_focus_and_lang() {
        let llm = EchoLlm::with_response("ok");
        let v = PassThroughVerifier;
        let w = Writer::new(&llm, &v);
        let _ = w.review("x", "structural-review", "ru").unwrap();
        let calls = llm.calls.lock();
        assert!(calls[0].2.contains("structural-review"));
        assert!(calls[0].2.contains("Output language: ru"));
    }

    // ── edit ────────────────────────────────────────────────────────────────

    #[test]
    fn edit_uses_default_tier_and_mode_system_prompt() {
        let llm = EchoLlm::with_response("polished");
        let v = PassThroughVerifier;
        let w = Writer::new(&llm, &v);
        let _ = w.edit("rough draft", EditMode::Polish, "en").unwrap();
        let calls = llm.calls.lock();
        assert_eq!(calls[0].0, LlmTier::Default);
        assert_eq!(calls[0].1, EditMode::Polish.system_prompt());
        assert!(calls[0].2.contains("Apply: polish"));
    }

    // ── cover_letter ────────────────────────────────────────────────────────

    #[test]
    fn cover_letter_truncates_manuscript_to_6000_chars() {
        let llm = EchoLlm::with_response("dear editor");
        let v = PassThroughVerifier;
        let w = Writer::new(&llm, &v);
        let huge = "x".repeat(10_000);
        w.cover_letter(&huge, "Cell", "Jaba Tkemaladze", "en").unwrap();
        let prompt = &llm.calls.lock()[0].2;
        // The "x..." block is at most 6000 chars
        let block_start = prompt.find("=== MANUSCRIPT").unwrap();
        let block_end = prompt.rfind("=== END ===").unwrap();
        let inner = &prompt[block_start..block_end];
        let xs = inner.chars().filter(|c| *c == 'x').count();
        assert_eq!(xs, 6000);
    }

    #[test]
    fn cover_letter_includes_journal_and_author() {
        let llm = EchoLlm::with_response("ok");
        let v = PassThroughVerifier;
        let w = Writer::new(&llm, &v);
        w.cover_letter("abs", "eLife", "Jaba", "en").unwrap();
        let prompt = &llm.calls.lock()[0].2;
        assert!(prompt.contains("Journal: eLife"));
        assert!(prompt.contains("Author: Jaba"));
    }

    // ── response_to_reviewers ───────────────────────────────────────────────

    #[test]
    fn response_uses_long_tier_and_truncates_8000() {
        let llm = EchoLlm::with_response("Reviewer 1 …");
        let v = PassThroughVerifier;
        let w = Writer::new(&llm, &v);
        let huge = "y".repeat(20_000);
        w.response_to_reviewers(&huge, "reviewer comments", "en").unwrap();
        let calls = llm.calls.lock();
        assert_eq!(calls[0].0, LlmTier::Long);
        let prompt = &calls[0].2;
        let ys = prompt.chars().filter(|c| *c == 'y').count();
        assert_eq!(ys, 8000);
        assert!(prompt.contains("=== REVIEWERS ==="));
    }

    #[test]
    fn response_strips_unverified_citations() {
        let llm = EchoLlm::with_response("we cite PMID 11111");
        let v = AnnotatingVerifier {
            rejected: vec!["PMID 11111"],
        };
        let w = Writer::new(&llm, &v);
        let out = w
            .response_to_reviewers("ms", "rev", "en")
            .unwrap();
        assert!(out.contains("[UNVERIFIED]"));
    }
}
