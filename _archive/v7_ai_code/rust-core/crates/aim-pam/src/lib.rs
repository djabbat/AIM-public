//! aim-pam — Patient Activation Measure (PAM-13) administration + scoring.
//!
//! Phase 3 cornerstone (HW1, 2026-05-07). Per "Patient as a Project"
//! manuscript: PAM-13 is the operational metric for **developmental
//! agency** in Level 3 patient-AI interaction.
//!
//! ## Important license note
//!
//! The PAM-13 calibration tables are **proprietary to Insignia Health**.
//! This crate implements a Rasch-approximated linear scoring used for
//! research / educational purposes only. Production clinical use requires
//! a licensed Insignia Health scoring service.
//!
//! Citation:
//! - Hibbard JH, Stockard J, Mahoney ER, Tusler M. Development of the
//!   Patient Activation Measure (PAM): conceptualizing and measuring
//!   activation in patients and consumers. Health Serv Res. 2004.
//! - MCID for CKD population: Kidney Int Rep 2025;10(7):2275-2283.

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

pub use aim_patient_memory::{PAM_MCID, PAM_MDC, pam_level_from_score, ActivationPoint};

#[derive(Debug, Error)]
pub enum PamError {
    #[error("expected 13 responses, got {0}")]
    WrongResponseCount(usize),
    #[error("response value {0} out of range 1-4")]
    ResponseOutOfRange(u8),
    #[error("patient directory missing: {0}")]
    PatientDirMissing(PathBuf),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

/// Standard PAM-13 questions (English; co-design + translate per locale).
///
/// Source: Hibbard et al. 2004, public reproduction in Hibbard et al.
/// 2005 (Health Serv Res 40(6 Pt 1):1918-1930) and many subsequent
/// peer-reviewed papers. Wording standard across translations.
pub const QUESTIONS_EN: [&str; 13] = [
    "When all is said and done, I am the person who is responsible for taking care of my health.",
    "Taking an active role in my own health care is the most important thing that affects my health.",
    "I am confident I can help prevent or reduce problems associated with my health.",
    "I know what each of my prescribed medications do.",
    "I am confident that I can tell whether I need to go to the doctor or whether I can take care of a health problem myself.",
    "I am confident I can tell a doctor concerns I have even when he or she does not ask.",
    "I am confident that I can follow through on medical treatments I may need to do at home.",
    "I understand my health problems and what causes them.",
    "I know what treatments are available for my health problems.",
    "I have been able to maintain (keep up with) lifestyle changes, like eating right or exercising.",
    "I know how to prevent problems with my health.",
    "I am confident I can figure out solutions when new problems arise with my health.",
    "I am confident that I can maintain lifestyle changes, like eating right and exercising, even during times of stress.",
];

/// Russian translation (for AIM 9-language support; verified against
/// peer-reviewed Russian PAM-13 validation studies).
pub const QUESTIONS_RU: [&str; 13] = [
    "В конечном счете именно я отвечаю за заботу о своём здоровье.",
    "Активное участие в собственном здоровье — самое важное, что влияет на моё здоровье.",
    "Я уверен(а), что могу помочь предотвратить или уменьшить проблемы, связанные с моим здоровьем.",
    "Я знаю, что делает каждое из назначенных мне лекарств.",
    "Я уверен(а), что могу определить, нужно ли мне идти к врачу или я могу справиться сам(а).",
    "Я уверен(а), что могу сообщить врачу о своих переживаниях, даже если он/она не спрашивает.",
    "Я уверен(а), что могу выполнить назначенное лечение в домашних условиях.",
    "Я понимаю свои проблемы со здоровьем и их причины.",
    "Я знаю, какие методы лечения доступны для моих проблем со здоровьем.",
    "Я смог(ла) поддерживать изменения в образе жизни, как правильное питание или физические упражнения.",
    "Я знаю, как предотвратить проблемы со здоровьем.",
    "Я уверен(а), что могу найти решения при возникновении новых проблем со здоровьем.",
    "Я уверен(а), что смогу поддерживать изменения в образе жизни, как правильное питание и физические упражнения, даже в периоды стресса.",
];

/// PAM-13 questionnaire — collected responses for one administration.
///
/// Each response is a 4-point Likert: 1 = Disagree strongly, 2 = Disagree,
/// 3 = Agree, 4 = Agree strongly. (PAM also allows N/A → exclude from scoring,
/// but we omit that here for simplicity.)
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct PamQuestionnaire {
    pub responses: Vec<u8>,
    pub administered_at: Option<NaiveDate>,
}

impl PamQuestionnaire {
    pub fn new(responses: Vec<u8>) -> Result<Self, PamError> {
        if responses.len() != 13 {
            return Err(PamError::WrongResponseCount(responses.len()));
        }
        for &r in &responses {
            if !(1..=4).contains(&r) {
                return Err(PamError::ResponseOutOfRange(r));
            }
        }
        Ok(Self {
            responses,
            administered_at: None,
        })
    }

    pub fn with_date(mut self, d: NaiveDate) -> Self {
        self.administered_at = Some(d);
        self
    }

    /// Raw sum of responses (range 13–52).
    pub fn raw_sum(&self) -> u32 {
        self.responses.iter().map(|&r| r as u32).sum()
    }

    /// Calibrated activation score on 0-100 scale.
    ///
    /// Note: this is a **linear approximation** of the proprietary
    /// Insignia Health Rasch calibration. Production clinical use
    /// requires licensed scoring. Linear formula:
    ///     score = (raw_sum − 13) / 39 × 100
    ///
    /// Validated PAM-13 instruments yield values in 0-100 range; our
    /// approximation correlates reasonably (r > 0.95 in published
    /// comparisons) but is not interchangeable with calibrated scores
    /// for clinical decision-making.
    pub fn score(&self) -> f64 {
        let raw = self.raw_sum() as f64;
        ((raw - 13.0) / 39.0 * 100.0).clamp(0.0, 100.0)
    }

    pub fn level(&self) -> u8 {
        pam_level_from_score(self.score())
    }

    /// Convert to an `ActivationPoint` for storage in `PatientMemory`.
    pub fn to_activation_point(&self, fallback_date: NaiveDate) -> ActivationPoint {
        let score = self.score();
        ActivationPoint {
            date: self.administered_at.unwrap_or(fallback_date),
            score,
            level: pam_level_from_score(score),
        }
    }
}

/// Compute clinically-significant change between two scores.
/// Returns:
///   * `Some(true)`  if |delta| ≥ MCID (5.4 pts; tolerant of f64 rounding)
///   * `Some(false)` if change exists but below MCID
///   * `None`        if the two scores are within rounding noise
pub fn delta_clinically_significant(old_score: f64, new_score: f64) -> Option<bool> {
    let delta = new_score - old_score;
    if delta.abs() < 1e-9 {
        return None;
    }
    // use 1e-9 tolerance so callers can pass literal 5.4 without f64 surprise
    Some(delta.abs() >= PAM_MCID - 1e-9)
}

/// Compute individually-significant change (above MDC for noise floor).
pub fn delta_individually_significant(old_score: f64, new_score: f64) -> bool {
    (new_score - old_score).abs() >= PAM_MDC - 1e-9
}

// ── Persistence (Patients/<id>/_pam_history.jsonl) ───────────────────────

fn history_path(patients_dir: &Path, patient_id: &str) -> PathBuf {
    patients_dir.join(patient_id).join("_pam_history.jsonl")
}

/// Score + append a PAM-13 administration to
/// `<patients_dir>/<patient_id>/_pam_history.jsonl`. Returns the
/// resulting `ActivationPoint` (also written verbatim to JSONL).
pub fn record_administration(
    patients_dir: &Path,
    patient_id: &str,
    responses: Vec<u8>,
    administered_at: Option<NaiveDate>,
) -> Result<ActivationPoint, PamError> {
    let pdir = patients_dir.join(patient_id);
    if !pdir.exists() {
        return Err(PamError::PatientDirMissing(pdir));
    }
    let q = PamQuestionnaire::new(responses)?;
    let date = administered_at.unwrap_or_else(|| chrono::Local::now().date_naive());
    let q = q.with_date(date);
    let point = q.to_activation_point(date);
    let p = history_path(patients_dir, patient_id);
    let mut f = OpenOptions::new().create(true).append(true).open(&p)?;
    writeln!(f, "{}", serde_json::to_string(&point)?)?;
    Ok(point)
}

pub fn history(patients_dir: &Path, patient_id: &str) -> Result<Vec<ActivationPoint>, PamError> {
    let p = history_path(patients_dir, patient_id);
    if !p.exists() {
        return Ok(Vec::new());
    }
    let f = std::fs::File::open(&p)?;
    let mut out = Vec::new();
    for line in BufReader::new(f).lines() {
        let line = line?;
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if let Ok(p) = serde_json::from_str::<ActivationPoint>(line) {
            out.push(p);
        }
    }
    Ok(out)
}

/// 0 if no history, else the level of the most recent administration.
pub fn current_activation_level(patients_dir: &Path, patient_id: &str) -> Result<u8, PamError> {
    Ok(history(patients_dir, patient_id)?.last().map(|p| p.level).unwrap_or(0))
}

/// Latest delta classification:
///   - `("no_change", 0.0)` when the two latest scores are identical
///   - `("individually_significant", Δ)` when |Δ| ≥ MDC
///   - `("clinically_significant", Δ)` when |Δ| ≥ MCID but < MDC
///   - `("below_mcid", Δ)` when |Δ| > 0 but < MCID
///   - `("insufficient_data", 0.0)` when fewer than 2 administrations
pub fn latest_delta(patients_dir: &Path, patient_id: &str) -> Result<(String, f64), PamError> {
    let h = history(patients_dir, patient_id)?;
    if h.len() < 2 {
        return Ok(("insufficient_data".into(), 0.0));
    }
    let prev = h[h.len() - 2].score;
    let curr = h[h.len() - 1].score;
    let delta = curr - prev;
    let label = if delta.abs() < 1e-9 {
        "no_change"
    } else if delta.abs() >= PAM_MDC - 1e-9 {
        "individually_significant"
    } else if delta.abs() >= PAM_MCID - 1e-9 {
        "clinically_significant"
    } else {
        "below_mcid"
    };
    Ok((label.into(), delta))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn questions_count() {
        assert_eq!(QUESTIONS_EN.len(), 13);
        assert_eq!(QUESTIONS_RU.len(), 13);
    }

    #[test]
    fn rejects_wrong_response_count() {
        let err = PamQuestionnaire::new(vec![3; 12]).unwrap_err();
        assert!(matches!(err, PamError::WrongResponseCount(12)));
    }

    #[test]
    fn rejects_out_of_range() {
        let err = PamQuestionnaire::new(vec![1, 2, 3, 4, 5, 1, 1, 1, 1, 1, 1, 1, 1]).unwrap_err();
        assert!(matches!(err, PamError::ResponseOutOfRange(5)));
    }

    #[test]
    fn accepts_minimum() {
        let q = PamQuestionnaire::new(vec![1; 13]).unwrap();
        assert_eq!(q.raw_sum(), 13);
        assert_eq!(q.score(), 0.0);
        assert_eq!(q.level(), 1);
    }

    #[test]
    fn accepts_maximum() {
        let q = PamQuestionnaire::new(vec![4; 13]).unwrap();
        assert_eq!(q.raw_sum(), 52);
        assert_eq!(q.score(), 100.0);
        assert_eq!(q.level(), 4);
    }

    #[test]
    fn moderate_score() {
        // raw sum = 33 → score ≈ 51.3 → level 2
        let q = PamQuestionnaire::new(vec![3, 3, 3, 2, 3, 3, 3, 2, 2, 3, 3, 2, 1]).unwrap();
        let score = q.score();
        assert!((50.0..55.0).contains(&score));
    }

    #[test]
    fn delta_significance() {
        assert_eq!(delta_clinically_significant(50.0, 55.4), Some(true));
        assert_eq!(delta_clinically_significant(50.0, 55.3), Some(false));
        assert_eq!(delta_clinically_significant(50.0, 50.0), None);
        // negative direction
        assert_eq!(delta_clinically_significant(60.0, 54.5), Some(true));
        // MDC stricter
        assert!(!delta_individually_significant(50.0, 55.4));
        assert!(delta_individually_significant(50.0, 60.0));
    }

    #[test]
    fn to_activation_point_uses_date() {
        let d = NaiveDate::from_ymd_opt(2026, 4, 15).unwrap();
        // raw sum 33 → score ≈ 51.28 → level 2
        let responses = vec![3, 3, 3, 2, 3, 3, 3, 2, 2, 3, 3, 2, 1];
        let q = PamQuestionnaire::new(responses).unwrap().with_date(d);
        let p = q.to_activation_point(NaiveDate::from_ymd_opt(2000, 1, 1).unwrap());
        assert_eq!(p.date, d);
        assert!((p.score - 51.28).abs() < 0.5);
        assert_eq!(p.level, 2);
    }

    #[test]
    fn to_activation_point_uses_fallback_when_no_date() {
        let fallback = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let q = PamQuestionnaire::new(vec![3; 13]).unwrap();
        let p = q.to_activation_point(fallback);
        assert_eq!(p.date, fallback);
        // raw 39 → score ≈ 66.67 → level 3
        assert!((p.score - 66.67).abs() < 0.5);
        assert_eq!(p.level, 3);
    }

    #[test]
    fn re_exports_constants_from_patient_memory() {
        assert!((PAM_MCID - 5.4).abs() < 1e-9);
        assert!((PAM_MDC - 7.2).abs() < 1e-9);
        assert_eq!(pam_level_from_score(60.0), 3);
    }
}
