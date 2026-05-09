//! aim-regimen-validator — strict regimen validator (D1).
//!
//! Port of `agents/regimen_validator.py`. Wraps drug-interaction lookup
//! results in a hard-refusal layer so the doctor agent can't ignore them
//! during synthesis.
//!
//! ## Refusal rules
//! - **Contraindicated** pair → ALWAYS refuse, no override.
//! - **Major** pair → refuse unless `physician_override = true`.
//! - **Moderate** pair → warn (in `monitoring_required`); do not refuse.
//! - **Minor / no_known** → silent.
//!
//! The interaction lookup itself is pluggable — production wires
//! `agents.interactions.check_regimen`; tests pass a [`Vec<Interaction>`]
//! directly via [`validate_with_lookups`].

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use thiserror::Error;

#[derive(Debug, Error)]
#[error("regimen refused: {summary} — offending pair: {drug_a} + {drug_b} ({severity}): {recommendation}")]
pub struct RegimenError {
    pub summary: String,
    pub drug_a: String,
    pub drug_b: String,
    pub severity: String,
    pub recommendation: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Contraindicated,
    Major,
    Moderate,
    Minor,
    NoKnown,
}

impl Severity {
    pub fn parse(s: &str) -> Severity {
        match s {
            "contraindicated" => Severity::Contraindicated,
            "major" => Severity::Major,
            "moderate" => Severity::Moderate,
            "minor" => Severity::Minor,
            _ => Severity::NoKnown,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Severity::Contraindicated => "contraindicated",
            Severity::Major => "major",
            Severity::Moderate => "moderate",
            Severity::Minor => "minor",
            Severity::NoKnown => "no_known",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Interaction {
    pub drug_a: String,
    pub drug_b: String,
    pub severity: Severity,
    #[serde(default)]
    pub recommendation: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Validation {
    pub interactions: Vec<Interaction>,
    pub contraindicated: Vec<Interaction>,
    pub major: Vec<Interaction>,
    pub moderate: Vec<Interaction>,
    pub safe_drugs: Vec<String>,
    pub must_drop: Vec<String>,
    pub monitoring_required: Vec<String>,
    pub refused: bool,
    pub summary: String,
}

/// Pluggable drug-interaction lookup. Production wires
/// `agents.interactions.check_regimen` (Python via subprocess) or a
/// pure-Rust port; tests pass a `FixedLookup` with predefined pairs.
pub trait InteractionLookup {
    fn lookup(&self, drugs: &[&str]) -> Vec<Interaction>;
}

pub struct FixedLookup(pub Vec<Interaction>);

impl InteractionLookup for FixedLookup {
    fn lookup(&self, _drugs: &[&str]) -> Vec<Interaction> {
        self.0.clone()
    }
}

fn bucket(interactions: &[Interaction]) -> (Vec<Interaction>, Vec<Interaction>, Vec<Interaction>) {
    let mut contraindicated = Vec::new();
    let mut major = Vec::new();
    let mut moderate = Vec::new();
    for ix in interactions {
        match ix.severity {
            Severity::Contraindicated => contraindicated.push(ix.clone()),
            Severity::Major => major.push(ix.clone()),
            Severity::Moderate => moderate.push(ix.clone()),
            _ => {}
        }
    }
    (contraindicated, major, moderate)
}

/// Run the lookup and classify the outcome. `physician_override = true`
/// allows MAJOR pairs through (still surfaced in `monitoring_required`)
/// but NEVER lets a contraindicated pair through.
pub fn validate(
    drugs: &[&str],
    lookup: &dyn InteractionLookup,
    physician_override: bool,
) -> Validation {
    let drugs_clean: Vec<String> = drugs
        .iter()
        .map(|d| d.trim().to_string())
        .filter(|d| !d.is_empty())
        .collect();
    let drug_refs: Vec<&str> = drugs_clean.iter().map(|s| s.as_str()).collect();
    let interactions = lookup.lookup(&drug_refs);
    let (contraindicated, major, moderate) = bucket(&interactions);

    let mut must_drop: BTreeSet<String> = BTreeSet::new();
    let mut monitoring: BTreeSet<String> = BTreeSet::new();

    for ix in &contraindicated {
        must_drop.insert(ix.drug_a.clone());
        must_drop.insert(ix.drug_b.clone());
    }
    if physician_override {
        for ix in &major {
            monitoring.insert(ix.drug_a.clone());
            monitoring.insert(ix.drug_b.clone());
        }
    } else {
        for ix in &major {
            must_drop.insert(ix.drug_a.clone());
            must_drop.insert(ix.drug_b.clone());
        }
    }
    for ix in &moderate {
        monitoring.insert(ix.drug_a.clone());
        monitoring.insert(ix.drug_b.clone());
    }

    let refused = !contraindicated.is_empty() || (!major.is_empty() && !physician_override);
    let drug_set: BTreeSet<String> = drugs_clean.iter().cloned().collect();
    let safe_drugs: Vec<String> = drug_set.difference(&must_drop).cloned().collect();
    let monitoring_clean: Vec<String> = monitoring.difference(&must_drop).cloned().collect();

    let mut pieces = Vec::new();
    if !contraindicated.is_empty() {
        pieces.push(format!("{} CONTRAINDICATED", contraindicated.len()));
    }
    if !major.is_empty() {
        pieces.push(format!("{} major", major.len()));
    }
    if !moderate.is_empty() {
        pieces.push(format!("{} moderate", moderate.len()));
    }
    if pieces.is_empty() {
        pieces.push("no flagged pairs".into());
    }
    let summary = format!("regimen review: {}", pieces.join(", "));

    Validation {
        interactions,
        contraindicated,
        major,
        moderate,
        safe_drugs,
        must_drop: must_drop.into_iter().collect(),
        monitoring_required: monitoring_clean,
        refused,
        summary,
    }
}

/// Same as [`validate`] but returns `Err(RegimenError)` on hard refusal.
pub fn validate_or_raise(
    drugs: &[&str],
    lookup: &dyn InteractionLookup,
    physician_override: bool,
) -> Result<Validation, RegimenError> {
    let v = validate(drugs, lookup, physician_override);
    if v.refused {
        let offender = v
            .contraindicated
            .first()
            .or_else(|| v.major.first())
            .cloned()
            .expect("refused implies offender exists");
        return Err(RegimenError {
            summary: v.summary,
            drug_a: offender.drug_a,
            drug_b: offender.drug_b,
            severity: offender.severity.as_str().into(),
            recommendation: offender.recommendation,
        });
    }
    Ok(v)
}

/// Append a regimen-validation footer to a doctor's draft. Used to make
/// any prescription advice machine-auditable.
pub fn annotate(
    draft_text: &str,
    drugs: &[&str],
    lookup: &dyn InteractionLookup,
    physician_override: bool,
) -> String {
    let v = validate(drugs, lookup, physician_override);
    if v.contraindicated.is_empty() && v.major.is_empty() && v.moderate.is_empty() {
        return draft_text.to_string();
    }
    let mut bits = vec![
        draft_text.trim_end().to_string(),
        String::new(),
        "─── Regimen safety review ───".into(),
    ];
    if !v.contraindicated.is_empty() {
        bits.push("⛔ CONTRAINDICATED — must not co-administer:".into());
        for ix in &v.contraindicated {
            bits.push(format!(
                "   • {} + {} — {}",
                ix.drug_a, ix.drug_b, ix.recommendation
            ));
        }
    }
    if !v.major.is_empty() {
        let marker = if physician_override {
            "⚠️ MAJOR (override active):"
        } else {
            "⛔ MAJOR — refused without physician_override:"
        };
        bits.push(marker.into());
        for ix in &v.major {
            bits.push(format!(
                "   • {} + {} — {}",
                ix.drug_a, ix.drug_b, ix.recommendation
            ));
        }
    }
    if !v.moderate.is_empty() {
        bits.push("🟡 MODERATE — monitoring required:".into());
        for ix in &v.moderate {
            bits.push(format!(
                "   • {} + {} — {}",
                ix.drug_a, ix.drug_b, ix.recommendation
            ));
        }
    }
    if !v.must_drop.is_empty() {
        bits.push(String::new());
        bits.push(format!("must drop: {}", v.must_drop.join(", ")));
    }
    if !v.monitoring_required.is_empty() {
        bits.push(format!(
            "monitoring: {}",
            v.monitoring_required.join(", ")
        ));
    }
    bits.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ix(a: &str, b: &str, sev: Severity, rec: &str) -> Interaction {
        Interaction {
            drug_a: a.into(),
            drug_b: b.into(),
            severity: sev,
            recommendation: rec.into(),
        }
    }

    #[test]
    fn no_interactions_returns_clean() {
        let lookup = FixedLookup(vec![]);
        let v = validate(&["aspirin", "metformin"], &lookup, false);
        assert!(!v.refused);
        assert_eq!(v.must_drop.len(), 0);
        assert_eq!(v.monitoring_required.len(), 0);
        assert_eq!(v.safe_drugs, vec!["aspirin", "metformin"]);
        assert!(v.summary.contains("no flagged pairs"));
    }

    #[test]
    fn contraindicated_always_refuses() {
        let lookup = FixedLookup(vec![ix(
            "warfarin",
            "fluconazole",
            Severity::Contraindicated,
            "stop one",
        )]);
        let v = validate(&["warfarin", "fluconazole"], &lookup, false);
        assert!(v.refused);
        assert_eq!(v.must_drop, vec!["fluconazole", "warfarin"]);
    }

    #[test]
    fn contraindicated_refuses_even_with_override() {
        let lookup = FixedLookup(vec![ix(
            "drugA",
            "drugB",
            Severity::Contraindicated,
            "stop",
        )]);
        let v = validate(&["drugA", "drugB"], &lookup, true);
        assert!(v.refused);
    }

    #[test]
    fn major_refuses_without_override() {
        let lookup = FixedLookup(vec![ix(
            "drugA",
            "drugB",
            Severity::Major,
            "watch INR",
        )]);
        let v = validate(&["drugA", "drugB"], &lookup, false);
        assert!(v.refused);
        assert_eq!(v.must_drop, vec!["drugA", "drugB"]);
        assert_eq!(v.monitoring_required.len(), 0);
    }

    #[test]
    fn major_passes_with_override_into_monitoring() {
        let lookup = FixedLookup(vec![ix(
            "drugA",
            "drugB",
            Severity::Major,
            "watch",
        )]);
        let v = validate(&["drugA", "drugB"], &lookup, true);
        assert!(!v.refused);
        assert!(v.must_drop.is_empty());
        assert_eq!(v.monitoring_required, vec!["drugA", "drugB"]);
    }

    #[test]
    fn moderate_warns_does_not_refuse() {
        let lookup = FixedLookup(vec![ix(
            "drugA",
            "drugB",
            Severity::Moderate,
            "monitor LFT",
        )]);
        let v = validate(&["drugA", "drugB"], &lookup, false);
        assert!(!v.refused);
        assert_eq!(v.monitoring_required, vec!["drugA", "drugB"]);
        assert!(v.must_drop.is_empty());
    }

    #[test]
    fn minor_and_no_known_silent() {
        let lookup = FixedLookup(vec![
            ix("a", "b", Severity::Minor, ""),
            ix("c", "d", Severity::NoKnown, ""),
        ]);
        let v = validate(&["a", "b", "c", "d"], &lookup, false);
        assert!(!v.refused);
        assert!(v.must_drop.is_empty());
        assert!(v.monitoring_required.is_empty());
        assert!(v.summary.contains("no flagged pairs"));
    }

    #[test]
    fn must_drop_excluded_from_monitoring() {
        // drugA is contraindicated AND moderate-paired; must_drop wins,
        // monitoring strips drugA.
        let lookup = FixedLookup(vec![
            ix("drugA", "drugB", Severity::Contraindicated, ""),
            ix("drugA", "drugC", Severity::Moderate, ""),
        ]);
        let v = validate(&["drugA", "drugB", "drugC"], &lookup, false);
        assert!(v.must_drop.contains(&"drugA".to_string()));
        assert!(!v.monitoring_required.contains(&"drugA".to_string()));
        assert!(v.monitoring_required.contains(&"drugC".to_string()));
    }

    #[test]
    fn empty_drugs_returns_clean() {
        let lookup = FixedLookup(vec![]);
        let v = validate(&[], &lookup, false);
        assert!(!v.refused);
        assert!(v.safe_drugs.is_empty());
    }

    #[test]
    fn whitespace_drugs_filtered() {
        let lookup = FixedLookup(vec![]);
        let v = validate(&["  ", "aspirin", ""], &lookup, false);
        assert_eq!(v.safe_drugs, vec!["aspirin"]);
    }

    #[test]
    fn summary_lists_all_severity_buckets() {
        let lookup = FixedLookup(vec![
            ix("a", "b", Severity::Contraindicated, ""),
            ix("c", "d", Severity::Major, ""),
            ix("e", "f", Severity::Moderate, ""),
        ]);
        let v = validate(&["a", "b", "c", "d", "e", "f"], &lookup, false);
        assert!(v.summary.contains("1 CONTRAINDICATED"));
        assert!(v.summary.contains("1 major"));
        assert!(v.summary.contains("1 moderate"));
    }

    #[test]
    fn validate_or_raise_returns_ok_when_clean() {
        let lookup = FixedLookup(vec![]);
        let v = validate_or_raise(&["aspirin"], &lookup, false).unwrap();
        assert!(!v.refused);
    }

    #[test]
    fn validate_or_raise_errors_with_offender() {
        let lookup = FixedLookup(vec![ix(
            "warfarin",
            "azole",
            Severity::Contraindicated,
            "stop",
        )]);
        let err = validate_or_raise(&["warfarin", "azole"], &lookup, false).unwrap_err();
        assert_eq!(err.drug_a, "warfarin");
        assert_eq!(err.severity, "contraindicated");
        assert_eq!(err.recommendation, "stop");
    }

    #[test]
    fn annotate_passes_through_when_clean() {
        let lookup = FixedLookup(vec![]);
        let out = annotate("doctor draft here", &["aspirin"], &lookup, false);
        assert_eq!(out, "doctor draft here");
    }

    #[test]
    fn annotate_appends_safety_block() {
        let lookup = FixedLookup(vec![ix(
            "warfarin",
            "azole",
            Severity::Contraindicated,
            "do not co-administer",
        )]);
        let out = annotate("Take meds", &["warfarin", "azole"], &lookup, false);
        assert!(out.starts_with("Take meds"));
        assert!(out.contains("Regimen safety review"));
        assert!(out.contains("⛔ CONTRAINDICATED"));
        assert!(out.contains("warfarin + azole"));
        assert!(out.contains("do not co-administer"));
        assert!(out.contains("must drop:"));
    }

    #[test]
    fn annotate_marks_major_override_distinctly() {
        let lookup = FixedLookup(vec![ix(
            "drugA",
            "drugB",
            Severity::Major,
            "watch INR",
        )]);
        let with_override = annotate("Plan:", &["drugA", "drugB"], &lookup, true);
        assert!(with_override.contains("MAJOR (override active)"));
        let without_override = annotate("Plan:", &["drugA", "drugB"], &lookup, false);
        assert!(without_override.contains("refused without physician_override"));
    }

    #[test]
    fn annotate_moderate_emits_monitoring_line() {
        let lookup = FixedLookup(vec![ix(
            "drugA",
            "drugB",
            Severity::Moderate,
            "monitor LFT",
        )]);
        let out = annotate("Plan", &["drugA", "drugB"], &lookup, false);
        assert!(out.contains("🟡 MODERATE"));
        assert!(out.contains("monitoring:"));
    }

    #[test]
    fn severity_parse_round_trip() {
        for s in &["contraindicated", "major", "moderate", "minor", "no_known"] {
            let sev = Severity::parse(s);
            assert_eq!(sev.as_str(), *s);
        }
        // unknown → no_known
        assert_eq!(Severity::parse("garbage"), Severity::NoKnown);
    }
}
