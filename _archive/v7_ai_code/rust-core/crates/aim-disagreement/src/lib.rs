//! aim-disagreement — performance-based 4-zone HCI for AI-clinician
//! disagreement (Blumenthal-Lee framework, "Patient as a Project"
//! cornerstone, 2026-05-07).
//!
//! Default thresholds and rationale come from the Blumenthal & Lee 2024-2025
//! work cited in the manuscript: when AI and clinician disagree, the friction
//! / evidence requirement should scale with the *base rate of correctness* of
//! each side, not just absolute confidence.
//!
//! The 4 zones (AI conf × Clinician conf):
//!
//! | AI conf | Clin conf | Agree? | Zone               | UI behaviour                                     |
//! |---------|-----------|--------|--------------------|--------------------------------------------------|
//! | high    | high      | yes    | `Aligned`          | Auto-execute, log only                           |
//! | high    | low       | n/a    | `AiLeads`          | Show evidence; clinician confirm before exec     |
//! | low     | high      | n/a    | `ClinicianLeads`   | Defer to clinician; record disagreement for eval |
//! | low     | low       | n/a    | `Escalate`         | MDT review / second opinion / wait for more data |
//! | high    | high      | no     | `ConflictHighStakes` | Force MDT escalation + audit                  |

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum DisagreementError {
    #[error("confidence value {0} out of range 0..=1")]
    ConfidenceOutOfRange(f64),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Zone {
    /// Both sides confident, agree → execute with audit.
    Aligned,
    /// AI confident, clinician unsure → show evidence, require confirm.
    AiLeads,
    /// Clinician confident, AI unsure → follow clinician, record for AI eval.
    ClinicianLeads,
    /// Neither confident → escalate / wait for more data.
    Escalate,
    /// Both confident but disagree → forced MDT review.
    ConflictHighStakes,
}

#[derive(Clone, Copy, Debug, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct ZoneThresholds {
    /// Confidence threshold above which AI is considered "high-confidence".
    pub ai_high: f64,
    /// Confidence threshold above which clinician is "high-confidence".
    pub clinician_high: f64,
}

impl Default for ZoneThresholds {
    fn default() -> Self {
        Self {
            ai_high: 0.80,
            clinician_high: 0.75,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UiAction {
    /// Run the action without further UI friction; just log.
    AutoExecute,
    /// Show supporting evidence (PMIDs, lab trends) and require an
    /// explicit clinician click to confirm.
    ShowEvidenceConfirm,
    /// Defer to clinician's decision; record disagreement for AI eval.
    DeferToClinicianRecord,
    /// Wait for more data, second opinion, or MDT review.
    Escalate,
    /// Force MDT or attending review; do not auto-execute even with override.
    ForceMdtReview,
}

impl Zone {
    pub fn ui_action(self) -> UiAction {
        match self {
            Zone::Aligned => UiAction::AutoExecute,
            Zone::AiLeads => UiAction::ShowEvidenceConfirm,
            Zone::ClinicianLeads => UiAction::DeferToClinicianRecord,
            Zone::Escalate => UiAction::Escalate,
            Zone::ConflictHighStakes => UiAction::ForceMdtReview,
        }
    }
}

/// Classify the AI / clinician disagreement context into one of the 5 zones.
///
/// `ai_conf` and `clinician_conf` are calibrated 0–1 probabilities (AI's
/// posterior; clinician's stated confidence elicited via 5-point Likert and
/// mapped to 0/0.25/0.5/0.75/1).
///
/// `agree` is whether both sides recommend the same action. For numerical
/// answers this should be set by the caller after a domain-specific
/// equivalence check.
pub fn classify(
    ai_conf: f64,
    clinician_conf: f64,
    agree: bool,
    th: ZoneThresholds,
) -> Result<Zone, DisagreementError> {
    if !(0.0..=1.0).contains(&ai_conf) {
        return Err(DisagreementError::ConfidenceOutOfRange(ai_conf));
    }
    if !(0.0..=1.0).contains(&clinician_conf) {
        return Err(DisagreementError::ConfidenceOutOfRange(clinician_conf));
    }
    let ai_hi = ai_conf >= th.ai_high;
    let cl_hi = clinician_conf >= th.clinician_high;
    Ok(match (ai_hi, cl_hi, agree) {
        (true, true, true) => Zone::Aligned,
        (true, true, false) => Zone::ConflictHighStakes,
        (true, false, _) => Zone::AiLeads,
        (false, true, _) => Zone::ClinicianLeads,
        (false, false, _) => Zone::Escalate,
    })
}

/// Decision record used by upstream callers (and serialized to JSONL).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DisagreementOutcome {
    pub zone: Zone,
    pub ui_action: UiAction,
    pub ai_conf: f64,
    pub clinician_conf: f64,
    pub agree: bool,
    /// One-line human-readable summary for display / logging.
    pub summary: String,
}

pub fn classify_with_outcome(
    ai_conf: f64,
    clinician_conf: f64,
    agree: bool,
    th: ZoneThresholds,
) -> Result<DisagreementOutcome, DisagreementError> {
    let zone = classify(ai_conf, clinician_conf, agree, th)?;
    let ui_action = zone.ui_action();
    let summary = match zone {
        Zone::Aligned => format!(
            "Aligned (AI {:.0}% / clin {:.0}%) — auto-execute with audit",
            ai_conf * 100.0,
            clinician_conf * 100.0
        ),
        Zone::AiLeads => format!(
            "AI leads (AI {:.0}% > clin {:.0}%) — show evidence, require confirm",
            ai_conf * 100.0,
            clinician_conf * 100.0
        ),
        Zone::ClinicianLeads => format!(
            "Clinician leads (AI {:.0}% < clin {:.0}%) — defer + record disagreement",
            ai_conf * 100.0,
            clinician_conf * 100.0
        ),
        Zone::Escalate => format!(
            "Escalate (both unsure: AI {:.0}%, clin {:.0}%) — wait/MDT/more data",
            ai_conf * 100.0,
            clinician_conf * 100.0
        ),
        Zone::ConflictHighStakes => format!(
            "Conflict-high-stakes (AI {:.0}% vs clin {:.0}%, disagree) — force MDT",
            ai_conf * 100.0,
            clinician_conf * 100.0
        ),
    };
    Ok(DisagreementOutcome { zone, ui_action, ai_conf, clinician_conf, agree, summary })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aligned_path() {
        let z = classify(0.95, 0.90, true, ZoneThresholds::default()).unwrap();
        assert_eq!(z, Zone::Aligned);
        assert_eq!(z.ui_action(), UiAction::AutoExecute);
    }

    #[test]
    fn high_high_disagree_is_conflict_high_stakes() {
        let z = classify(0.95, 0.90, false, ZoneThresholds::default()).unwrap();
        assert_eq!(z, Zone::ConflictHighStakes);
        assert_eq!(z.ui_action(), UiAction::ForceMdtReview);
    }

    #[test]
    fn ai_high_clin_low_is_ai_leads() {
        let z = classify(0.95, 0.40, true, ZoneThresholds::default()).unwrap();
        assert_eq!(z, Zone::AiLeads);
        // even when "agree", AI-leads UI shows evidence + confirm because
        // clinician has low confidence — protects against rubber-stamping.
        assert_eq!(z.ui_action(), UiAction::ShowEvidenceConfirm);
    }

    #[test]
    fn ai_low_clin_high_is_clinician_leads() {
        let z = classify(0.30, 0.90, false, ZoneThresholds::default()).unwrap();
        assert_eq!(z, Zone::ClinicianLeads);
        assert_eq!(z.ui_action(), UiAction::DeferToClinicianRecord);
    }

    #[test]
    fn both_low_is_escalate() {
        let z = classify(0.40, 0.50, false, ZoneThresholds::default()).unwrap();
        assert_eq!(z, Zone::Escalate);
        assert_eq!(z.ui_action(), UiAction::Escalate);
    }

    #[test]
    fn rejects_out_of_range_ai_conf() {
        let err = classify(1.5, 0.5, true, ZoneThresholds::default()).unwrap_err();
        assert_eq!(err, DisagreementError::ConfidenceOutOfRange(1.5));
    }

    #[test]
    fn rejects_negative_clinician_conf() {
        let err = classify(0.5, -0.1, true, ZoneThresholds::default()).unwrap_err();
        assert!(matches!(err, DisagreementError::ConfidenceOutOfRange(_)));
    }

    #[test]
    fn custom_thresholds() {
        // raise AI threshold so 0.85 is no longer "high"
        let th = ZoneThresholds { ai_high: 0.90, clinician_high: 0.75 };
        let z = classify(0.85, 0.80, true, th).unwrap();
        assert_eq!(z, Zone::ClinicianLeads);
    }

    #[test]
    fn outcome_carries_summary() {
        let r = classify_with_outcome(0.95, 0.90, true, ZoneThresholds::default()).unwrap();
        assert_eq!(r.zone, Zone::Aligned);
        assert!(r.summary.contains("Aligned"));
        assert_eq!(r.ui_action, UiAction::AutoExecute);
    }

    #[test]
    fn outcome_serde_roundtrip() {
        let r = classify_with_outcome(0.30, 0.85, false, ZoneThresholds::default()).unwrap();
        let s = serde_json::to_string(&r).unwrap();
        let r2: DisagreementOutcome = serde_json::from_str(&s).unwrap();
        assert_eq!(r, r2);
    }

    #[test]
    fn boundary_at_threshold() {
        // exactly at threshold should count as "high"
        let th = ZoneThresholds::default();
        let z = classify(th.ai_high, th.clinician_high, true, th).unwrap();
        assert_eq!(z, Zone::Aligned);
    }
}
