//! aim-doctor-consult — structured diagnostic flow (DC1).
//!
//! Port of `agents/doctor_consult.py`. A higher-order entry point that
//! composes:
//!   1. intake → structured patient input
//!   2. doctor_fn → top-N hypotheses + draft regimen
//!   3. calibration log → record predictions for D2
//!   4. dry_run → citation_guard + regimen_validator
//!
//! All collaborators sit behind traits ([`DoctorFn`], [`CalibrationSink`],
//! [`DryRunner`]) so the consult orchestration is testable without
//! pulling the actual clinical engines.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConsultError {
    #[error("doctor error: {0}")]
    Doctor(String),
}

pub type Result<T> = std::result::Result<T, ConsultError>;

// ── intake ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Intake {
    pub chief_complaint: String,
    pub age: Option<i32>,
    pub sex: Option<String>,
    pub history: String,
    pub exam: String,
    pub labs: String,
    pub drugs: Vec<String>,
    pub case_id: Option<String>,
}

impl Intake {
    /// Render the intake as a prompt block (one field per line).
    pub fn as_prompt(&self) -> String {
        let mut bits: Vec<String> = vec![format!("Chief complaint: {}", self.chief_complaint)];
        if let Some(age) = self.age {
            bits.push(format!("Age: {}", age));
        }
        if let Some(sex) = &self.sex {
            if !sex.is_empty() {
                bits.push(format!("Sex: {}", sex));
            }
        }
        if !self.history.is_empty() {
            bits.push(format!("History: {}", self.history));
        }
        if !self.exam.is_empty() {
            bits.push(format!("Exam: {}", self.exam));
        }
        if !self.labs.is_empty() {
            bits.push(format!("Labs: {}", self.labs));
        }
        if !self.drugs.is_empty() {
            bits.push(format!("Current regimen: {}", self.drugs.join(", ")));
        }
        bits.join("\n")
    }
}

// ── outputs ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Hypothesis {
    pub label: String,
    pub confidence: f64,
    pub rationale: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Consult {
    pub intake: Intake,
    pub differential: Vec<Hypothesis>,
    pub regimen_text: String,
    pub safety_text: String,
    pub citation_issues: Vec<String>,
    pub refused: bool,
    pub refusal_reason: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DryRunOutcome {
    pub text: String,
    pub citation_issues: Vec<String>,
    /// `Some(reason)` → regimen hard-rejected; caller treats as refusal.
    pub refused_reason: Option<String>,
}

// ── traits ──────────────────────────────────────────────────────────────────

/// The actual clinical reasoner. Production binds to `aim-doctor-agent`;
/// tests use a deterministic stub.
pub trait DoctorFn: Send + Sync {
    /// Returns `(differential, draft_regimen_text)`.
    fn diagnose(&self, intake: &Intake) -> Result<(Vec<Hypothesis>, String)>;
}

/// Calibration record sink. Production binds to `aim-doctor-calibration`;
/// tests use a counting stub.
pub trait CalibrationSink: Send + Sync {
    fn record(
        &self,
        label: &str,
        confidence: f64,
        case_id: Option<&str>,
        domain: &str,
        rationale: &str,
    );
}

pub struct NoopCalibration;
impl CalibrationSink for NoopCalibration {
    fn record(&self, _: &str, _: f64, _: Option<&str>, _: &str, _: &str) {}
}

/// Citation/regimen safety pass. `dry_run` returns either an annotated
/// regimen with optional soft warnings, or a hard refusal via
/// `refused_reason`.
pub trait DryRunner: Send + Sync {
    fn dry_run(&self, draft: &str, drugs: &[String], physician_override: bool) -> DryRunOutcome;
}

/// Default no-op dry-run: returns the draft unchanged with no warnings.
pub struct NoopDryRunner;
impl DryRunner for NoopDryRunner {
    fn dry_run(&self, draft: &str, _drugs: &[String], _: bool) -> DryRunOutcome {
        DryRunOutcome {
            text: draft.to_string(),
            citation_issues: Vec::new(),
            refused_reason: None,
        }
    }
}

/// Deterministic fallback used when no real `DoctorFn` is wired in.
/// Returns a single low-confidence hypothesis based on the chief complaint.
pub struct DefaultDoctor;
impl DoctorFn for DefaultDoctor {
    fn diagnose(&self, intake: &Intake) -> Result<(Vec<Hypothesis>, String)> {
        let label_tail: String = intake
            .chief_complaint
            .chars()
            .take(40)
            .collect();
        Ok((
            vec![Hypothesis {
                label: format!("Symptomatic ({})", label_tail),
                confidence: 0.3,
                rationale:
                    "No domain-specific reasoning available; treat symptomatically pending workup."
                        .into(),
            }],
            "Workup: see clinic for full evaluation. No regimen prescribed from this stub.".into(),
        ))
    }
}

// ── orchestrator ────────────────────────────────────────────────────────────

pub struct ConsultRunner<'a> {
    pub doctor: &'a dyn DoctorFn,
    pub calibration: &'a dyn CalibrationSink,
    pub dry_runner: &'a dyn DryRunner,
}

impl<'a> ConsultRunner<'a> {
    pub fn new(
        doctor: &'a dyn DoctorFn,
        calibration: &'a dyn CalibrationSink,
        dry_runner: &'a dyn DryRunner,
    ) -> Self {
        Self {
            doctor,
            calibration,
            dry_runner,
        }
    }

    /// Run the full diagnostic stack on the intake. Always returns a
    /// `Consult`; `refused=true` means the regimen layer hard-rejected
    /// a contraindicated combination — `regimen_text` is empty and the
    /// reason is in `refusal_reason`.
    pub fn consult(&self, intake: Intake, physician_override: bool) -> Consult {
        // 1. Hypotheses + draft regimen.
        let (hypotheses, draft) = match self.doctor.diagnose(&intake) {
            Ok(p) => p,
            Err(e) => {
                tracing::warn!("doctor_fn raised: {}", e);
                (
                    vec![Hypothesis {
                        label: "(diagnostic engine failed)".into(),
                        confidence: 0.0,
                        rationale: e.to_string(),
                    }],
                    String::new(),
                )
            }
        };

        // 2. Calibration log: persist each hypothesis (best-effort).
        for h in &hypotheses {
            let rationale_truncated: String = h.rationale.chars().take(1000).collect();
            self.calibration.record(
                &h.label,
                h.confidence,
                intake.case_id.as_deref(),
                "diagnosis",
                &rationale_truncated,
            );
        }

        // 3. Dry-run.
        let outcome = self
            .dry_runner
            .dry_run(&draft, &intake.drugs, physician_override);

        let refused = outcome.refused_reason.is_some();
        let refusal_reason = outcome.refused_reason.clone();
        let safe_regimen = if refused {
            String::new()
        } else {
            outcome.text
        };
        let citation_issues = outcome.citation_issues;
        let safety_text = if !citation_issues.is_empty() {
            let preview: Vec<&str> = citation_issues.iter().take(5).map(|s| s.as_str()).collect();
            format!("Soft citation warnings: {}", preview.join(", "))
        } else {
            String::new()
        };

        Consult {
            intake,
            differential: hypotheses,
            regimen_text: safe_regimen,
            safety_text,
            citation_issues,
            refused,
            refusal_reason,
        }
    }
}

// ── pretty-printer ─────────────────────────────────────────────────────────

/// Render a [`Consult`] for CLI / Telegram output. Mirrors Python
/// `consult_summary`.
pub fn consult_summary(c: &Consult) -> String {
    let mut parts: Vec<String> = Vec::new();
    let cc_truncated: String = c.intake.chief_complaint.chars().take(80).collect();
    parts.push(format!("🩺 Consult — chief complaint: {}", cc_truncated));
    if !c.differential.is_empty() {
        parts.push("Differential:".into());
        for h in c.differential.iter().take(5) {
            let rationale: String = h.rationale.chars().take(120).collect();
            parts.push(format!(
                "  • {}  ({:.0}%) — {}",
                h.label,
                h.confidence * 100.0,
                rationale
            ));
        }
    }
    if c.refused {
        parts.push(format!(
            "❌ Regimen refused: {}",
            c.refusal_reason.as_deref().unwrap_or("")
        ));
    } else if !c.regimen_text.is_empty() {
        parts.push("Regimen:".into());
        for line in c.regimen_text.lines() {
            parts.push(format!("  {}", line));
        }
    }
    if !c.safety_text.is_empty() {
        parts.push(format!("⚠ {}", c.safety_text));
    }
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct CountingCalibration {
        records: Mutex<Vec<(String, f64, Option<String>, String, String)>>,
    }
    impl CalibrationSink for CountingCalibration {
        fn record(
            &self,
            label: &str,
            confidence: f64,
            case_id: Option<&str>,
            domain: &str,
            rationale: &str,
        ) {
            self.records.lock().push((
                label.into(),
                confidence,
                case_id.map(String::from),
                domain.into(),
                rationale.into(),
            ));
        }
    }

    struct ScriptedDoctor {
        out: Mutex<Option<Result<(Vec<Hypothesis>, String)>>>,
    }
    impl ScriptedDoctor {
        fn ok(h: Vec<Hypothesis>, draft: &str) -> Self {
            Self {
                out: Mutex::new(Some(Ok((h, draft.into())))),
            }
        }
        fn fail(msg: &str) -> Self {
            Self {
                out: Mutex::new(Some(Err(ConsultError::Doctor(msg.into())))),
            }
        }
    }
    impl DoctorFn for ScriptedDoctor {
        fn diagnose(&self, _: &Intake) -> Result<(Vec<Hypothesis>, String)> {
            self.out
                .lock()
                .take()
                .unwrap_or(Err(ConsultError::Doctor("exhausted".into())))
        }
    }

    struct ScriptedRunner(DryRunOutcome);
    impl DryRunner for ScriptedRunner {
        fn dry_run(&self, _draft: &str, _drugs: &[String], _: bool) -> DryRunOutcome {
            self.0.clone()
        }
    }

    fn intake_min(cc: &str) -> Intake {
        Intake {
            chief_complaint: cc.into(),
            ..Default::default()
        }
    }

    // ── Intake.as_prompt ────────────────────────────────────────────────────

    #[test]
    fn intake_prompt_includes_chief_complaint() {
        let i = Intake {
            chief_complaint: "chest pain".into(),
            age: Some(54),
            sex: Some("M".into()),
            history: "HTN".into(),
            exam: "LV heave".into(),
            labs: "Trop+".into(),
            drugs: vec!["aspirin".into(), "atorva".into()],
            ..Default::default()
        };
        let s = i.as_prompt();
        assert!(s.contains("Chief complaint: chest pain"));
        assert!(s.contains("Age: 54"));
        assert!(s.contains("Sex: M"));
        assert!(s.contains("History: HTN"));
        assert!(s.contains("Exam: LV heave"));
        assert!(s.contains("Labs: Trop+"));
        assert!(s.contains("Current regimen: aspirin, atorva"));
    }

    #[test]
    fn intake_prompt_omits_empty_fields() {
        let i = intake_min("headache");
        let s = i.as_prompt();
        assert_eq!(s, "Chief complaint: headache");
    }

    // ── DefaultDoctor ─────────────────────────────────────────────────────

    #[test]
    fn default_doctor_returns_low_conf_hypothesis() {
        let d = DefaultDoctor;
        let (h, draft) = d.diagnose(&intake_min("severe chest pain")).unwrap();
        assert_eq!(h.len(), 1);
        assert!(h[0].label.contains("Symptomatic"));
        assert_eq!(h[0].confidence, 0.3);
        assert!(draft.contains("No regimen prescribed"));
    }

    // ── consult orchestration ─────────────────────────────────────────────

    #[test]
    fn consult_records_each_hypothesis_via_calibration() {
        let doc = ScriptedDoctor::ok(
            vec![
                Hypothesis {
                    label: "STEMI".into(),
                    confidence: 0.7,
                    rationale: "ST elevation".into(),
                },
                Hypothesis {
                    label: "PE".into(),
                    confidence: 0.2,
                    rationale: "no risk factors".into(),
                },
            ],
            "regimen body",
        );
        let cal = CountingCalibration::default();
        let dr = NoopDryRunner;
        let runner = ConsultRunner::new(&doc, &cal, &dr);
        let intake = Intake {
            chief_complaint: "cp".into(),
            case_id: Some("case-1".into()),
            ..Default::default()
        };
        let c = runner.consult(intake, false);
        assert_eq!(c.differential.len(), 2);
        let recs = cal.records.lock();
        assert_eq!(recs.len(), 2);
        assert_eq!(recs[0].0, "STEMI");
        assert_eq!(recs[0].1, 0.7);
        assert_eq!(recs[0].2.as_deref(), Some("case-1"));
        assert_eq!(recs[0].3, "diagnosis");
        assert_eq!(recs[1].0, "PE");
    }

    #[test]
    fn consult_records_truncated_rationale() {
        let big = "x".repeat(2000);
        let doc = ScriptedDoctor::ok(
            vec![Hypothesis {
                label: "X".into(),
                confidence: 0.5,
                rationale: big,
            }],
            "draft",
        );
        let cal = CountingCalibration::default();
        let dr = NoopDryRunner;
        let runner = ConsultRunner::new(&doc, &cal, &dr);
        runner.consult(intake_min("cp"), false);
        let recs = cal.records.lock();
        assert_eq!(recs[0].4.chars().count(), 1000);
    }

    #[test]
    fn consult_refused_blanks_regimen() {
        let doc = ScriptedDoctor::ok(
            vec![Hypothesis {
                label: "x".into(),
                confidence: 0.5,
                rationale: "".into(),
            }],
            "draft contraindicated",
        );
        let cal = NoopCalibration;
        let dr = ScriptedRunner(DryRunOutcome {
            text: String::new(),
            citation_issues: Vec::new(),
            refused_reason: Some("warfarin + aspirin major interaction".into()),
        });
        let runner = ConsultRunner::new(&doc, &cal, &dr);
        let c = runner.consult(intake_min("cp"), false);
        assert!(c.refused);
        assert_eq!(c.regimen_text, "");
        assert!(c.refusal_reason.unwrap().contains("warfarin"));
    }

    #[test]
    fn consult_passes_through_safe_regimen_with_citation_warnings() {
        let doc = ScriptedDoctor::ok(
            vec![Hypothesis {
                label: "x".into(),
                confidence: 0.5,
                rationale: "".into(),
            }],
            "draft",
        );
        let cal = NoopCalibration;
        let dr = ScriptedRunner(DryRunOutcome {
            text: "annotated regimen".into(),
            citation_issues: vec!["PMID:1".into(), "DOI:x".into()],
            refused_reason: None,
        });
        let runner = ConsultRunner::new(&doc, &cal, &dr);
        let c = runner.consult(intake_min("cp"), false);
        assert!(!c.refused);
        assert_eq!(c.regimen_text, "annotated regimen");
        assert!(c.safety_text.contains("Soft citation warnings"));
        assert!(c.safety_text.contains("PMID:1"));
        assert_eq!(c.citation_issues.len(), 2);
    }

    #[test]
    fn consult_handles_doctor_error() {
        let doc = ScriptedDoctor::fail("LLM down");
        let cal = NoopCalibration;
        let dr = NoopDryRunner;
        let runner = ConsultRunner::new(&doc, &cal, &dr);
        let c = runner.consult(intake_min("cp"), false);
        assert_eq!(c.differential.len(), 1);
        assert!(c.differential[0].label.contains("failed"));
        assert_eq!(c.differential[0].confidence, 0.0);
        assert!(!c.refused);
    }

    // ── consult_summary ────────────────────────────────────────────────────

    #[test]
    fn summary_renders_diff_and_regimen() {
        let c = Consult {
            intake: intake_min("cp"),
            differential: vec![
                Hypothesis {
                    label: "STEMI".into(),
                    confidence: 0.7,
                    rationale: "ST elev".into(),
                },
            ],
            regimen_text: "aspirin 325 mg".into(),
            safety_text: String::new(),
            ..Default::default()
        };
        let s = consult_summary(&c);
        assert!(s.contains("🩺 Consult"));
        assert!(s.contains("STEMI"));
        assert!(s.contains("(70%)"));
        assert!(s.contains("Regimen:"));
        assert!(s.contains("aspirin 325 mg"));
    }

    #[test]
    fn summary_renders_refusal() {
        let c = Consult {
            intake: intake_min("cp"),
            refused: true,
            refusal_reason: Some("major interaction".into()),
            ..Default::default()
        };
        let s = consult_summary(&c);
        assert!(s.contains("❌ Regimen refused"));
        assert!(s.contains("major interaction"));
        assert!(!s.contains("Regimen:"));
    }

    #[test]
    fn summary_renders_safety_warning() {
        let c = Consult {
            intake: intake_min("cp"),
            regimen_text: "ok".into(),
            safety_text: "Soft citation warnings: PMID:1".into(),
            ..Default::default()
        };
        let s = consult_summary(&c);
        assert!(s.contains("⚠ Soft citation warnings"));
    }

    #[test]
    fn summary_caps_differential_at_five() {
        let mut diff = Vec::new();
        for i in 0..10 {
            diff.push(Hypothesis {
                label: format!("dx{}", i),
                confidence: 0.5,
                rationale: "x".into(),
            });
        }
        let c = Consult {
            intake: intake_min("cp"),
            differential: diff,
            ..Default::default()
        };
        let s = consult_summary(&c);
        assert!(s.contains("dx0"));
        assert!(s.contains("dx4"));
        assert!(!s.contains("dx5"));
    }
}
