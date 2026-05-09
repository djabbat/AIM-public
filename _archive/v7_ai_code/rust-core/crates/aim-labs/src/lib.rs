//! aim-labs — kernel-powered lab interpretation.
//!
//! Port of `agents/labs.py` (deterministic core: red flags, pattern
//! detectors, alternative generator). The `kernel.decide()` invocation
//! is left to consumers; this crate emits ready-to-feed `Decision`-shape
//! payloads for `aim-kernel`.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LabsError {
    #[error("invalid value: {0}")]
    InvalidValue(String),
}

// ── analyte status ─────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnalyteStatus {
    Normal,
    Low,
    High,
    CriticalLow,
    CriticalHigh,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct AnalyteResult {
    pub value: f64,
    pub status: Option<AnalyteStatus>,
}

pub type Results = BTreeMap<String, AnalyteResult>;

pub fn results_from<I, S>(pairs: I) -> Results
where
    I: IntoIterator<Item = (S, f64, Option<AnalyteStatus>)>,
    S: Into<String>,
{
    pairs
        .into_iter()
        .map(|(k, v, s)| (k.into(), AnalyteResult { value: v, status: s }))
        .collect()
}

fn value_or(results: &Results, key: &str, default: f64) -> f64 {
    results
        .get(key)
        .map(|r| r.value)
        .unwrap_or(default)
}

fn value(results: &Results, key: &str) -> Option<f64> {
    results.get(key).map(|r| r.value)
}

// ── critical patterns (L1 red flags) ───────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RedFlag {
    pub name: String,
    pub message: String,
    pub action: String,
}

pub fn detect_red_flags(results: &Results) -> Vec<RedFlag> {
    let mut flags: Vec<RedFlag> = Vec::new();
    let push = |flags: &mut Vec<RedFlag>, name: &str, msg: &str| {
        flags.push(RedFlag {
            name: name.into(),
            message: msg.into(),
            action: "urgent_intervention".into(),
        });
    };

    if value_or(results, "potassium", 0.0) > 6.5 {
        push(&mut flags, "hyperkalemia_severe", "K+ > 6.5 mmol/L — риск аритмии");
    }
    if value_or(results, "sodium", 140.0) < 120.0 {
        push(&mut flags, "hyponatremia_severe", "Na+ < 120 mmol/L — риск seizure/coma");
    }
    if value_or(results, "glucose", 5.0) < 2.8 {
        push(&mut flags, "hypoglycemia", "Gluc < 2.8 mmol/L — neurological risk");
    }
    if value_or(results, "glucose", 5.0) > 15.0 {
        push(&mut flags, "hyperglycemia_dka_suspect", "Gluc > 15 mmol/L — suspect DKA/HHS");
    }
    let hb_m = value_or(results, "hemoglobin_m", 150.0);
    let hb_f = value_or(results, "hemoglobin_f", 150.0);
    if hb_m < 70.0 || hb_f < 70.0 {
        push(&mut flags, "severe_anemia", "Hb < 70 g/L — severe anemia");
    }
    if value_or(results, "wbc", 5.0) < 1.0 {
        push(&mut flags, "severe_neutropenia", "WBC < 1.0 — neutropenic fever risk");
    }
    if value_or(results, "creatinine", 0.0) > 300.0 {
        push(&mut flags, "acute_kidney_injury", "Creat > 300 µmol/L — AKI");
    }
    if value_or(results, "platelets", 200.0) < 20.0 {
        push(&mut flags, "severe_thrombocytopenia", "Plt < 20 — bleeding risk");
    }
    flags
}

// ── pattern detectors ──────────────────────────────────────────────────────

pub fn detect_patterns(results: &Results) -> Vec<&'static str> {
    let mut out: Vec<&'static str> = Vec::new();

    let hb_m = value(results, "hemoglobin_m");
    let hb_f = value(results, "hemoglobin_f");
    let mcv = value(results, "mcv");
    let low_hb = matches!(hb_m, Some(v) if v < 130.0) || matches!(hb_f, Some(v) if v < 120.0);
    let low_mcv = matches!(mcv, Some(v) if v < 80.0);
    if low_hb && low_mcv {
        out.push("microcytic_anemia_iron_deficiency_suspect");
    }

    if matches!(value(results, "creatinine"), Some(v) if v > 120.0) {
        out.push("ckd_workup_needed");
    }

    let alt = value_or(results, "alt", 0.0);
    let ast = value_or(results, "ast", 0.0);
    if alt > 100.0 || ast > 100.0 {
        out.push("hepatocellular_injury");
    }

    if matches!(value(results, "ldl"), Some(v) if v > 4.9) {
        out.push("dyslipidemia_high_risk");
    }

    if value_or(results, "wbc", 0.0) > 12.0 || value_or(results, "crp", 0.0) > 50.0 {
        out.push("inflammation_infection_suspect");
    }

    if matches!(value(results, "tsh"), Some(v) if v > 10.0) {
        out.push("hypothyroidism_suspect");
    }

    out
}

// ── decision generation ────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AltDecision {
    pub id: String,
    pub action_type: String,
    pub description: String,
    pub payload: serde_json::Value,
}

pub fn any_abnormal(results: &Results) -> bool {
    results
        .values()
        .any(|r| matches!(r.status, Some(AnalyteStatus::Low) | Some(AnalyteStatus::High)
            | Some(AnalyteStatus::CriticalLow) | Some(AnalyteStatus::CriticalHigh)))
}

pub fn any_critical(results: &Results) -> bool {
    results
        .values()
        .any(|r| matches!(r.status, Some(AnalyteStatus::CriticalLow) | Some(AnalyteStatus::CriticalHigh)))
}

#[derive(Clone, Debug, Default)]
pub struct PatientCtx {
    pub primary_complaint_undiagnosed: bool,
}

pub fn generate_alternatives(
    results: &Results,
    red_flags: &[RedFlag],
    patterns: &[&'static str],
    patient: &PatientCtx,
) -> Vec<AltDecision> {
    let mut alts: Vec<AltDecision> = Vec::new();

    let abnormal = any_abnormal(results);
    let critical = any_critical(results);

    if critical || !red_flags.is_empty() {
        let flags_summary: Vec<&str> = red_flags.iter().map(|f| f.message.as_str()).collect();
        let detail = if flags_summary.is_empty() {
            "critical values".to_string()
        } else {
            flags_summary.join("; ")
        };
        alts.push(AltDecision {
            id: "urgent_ref".into(),
            action_type: "referral".into(),
            description: format!(
                "Срочное направление (ER/stationary). Red flags: {}",
                detail
            ),
            payload: serde_json::json!({
                "urgency": "immediate",
                "red_flags": red_flags.iter().map(|f| f.message.clone()).collect::<Vec<_>>(),
                "guideline_based": true,
            }),
        });
    }

    let has = |p: &str| patterns.contains(&p);

    if has("microcytic_anemia_iron_deficiency_suspect") {
        alts.push(AltDecision {
            id: "iron_panel".into(),
            action_type: "test".into(),
            description: "Iron panel + ferritin + TIBC + reticulocytes".into(),
            payload: serde_json::json!({
                "tests": ["iron", "ferritin", "tibc", "reticulocytes"],
                "guideline_based": true,
            }),
        });
    }
    if has("ckd_workup_needed") {
        alts.push(AltDecision {
            id: "ckd_workup".into(),
            action_type: "test".into(),
            description: "eGFR + cystatin C + urine ACR + renal US".into(),
            payload: serde_json::json!({
                "tests": ["egfr", "cystatin_c", "urine_acr"],
                "guideline_based": true,
            }),
        });
    }
    if has("hepatocellular_injury") {
        alts.push(AltDecision {
            id: "hepa_workup".into(),
            action_type: "test".into(),
            description: "Hepatitis panel + INR + albumin + abdominal US".into(),
            payload: serde_json::json!({
                "tests": ["hep_abc_serology", "inr", "albumin"],
                "guideline_based": true,
            }),
        });
    }
    if has("dyslipidemia_high_risk") {
        alts.push(AltDecision {
            id: "cv_risk_assess".into(),
            action_type: "test".into(),
            description: "Lipid profile full + ApoB + Lp(a) + CV risk calc".into(),
            payload: serde_json::json!({
                "tests": ["full_lipid", "apob", "lpa"],
                "guideline_based": true,
            }),
        });
    }
    if has("hypothyroidism_suspect") {
        alts.push(AltDecision {
            id: "thyroid_workup".into(),
            action_type: "test".into(),
            description: "Free T4 + anti-TPO + anti-TG антитела".into(),
            payload: serde_json::json!({
                "tests": ["ft4", "anti_tpo", "anti_tg"],
                "guideline_based": true,
            }),
        });
    }

    // Generic follow-up if abnormal but no pattern matched a workup
    let workup_count = alts
        .iter()
        .filter(|a| a.action_type == "test")
        .count();
    if abnormal && workup_count == 0 && !alts.iter().any(|a| a.id == "urgent_ref") {
        alts.push(AltDecision {
            id: "repeat_panel".into(),
            action_type: "test".into(),
            description: "Повторить panel через 2-4 недели для trend".into(),
            payload: serde_json::json!({"guideline_based": true}),
        });
    }

    if !abnormal && red_flags.is_empty() {
        if patient.primary_complaint_undiagnosed {
            alts.push(AltDecision {
                id: "expanded_workup".into(),
                action_type: "test".into(),
                description: "Лабы нормальны, но жалобы остаются → расширенный workup".into(),
                payload: serde_json::json!({"guideline_based": true}),
            });
            alts.push(AltDecision {
                id: "specialist_ref".into(),
                action_type: "referral".into(),
                description: "Консультация профильного специалиста".into(),
                payload: serde_json::json!({}),
            });
        } else {
            alts.push(AltDecision {
                id: "reassure".into(),
                action_type: "dx".into(),
                description: "Все лабораторные параметры в пределах нормы, reassurance".into(),
                payload: serde_json::json!({"has_confirmed_dx_ctx": false}),
            });
        }
    }

    if !alts.iter().any(|a| a.action_type == "referral") {
        alts.push(AltDecision {
            id: "gp_followup".into(),
            action_type: "referral".into(),
            description: "Follow-up у GP через 2-4 недели".into(),
            payload: serde_json::json!({}),
        });
    }
    alts
}

#[cfg(test)]
mod tests {
    use super::*;

    fn r(value: f64, status: Option<AnalyteStatus>) -> AnalyteResult {
        AnalyteResult { value, status }
    }

    fn results_with(pairs: &[(&str, f64, Option<AnalyteStatus>)]) -> Results {
        pairs
            .iter()
            .map(|(k, v, s)| (k.to_string(), r(*v, *s)))
            .collect()
    }

    // ── red flags ──────────────────────────────────────────────────────────

    #[test]
    fn red_flag_hyperkalemia() {
        let res = results_with(&[("potassium", 7.0, Some(AnalyteStatus::CriticalHigh))]);
        let flags = detect_red_flags(&res);
        assert_eq!(flags.len(), 1);
        assert_eq!(flags[0].name, "hyperkalemia_severe");
    }

    #[test]
    fn red_flag_hypoglycemia_and_dka() {
        // Cannot have both at once but each independently
        let r1 = results_with(&[("glucose", 2.0, None)]);
        assert_eq!(detect_red_flags(&r1)[0].name, "hypoglycemia");
        let r2 = results_with(&[("glucose", 18.0, None)]);
        assert_eq!(detect_red_flags(&r2)[0].name, "hyperglycemia_dka_suspect");
    }

    #[test]
    fn red_flag_severe_anemia_either_sex_field() {
        let r1 = results_with(&[("hemoglobin_m", 65.0, None)]);
        assert!(detect_red_flags(&r1).iter().any(|f| f.name == "severe_anemia"));
        let r2 = results_with(&[("hemoglobin_f", 60.0, None)]);
        assert!(detect_red_flags(&r2).iter().any(|f| f.name == "severe_anemia"));
    }

    #[test]
    fn red_flag_aki_neutropenia_thrombocytopenia() {
        let res = results_with(&[
            ("creatinine", 320.0, None),
            ("wbc", 0.5, None),
            ("platelets", 15.0, None),
        ]);
        let flags = detect_red_flags(&res);
        let names: Vec<&str> = flags.iter().map(|f| f.name.as_str()).collect();
        assert!(names.contains(&"acute_kidney_injury"));
        assert!(names.contains(&"severe_neutropenia"));
        assert!(names.contains(&"severe_thrombocytopenia"));
    }

    #[test]
    fn red_flag_no_flags_when_normal() {
        let res = results_with(&[
            ("potassium", 4.0, Some(AnalyteStatus::Normal)),
            ("glucose", 5.0, Some(AnalyteStatus::Normal)),
        ]);
        assert!(detect_red_flags(&res).is_empty());
    }

    #[test]
    fn red_flag_action_is_urgent_intervention() {
        let res = results_with(&[("potassium", 7.0, None)]);
        let flags = detect_red_flags(&res);
        assert_eq!(flags[0].action, "urgent_intervention");
    }

    // ── patterns ───────────────────────────────────────────────────────────

    #[test]
    fn pattern_microcytic_anemia() {
        let res = results_with(&[("hemoglobin_m", 110.0, None), ("mcv", 75.0, None)]);
        let p = detect_patterns(&res);
        assert!(p.contains(&"microcytic_anemia_iron_deficiency_suspect"));
    }

    #[test]
    fn pattern_ckd() {
        let res = results_with(&[("creatinine", 150.0, None)]);
        assert!(detect_patterns(&res).contains(&"ckd_workup_needed"));
    }

    #[test]
    fn pattern_hepatocellular() {
        let res = results_with(&[("alt", 200.0, None)]);
        assert!(detect_patterns(&res).contains(&"hepatocellular_injury"));
    }

    #[test]
    fn pattern_dyslipidemia() {
        let res = results_with(&[("ldl", 5.5, None)]);
        assert!(detect_patterns(&res).contains(&"dyslipidemia_high_risk"));
    }

    #[test]
    fn pattern_inflammation() {
        let r1 = results_with(&[("wbc", 14.0, None)]);
        assert!(detect_patterns(&r1).contains(&"inflammation_infection_suspect"));
        let r2 = results_with(&[("crp", 80.0, None)]);
        assert!(detect_patterns(&r2).contains(&"inflammation_infection_suspect"));
    }

    #[test]
    fn pattern_hypothyroidism() {
        let res = results_with(&[("tsh", 12.0, None)]);
        assert!(detect_patterns(&res).contains(&"hypothyroidism_suspect"));
    }

    // ── alternatives ───────────────────────────────────────────────────────

    #[test]
    fn alternatives_critical_emits_urgent_ref() {
        let res = results_with(&[("potassium", 7.0, Some(AnalyteStatus::CriticalHigh))]);
        let flags = detect_red_flags(&res);
        let alts = generate_alternatives(&res, &flags, &[], &PatientCtx::default());
        assert!(alts.iter().any(|a| a.id == "urgent_ref"));
    }

    #[test]
    fn alternatives_ckd_pattern_emits_workup() {
        let res = results_with(&[("creatinine", 150.0, Some(AnalyteStatus::High))]);
        let flags: Vec<RedFlag> = Vec::new();
        let p = vec!["ckd_workup_needed"];
        let alts = generate_alternatives(&res, &flags, &p, &PatientCtx::default());
        assert!(alts.iter().any(|a| a.id == "ckd_workup"));
    }

    #[test]
    fn alternatives_normal_with_complaint_emits_expanded_workup() {
        let res = results_with(&[("glucose", 5.0, Some(AnalyteStatus::Normal))]);
        let alts = generate_alternatives(
            &res,
            &[],
            &[],
            &PatientCtx {
                primary_complaint_undiagnosed: true,
            },
        );
        assert!(alts.iter().any(|a| a.id == "expanded_workup"));
        assert!(alts.iter().any(|a| a.id == "specialist_ref"));
        assert!(!alts.iter().any(|a| a.id == "reassure"));
    }

    #[test]
    fn alternatives_normal_without_complaint_emits_reassure() {
        let res = results_with(&[("glucose", 5.0, Some(AnalyteStatus::Normal))]);
        let alts = generate_alternatives(&res, &[], &[], &PatientCtx::default());
        assert!(alts.iter().any(|a| a.id == "reassure"));
        assert!(!alts.iter().any(|a| a.id == "expanded_workup"));
    }

    #[test]
    fn alternatives_abnormal_without_pattern_emits_repeat_panel() {
        let res = results_with(&[("potassium", 5.5, Some(AnalyteStatus::High))]);
        let alts = generate_alternatives(&res, &[], &[], &PatientCtx::default());
        assert!(alts.iter().any(|a| a.id == "repeat_panel"));
    }

    #[test]
    fn alternatives_always_include_referral_baseline() {
        let res = results_with(&[("glucose", 5.0, Some(AnalyteStatus::Normal))]);
        let alts = generate_alternatives(&res, &[], &[], &PatientCtx::default());
        assert!(alts.iter().any(|a| a.action_type == "referral"));
    }

    // ── any_abnormal / any_critical ────────────────────────────────────────

    #[test]
    fn any_abnormal_detects_low_high_critical_states() {
        let r1 = results_with(&[("x", 1.0, Some(AnalyteStatus::Normal))]);
        assert!(!any_abnormal(&r1));
        let r2 = results_with(&[("x", 1.0, Some(AnalyteStatus::Low))]);
        assert!(any_abnormal(&r2));
        let r3 = results_with(&[("x", 1.0, Some(AnalyteStatus::CriticalHigh))]);
        assert!(any_critical(&r3));
    }
}
