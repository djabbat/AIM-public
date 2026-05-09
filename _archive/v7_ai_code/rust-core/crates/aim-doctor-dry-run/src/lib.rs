//! aim-doctor-dry-run — pre-emit safety pass (DR1).
//!
//! Port of `agents/doctor_dry_run.py`. Composes citation_guard +
//! regimen_validator into a single call the doctor agent runs before
//! sending its draft to the user.
//!
//! Both safety primitives sit behind traits ([`CitationGuard`],
//! [`RegimenValidator`]); the audit log is also pluggable.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DryRunError {
    #[error("citation error: {0}")]
    Citation(String),
    #[error("regimen refused: {0}")]
    Regimen(String),
}

pub type Result<T> = std::result::Result<T, DryRunError>;

// ── citation guard ──────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CitationIssue {
    pub kind: String,
    pub raw: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CitationVerification {
    pub unresolved: Vec<CitationIssue>,
}

pub trait CitationGuard: Send + Sync {
    /// Strict mode → returns `Err(Citation)` on any unresolved citation.
    /// Non-strict → returns the verification report.
    fn verify(&self, text: &str, strict: bool) -> Result<CitationVerification>;
    /// Strip / annotate unresolved citations. Returns the rewritten text.
    fn sanitize(&self, text: &str) -> String;
}

/// Default no-op guard: nothing unresolved, sanitize is identity.
pub struct NoopCitationGuard;
impl CitationGuard for NoopCitationGuard {
    fn verify(&self, _text: &str, _strict: bool) -> Result<CitationVerification> {
        Ok(CitationVerification::default())
    }
    fn sanitize(&self, text: &str) -> String {
        text.to_string()
    }
}

// ── regimen validator ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct RegimenValidation {
    pub interactions: Vec<String>,
    pub overrides_used: bool,
}

pub trait RegimenValidator: Send + Sync {
    /// Returns `Ok(validation)` on pass; `Err(Regimen)` on hard refusal.
    fn validate(&self, drugs: &[String], physician_override: bool) -> Result<RegimenValidation>;
    /// Append a validation footer to `text`. Pure formatting — never errors.
    fn annotate(&self, text: &str, drugs: &[String], physician_override: bool) -> String;
}

pub struct NoopRegimenValidator;
impl RegimenValidator for NoopRegimenValidator {
    fn validate(&self, _: &[String], _: bool) -> Result<RegimenValidation> {
        Ok(RegimenValidation::default())
    }
    fn annotate(&self, text: &str, _: &[String], _: bool) -> String {
        text.to_string()
    }
}

// ── audit sink ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AuditRecord {
    pub draft_length: usize,
    pub n_citation_issues: usize,
    pub n_drugs: usize,
    pub physician_override: bool,
}

pub trait AuditSink: Send + Sync {
    fn record(&self, rec: AuditRecord);
}

pub struct NoopAudit;
impl AuditSink for NoopAudit {
    fn record(&self, _: AuditRecord) {}
}

// ── result + service ───────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DryRunResult {
    pub text: String,
    pub citation_issues: Vec<CitationIssue>,
    pub regimen: Option<RegimenValidation>,
}

#[derive(Clone, Debug)]
pub struct DryRunOptions {
    pub strict_citations: bool,
    pub physician_override: bool,
}

impl Default for DryRunOptions {
    fn default() -> Self {
        Self {
            strict_citations: false,
            physician_override: false,
        }
    }
}

pub struct DryRun<'a> {
    pub citations: &'a dyn CitationGuard,
    pub regimen: &'a dyn RegimenValidator,
    pub audit: &'a dyn AuditSink,
}

impl<'a> DryRun<'a> {
    pub fn new(
        citations: &'a dyn CitationGuard,
        regimen: &'a dyn RegimenValidator,
        audit: &'a dyn AuditSink,
    ) -> Self {
        Self {
            citations,
            regimen,
            audit,
        }
    }

    pub fn run(&self, draft: &str, drugs: &[String], opts: &DryRunOptions) -> Result<DryRunResult> {
        // Filter empty / whitespace-only drug entries (Python parity).
        let drugs: Vec<String> = drugs
            .iter()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        // 1. Citations.
        let mut text = draft.to_string();
        let mut citation_issues: Vec<CitationIssue> = Vec::new();
        if opts.strict_citations {
            // verify(strict=true) bubbles errors directly.
            self.citations.verify(&text, true)?;
        } else {
            match self.citations.verify(&text, false) {
                Ok(v) => {
                    if !v.unresolved.is_empty() {
                        citation_issues = v.unresolved.clone();
                        text = self.citations.sanitize(&text);
                    }
                }
                Err(DryRunError::Citation(_)) => {
                    // Soft mode shouldn't surface hard errors; treat as none.
                }
                Err(e) => return Err(e),
            }
        }

        // 2. Regimen — only when drugs is non-empty.
        let regimen = if !drugs.is_empty() {
            let v = self.regimen.validate(&drugs, opts.physician_override)?;
            text = self.regimen.annotate(&text, &drugs, opts.physician_override);
            Some(v)
        } else {
            None
        };

        // 3. Audit.
        self.audit.record(AuditRecord {
            draft_length: draft.chars().count(),
            n_citation_issues: citation_issues.len(),
            n_drugs: drugs.len(),
            physician_override: opts.physician_override,
        });

        Ok(DryRunResult {
            text,
            citation_issues,
            regimen,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct ConfigurableCitations {
        unresolved: Vec<CitationIssue>,
        strict_err: Option<String>,
        sanitize_to: String,
        verify_calls: Mutex<usize>,
        sanitize_calls: Mutex<usize>,
    }
    impl ConfigurableCitations {
        fn new() -> Self {
            Self {
                unresolved: Vec::new(),
                strict_err: None,
                sanitize_to: "[sanitised]".into(),
                verify_calls: Mutex::new(0),
                sanitize_calls: Mutex::new(0),
            }
        }
    }
    impl CitationGuard for ConfigurableCitations {
        fn verify(&self, _text: &str, strict: bool) -> Result<CitationVerification> {
            *self.verify_calls.lock() += 1;
            if strict {
                if let Some(e) = &self.strict_err {
                    return Err(DryRunError::Citation(e.clone()));
                }
                return Ok(CitationVerification::default());
            }
            Ok(CitationVerification {
                unresolved: self.unresolved.clone(),
            })
        }
        fn sanitize(&self, _text: &str) -> String {
            *self.sanitize_calls.lock() += 1;
            self.sanitize_to.clone()
        }
    }

    struct ConfigurableRegimen {
        refuse: Option<String>,
        validation: RegimenValidation,
        validate_calls: Mutex<Vec<(Vec<String>, bool)>>,
        annotate_calls: Mutex<usize>,
    }
    impl ConfigurableRegimen {
        fn ok() -> Self {
            Self {
                refuse: None,
                validation: RegimenValidation::default(),
                validate_calls: Mutex::new(Vec::new()),
                annotate_calls: Mutex::new(0),
            }
        }
        fn refusing(reason: &str) -> Self {
            Self {
                refuse: Some(reason.into()),
                validation: RegimenValidation::default(),
                validate_calls: Mutex::new(Vec::new()),
                annotate_calls: Mutex::new(0),
            }
        }
    }
    impl RegimenValidator for ConfigurableRegimen {
        fn validate(&self, drugs: &[String], po: bool) -> Result<RegimenValidation> {
            self.validate_calls
                .lock()
                .push((drugs.to_vec(), po));
            if let Some(r) = &self.refuse {
                return Err(DryRunError::Regimen(r.clone()));
            }
            Ok(self.validation.clone())
        }
        fn annotate(&self, text: &str, _drugs: &[String], _po: bool) -> String {
            *self.annotate_calls.lock() += 1;
            format!("{} [annotated]", text)
        }
    }

    #[derive(Default)]
    struct CountingAudit(Mutex<Vec<AuditRecord>>);
    impl AuditSink for CountingAudit {
        fn record(&self, r: AuditRecord) {
            self.0.lock().push(r);
        }
    }

    // ── basic flow ─────────────────────────────────────────────────────────

    #[test]
    fn run_clean_draft_no_drugs_passes_through() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let out = dr.run("clean draft", &[], &DryRunOptions::default()).unwrap();
        assert_eq!(out.text, "clean draft");
        assert!(out.citation_issues.is_empty());
        assert!(out.regimen.is_none());
        assert_eq!(*cit.verify_calls.lock(), 1);
        assert_eq!(*cit.sanitize_calls.lock(), 0);
        assert_eq!(reg.validate_calls.lock().len(), 0);
    }

    // ── citations ──────────────────────────────────────────────────────────

    #[test]
    fn run_unresolved_citations_trigger_sanitize() {
        let mut cit = ConfigurableCitations::new();
        cit.unresolved = vec![CitationIssue {
            kind: "PMID".into(),
            raw: "999".into(),
        }];
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let out = dr.run("draft with PMID 999", &[], &DryRunOptions::default()).unwrap();
        assert_eq!(out.citation_issues.len(), 1);
        assert_eq!(out.text, "[sanitised]");
        assert_eq!(*cit.sanitize_calls.lock(), 1);
    }

    #[test]
    fn run_strict_citations_propagates_error() {
        let mut cit = ConfigurableCitations::new();
        cit.strict_err = Some("PMID:99 unresolved".into());
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let opts = DryRunOptions {
            strict_citations: true,
            ..Default::default()
        };
        let err = dr.run("draft", &[], &opts).unwrap_err();
        assert!(matches!(err, DryRunError::Citation(_)));
    }

    #[test]
    fn run_strict_citations_clean_passes() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let opts = DryRunOptions {
            strict_citations: true,
            ..Default::default()
        };
        let out = dr.run("draft", &[], &opts).unwrap();
        // sanitize is NOT called on strict path, even if it would have been
        assert_eq!(*cit.sanitize_calls.lock(), 0);
        assert_eq!(out.text, "draft");
    }

    // ── regimen ────────────────────────────────────────────────────────────

    #[test]
    fn run_regimen_annotates_when_drugs_present() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let drugs = vec!["aspirin".into(), "atorva".into()];
        let out = dr.run("draft", &drugs, &DryRunOptions::default()).unwrap();
        assert_eq!(out.text, "draft [annotated]");
        assert!(out.regimen.is_some());
        assert_eq!(*reg.annotate_calls.lock(), 1);
        let calls = reg.validate_calls.lock();
        assert_eq!(calls[0].0, drugs);
        assert_eq!(calls[0].1, false);
    }

    #[test]
    fn run_regimen_filters_empty_drug_strings() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let drugs = vec!["".into(), "  ".into(), "aspirin".into(), "  atorva".into()];
        let out = dr.run("draft", &drugs, &DryRunOptions::default()).unwrap();
        assert!(out.regimen.is_some());
        let calls = reg.validate_calls.lock();
        assert_eq!(calls[0].0, vec!["aspirin".to_string(), "atorva".to_string()]);
    }

    #[test]
    fn run_regimen_refusal_propagates_error() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::refusing("warfarin + aspirin major");
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let drugs = vec!["warfarin".into(), "aspirin".into()];
        let err = dr.run("draft", &drugs, &DryRunOptions::default()).unwrap_err();
        assert!(matches!(err, DryRunError::Regimen(s) if s.contains("warfarin")));
    }

    #[test]
    fn run_skips_regimen_when_only_empty_drugs() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let drugs = vec!["".into(), "   ".into()];
        let out = dr.run("draft", &drugs, &DryRunOptions::default()).unwrap();
        assert!(out.regimen.is_none());
        assert_eq!(*reg.annotate_calls.lock(), 0);
    }

    #[test]
    fn run_passes_physician_override_through() {
        let cit = ConfigurableCitations::new();
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        let opts = DryRunOptions {
            physician_override: true,
            ..Default::default()
        };
        dr.run("draft", &["aspirin".into()], &opts).unwrap();
        let calls = reg.validate_calls.lock();
        assert_eq!(calls[0].1, true);
    }

    // ── audit ──────────────────────────────────────────────────────────────

    #[test]
    fn run_audits_every_call() {
        let mut cit = ConfigurableCitations::new();
        cit.unresolved = vec![CitationIssue {
            kind: "PMID".into(),
            raw: "1".into(),
        }];
        let reg = ConfigurableRegimen::ok();
        let aud = CountingAudit::default();
        let dr = DryRun::new(&cit, &reg, &aud);
        dr.run("draft длинный", &["aspirin".into()], &DryRunOptions::default())
            .unwrap();
        let recs = aud.0.lock();
        assert_eq!(recs.len(), 1);
        assert_eq!(recs[0].n_citation_issues, 1);
        assert_eq!(recs[0].n_drugs, 1);
        assert_eq!(recs[0].draft_length, "draft длинный".chars().count());
        assert_eq!(recs[0].physician_override, false);
    }

    // ── default no-op stubs ────────────────────────────────────────────────

    #[test]
    fn noop_stubs_pass_through_cleanly() {
        let cit = NoopCitationGuard;
        let reg = NoopRegimenValidator;
        let aud = NoopAudit;
        let dr = DryRun::new(&cit, &reg, &aud);
        let out = dr.run("anything", &["x".into()], &DryRunOptions::default()).unwrap();
        assert_eq!(out.text, "anything");
        assert!(out.citation_issues.is_empty());
        assert!(out.regimen.is_some());
    }
}
