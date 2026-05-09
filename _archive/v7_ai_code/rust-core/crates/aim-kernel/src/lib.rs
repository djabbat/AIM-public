//! aim-kernel — decision laws + Ze-formula scoring.
//!
//! Port of `agents/kernel.py`. Covers:
//!   • Three Laws + Zeroth Law (L0–L3)
//!   • Extended laws (L_PRIVACY, L_CONSENT, L_VERIFIABILITY, L_AGENCY)
//!   • Impedance / 𝒞 / Φ_Ze / ethics scoring (deterministic checklist core)
//!
//! Skipped (deferred to higher-level crates with their own dependencies):
//!   • LLM-delta impedance (needs `aim-llm`)
//!   • DB audit logging (needs `aim-cost-ledger` style sink)
//!   • decide() / format_compact / format_verbose (CLI / locale concerns)

use std::collections::BTreeMap;

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum KernelError {
    #[error("kernel violation: {0}")]
    Violation(String),
}

pub type Result<T> = std::result::Result<T, KernelError>;

const EPS: f64 = 1e-6;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Decision {
    pub id: String,
    pub description: String,
    pub action_type: String,
    pub payload: serde_json::Value,
    pub meta: serde_json::Value,
}

impl Decision {
    pub fn new(id: impl Into<String>, action_type: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            description: String::new(),
            action_type: action_type.into(),
            payload: serde_json::json!({}),
            meta: serde_json::json!({}),
        }
    }

    pub fn payload_str(&self, key: &str) -> &str {
        self.payload.get(key).and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn payload_bool(&self, key: &str) -> bool {
        self.payload.get(key).and_then(|v| v.as_bool()).unwrap_or(false)
    }

    pub fn payload_array<'a>(&'a self, key: &str) -> &'a [serde_json::Value] {
        self.payload
            .get(key)
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
    }

    fn payload_blob_lower(&self) -> String {
        serde_json::to_string(&self.payload)
            .unwrap_or_default()
            .to_lowercase()
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Patient {
    pub allergies: Vec<String>,
    pub medications: Vec<Medication>,
    pub red_flags: Vec<String>,
    pub missing_labs_count: i32,
    pub history_contradictions: i32,
    pub unexplained_symptoms_count: i32,
    pub last_visit_years_ago: i32,
    pub dx_without_evidence: bool,
    /// `primary_complaint_undiagnosed` defaults to `true` per Python; use
    /// `Patient::with_diagnosed_complaint()` to override.
    pub primary_complaint_undiagnosed: bool,
    pub has_confirmed_dx: bool,
    pub refusal_noted: bool,
    /// Patient Activation Measure (PAM-13) level 1-4. 0 = unknown / not
    /// administered. Used by L_AGENCY: level 1 = disengaged, accept
    /// physician-designed plan but flag for capacity-building; ≥2 = require
    /// co-design.
    pub activation_level: u8,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Medication {
    pub name: String,
}

impl Patient {
    pub fn new() -> Self {
        Self {
            primary_complaint_undiagnosed: true,
            ..Default::default()
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Context {
    pub commanded_action_type: Option<String>,
    pub privacy_consent: bool,
    pub user_confirmed: Option<bool>,
    pub impedance_before: Option<f64>,
    /// True if the action has been co-designed with the patient (Tao et al.,
    /// Nat Med 2026). Required by L_AGENCY for patients at activation level
    /// ≥2 before any treatment / lifestyle / behavior-change action.
    pub patient_codesigned: Option<bool>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LawsResult {
    pub l0: bool,
    pub l1: bool,
    pub l2: bool,
    pub l3: bool,
    pub reasons: Vec<String>,
}

impl LawsResult {
    pub fn passed(&self) -> bool {
        self.l0 && self.l1 && self.l2 && self.l3
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ExtendedLawsResult {
    pub privacy: bool,
    pub consent: bool,
    pub verifiability: bool,
    /// L_AGENCY (developmental agency, 2026-05-07 cornerstone). True =
    /// action either is not agency-relevant, or has been co-designed with
    /// the patient, or patient is too disengaged (level 1) for co-design
    /// to be meaningful (in which case a capacity-building flag is logged
    /// in `reasons` instead).
    pub agency: bool,
    pub reasons: Vec<String>,
}

impl ExtendedLawsResult {
    pub fn passed(&self) -> bool {
        self.privacy && self.consent && self.verifiability && self.agency
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ScoringResult {
    pub impedance_before: f64,
    pub impedance_after: f64,
    pub instant_c: f64,
    pub phi_ze: f64,
    pub ethics_ze_learn_cheat: f64,
    pub ethics_autonomy: f64,
    pub ethics_beneficence: f64,
    pub ethics_nonmaleficence: f64,
    pub ethics_justice: f64,
    pub ethics_composite: f64,
    pub utility: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct KernelWeights {
    pub alpha: f64,        // weight on 𝒞
    pub beta: f64,         // weight on Φ_Ze
    pub gamma: f64,        // weight on Ethics composite
    pub ethics_ze: f64,
    pub ethics_auto: f64,
    pub ethics_benef: f64,
    pub ethics_nonmal: f64,
    pub ethics_justice: f64,
    /// 𝓘 threshold above which kernel suggests clarifying questions
    /// before action. Mirrors Python `KernelWeights.CLARIFY_IMPEDANCE_THRESHOLD`.
    pub clarify_impedance_threshold: f64,
}

impl Default for KernelWeights {
    /// Defaults match Python `config.KernelWeights` (Q4 preset "balanced",
    /// AIM_KERNEL_ALPHA/BETA/GAMMA env defaults).
    fn default() -> Self {
        Self {
            alpha: parse_env("AIM_KERNEL_ALPHA", 0.2),
            beta: parse_env("AIM_KERNEL_BETA", 0.4),
            gamma: parse_env("AIM_KERNEL_GAMMA", 0.4),
            ethics_ze: 0.40,
            ethics_auto: 0.15,
            ethics_benef: 0.15,
            ethics_nonmal: 0.15,
            ethics_justice: 0.15,
            clarify_impedance_threshold: 0.7,
        }
    }
}

fn parse_env(key: &str, fallback: f64) -> f64 {
    std::env::var(key)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(fallback)
}

// ── L0 ──────────────────────────────────────────────────────────────────────

const DANGER_SIGNALS: &[&str] = &[
    "synthesize_biohazard",
    "make_explosive",
    "weapon_design",
    "forge_documents",
    "bypass_safety_system",
];

const BROAD_ABX: &[&str] = &["vancomycin", "meropenem", "piperacillin", "linezolid"];
const VIRAL_INDICATIONS: &[&str] = &["viral", "orvi", "uri", "common cold", "орви", "простуда"];

pub fn evaluate_l0(decision: &Decision) -> (bool, String) {
    let payload_lower = decision.payload_blob_lower();
    let desc_lower = decision.description.to_lowercase();
    for sig in DANGER_SIGNALS {
        let sig_space = sig.replace('_', " ");
        if payload_lower.contains(sig)
            || desc_lower.contains(sig)
            || desc_lower.contains(&sig_space)
            || payload_lower.contains(&sig_space)
        {
            return (false, format!("L0 block: danger signal '{}'", sig));
        }
    }
    if decision.action_type == "treatment" {
        let drug = decision.payload_str("drug").to_lowercase();
        let indication = decision.payload_str("indication").to_lowercase();
        let is_broad = BROAD_ABX.iter().any(|b| drug.contains(b));
        let is_viral = VIRAL_INDICATIONS.iter().any(|v| indication.contains(v));
        if is_broad && is_viral {
            return (
                false,
                "L0 risk: broad-spectrum ABx for likely viral — resistance pressure".into(),
            );
        }
    }
    (true, "L0 ok".into())
}

// ── L1 ──────────────────────────────────────────────────────────────────────

pub fn evaluate_l1(decision: &Decision, patient: &Patient, context: &Context) -> (bool, String) {
    let allergies: Vec<String> = patient.allergies.iter().map(|a| a.to_lowercase()).collect();
    if decision.action_type == "treatment" {
        let drug = decision.payload_str("drug").to_lowercase();
        for allergy in &allergies {
            if (allergy.contains("penicillin") || allergy.contains("пеницил"))
                && ["amoxi", "ampi", "penici", "пеницил"]
                    .iter()
                    .any(|k| drug.contains(k))
            {
                return (
                    false,
                    format!("L1 block: {} в семействе аллергии '{}'", drug, allergy),
                );
            }
            let first_word = allergy.split_whitespace().next().unwrap_or("");
            if !first_word.is_empty() && drug.contains(first_word) {
                return (
                    false,
                    format!("L1 block: {} совпадает с allergy '{}'", drug, allergy),
                );
            }
        }
        for intx in decision.payload_array("interactions") {
            let sev = intx.get("severity").and_then(|v| v.as_str()).unwrap_or("");
            if sev == "major" || sev == "contraindicated" {
                let summary = intx.get("summary").and_then(|v| v.as_str()).unwrap_or("");
                return (false, format!("L1 block: interaction '{}'", summary));
            }
        }
    }
    if decision.action_type == "wait" {
        let impedance = context.impedance_before.unwrap_or(0.5);
        if impedance > 0.85 || !patient.red_flags.is_empty() {
            return (
                false,
                format!(
                    "L1 inaction harm: impedance={:.2}, red_flags={:?}",
                    impedance, patient.red_flags
                ),
            );
        }
    }
    (true, "L1 ok".into())
}

// ── L2 ──────────────────────────────────────────────────────────────────────

pub fn evaluate_l2(decision: &Decision, context: &Context) -> (bool, String) {
    if let Some(commanded) = &context.commanded_action_type {
        if decision.action_type != *commanded {
            return (
                false,
                format!(
                    "L2: врач указал action_type='{}', decision='{}'",
                    commanded, decision.action_type
                ),
            );
        }
    }
    (true, "L2 ok".into())
}

// ── L3 ──────────────────────────────────────────────────────────────────────

pub fn evaluate_l3(decision: &Decision) -> (bool, String) {
    if decision.action_type == "system_modification" && decision.payload_bool("destructive") {
        return (false, "L3: destructive system-modification without explicit override".into());
    }
    (true, "L3 ok".into())
}

pub fn evaluate_laws(decision: &Decision, patient: &Patient, context: &Context) -> LawsResult {
    let (ok0, r0) = evaluate_l0(decision);
    let (ok1, r1) = evaluate_l1(decision, patient, context);
    let (ok2, r2) = evaluate_l2(decision, context);
    let (ok3, r3) = evaluate_l3(decision);
    LawsResult {
        l0: ok0,
        l1: ok1,
        l2: ok2,
        l3: ok3,
        reasons: vec![r0, r1, r2, r3],
    }
}

// ── extended laws ───────────────────────────────────────────────────────────

const PRIVACY_ACTIONS: &[&str] = &[
    "email_send",
    "web_post",
    "git_push_public",
    "upload_external",
    "telegram_broadcast",
    "external_api_call_with_data",
];

const CONSENT_ACTIONS: &[&str] = &[
    "email_send",
    "git_push_public",
    "telegram_broadcast",
    "slack_post",
    "web_publish",
    "submit_form",
    "delete_persistent",
    "irreversible_external",
];

const VERIFIABILITY_ACTIONS: &[&str] = &[
    "emit_text",
    "write_manuscript",
    "send_letter",
    "generate_citations",
    "peer_review_emit",
    "grant_letter",
];

static PHONE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\+?\d[\d\s().\-]{8,}\d").expect("phone regex"));
static BIRTHDATE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b(19|20)\d{2}[-_/](0?[1-9]|1[0-2])[-_/](0?[1-9]|[12]\d|3[01])\b").expect("dob regex"));
static MRN_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\b(?:passport|mrn|медкарт)[:#\s]+\S+").expect("mrn regex"));

pub fn evaluate_l_privacy(decision: &Decision, context: &Context) -> (bool, String) {
    if !PRIVACY_ACTIONS.contains(&decision.action_type.as_str()) {
        return (true, "L_PRIVACY n/a".into());
    }
    let blob = decision.payload_blob_lower();
    let mut flags: Vec<&str> = Vec::new();
    if blob.contains("patients/") || blob.contains("/patients/") {
        flags.push("Patients/ path in payload");
    }
    if PHONE_RE.is_match(&blob) {
        flags.push("phone-like number in payload");
    }
    if BIRTHDATE_RE.is_match(&blob) {
        flags.push("birthdate-like pattern in payload");
    }
    if MRN_RE.is_match(&blob) {
        flags.push("medical record / passport identifier");
    }
    if !flags.is_empty() && !context.privacy_consent {
        return (
            false,
            format!(
                "L_PRIVACY: {} (require privacy_consent=True)",
                flags.join("; ")
            ),
        );
    }
    (true, "L_PRIVACY ok".into())
}

pub fn evaluate_l_consent(decision: &Decision, context: &Context) -> (bool, String) {
    if !CONSENT_ACTIONS.contains(&decision.action_type.as_str()) {
        return (true, "L_CONSENT n/a".into());
    }
    if context.user_confirmed == Some(true) {
        return (true, "L_CONSENT confirmed by user".into());
    }
    (
        false,
        format!(
            "L_CONSENT: action='{}' has external blast radius and requires explicit user confirmation",
            decision.action_type
        ),
    )
}

/// L_VERIFIABILITY assumes the actual citation check is delegated to the
/// caller's `CitationChecker` (so this crate stays free of a literature
/// dependency). The function returns (false, ...) if `checker` reports any
/// rejected citation; (true, "n/a") if the action isn't a citation action.
pub trait CitationChecker: Send + Sync {
    fn check(&self, text: &str) -> CitationCheckResult;
}

#[derive(Clone, Debug, Default)]
pub struct CitationCheckResult {
    pub rejected: Vec<String>,
}

pub fn evaluate_l_verifiability(
    decision: &Decision,
    checker: Option<&dyn CitationChecker>,
) -> (bool, String) {
    if !VERIFIABILITY_ACTIONS.contains(&decision.action_type.as_str()) {
        return (true, "L_VERIFIABILITY n/a".into());
    }
    let text = match decision
        .payload
        .get("text")
        .or_else(|| decision.payload.get("body"))
        .and_then(|v| v.as_str())
    {
        Some(s) if !s.is_empty() => s,
        _ => return (true, "L_VERIFIABILITY: no text to verify".into()),
    };
    let Some(c) = checker else {
        // No checker wired up — fail closed (matches Python "failing closed").
        return (
            false,
            "L_VERIFIABILITY: citation checker unavailable; failing closed".into(),
        );
    };
    let res = c.check(text);
    if !res.rejected.is_empty() {
        return (
            false,
            format!(
                "L_VERIFIABILITY: {} unverified citation(s) — {}",
                res.rejected.len(),
                res.rejected.join(", ")
            ),
        );
    }
    (true, "L_VERIFIABILITY ok".into())
}

/// Action types that require co-design with the patient when their PAM-13
/// activation level ≥ 2 (per "Patient as a Project" cornerstone).
const AGENCY_ACTIONS: &[&str] = &[
    "treatment",
    "lifestyle_directive",
    "behavior_change",
    "regimen_change",
    "auto_action",
];

/// L_AGENCY (developmental agency).
///
/// Implements the 4th extended law from the "Patient as a Project" framework
/// (Tkemaladze 2026, *Longevity Horizon*,
/// longevity.ge/longhoriz/article/view/177). Codifies that an AI must not bypass
/// patient agency on actions where the patient is the legitimate
/// co-decider. The rule:
///
/// 1. If `action_type` is not in `AGENCY_ACTIONS` → n/a, pass.
/// 2. If `context.patient_codesigned == Some(true)` → pass.
/// 3. If `patient.activation_level <= 1` (disengaged or unknown):
///    pass, but emit a "needs capacity-building" reason so the orchestrator
///    pairs the action with coaching. Forcing a level-1 patient to co-design
///    is itself paternalistic.
/// 4. Otherwise (activation ≥ 2 + not co-designed) → fail.
pub fn evaluate_l_agency(decision: &Decision, patient: &Patient, context: &Context) -> (bool, String) {
    if !AGENCY_ACTIONS.contains(&decision.action_type.as_str()) {
        return (true, "L_AGENCY n/a".into());
    }
    if context.patient_codesigned == Some(true) {
        return (true, "L_AGENCY co-designed".into());
    }
    if patient.activation_level <= 1 {
        return (
            true,
            format!(
                "L_AGENCY pass with flag: patient activation level={} → pair action with capacity-building",
                patient.activation_level
            ),
        );
    }
    (
        false,
        format!(
            "L_AGENCY: action='{}' on activated patient (level {}) requires co-design (set context.patient_codesigned=True)",
            decision.action_type, patient.activation_level
        ),
    )
}

pub fn evaluate_extended(
    decision: &Decision,
    context: &Context,
    checker: Option<&dyn CitationChecker>,
) -> ExtendedLawsResult {
    let (p_ok, p_r) = evaluate_l_privacy(decision, context);
    let (c_ok, c_r) = evaluate_l_consent(decision, context);
    let (v_ok, v_r) = evaluate_l_verifiability(decision, checker);
    // L_AGENCY needs the patient too — without one, treat as unknown patient
    // (activation_level=0), which falls through the level-1 branch.
    let default_patient = Patient::default();
    let (a_ok, a_r) = evaluate_l_agency(decision, &default_patient, context);
    ExtendedLawsResult {
        privacy: p_ok,
        consent: c_ok,
        verifiability: v_ok,
        agency: a_ok,
        reasons: vec![p_r, c_r, v_r, a_r],
    }
}

/// Evaluate all extended laws including L_AGENCY with explicit patient.
/// Prefer this over `evaluate_extended` when a patient is in scope.
pub fn evaluate_extended_with_patient(
    decision: &Decision,
    patient: &Patient,
    context: &Context,
    checker: Option<&dyn CitationChecker>,
) -> ExtendedLawsResult {
    let (p_ok, p_r) = evaluate_l_privacy(decision, context);
    let (c_ok, c_r) = evaluate_l_consent(decision, context);
    let (v_ok, v_r) = evaluate_l_verifiability(decision, checker);
    let (a_ok, a_r) = evaluate_l_agency(decision, patient, context);
    ExtendedLawsResult {
        privacy: p_ok,
        consent: c_ok,
        verifiability: v_ok,
        agency: a_ok,
        reasons: vec![p_r, c_r, v_r, a_r],
    }
}

// ── impedance ───────────────────────────────────────────────────────────────

pub fn impedance_checklist(patient: &Patient) -> f64 {
    let mut i = 0.0_f64;
    i += (patient.missing_labs_count as f64 * 0.04).min(0.20);
    i += (patient.history_contradictions as f64 * 0.10).min(0.30);
    i += (patient.unexplained_symptoms_count as f64 * 0.04).min(0.20);
    if patient.last_visit_years_ago > 2 {
        i += 0.05;
    }
    if patient.dx_without_evidence {
        i += 0.10;
    }
    if patient.primary_complaint_undiagnosed {
        i += 0.10;
    }
    i.min(0.8)
}

/// Without an LLM-delta, total impedance == checklist (mirrors the Python
/// path where `AIM_KERNEL_LLM_DELTA=0`).
pub fn impedance(patient: &Patient) -> f64 {
    impedance_checklist(patient)
}

// ── scoring ─────────────────────────────────────────────────────────────────

fn duration_days(action_type: &str) -> f64 {
    match action_type {
        "wait" => 7.0,
        "test" => 1.0,
        "imaging" => 3.0,
        "treatment" => 7.0,
        "dx" => 0.5,
        "referral" => 14.0,
        "clarify" => 0.1,
        _ => 1.0,
    }
}

pub fn expected_impedance_after(decision: &Decision, patient: &Patient) -> f64 {
    let i_before = impedance(patient);
    let reduction = match decision.action_type.as_str() {
        "test" => 0.4,
        "imaging" => 0.5,
        "referral" => 0.3,
        "dx" => 0.2,
        "treatment" => 0.15,
        "clarify" => 0.25,
        "wait" => 0.05,
        _ => 0.1,
    };
    let mut i_after = (i_before * (1.0 - reduction)).max(0.0);
    if decision.action_type == "treatment" && !patient.has_confirmed_dx {
        // cheating penalty: treatment without dx → barely reduces real I
        i_after = i_before * 0.9;
    }
    i_after
}

pub fn instant_c(decision: &Decision, patient: &Patient) -> f64 {
    let i_before = impedance(patient);
    let i_after = expected_impedance_after(decision, patient);
    let dur = duration_days(&decision.action_type).max(0.1);
    ((i_before - i_after) / dur).clamp(0.0, 1.0)
}

pub fn phi_ze_path_integral(decision: &Decision, patient: &Patient) -> f64 {
    let i_before = impedance(patient);
    let i_after = expected_impedance_after(decision, patient);
    let dur = duration_days(&decision.action_type);
    let avg = (i_before + i_after) / 2.0;
    let phi_raw = avg * dur;
    let phi_norm = (phi_raw / 30.0).min(1.0);
    1.0 - phi_norm
}

// ── ethics ──────────────────────────────────────────────────────────────────

pub fn ethics_ze_score(decision: &Decision, patient: &Patient) -> f64 {
    let x = match decision.action_type.as_str() {
        "test" | "imaging" => 0.9,
        "referral" => 0.8,
        "clarify" => 0.85,
        "dx" => 0.5,
        "treatment" => 0.3,
        "wait" => 0.2,
        _ => 0.5,
    };
    let y = match decision.action_type.as_str() {
        "test" | "imaging" | "referral" | "clarify" => 0.0,
        "dx" => 0.1,
        "treatment" => {
            if patient.has_confirmed_dx {
                0.1
            } else {
                0.5
            }
        }
        "wait" => {
            if patient.primary_complaint_undiagnosed {
                0.3
            } else {
                0.1
            }
        }
        _ => 0.1,
    };
    let raw = (x - y) / (x + y + EPS);
    (raw + 1.0) / 2.0
}

pub fn ethics_autonomy(decision: &Decision, patient: &Patient) -> f64 {
    let mut score = 0.7_f64;
    if decision.payload_bool("informed_consent_noted") {
        score += 0.15;
    }
    let pref_respected = decision
        .payload
        .get("patient_preference_respected")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    if pref_respected {
        score += 0.10;
    }
    if patient.refusal_noted && decision.action_type != "clarify" {
        score -= 0.30;
    }
    score.clamp(0.0, 1.0)
}

pub fn ethics_beneficence(decision: &Decision, patient: &Patient) -> f64 {
    let mut base: f64 = match decision.action_type.as_str() {
        "test" => 0.75,
        "imaging" => 0.80,
        "referral" => 0.75,
        "clarify" => 0.60,
        "dx" => 0.70,
        "treatment" => {
            if patient.has_confirmed_dx {
                0.85
            } else {
                0.40
            }
        }
        "wait" => 0.40,
        _ => 0.5,
    };
    if !patient.red_flags.is_empty()
        && matches!(decision.action_type.as_str(), "test" | "imaging" | "referral")
    {
        base = (base + 0.15).min(1.0);
    }
    base
}

pub fn ethics_nonmaleficence(decision: &Decision) -> f64 {
    let mut base = 0.9_f64;
    if decision.action_type == "treatment" {
        let drug = decision.payload_str("drug").to_lowercase();
        let risky = ["warfarin", "digoxin", "lithium", "amiodarone", "methotrexate"];
        if risky.iter().any(|r| drug.contains(r)) {
            base = 0.6;
        }
        let controlled = ["opioid", "morphine", "fentanyl", "oxycodone"];
        if controlled.iter().any(|c| drug.contains(c)) {
            base = 0.5;
        }
    }
    if decision.action_type == "imaging" {
        let modality = decision.payload_str("modality").to_lowercase();
        if modality.contains("ct") || modality.contains("x-ray") {
            base -= 0.05;
        }
    }
    base.clamp(0.0, 1.0)
}

pub fn ethics_justice(decision: &Decision) -> f64 {
    let mut score = 0.85_f64;
    if decision.payload_bool("demographic_gated") {
        score -= 0.40;
    }
    if decision.payload_bool("guideline_based") {
        score += 0.10;
    }
    score.clamp(0.0, 1.0)
}

#[derive(Clone, Debug)]
pub struct EthicsParts {
    pub ze_learn_cheat: f64,
    pub autonomy: f64,
    pub beneficence: f64,
    pub nonmaleficence: f64,
    pub justice: f64,
}

pub fn ethics_composite(
    decision: &Decision,
    patient: &Patient,
    weights: &KernelWeights,
) -> (f64, EthicsParts) {
    let ze = ethics_ze_score(decision, patient);
    let auto = ethics_autonomy(decision, patient);
    let benef = ethics_beneficence(decision, patient);
    let nonmal = ethics_nonmaleficence(decision);
    let justice = ethics_justice(decision);
    let composite = weights.ethics_ze * ze
        + weights.ethics_auto * auto
        + weights.ethics_benef * benef
        + weights.ethics_nonmal * nonmal
        + weights.ethics_justice * justice;
    (
        composite,
        EthicsParts {
            ze_learn_cheat: ze,
            autonomy: auto,
            beneficence: benef,
            nonmaleficence: nonmal,
            justice,
        },
    )
}

pub fn score_decision(
    decision: &Decision,
    patient: &Patient,
    weights: &KernelWeights,
) -> ScoringResult {
    let i_before = impedance(patient);
    let i_after = expected_impedance_after(decision, patient);
    let c = instant_c(decision, patient);
    let phi = phi_ze_path_integral(decision, patient);
    let (ethics, parts) = ethics_composite(decision, patient, weights);
    let utility = weights.alpha * c + weights.beta * phi + weights.gamma * ethics;
    ScoringResult {
        impedance_before: i_before,
        impedance_after: i_after,
        instant_c: c,
        phi_ze: phi,
        ethics_ze_learn_cheat: parts.ze_learn_cheat,
        ethics_autonomy: parts.autonomy,
        ethics_beneficence: parts.beneficence,
        ethics_nonmaleficence: parts.nonmaleficence,
        ethics_justice: parts.justice,
        ethics_composite: ethics,
        utility,
    }
}

// ── Override + Scored + decide ─────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OverrideKind {
    #[default]
    None,
    /// Bias preference toward `forced_decision_id` if it passes laws,
    /// otherwise normal utility argmax.
    Soft,
    /// Force `forced_decision_id` even if it loses on utility, BUT L0+L1
    /// are still enforced. Hard override never bypasses safety filters.
    Hard,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct OverrideContext {
    pub kind: OverrideKind,
    pub forced_decision_id: Option<String>,
    pub reason: Option<String>,
}

impl OverrideContext {
    pub fn none() -> Self {
        Self::default()
    }
    pub fn soft(forced_id: impl Into<String>, reason: impl Into<String>) -> Self {
        Self {
            kind: OverrideKind::Soft,
            forced_decision_id: Some(forced_id.into()),
            reason: Some(reason.into()),
        }
    }
    pub fn hard(forced_id: impl Into<String>, reason: impl Into<String>) -> Self {
        Self {
            kind: OverrideKind::Hard,
            forced_decision_id: Some(forced_id.into()),
            reason: Some(reason.into()),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Scored {
    pub decision: Decision,
    pub laws: LawsResult,
    /// `None` when `laws.passed()` is false — no scoring computed for
    /// alternatives that were filtered out.
    pub scoring: Option<ScoringResult>,
    /// Extended laws (L_PRIVACY/CONSENT/VERIFIABILITY/L_AGENCY). Populated
    /// by `decide()` for every alternative starting Fix #1 (2026-05-07);
    /// `None` only on legacy code paths that bypass `decide()`.
    #[serde(default)]
    pub extended: Option<ExtendedLawsResult>,
}

impl Scored {
    pub fn passed(&self) -> bool {
        self.laws.passed()
            && self.scoring.is_some()
            && self.extended.as_ref().map(|e| e.passed()).unwrap_or(true)
    }
}

/// Main decision entry — port of `agents/kernel.py:decide`.
///
/// Pipeline:
///   1. If `override.kind == Hard`: force `forced_decision_id`, but
///      L0+L1 still enforced → KernelError if violated.
///   2. Otherwise: filter all `alternatives` through laws; score the
///      passers; argmax(utility). Soft override biases toward
///      `forced_decision_id` if it passes.
///   3. If zero alternatives pass laws → KernelError.
///   4. Audit logging is the caller's responsibility (call
///      `log_decision()` separately) — this keeps `decide()` pure
///      so Phase 3a shadow validator can call it without side
///      effects.
pub fn decide(
    alternatives: &[Decision],
    patient: &Patient,
    context: &Context,
    overrides: &OverrideContext,
    weights: &KernelWeights,
) -> Result<DecideResult> {
    if overrides.kind == OverrideKind::Hard {
        let forced_id = overrides
            .forced_decision_id
            .as_deref()
            .ok_or_else(|| KernelError::Violation("hard override requires forced_decision_id".into()))?;
        let forced = alternatives
            .iter()
            .find(|d| d.id == forced_id)
            .ok_or_else(|| {
                KernelError::Violation(format!(
                    "hard override: forced id {forced_id:?} not in alternatives"
                ))
            })?;
        let laws = evaluate_laws(forced, patient, context);
        if !(laws.l0 && laws.l1) {
            return Err(KernelError::Violation(format!(
                "hard override refused: L0/L1 violated ({})",
                laws.reasons.join("; ")
            )));
        }
        // Extended laws — even hard override does not bypass these.
        // L_AGENCY in particular protects the patient from a clinician
        // forcing a treatment without co-design. (Fix #1, 2026-05-07.)
        let ext = evaluate_extended_with_patient(forced, patient, context, None);
        if !ext.passed() {
            return Err(KernelError::Violation(format!(
                "hard override refused: extended laws violated ({})",
                ext.reasons.join("; ")
            )));
        }
        let scoring = ScoringResult {
            impedance_before: impedance(patient),
            impedance_after: expected_impedance_after(forced, patient),
            instant_c: 0.0,
            phi_ze: 0.0,
            ethics_ze_learn_cheat: 0.0,
            ethics_autonomy: 0.0,
            ethics_beneficence: 0.0,
            ethics_nonmaleficence: 0.0,
            ethics_justice: 0.0,
            ethics_composite: 0.0,
            utility: f64::INFINITY,
        };
        let chosen = Scored {
            decision: forced.clone(),
            laws,
            scoring: Some(scoring),
            extended: Some(ext),
        };
        return Ok(DecideResult {
            chosen: chosen.clone(),
            alternatives: vec![chosen],
        });
    }

    // Normal flow
    let mut scored_list: Vec<Scored> = Vec::with_capacity(alternatives.len());
    for d in alternatives {
        let laws = evaluate_laws(d, patient, context);
        // Extended laws fire for every alternative — including those that
        // already failed L0-L3 — so the audit trail captures full reasoning.
        let ext = evaluate_extended_with_patient(d, patient, context, None);
        if !(laws.passed() && ext.passed()) {
            scored_list.push(Scored {
                decision: d.clone(),
                laws,
                scoring: None,
                extended: Some(ext),
            });
            continue;
        }
        let scoring = score_decision(d, patient, weights);
        scored_list.push(Scored {
            decision: d.clone(),
            laws,
            scoring: Some(scoring),
            extended: Some(ext),
        });
    }

    let passed: Vec<&Scored> = scored_list.iter().filter(|s| s.passed()).collect();
    if passed.is_empty() {
        let reasons: Vec<String> = scored_list
            .iter()
            .map(|s| {
                let mut combined = s.laws.reasons.join(", ");
                if let Some(ext) = &s.extended {
                    if !combined.is_empty() {
                        combined.push_str(" | ");
                    }
                    combined.push_str(&ext.reasons.join(", "));
                }
                combined
            })
            .collect();
        return Err(KernelError::Violation(format!(
            "all {} alternatives violate laws: [{}]",
            scored_list.len(),
            reasons.join(" | ")
        )));
    }

    let chosen: Scored = if overrides.kind == OverrideKind::Soft {
        if let Some(forced_id) = overrides.forced_decision_id.as_deref() {
            if let Some(matched) = passed.iter().find(|s| s.decision.id == forced_id) {
                (*matched).clone()
            } else {
                argmax_utility(&passed)
            }
        } else {
            argmax_utility(&passed)
        }
    } else {
        argmax_utility(&passed)
    };

    Ok(DecideResult {
        chosen,
        alternatives: scored_list,
    })
}

fn argmax_utility(scored: &[&Scored]) -> Scored {
    scored
        .iter()
        .max_by(|a, b| {
            let ua = a.scoring.as_ref().map(|s| s.utility).unwrap_or(f64::NEG_INFINITY);
            let ub = b.scoring.as_ref().map(|s| s.utility).unwrap_or(f64::NEG_INFINITY);
            ua.partial_cmp(&ub).unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|&s| s.clone())
        .expect("argmax called with empty slice")
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DecideResult {
    pub chosen: Scored,
    /// Full list of all candidates with their laws + scoring (or None
    /// if filtered). Order preserved from input `alternatives`.
    pub alternatives: Vec<Scored>,
}

// ── format_compact / format_verbose / needs_clarification ─────────────────

pub fn format_compact(scored: &Scored, lang: &str) -> String {
    let d = &scored.decision;
    let u = scored.scoring.as_ref().map(|s| s.utility).unwrap_or(0.0);
    if lang == "ru" {
        format!(
            "**Рекомендация:** {}\n_(U={:.2}; для деталей — `!explain`)_",
            d.description, u
        )
    } else {
        format!(
            "**Recommendation:** {}\n_(U={:.2}; `!explain` for details)_",
            d.description, u
        )
    }
}

pub fn format_verbose(scored: &Scored, lang: &str) -> String {
    let d = &scored.decision;
    let s = match &scored.scoring {
        Some(s) => s,
        None => {
            return if lang == "ru" {
                format!("**Решение:** {} — не прошло Laws gate", d.description)
            } else {
                format!("**Decision:** {} — failed Laws gate", d.description)
            };
        }
    };
    if lang == "ru" {
        format!(
            "**Рекомендация:** {desc}\n\n\
📊 **Scoring:**\n\
- 𝓘 (импеданс): {ib:.2} → {ia:.2}\n\
- 𝒞 (мгновенное сознание): {c:.3}\n\
- Φ_Ze (интегральное): {phi:.3}\n\
- **Utility U: {u:.3}**\n\n\
⚖️ **Ethics breakdown:**\n\
- Ze learn/cheat: {ze:.2}\n\
- Autonomy: {auto:.2}\n\
- Beneficence: {ben:.2}\n\
- Non-maleficence: {nm:.2}\n\
- Justice: {just:.2}\n\
- **Composite: {ec:.2}**\n\n\
✅ **Laws:** L0={l0} L1={l1} L2={l2} L3={l3}",
            desc = d.description,
            ib = s.impedance_before,
            ia = s.impedance_after,
            c = s.instant_c,
            phi = s.phi_ze,
            u = s.utility,
            ze = s.ethics_ze_learn_cheat,
            auto = s.ethics_autonomy,
            ben = s.ethics_beneficence,
            nm = s.ethics_nonmaleficence,
            just = s.ethics_justice,
            ec = s.ethics_composite,
            l0 = scored.laws.l0,
            l1 = scored.laws.l1,
            l2 = scored.laws.l2,
            l3 = scored.laws.l3,
        )
    } else {
        format!(
            "**Recommendation:** {desc}\n\n\
📊 **Scoring:** I: {ib:.2}→{ia:.2}, C={c:.3}, Phi_Ze={phi:.3}, **U={u:.3}**\n\n\
⚖️ **Ethics:** Ze={ze:.2}, Auto={auto:.2}, Ben={ben:.2}, NonMal={nm:.2}, \
Just={just:.2}, **Composite={ec:.2}**\n\n\
✅ Laws: L0={l0} L1={l1} L2={l2} L3={l3}",
            desc = d.description,
            ib = s.impedance_before,
            ia = s.impedance_after,
            c = s.instant_c,
            phi = s.phi_ze,
            u = s.utility,
            ze = s.ethics_ze_learn_cheat,
            auto = s.ethics_autonomy,
            ben = s.ethics_beneficence,
            nm = s.ethics_nonmaleficence,
            just = s.ethics_justice,
            ec = s.ethics_composite,
            l0 = scored.laws.l0,
            l1 = scored.laws.l1,
            l2 = scored.laws.l2,
            l3 = scored.laws.l3,
        )
    }
}

pub fn needs_clarification(patient: &Patient, weights: &KernelWeights) -> bool {
    impedance(patient) > weights.clarify_impedance_threshold
}

// ── LlmCaller trait + impedance_with_llm ──────────────────────────────────

/// Pluggable LLM caller for `impedance_llm_delta`. Phase 2 PyO3 binding
/// will provide a Python-backed impl that calls `llm.ask_fast`. For
/// pure-Rust callers, leave `None` to skip LLM-judge and use checklist
/// only — that's what Python `impedance_llm_delta` does on `llm_caller=None`.
pub trait LlmCaller: Send + Sync {
    fn ask(&self, prompt: &str) -> std::result::Result<String, String>;
}

/// Delta from LLM judge, normalised to [0, 0.4]. Returns 0.0 when
/// `caller` is None or call fails — matches Python `impedance_llm_delta`
/// fallback behaviour.
pub fn impedance_llm_delta(
    patient: &Patient,
    caller: Option<&dyn LlmCaller>,
) -> f64 {
    let Some(caller) = caller else {
        return 0.0;
    };
    let prompt = format!(
        "Patient summary: red_flags={:?}, history_contradictions={}, \
unexplained_symptoms={}, dx_without_evidence={}. \
Reply with a single float 0.0-0.4 indicating residual diagnostic uncertainty.",
        patient.red_flags,
        patient.history_contradictions,
        patient.unexplained_symptoms_count,
        patient.dx_without_evidence
    );
    match caller.ask(&prompt) {
        Ok(raw) => raw
            .trim()
            .parse::<f64>()
            .ok()
            .map(|x| x.clamp(0.0, 0.4))
            .unwrap_or(0.0),
        Err(_) => 0.0,
    }
}

/// Combined impedance: deterministic checklist + optional LLM delta.
/// Capped at 1.0. Mirrors Python `impedance(patient, context, llm_caller)`.
pub fn impedance_with_llm(patient: &Patient, caller: Option<&dyn LlmCaller>) -> f64 {
    let base = impedance_checklist(patient);
    let delta = impedance_llm_delta(patient, caller);
    (base + delta).min(1.0)
}

// ── log_decision ─────────────────────────────────────────────────────────

/// Audit sink — SQLite ai_events table + per-patient AI_LOG.md append.
/// Mirrors Python `log_decision`. `db_path` and `patients_dir` come
/// from caller (no global config in Rust core — let the binary or
/// PyO3 binding decide).
pub fn log_decision(
    db_path: &std::path::Path,
    patients_dir: &std::path::Path,
    patient_id: &str,
    agent: &str,
    decision_type: &str,
    result: &DecideResult,
    overrides: &OverrideContext,
    session_id: Option<&str>,
) -> Result<()> {
    use rusqlite::params;

    if let Some(parent) = db_path.parent() {
        if !parent.as_os_str().is_empty() {
            let _ = std::fs::create_dir_all(parent);
        }
    }
    let conn = rusqlite::Connection::open(db_path)
        .map_err(|e| KernelError::Violation(format!("sqlite open: {e}")))?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_events (\
            id INTEGER PRIMARY KEY AUTOINCREMENT, \
            ts TEXT DEFAULT CURRENT_TIMESTAMP, \
            patient_id TEXT, session_id TEXT, agent TEXT, \
            decision_type TEXT, alternatives_json TEXT, chosen_id TEXT, \
            laws_json TEXT, scoring_json TEXT, \
            override_type TEXT, override_reason TEXT)",
        [],
    )
    .map_err(|e| KernelError::Violation(format!("ai_events schema: {e}")))?;
    // Additive: extended_json column added 2026-05-07 for L_AGENCY/CONSENT/
    // PRIVACY/VERIFIABILITY audit trail. SQLite's ALTER TABLE doesn't have
    // IF NOT EXISTS, so probe the schema first.
    let mut has_extended = false;
    {
        let mut stmt = conn
            .prepare("PRAGMA table_info(ai_events)")
            .map_err(|e| KernelError::Violation(format!("pragma: {e}")))?;
        let rows = stmt
            .query_map([], |r| r.get::<_, String>(1))
            .map_err(|e| KernelError::Violation(format!("pragma rows: {e}")))?;
        for name in rows.flatten() {
            if name == "extended_json" {
                has_extended = true;
                break;
            }
        }
    }
    if !has_extended {
        conn.execute("ALTER TABLE ai_events ADD COLUMN extended_json TEXT", [])
            .map_err(|e| KernelError::Violation(format!("ai_events alter: {e}")))?;
    }

    let alts_json = serde_json::to_string(&result.alternatives).unwrap_or_default();
    let chosen_id = &result.chosen.decision.id;
    let laws_json = serde_json::to_string(&result.chosen.laws).unwrap_or_default();
    let scoring_json = result
        .chosen
        .scoring
        .as_ref()
        .and_then(|s| serde_json::to_string(s).ok())
        .unwrap_or_default();
    let extended_json = result
        .chosen
        .extended
        .as_ref()
        .and_then(|e| serde_json::to_string(e).ok())
        .unwrap_or_default();
    let kind_str = match overrides.kind {
        OverrideKind::None => "none",
        OverrideKind::Soft => "soft",
        OverrideKind::Hard => "hard",
    };
    let reason = overrides.reason.as_deref().unwrap_or("");
    conn.execute(
        "INSERT INTO ai_events (patient_id, session_id, agent, decision_type, \
            alternatives_json, chosen_id, laws_json, scoring_json, \
            override_type, override_reason, extended_json) \
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        params![
            patient_id,
            session_id.unwrap_or(""),
            agent,
            decision_type,
            alts_json,
            chosen_id,
            laws_json,
            scoring_json,
            kind_str,
            reason,
            extended_json,
        ],
    )
    .map_err(|e| KernelError::Violation(format!("ai_events insert: {e}")))?;

    if !patient_id.is_empty() {
        write_ai_log_md(patients_dir, patient_id, agent, decision_type, result, overrides)?;
    }
    Ok(())
}

fn write_ai_log_md(
    patients_dir: &std::path::Path,
    patient_id: &str,
    agent: &str,
    decision_type: &str,
    result: &DecideResult,
    overrides: &OverrideContext,
) -> Result<()> {
    let dir = patients_dir.join(patient_id);
    std::fs::create_dir_all(&dir)
        .map_err(|e| KernelError::Violation(format!("mkdir patient: {e}")))?;
    let log = dir.join("AI_LOG.md");
    let ts = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
    let mut entry = String::new();
    use std::fmt::Write as _;
    let _ = writeln!(entry, "\n## {ts} — {decision_type} by {agent}\n");
    let _ = writeln!(
        entry,
        "**Alternatives considered:** {}",
        result.alternatives.len()
    );
    for s in &result.alternatives {
        let mark = if s.decision.id == result.chosen.decision.id {
            "⭐"
        } else {
            "  "
        };
        if let Some(sc) = &s.scoring {
            let _ = writeln!(
                entry,
                "- {mark} `{id}` ({at}): U={u:.3} (𝒞={c:.2}, Φ_Ze={phi:.2}, Ethics={e:.2}) — {desc}",
                id = s.decision.id,
                at = s.decision.action_type,
                u = sc.utility,
                c = sc.instant_c,
                phi = sc.phi_ze,
                e = sc.ethics_composite,
                desc = truncate(&s.decision.description, 80),
            );
        } else {
            let _ = writeln!(
                entry,
                "- ❌ `{id}` ({at}): Laws FAIL — {desc}",
                id = s.decision.id,
                at = s.decision.action_type,
                desc = truncate(&s.decision.description, 80),
            );
        }
    }
    if let Some(sc) = &result.chosen.scoring {
        let _ = writeln!(
            entry,
            "\n**Decision:** `{id}` — {desc}",
            id = result.chosen.decision.id,
            desc = result.chosen.decision.description
        );
        let _ = writeln!(
            entry,
            "- 𝓘: {ib:.2} → {ia:.2} (expected)",
            ib = sc.impedance_before,
            ia = sc.impedance_after
        );
    }
    if let Some(ext) = &result.chosen.extended {
        let tick = |b: bool| if b { "✅" } else { "❌" };
        let _ = writeln!(
            entry,
            "- Extended laws: privacy {} · consent {} · verifiability {} · agency {}",
            tick(ext.privacy),
            tick(ext.consent),
            tick(ext.verifiability),
            tick(ext.agency)
        );
        for r in &ext.reasons {
            let lower = r.to_lowercase();
            if !lower.contains(" ok") && !lower.contains("n/a") {
                let _ = writeln!(entry, "  - {r}");
            }
        }
    }
    if overrides.kind != OverrideKind::None {
        let kind = match overrides.kind {
            OverrideKind::Soft => "soft",
            OverrideKind::Hard => "hard",
            OverrideKind::None => unreachable!(),
        };
        let _ = writeln!(
            entry,
            "\n**Override:** type={kind}, reason={}",
            overrides.reason.as_deref().unwrap_or("n/a")
        );
    }
    entry.push_str("\n---\n");

    use std::io::Write;
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log)
        .map_err(|e| KernelError::Violation(format!("open AI_LOG.md: {e}")))?;
    f.write_all(entry.as_bytes())
        .map_err(|e| KernelError::Violation(format!("write AI_LOG.md: {e}")))?;
    Ok(())
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    s.chars().take(max).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dec(action: &str, payload: serde_json::Value) -> Decision {
        Decision {
            id: "d1".into(),
            description: String::new(),
            action_type: action.into(),
            payload,
            meta: serde_json::json!({}),
        }
    }

    // ── L0 ──────────────────────────────────────────────────────────────────

    #[test]
    fn l0_rejects_danger_signal_in_description() {
        let mut d = dec("dx", serde_json::json!({}));
        d.description = "weapon design plan".into();
        let (ok, _) = evaluate_l0(&d);
        assert!(!ok);
    }

    #[test]
    fn l0_rejects_broad_abx_for_viral() {
        let d = dec(
            "treatment",
            serde_json::json!({"drug": "vancomycin", "indication": "viral URI"}),
        );
        let (ok, r) = evaluate_l0(&d);
        assert!(!ok);
        assert!(r.contains("resistance"));
    }

    #[test]
    fn l0_accepts_clean_treatment() {
        let d = dec(
            "treatment",
            serde_json::json!({"drug": "amoxicillin", "indication": "strep throat"}),
        );
        let (ok, _) = evaluate_l0(&d);
        assert!(ok);
    }

    // ── L1 ──────────────────────────────────────────────────────────────────

    #[test]
    fn l1_blocks_drug_in_allergy_family() {
        let d = dec("treatment", serde_json::json!({"drug": "amoxicillin"}));
        let mut p = Patient::new();
        p.allergies.push("penicillin rash".into());
        let (ok, r) = evaluate_l1(&d, &p, &Context::default());
        assert!(!ok);
        assert!(r.contains("семействе"));
    }

    #[test]
    fn l1_blocks_major_interaction() {
        let d = dec(
            "treatment",
            serde_json::json!({
                "drug": "x",
                "interactions": [{"severity": "major", "summary": "x + y"}]
            }),
        );
        let p = Patient::new();
        let (ok, _) = evaluate_l1(&d, &p, &Context::default());
        assert!(!ok);
    }

    #[test]
    fn l1_blocks_wait_with_red_flags() {
        let d = dec("wait", serde_json::json!({}));
        let mut p = Patient::new();
        p.red_flags.push("chest pain".into());
        let (ok, r) = evaluate_l1(&d, &p, &Context::default());
        assert!(!ok);
        assert!(r.contains("inaction"));
    }

    #[test]
    fn l1_blocks_wait_with_high_impedance() {
        let d = dec("wait", serde_json::json!({}));
        let p = Patient::new();
        let mut ctx = Context::default();
        ctx.impedance_before = Some(0.95);
        let (ok, _) = evaluate_l1(&d, &p, &ctx);
        assert!(!ok);
    }

    #[test]
    fn l1_passes_clean_treatment() {
        let d = dec("treatment", serde_json::json!({"drug": "ibuprofen"}));
        let p = Patient::new();
        let (ok, _) = evaluate_l1(&d, &p, &Context::default());
        assert!(ok);
    }

    // ── L2 / L3 ─────────────────────────────────────────────────────────────

    #[test]
    fn l2_blocks_action_mismatch() {
        let d = dec("dx", serde_json::json!({}));
        let mut ctx = Context::default();
        ctx.commanded_action_type = Some("test".into());
        let (ok, _) = evaluate_l2(&d, &ctx);
        assert!(!ok);
    }

    #[test]
    fn l2_passes_when_no_command_or_match() {
        let d = dec("dx", serde_json::json!({}));
        let (ok, _) = evaluate_l2(&d, &Context::default());
        assert!(ok);
        let mut ctx = Context::default();
        ctx.commanded_action_type = Some("dx".into());
        let (ok2, _) = evaluate_l2(&d, &ctx);
        assert!(ok2);
    }

    #[test]
    fn l3_blocks_destructive_system_modification() {
        let d = dec(
            "system_modification",
            serde_json::json!({"destructive": true}),
        );
        let (ok, _) = evaluate_l3(&d);
        assert!(!ok);
    }

    #[test]
    fn evaluate_laws_combines_branches() {
        let d = dec("dx", serde_json::json!({}));
        let p = Patient::new();
        let r = evaluate_laws(&d, &p, &Context::default());
        assert!(r.passed());
        assert_eq!(r.reasons.len(), 4);
    }

    // ── L_PRIVACY ───────────────────────────────────────────────────────────

    #[test]
    fn privacy_na_for_non_egress_actions() {
        let d = dec("dx", serde_json::json!({"text": "Patients/X"}));
        let (ok, r) = evaluate_l_privacy(&d, &Context::default());
        assert!(ok);
        assert!(r.contains("n/a"));
    }

    #[test]
    fn privacy_blocks_patient_path_in_egress() {
        let d = dec(
            "email_send",
            serde_json::json!({"body": "see Patients/Smith_John"}),
        );
        let (ok, _) = evaluate_l_privacy(&d, &Context::default());
        assert!(!ok);
    }

    #[test]
    fn privacy_blocks_phone_pattern() {
        let d = dec(
            "email_send",
            serde_json::json!({"body": "call +995 555 1234567"}),
        );
        let (ok, _) = evaluate_l_privacy(&d, &Context::default());
        assert!(!ok);
    }

    #[test]
    fn privacy_passes_with_consent() {
        let d = dec(
            "email_send",
            serde_json::json!({"body": "see Patients/Smith_John"}),
        );
        let mut ctx = Context::default();
        ctx.privacy_consent = true;
        let (ok, _) = evaluate_l_privacy(&d, &ctx);
        assert!(ok);
    }

    // ── L_CONSENT ───────────────────────────────────────────────────────────

    #[test]
    fn consent_blocks_unconfirmed_email() {
        let d = dec("email_send", serde_json::json!({}));
        let (ok, _) = evaluate_l_consent(&d, &Context::default());
        assert!(!ok);
    }

    #[test]
    fn consent_passes_when_confirmed() {
        let d = dec("email_send", serde_json::json!({}));
        let mut ctx = Context::default();
        ctx.user_confirmed = Some(true);
        let (ok, _) = evaluate_l_consent(&d, &ctx);
        assert!(ok);
    }

    // ── L_VERIFIABILITY ─────────────────────────────────────────────────────

    struct AlwaysClean;
    impl CitationChecker for AlwaysClean {
        fn check(&self, _: &str) -> CitationCheckResult {
            CitationCheckResult::default()
        }
    }
    struct AlwaysReject;
    impl CitationChecker for AlwaysReject {
        fn check(&self, _: &str) -> CitationCheckResult {
            CitationCheckResult {
                rejected: vec!["PMID:99999".into()],
            }
        }
    }

    #[test]
    fn verif_na_for_non_emit_actions() {
        let d = dec("dx", serde_json::json!({"text": "x"}));
        let (ok, _) = evaluate_l_verifiability(&d, Some(&AlwaysReject));
        assert!(ok);
    }

    #[test]
    fn verif_passes_clean_text() {
        let d = dec("emit_text", serde_json::json!({"text": "claim"}));
        let (ok, _) = evaluate_l_verifiability(&d, Some(&AlwaysClean));
        assert!(ok);
    }

    #[test]
    fn verif_blocks_rejected_citation() {
        let d = dec("emit_text", serde_json::json!({"text": "see PMID 99999"}));
        let (ok, _) = evaluate_l_verifiability(&d, Some(&AlwaysReject));
        assert!(!ok);
    }

    #[test]
    fn verif_fails_closed_when_no_checker() {
        let d = dec("emit_text", serde_json::json!({"text": "x"}));
        let (ok, _) = evaluate_l_verifiability(&d, None);
        assert!(!ok);
    }

    #[test]
    fn verif_passes_when_no_text() {
        let d = dec("emit_text", serde_json::json!({}));
        let (ok, _) = evaluate_l_verifiability(&d, None);
        assert!(ok);
    }

    // ── L_AGENCY ────────────────────────────────────────────────────────────

    #[test]
    fn agency_na_for_non_agency_actions() {
        let d = dec("dx", serde_json::json!({}));
        let p = Patient { activation_level: 3, ..Patient::new() };
        let (ok, r) = evaluate_l_agency(&d, &p, &Context::default());
        assert!(ok);
        assert!(r.contains("n/a"));
    }

    #[test]
    fn agency_passes_when_codesigned() {
        let d = dec("treatment", serde_json::json!({"drug": "lisinopril"}));
        let p = Patient { activation_level: 3, ..Patient::new() };
        let mut ctx = Context::default();
        ctx.patient_codesigned = Some(true);
        let (ok, r) = evaluate_l_agency(&d, &p, &ctx);
        assert!(ok);
        assert!(r.contains("co-designed"));
    }

    #[test]
    fn agency_blocks_activated_patient_without_codesign() {
        let d = dec("lifestyle_directive", serde_json::json!({"text": "walk 30 min"}));
        let p = Patient { activation_level: 3, ..Patient::new() };
        let (ok, r) = evaluate_l_agency(&d, &p, &Context::default());
        assert!(!ok);
        assert!(r.contains("co-design"));
    }

    #[test]
    fn agency_passes_with_flag_for_disengaged_patient() {
        // level 1 — disengaged. Pass but flag for capacity-building.
        let d = dec("treatment", serde_json::json!({}));
        let p = Patient { activation_level: 1, ..Patient::new() };
        let (ok, r) = evaluate_l_agency(&d, &p, &Context::default());
        assert!(ok);
        assert!(r.contains("capacity-building"));
    }

    #[test]
    fn agency_passes_with_flag_for_unknown_activation() {
        // activation_level 0 = unknown → treat like level 1.
        let d = dec("regimen_change", serde_json::json!({}));
        let p = Patient::new(); // default activation_level = 0
        let (ok, r) = evaluate_l_agency(&d, &p, &Context::default());
        assert!(ok);
        assert!(r.contains("capacity-building"));
    }

    #[test]
    fn agency_blocks_at_level_2_threshold() {
        let d = dec("behavior_change", serde_json::json!({}));
        let p = Patient { activation_level: 2, ..Patient::new() };
        let (ok, _) = evaluate_l_agency(&d, &p, &Context::default());
        assert!(!ok);
    }

    #[test]
    fn evaluate_extended_with_patient_carries_agency() {
        let d = dec("treatment", serde_json::json!({}));
        let p = Patient { activation_level: 4, ..Patient::new() };
        // Not co-designed → agency should fail
        let res = evaluate_extended_with_patient(&d, &p, &Context::default(), None);
        assert!(!res.passed());
        assert!(!res.agency);
        assert_eq!(res.reasons.len(), 4);
    }

    #[test]
    fn evaluate_extended_with_patient_passes_when_codesigned() {
        let d = dec("treatment", serde_json::json!({}));
        let p = Patient { activation_level: 4, ..Patient::new() };
        let mut ctx = Context::default();
        ctx.patient_codesigned = Some(true);
        let res = evaluate_extended_with_patient(&d, &p, &ctx, None);
        assert!(res.agency);
    }

    // ── impedance ───────────────────────────────────────────────────────────

    #[test]
    fn impedance_baseline_undiagnosed_complaint() {
        let p = Patient::new(); // primary_complaint_undiagnosed = true
        // = 0 + 0 + 0 + 0 + 0 + 0.10 = 0.10
        assert!((impedance(&p) - 0.10).abs() < 1e-9);
    }

    #[test]
    fn impedance_caps_at_eight_tenths() {
        let p = Patient {
            missing_labs_count: 100,
            history_contradictions: 100,
            unexplained_symptoms_count: 100,
            last_visit_years_ago: 5,
            dx_without_evidence: true,
            primary_complaint_undiagnosed: true,
            ..Default::default()
        };
        assert!((impedance(&p) - 0.8).abs() < 1e-9);
    }

    // ── scoring ─────────────────────────────────────────────────────────────

    #[test]
    fn score_test_action_has_higher_utility_than_wait_for_red_flag() {
        let mut p = Patient::new();
        p.red_flags.push("chest pain".into());
        let test = dec("test", serde_json::json!({}));
        let wait = dec("wait", serde_json::json!({}));
        let w = KernelWeights::default();
        let s_test = score_decision(&test, &p, &w);
        let s_wait = score_decision(&wait, &p, &w);
        assert!(s_test.utility > s_wait.utility);
    }

    #[test]
    fn score_treatment_without_dx_has_low_ze() {
        let p = Patient::new();
        let d = dec("treatment", serde_json::json!({"drug": "ibuprofen"}));
        let s = score_decision(&d, &p, &KernelWeights::default());
        // x=0.3, y=0.5 → raw=-0.25 → 0.375
        assert!(s.ethics_ze_learn_cheat < 0.5);
    }

    #[test]
    fn score_treatment_with_dx_has_higher_beneficence() {
        let mut p = Patient::new();
        p.has_confirmed_dx = true;
        let d = dec("treatment", serde_json::json!({}));
        let s = score_decision(&d, &p, &KernelWeights::default());
        assert!(s.ethics_beneficence > 0.7);
    }

    #[test]
    fn ethics_nonmal_drops_for_risky_drug() {
        let d = dec("treatment", serde_json::json!({"drug": "warfarin"}));
        assert_eq!(ethics_nonmaleficence(&d), 0.6);
    }

    #[test]
    fn ethics_nonmal_drops_for_controlled_substance() {
        let d = dec("treatment", serde_json::json!({"drug": "morphine sulfate"}));
        assert_eq!(ethics_nonmaleficence(&d), 0.5);
    }

    #[test]
    fn ethics_justice_penalises_demographic_gating() {
        let d = dec("test", serde_json::json!({"demographic_gated": true}));
        let j = ethics_justice(&d);
        assert!(j < 0.5);
    }

    #[test]
    fn instant_c_positive_for_information_gathering() {
        let p = Patient::new();
        let d = dec("test", serde_json::json!({}));
        assert!(instant_c(&d, &p) > 0.0);
    }

    #[test]
    fn phi_ze_in_unit_interval() {
        let p = Patient::new();
        let d = dec("imaging", serde_json::json!({}));
        let phi = phi_ze_path_integral(&d, &p);
        assert!((0.0..=1.0).contains(&phi));
    }

    #[test]
    fn extended_evaluates_four_laws() {
        let d = dec("emit_text", serde_json::json!({"text": "x"}));
        let r = evaluate_extended(&d, &Context::default(), Some(&AlwaysClean));
        assert!(r.privacy);
        assert!(r.consent);
        assert!(r.verifiability);
        assert!(r.agency); // emit_text is not in AGENCY_ACTIONS → n/a → ok
        assert_eq!(r.reasons.len(), 4);
    }

    // ── Phase 1 (HW1, 2026-05-07): decide() + override + format + log ──────

    fn safe_dx(id: &str) -> Decision {
        let mut d = dec("dx", serde_json::json!({"text": "common cold"}));
        d.id = id.into();
        d.description = format!("dx alternative {id}");
        d
    }

    fn unsafe_treatment(id: &str, drug: &str) -> Decision {
        let mut d = dec("treatment", serde_json::json!({"drug": drug}));
        d.id = id.into();
        d.description = format!("treatment with {drug}");
        d
    }

    #[test]
    fn decide_picks_argmax_utility_when_no_override() {
        let alts = vec![safe_dx("a"), safe_dx("b"), safe_dx("c")];
        let p = Patient::new();
        let r = decide(&alts, &p, &Context::default(),
                       &OverrideContext::none(), &KernelWeights::default()).unwrap();
        assert!(["a", "b", "c"].contains(&r.chosen.decision.id.as_str()));
        assert_eq!(r.alternatives.len(), 3);
        assert!(r.alternatives.iter().all(|s| s.scoring.is_some()));
    }

    #[test]
    fn decide_returns_error_when_all_violate_laws() {
        let mut p = Patient::new();
        p.allergies.push("penicillin".into());
        let alts = vec![
            unsafe_treatment("a", "amoxicillin"),
            unsafe_treatment("b", "ampicillin"),
        ];
        let err = decide(&alts, &p, &Context::default(),
                          &OverrideContext::none(), &KernelWeights::default()).unwrap_err();
        assert!(matches!(err, KernelError::Violation(_)));
    }

    #[test]
    fn decide_soft_override_prefers_forced_id() {
        let alts = vec![safe_dx("a"), safe_dx("b"), safe_dx("c")];
        let p = Patient::new();
        let ov = OverrideContext::soft("b", "doctor preference");
        let r = decide(&alts, &p, &Context::default(), &ov, &KernelWeights::default()).unwrap();
        assert_eq!(r.chosen.decision.id, "b");
    }

    #[test]
    fn decide_soft_override_falls_back_when_forced_violates() {
        let mut p = Patient::new();
        p.allergies.push("penicillin".into());
        let alts = vec![
            safe_dx("safe1"),
            unsafe_treatment("forced_bad", "amoxicillin"),
            safe_dx("safe2"),
        ];
        let ov = OverrideContext::soft("forced_bad", "doctor pref");
        let r = decide(&alts, &p, &Context::default(), &ov, &KernelWeights::default()).unwrap();
        assert!(["safe1", "safe2"].contains(&r.chosen.decision.id.as_str()));
    }

    #[test]
    fn decide_hard_override_forces_id_if_l0_l1_pass() {
        let alts = vec![safe_dx("a"), safe_dx("b"), safe_dx("c")];
        let p = Patient::new();
        let ov = OverrideContext::hard("c", "physician override");
        let r = decide(&alts, &p, &Context::default(), &ov, &KernelWeights::default()).unwrap();
        assert_eq!(r.chosen.decision.id, "c");
        assert_eq!(r.chosen.scoring.as_ref().unwrap().utility, f64::INFINITY);
    }

    #[test]
    fn decide_hard_override_refused_when_l1_blocks() {
        let mut p = Patient::new();
        p.allergies.push("penicillin".into());
        let alts = vec![
            safe_dx("a"),
            unsafe_treatment("bad", "amoxicillin"),
        ];
        let ov = OverrideContext::hard("bad", "physician override");
        let err = decide(&alts, &p, &Context::default(), &ov, &KernelWeights::default()).unwrap_err();
        assert!(matches!(err, KernelError::Violation(_)));
    }

    #[test]
    fn decide_hard_override_missing_forced_id_errors() {
        let alts = vec![safe_dx("a")];
        let p = Patient::new();
        let mut ov = OverrideContext::hard("dummy", "x");
        ov.forced_decision_id = None;
        let err = decide(&alts, &p, &Context::default(), &ov, &KernelWeights::default()).unwrap_err();
        assert!(matches!(err, KernelError::Violation(_)));
    }

    #[test]
    fn decide_hard_override_unknown_id_errors() {
        let alts = vec![safe_dx("a")];
        let p = Patient::new();
        let ov = OverrideContext::hard("ghost", "x");
        let err = decide(&alts, &p, &Context::default(), &ov, &KernelWeights::default()).unwrap_err();
        assert!(matches!(err, KernelError::Violation(_)));
    }

    // ── format / clarification ─────────────────────────────────────────────

    #[test]
    fn format_compact_ru_includes_utility() {
        let alts = vec![safe_dx("a")];
        let r = decide(&alts, &Patient::new(), &Context::default(),
                       &OverrideContext::none(), &KernelWeights::default()).unwrap();
        let s = format_compact(&r.chosen, "ru");
        assert!(s.contains("Рекомендация"));
        assert!(s.contains("U="));
    }

    #[test]
    fn format_compact_en() {
        let alts = vec![safe_dx("a")];
        let r = decide(&alts, &Patient::new(), &Context::default(),
                       &OverrideContext::none(), &KernelWeights::default()).unwrap();
        let s = format_compact(&r.chosen, "en");
        assert!(s.contains("Recommendation"));
    }

    #[test]
    fn format_verbose_includes_breakdown() {
        let alts = vec![safe_dx("a")];
        let r = decide(&alts, &Patient::new(), &Context::default(),
                       &OverrideContext::none(), &KernelWeights::default()).unwrap();
        let s = format_verbose(&r.chosen, "ru");
        assert!(s.contains("Scoring"));
        assert!(s.contains("Ethics"));
        assert!(s.contains("Laws"));
    }

    #[test]
    fn needs_clarification_basic() {
        let p = Patient::new();
        let weights = KernelWeights::default();
        assert!(!needs_clarification(&p, &weights));
    }

    #[test]
    fn needs_clarification_high_impedance_patient() {
        let mut p = Patient::new();
        p.missing_labs_count = 5;
        p.history_contradictions = 3;
        p.unexplained_symptoms_count = 4;
        p.dx_without_evidence = true;
        let weights = KernelWeights::default();
        assert!(needs_clarification(&p, &weights));
    }

    // ── LlmCaller / impedance_with_llm ─────────────────────────────────────

    struct ConstantCaller(f64);
    impl LlmCaller for ConstantCaller {
        fn ask(&self, _: &str) -> std::result::Result<String, String> {
            Ok(self.0.to_string())
        }
    }
    struct FailingCaller;
    impl LlmCaller for FailingCaller {
        fn ask(&self, _: &str) -> std::result::Result<String, String> {
            Err("network".into())
        }
    }

    #[test]
    fn impedance_llm_delta_clamps_to_range() {
        let p = Patient::new();
        let high = ConstantCaller(0.95);
        assert_eq!(impedance_llm_delta(&p, Some(&high)), 0.4);
        let neg = ConstantCaller(-0.5);
        assert_eq!(impedance_llm_delta(&p, Some(&neg)), 0.0);
    }

    #[test]
    fn impedance_llm_delta_zero_on_none() {
        let p = Patient::new();
        assert_eq!(impedance_llm_delta(&p, None), 0.0);
    }

    #[test]
    fn impedance_llm_delta_zero_on_failure() {
        let p = Patient::new();
        assert_eq!(impedance_llm_delta(&p, Some(&FailingCaller)), 0.0);
    }

    #[test]
    fn impedance_with_llm_caps_at_one() {
        let mut p = Patient::new();
        p.missing_labs_count = 100;
        p.history_contradictions = 100;
        p.unexplained_symptoms_count = 100;
        p.last_visit_years_ago = 100;
        p.dx_without_evidence = true;
        p.red_flags = vec!["x".into(); 50];
        let big = ConstantCaller(0.4);
        let val = impedance_with_llm(&p, Some(&big));
        assert!(val <= 1.0 + 1e-9, "expected ≤1.0, got {val}");
        // With saturated checklist + 0.4 LLM delta, must clamp.
        assert!((val - 1.0).abs() < 1e-9, "expected exactly 1.0 cap, got {val}");
    }

    // ── log_decision ───────────────────────────────────────────────────────

    #[test]
    fn log_decision_writes_db_and_md() {
        let tmp = tempfile::TempDir::new().unwrap();
        let db = tmp.path().join("aim.db");
        let pdir = tmp.path().join("Patients");

        let alts = vec![safe_dx("a"), safe_dx("b")];
        let r = decide(&alts, &Patient::new(), &Context::default(),
                       &OverrideContext::none(), &KernelWeights::default()).unwrap();
        log_decision(&db, &pdir, "Smith_John_1980_05_15", "test_agent",
                     "triage", &r, &OverrideContext::none(), Some("session-1")).unwrap();

        let conn = rusqlite::Connection::open(&db).unwrap();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM ai_events", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 1);

        let log = pdir.join("Smith_John_1980_05_15").join("AI_LOG.md");
        assert!(log.exists());
        let txt = std::fs::read_to_string(&log).unwrap();
        assert!(txt.contains("triage by test_agent"));
        assert!(txt.contains("Decision:"));
    }

    #[test]
    fn log_decision_skips_md_for_empty_patient_id() {
        let tmp = tempfile::TempDir::new().unwrap();
        let db = tmp.path().join("aim.db");
        let pdir = tmp.path().join("Patients");
        let alts = vec![safe_dx("a")];
        let r = decide(&alts, &Patient::new(), &Context::default(),
                       &OverrideContext::none(), &KernelWeights::default()).unwrap();
        log_decision(&db, &pdir, "", "agent", "triage",
                     &r, &OverrideContext::none(), None).unwrap();
        assert!(!pdir.exists()
            || std::fs::read_dir(&pdir).map(|d| d.count() == 0).unwrap_or(true));
    }

    #[test]
    fn kernel_weights_env_overrides() {
        std::env::set_var("AIM_KERNEL_ALPHA", "0.5");
        std::env::set_var("AIM_KERNEL_BETA", "0.3");
        std::env::set_var("AIM_KERNEL_GAMMA", "0.2");
        let w = KernelWeights::default();
        assert!((w.alpha - 0.5).abs() < 1e-9);
        assert!((w.beta - 0.3).abs() < 1e-9);
        assert!((w.gamma - 0.2).abs() < 1e-9);
        std::env::remove_var("AIM_KERNEL_ALPHA");
        std::env::remove_var("AIM_KERNEL_BETA");
        std::env::remove_var("AIM_KERNEL_GAMMA");
    }
}

// keep unused alias quiet
#[allow(dead_code)]
type _BTreeMapAlias = BTreeMap<String, serde_json::Value>;
