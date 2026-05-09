//! aim-researcher — verified literature search & summarisation.
//!
//! Port of `agents/researcher.py`. Principle: never trust the LLM with
//! DOIs/PMIDs. The LLM is used only for query formulation and summary
//! prose; every citation passes through the [`Literature`] trait.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ResearcherError {
    #[error("llm error: {0}")]
    Llm(String),
    #[error("literature error: {0}")]
    Literature(String),
}

pub type Result<T> = std::result::Result<T, ResearcherError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Record {
    pub pmid: Option<String>,
    pub doi: Option<String>,
    pub title: Option<String>,
    pub journal: Option<String>,
    pub year: Option<String>,
    pub authors: Vec<String>,
}

impl Record {
    pub fn id_label(&self) -> String {
        if let Some(p) = &self.pmid {
            format!("PMID:{}", p)
        } else if let Some(d) = &self.doi {
            format!("doi:{}", d)
        } else {
            "?".to_string()
        }
    }
    pub fn first_author(&self) -> &str {
        self.authors.first().map(String::as_str).unwrap_or("?")
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Source {
    Pubmed,
    Crossref,
    Both,
}

impl Source {
    pub fn parse(s: &str) -> Self {
        match s {
            "crossref" => Self::Crossref,
            "both" => Self::Both,
            _ => Self::Pubmed,
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CitationReport {
    pub text: String,
    pub verified: Vec<String>,
    pub rejected: Vec<String>,
}

// ── traits ──────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LlmTier {
    Fast,
    Deep,
}

pub trait Llm: Send + Sync {
    fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String>;
}

pub trait Literature: Send + Sync {
    fn pubmed_search(&self, query: &str, n: usize) -> Result<Vec<Record>>;
    fn crossref_search(&self, query: &str, n: usize) -> Result<Vec<Record>>;
    fn enforce_citations(&self, text: &str, mode: &str) -> Result<CitationReport>;
}

// ── helpers ─────────────────────────────────────────────────────────────────

/// Parse the LLM's plaintext list of queries — one per line, stripped of
/// common bullet markers, capped at `n`, length-filtered to (3, 250).
pub fn parse_query_list(raw: &str, n: usize) -> Vec<String> {
    raw.lines()
        .map(|ln| ln.trim().trim_start_matches(['-', '*', '•', '\t', ' ']).trim().to_string())
        .filter(|q| !q.is_empty())
        .take(n)
        .filter(|q| q.len() > 3 && q.len() < 250)
        .collect()
}

/// Dedup records by lowercase DOI when present, else PMID. Mirrors the
/// Python loop's "key = doi.lower() or pmid" rule.
pub fn dedup_records(records: Vec<Record>) -> Vec<Record> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for r in records {
        let key = r
            .doi
            .as_ref()
            .map(|d| d.to_lowercase())
            .filter(|s| !s.is_empty())
            .or_else(|| r.pmid.clone())
            .unwrap_or_default();
        if seen.insert(key) {
            out.push(r);
        }
    }
    out
}

/// Format records as numbered cards for the summariser prompt.
pub fn format_cards(records: &[Record]) -> String {
    let mut blocks: Vec<String> = Vec::new();
    for (i, r) in records.iter().enumerate() {
        let n = i + 1;
        let id = r.id_label();
        let block = format!(
            "[{}] {} {} | {} | {}\n    Title: {}",
            n,
            r.first_author(),
            r.year.as_deref().unwrap_or(""),
            r.journal.as_deref().unwrap_or("?"),
            id,
            r.title.as_deref().unwrap_or("?")
        );
        blocks.push(block);
    }
    blocks.join("\n\n")
}

/// Replace `[N]` numeric markers in `text` with the corresponding record's
/// id label (`PMID:1234` / `doi:10.x/y`). Numbers out of range pass through
/// unchanged.
pub fn expand_numeric_citations(text: &str, records: &[Record]) -> String {
    let re = regex::Regex::new(r"\[(\d+)\]").expect("regex compiles");
    re.replace_all(text, |caps: &regex::Captures| {
        let raw = &caps[1];
        match raw.parse::<usize>() {
            Ok(n) if n >= 1 && n <= records.len() => format!("[{}]", records[n - 1].id_label()),
            _ => caps[0].to_string(),
        }
    })
    .into_owned()
}

// ── researcher ──────────────────────────────────────────────────────────────

pub struct Researcher<'a> {
    pub llm: &'a dyn Llm,
    pub lit: &'a dyn Literature,
}

impl<'a> Researcher<'a> {
    pub fn new(llm: &'a dyn Llm, lit: &'a dyn Literature) -> Self {
        Self { llm, lit }
    }

    /// Ask the LLM for `n` PubMed-friendly queries.
    pub fn formulate_queries(&self, topic: &str, n: usize) -> Result<Vec<String>> {
        let prompt = format!(
            "Topic: {}\n\nGenerate {} distinct PubMed query strings that would surface the most relevant peer-reviewed evidence on this topic. Output: one query per line, no numbering, no explanation. Use MeSH terms and Boolean operators where helpful.",
            topic, n
        );
        let raw = self.llm.complete(LlmTier::Fast, "", &prompt, "en")?;
        Ok(parse_query_list(&raw, n))
    }

    /// Hard-verified search over one or both sources, deduped.
    pub fn find(&self, query: &str, n: usize, source: Source) -> Result<Vec<Record>> {
        let mut out = Vec::new();
        if matches!(source, Source::Pubmed | Source::Both) {
            out.extend(self.lit.pubmed_search(query, n)?);
        }
        if matches!(source, Source::Crossref | Source::Both) {
            out.extend(self.lit.crossref_search(query, n)?);
        }
        Ok(dedup_records(out))
    }

    /// Summarise verified records around a focus question. Citations in the
    /// LLM output are expanded from `[N]` to `[PMID:.../doi:...]`.
    pub fn summarise(&self, records: &[Record], focus: &str, lang: &str) -> Result<String> {
        if records.is_empty() {
            return Ok("No verified records to summarise.".into());
        }
        let block = format_cards(records);
        let sys = "You are an evidence synthesiser. Use ONLY the records below; \
                   do not introduce any new citations. Cite as [N] referring to the \
                   card numbers. Be precise about what each record actually shows \
                   vs what would be required to support the focus question.";
        let prompt = format!(
            "=== RECORDS ===\n{}\n=== END ===\n\nFocus: {}",
            block, focus
        );
        let out = self.llm.complete(LlmTier::Deep, sys, &prompt, lang)?;
        Ok(expand_numeric_citations(&out, records))
    }

    /// Pass-through to the citation enforcer.
    pub fn verify_text(&self, text: &str, mode: &str) -> Result<CitationReport> {
        self.lit.enforce_citations(text, mode)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct ScriptedLlm {
        responses: Mutex<Vec<String>>,
        calls: Mutex<Vec<(LlmTier, String, String, String)>>,
    }

    impl ScriptedLlm {
        fn new(responses: Vec<&str>) -> Self {
            Self {
                responses: Mutex::new(responses.into_iter().map(String::from).collect()),
                calls: Mutex::new(Vec::new()),
            }
        }
    }

    impl Llm for ScriptedLlm {
        fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String> {
            self.calls.lock().push((
                tier,
                system.to_string(),
                prompt.to_string(),
                lang.to_string(),
            ));
            let mut r = self.responses.lock();
            if r.is_empty() {
                Ok("(no response)".into())
            } else {
                Ok(r.remove(0))
            }
        }
    }

    struct StubLit {
        pubmed: Mutex<Vec<Record>>,
        crossref: Mutex<Vec<Record>>,
        report: Mutex<Option<CitationReport>>,
    }

    impl StubLit {
        fn new() -> Self {
            Self {
                pubmed: Mutex::new(Vec::new()),
                crossref: Mutex::new(Vec::new()),
                report: Mutex::new(None),
            }
        }
    }

    impl Literature for StubLit {
        fn pubmed_search(&self, _q: &str, _n: usize) -> Result<Vec<Record>> {
            Ok(self.pubmed.lock().clone())
        }
        fn crossref_search(&self, _q: &str, _n: usize) -> Result<Vec<Record>> {
            Ok(self.crossref.lock().clone())
        }
        fn enforce_citations(&self, text: &str, _mode: &str) -> Result<CitationReport> {
            Ok(self.report.lock().clone().unwrap_or(CitationReport {
                text: text.to_string(),
                ..Default::default()
            }))
        }
    }

    fn rec(pmid: Option<&str>, doi: Option<&str>, title: &str, year: &str) -> Record {
        Record {
            pmid: pmid.map(String::from),
            doi: doi.map(String::from),
            title: Some(title.into()),
            journal: Some("Cell".into()),
            year: Some(year.into()),
            authors: vec!["Smith".into(), "Jones".into()],
        }
    }

    // ── parse_query_list ────────────────────────────────────────────────────

    #[test]
    fn parse_query_list_strips_bullets_and_filters_lengths() {
        let raw = "- a\n* meaningful PubMed query string\n• tiny\n   another good query\n";
        let qs = parse_query_list(raw, 5);
        assert!(qs.iter().any(|q| q == "meaningful PubMed query string"));
        assert!(qs.iter().any(|q| q == "another good query"));
        // "a" and "tiny" filtered (≤3 chars and exactly 4)
        assert!(!qs.iter().any(|q| q == "a"));
    }

    #[test]
    fn parse_query_list_caps_at_n() {
        let raw = "first long enough query\nsecond query string\nthird query string\nfourth query string";
        let qs = parse_query_list(raw, 2);
        assert_eq!(qs.len(), 2);
    }

    #[test]
    fn parse_query_list_drops_too_long() {
        let long = "x".repeat(300);
        let qs = parse_query_list(&long, 5);
        assert!(qs.is_empty());
    }

    // ── dedup_records ───────────────────────────────────────────────────────

    #[test]
    fn dedup_keeps_first_seen_doi_case_insensitive() {
        let r1 = rec(None, Some("10.1/X"), "A", "2024");
        let r2 = rec(None, Some("10.1/x"), "B", "2024");
        let out = dedup_records(vec![r1.clone(), r2]);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].title.as_deref(), Some("A"));
    }

    #[test]
    fn dedup_falls_back_to_pmid() {
        let r1 = rec(Some("123"), None, "A", "2024");
        let r2 = rec(Some("123"), None, "B", "2024");
        let r3 = rec(Some("456"), None, "C", "2024");
        let out = dedup_records(vec![r1, r2, r3]);
        assert_eq!(out.len(), 2);
    }

    #[test]
    fn dedup_preserves_distinct_records() {
        let out = dedup_records(vec![
            rec(Some("1"), None, "A", "2024"),
            rec(Some("2"), None, "B", "2024"),
            rec(None, Some("10.1/c"), "C", "2024"),
        ]);
        assert_eq!(out.len(), 3);
    }

    // ── format_cards ────────────────────────────────────────────────────────

    #[test]
    fn format_cards_renders_id_and_title() {
        let r = rec(Some("12345"), None, "Centriole asymmetry", "2026");
        let s = format_cards(&[r]);
        assert!(s.contains("[1]"));
        assert!(s.contains("Smith"));
        assert!(s.contains("PMID:12345"));
        assert!(s.contains("Title: Centriole asymmetry"));
    }

    #[test]
    fn format_cards_uses_doi_when_no_pmid() {
        let r = rec(None, Some("10.1073/x"), "X", "2026");
        let s = format_cards(&[r]);
        assert!(s.contains("doi:10.1073/x"));
    }

    // ── expand_numeric_citations ────────────────────────────────────────────

    #[test]
    fn expand_replaces_in_range_numbers() {
        let r = vec![
            rec(Some("1"), None, "A", ""),
            rec(None, Some("10.1/B"), "B", ""),
        ];
        let out = expand_numeric_citations("see [1] and [2]", &r);
        assert!(out.contains("[PMID:1]"));
        assert!(out.contains("[doi:10.1/B]"));
    }

    #[test]
    fn expand_passes_through_out_of_range() {
        let r = vec![rec(Some("1"), None, "A", "")];
        let out = expand_numeric_citations("[5]", &r);
        assert_eq!(out, "[5]");
    }

    // ── formulate_queries ───────────────────────────────────────────────────

    #[test]
    fn formulate_queries_uses_fast_tier() {
        let llm = ScriptedLlm::new(vec!["query string one\nquery string two"]);
        let lit = StubLit::new();
        let r = Researcher::new(&llm, &lit);
        let qs = r.formulate_queries("centrioles", 5).unwrap();
        assert_eq!(qs.len(), 2);
        assert_eq!(llm.calls.lock()[0].0, LlmTier::Fast);
        assert!(llm.calls.lock()[0].2.contains("centrioles"));
    }

    // ── find ────────────────────────────────────────────────────────────────

    #[test]
    fn find_pubmed_only_calls_pubmed() {
        let llm = ScriptedLlm::new(vec![]);
        let lit = StubLit::new();
        *lit.pubmed.lock() = vec![rec(Some("1"), None, "A", "")];
        *lit.crossref.lock() = vec![rec(Some("2"), None, "B", "")];
        let r = Researcher::new(&llm, &lit);
        let out = r.find("q", 10, Source::Pubmed).unwrap();
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].pmid.as_deref(), Some("1"));
    }

    #[test]
    fn find_both_dedups_overlap() {
        let llm = ScriptedLlm::new(vec![]);
        let lit = StubLit::new();
        *lit.pubmed.lock() = vec![rec(Some("1"), Some("10.1/X"), "A", "")];
        *lit.crossref.lock() = vec![rec(None, Some("10.1/x"), "A-cr", "")];
        let r = Researcher::new(&llm, &lit);
        let out = r.find("q", 10, Source::Both).unwrap();
        assert_eq!(out.len(), 1);
    }

    // ── summarise ───────────────────────────────────────────────────────────

    #[test]
    fn summarise_empty_returns_canned_message() {
        let llm = ScriptedLlm::new(vec![]);
        let lit = StubLit::new();
        let r = Researcher::new(&llm, &lit);
        let out = r.summarise(&[], "focus", "en").unwrap();
        assert_eq!(out, "No verified records to summarise.");
    }

    #[test]
    fn summarise_uses_deep_tier_and_expands_numeric_cites() {
        let llm = ScriptedLlm::new(vec!["A claim is supported [1] and [2]."]);
        let lit = StubLit::new();
        let recs = vec![
            rec(Some("11111"), None, "A", "2026"),
            rec(None, Some("10.1/y"), "B", "2026"),
        ];
        let r = Researcher::new(&llm, &lit);
        let out = r.summarise(&recs, "centrioles", "en").unwrap();
        assert_eq!(llm.calls.lock()[0].0, LlmTier::Deep);
        assert!(out.contains("[PMID:11111]"));
        assert!(out.contains("[doi:10.1/y]"));
    }

    // ── verify_text ─────────────────────────────────────────────────────────

    #[test]
    fn verify_text_passes_through_to_lit() {
        let llm = ScriptedLlm::new(vec![]);
        let lit = StubLit::new();
        *lit.report.lock() = Some(CitationReport {
            text: "cleaned".into(),
            verified: vec!["10.1/x".into()],
            rejected: vec!["fake".into()],
        });
        let r = Researcher::new(&llm, &lit);
        let rep = r.verify_text("any", "annotate").unwrap();
        assert_eq!(rep.text, "cleaned");
        assert_eq!(rep.verified, vec!["10.1/x"]);
    }

    // ── Source::parse ───────────────────────────────────────────────────────

    #[test]
    fn source_parse_branches() {
        assert_eq!(Source::parse("pubmed"), Source::Pubmed);
        assert_eq!(Source::parse("crossref"), Source::Crossref);
        assert_eq!(Source::parse("both"), Source::Both);
        assert_eq!(Source::parse("anything"), Source::Pubmed);
    }
}
