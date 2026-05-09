//! aim-citation-guard — R1 zero-hallucination citation pipeline.
//!
//! 1. [`extract`] — regex out every PMID, DOI, NCT, arXiv id mentioned
//!    in the text.
//! 2. [`verify`] — call a caller-supplied [`Verifier`] for each id;
//!    cache hits across calls in a [`Guard`] instance.
//! 3. [`sanitize`] — replace unresolved citations with a marker so
//!    downstream readers see the gap immediately.
//!
//! Strict mode in [`Guard::verify_strict`] returns
//! [`CitationError::Unresolved`] on the first miss.
//!
//! Rust port of `agents/citation_guard.py`. The Python predecessor's
//! actual PubMed / Crossref network calls live in
//! `tools.literature.verify_*`; we keep them out of this crate so it
//! stays unit-testable. Production binaries inject a [`Verifier`] that
//! talks to PubMed/Crossref.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CitationError {
    #[error("unresolved citations: {kinds:?}")]
    Unresolved { kinds: Vec<String> },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Kind {
    Pmid,
    Doi,
    Nct,
    Arxiv,
}

impl Kind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Kind::Pmid => "pmid",
            Kind::Doi => "doi",
            Kind::Nct => "nct",
            Kind::Arxiv => "arxiv",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Citation {
    pub kind: Kind,
    pub raw: String,
    pub start: usize,
    pub end: usize,
    pub resolved: bool,
    pub title: String,
    pub year: Option<u32>,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Verdict {
    pub citations: Vec<Citation>,
    pub ok: bool,
}

impl Verdict {
    pub fn unresolved(&self) -> Vec<&Citation> {
        self.citations.iter().filter(|c| !c.resolved).collect()
    }
}

/// What `verify` returns about a single citation.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ResolveInfo {
    pub resolved: bool,
    pub title: String,
    pub year: Option<u32>,
    pub note: String,
}

/// Caller-supplied verifier. Implementations talk to PubMed / Crossref
/// / etc. The trait is sync; for async clients wrap with
/// `tokio::task::spawn_blocking` or use a runtime in the impl.
pub trait Verifier: Send + Sync {
    fn verify(&self, kind: Kind, raw: &str) -> ResolveInfo;
}

/// Trivial verifier that says "unresolved" for every input. Useful as
/// a default in tests or when network isn't available.
pub struct AlwaysUnresolved;

impl Verifier for AlwaysUnresolved {
    fn verify(&self, _kind: Kind, _raw: &str) -> ResolveInfo {
        ResolveInfo::default()
    }
}

/// Verifier that resolves only the explicit allow-list. Used to write
/// reproducible tests.
pub struct AllowList<'a>(pub &'a [(&'a str, &'a str)]);

impl<'a> Verifier for AllowList<'a> {
    fn verify(&self, _kind: Kind, raw: &str) -> ResolveInfo {
        for (allowed, title) in self.0 {
            if *allowed == raw {
                return ResolveInfo {
                    resolved: true,
                    title: (*title).into(),
                    year: None,
                    note: String::new(),
                };
            }
        }
        ResolveInfo::default()
    }
}

// ── extraction ──────────────────────────────────────────────────

pub fn extract(text: &str) -> Vec<Citation> {
    use once_cell::sync::Lazy;
    use regex::{Regex, RegexBuilder};
    static PMID: Lazy<Regex> = Lazy::new(|| {
        RegexBuilder::new(r"(?:^|[^A-Za-z0-9])PMID[:\s]*([0-9]{4,9})(?:[^A-Za-z0-9]|$)")
            .case_insensitive(true)
            .build()
            .unwrap()
    });
    static DOI: Lazy<Regex> = Lazy::new(|| {
        RegexBuilder::new(r"\b(10\.\d{4,9}/[^\s,;)]+)")
            .case_insensitive(true)
            .build()
            .unwrap()
    });
    static NCT: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b(NCT\d{8})\b").unwrap());
    static ARXIV: Lazy<Regex> = Lazy::new(|| {
        RegexBuilder::new(
            r"\b(?:arxiv|arXiv)[:\s]+([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
        )
        .case_insensitive(true)
        .build()
        .unwrap()
    });

    let mut out: Vec<Citation> = Vec::new();
    for cap in PMID.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            out.push(Citation {
                kind: Kind::Pmid,
                raw: m.as_str().to_string(),
                start: m.start(),
                end: m.end(),
                resolved: false,
                title: String::new(),
                year: None,
                note: String::new(),
            });
        }
    }
    for cap in DOI.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            let raw = m.as_str().trim_end_matches(|c| ".,;)".contains(c)).to_string();
            out.push(Citation {
                kind: Kind::Doi,
                raw,
                start: m.start(),
                end: m.end(),
                resolved: false,
                title: String::new(),
                year: None,
                note: String::new(),
            });
        }
    }
    for cap in NCT.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            out.push(Citation {
                kind: Kind::Nct,
                raw: m.as_str().to_string(),
                start: m.start(),
                end: m.end(),
                resolved: false,
                title: String::new(),
                year: None,
                note: String::new(),
            });
        }
    }
    for cap in ARXIV.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            out.push(Citation {
                kind: Kind::Arxiv,
                raw: m.as_str().to_string(),
                start: m.start(),
                end: m.end(),
                resolved: false,
                title: String::new(),
                year: None,
                note: String::new(),
            });
        }
    }
    out
}

// ── Guard: verify with cache + sanitize ─────────────────────────

pub struct Guard<V: Verifier> {
    verifier: V,
    cache: Mutex<HashMap<(Kind, String), ResolveInfo>>,
}

impl<V: Verifier> Guard<V> {
    pub fn new(verifier: V) -> Self {
        Self {
            verifier,
            cache: Mutex::new(HashMap::new()),
        }
    }

    fn resolve_cached(&self, kind: Kind, raw: &str) -> ResolveInfo {
        if let Some(info) = self.cache.lock().unwrap().get(&(kind, raw.to_string())) {
            return info.clone();
        }
        let info = self.verifier.verify(kind, raw);
        self.cache
            .lock()
            .unwrap()
            .insert((kind, raw.to_string()), info.clone());
        info
    }

    pub fn verify(&self, text: &str) -> Verdict {
        let mut cites = extract(text);
        for c in cites.iter_mut() {
            let info = self.resolve_cached(c.kind, &c.raw);
            c.resolved = info.resolved;
            c.title = info.title;
            c.year = info.year;
            c.note = info.note;
        }
        let ok = cites.iter().all(|c| c.resolved);
        Verdict {
            citations: cites,
            ok,
        }
    }

    pub fn verify_strict(&self, text: &str) -> Result<Verdict, CitationError> {
        let v = self.verify(text);
        if !v.ok {
            let kinds: Vec<String> = v
                .unresolved()
                .iter()
                .map(|c| format!("{}:{}", c.kind.as_str(), c.raw))
                .collect();
            return Err(CitationError::Unresolved { kinds });
        }
        Ok(v)
    }

    /// Replace each unresolved citation in `text` with `replacement`.
    /// Resolved citations are left intact.
    pub fn sanitize(&self, text: &str, replacement: &str) -> String {
        let v = self.verify(text);
        sanitize_with_verdict(text, &v, replacement)
    }
}

/// Pure helper — apply a Verdict to text, splicing `replacement` over
/// each unresolved citation span.
pub fn sanitize_with_verdict(text: &str, v: &Verdict, replacement: &str) -> String {
    let mut spans: Vec<(usize, usize)> = v
        .citations
        .iter()
        .filter(|c| !c.resolved)
        .map(|c| (c.start, c.end))
        .collect();
    spans.sort_by_key(|s| s.0);
    if spans.is_empty() {
        return text.to_string();
    }
    let bytes = text.as_bytes();
    let mut out = Vec::<u8>::with_capacity(bytes.len());
    let mut cursor = 0usize;
    for (s, e) in spans {
        if s > cursor {
            out.extend_from_slice(&bytes[cursor..s]);
        }
        out.extend_from_slice(replacement.as_bytes());
        cursor = e;
    }
    if cursor < bytes.len() {
        out.extend_from_slice(&bytes[cursor..]);
    }
    String::from_utf8(out).unwrap_or_else(|_| text.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_pmid_basic() {
        let cs = extract("see PMID 36583780 for details");
        assert_eq!(cs.len(), 1);
        assert_eq!(cs[0].kind, Kind::Pmid);
        assert_eq!(cs[0].raw, "36583780");
    }

    #[test]
    fn extract_pmid_with_colon() {
        let cs = extract("PMID: 12345");
        assert_eq!(cs.len(), 1);
        assert_eq!(cs[0].raw, "12345");
    }

    #[test]
    fn extract_doi_strips_trailing_punct() {
        let cs = extract("see 10.65649/v6eb0t18, also relevant");
        assert!(cs.iter().any(|c| c.kind == Kind::Doi && c.raw == "10.65649/v6eb0t18"));
    }

    #[test]
    fn extract_nct() {
        let cs = extract("trial NCT04567890 enrolled 200");
        assert!(cs.iter().any(|c| c.kind == Kind::Nct && c.raw == "NCT04567890"));
    }

    #[test]
    fn extract_arxiv_only_with_prefix() {
        let cs = extract("see arXiv:2509.12345 paper. Dosage 0.5/1.5 mg.");
        assert!(cs.iter().any(|c| c.kind == Kind::Arxiv));
        // 0.5 / 1.5 must NOT be picked up
        assert!(!cs.iter().any(|c| c.kind == Kind::Arxiv && c.raw == "0.5"));
    }

    #[test]
    fn extract_empty_text_no_citations() {
        assert!(extract("").is_empty());
        assert!(extract("nothing to see").is_empty());
    }

    #[test]
    fn verify_resolves_via_allow_list() {
        let g = Guard::new(AllowList(&[
            ("36583780", "Tkemaladze 2023"),
            ("10.65649/v6eb0t18", "Ze Theorem"),
        ]));
        let v = g.verify("see PMID 36583780 and 10.65649/v6eb0t18");
        assert!(v.ok);
        assert!(v.citations.iter().all(|c| c.resolved));
        let titles: Vec<&str> = v.citations.iter().map(|c| c.title.as_str()).collect();
        assert!(titles.iter().any(|t| t.contains("Tkemaladze")));
    }

    #[test]
    fn verify_flags_missing_pmid() {
        let g = Guard::new(AllowList(&[("11111111", "OK")]));
        let v = g.verify("see PMID 99999999");
        assert!(!v.ok);
        assert_eq!(v.unresolved().len(), 1);
    }

    #[test]
    fn verify_strict_errors_on_miss() {
        let g = Guard::new(AlwaysUnresolved);
        let r = g.verify_strict("PMID 1");  // 1 has only 1 digit → not extracted; OK
        // No citations extracted → ok=true
        assert!(r.is_ok());
        let r = g.verify_strict("PMID 99999999");
        assert!(matches!(r, Err(CitationError::Unresolved { .. })));
    }

    #[test]
    fn sanitize_replaces_unresolved_only() {
        let g = Guard::new(AllowList(&[("11111111", "OK")]));
        let text = "good PMID 11111111 and bad PMID 99999999.";
        let s = g.sanitize(text, "[ref unverified]");
        assert!(s.contains("PMID 11111111"));
        assert!(!s.contains("99999999"));
        assert!(s.contains("[ref unverified]"));
    }

    #[test]
    fn cache_hits_skip_re_verification() {
        struct Counting {
            n: Mutex<u32>,
        }
        impl Verifier for Counting {
            fn verify(&self, _: Kind, _: &str) -> ResolveInfo {
                *self.n.lock().unwrap() += 1;
                ResolveInfo::default()
            }
        }
        let g = Guard::new(Counting { n: Mutex::new(0) });
        g.verify("PMID 11111111");
        g.verify("PMID 11111111");
        g.verify("PMID 11111111");
        assert_eq!(*g.verifier.n.lock().unwrap(), 1);
    }

    #[test]
    fn sanitize_with_verdict_pure_helper() {
        let v = Verdict {
            citations: vec![Citation {
                kind: Kind::Pmid,
                raw: "x".into(),
                start: 4,
                end: 9,
                resolved: false,
                title: String::new(),
                year: None,
                note: String::new(),
            }],
            ok: false,
        };
        let s = sanitize_with_verdict("foo MMMMM bar", &v, "[X]");
        assert_eq!(s, "foo [X] bar");
    }
}
