//! aim-compat — unified medication compatibility checker.
//!
//! Layers on top of `aim-interactions` (drug-drug pairs) and adds:
//!   * Age-based contraindications
//!   * Allergy / cross-reactivity matching
//!   * Pregnancy contraindications (FDA category X / known teratogens)
//!   * Renal & hepatic flags from conditions
//!
//! Output is a flat `Vec<Conflict>` with severity, so callers (Phoenix
//! LiveView, doctor agent treatment-by-button) can sort/filter without
//! re-implementing severity ordering.
//!
//! **Scope (v0.1 / 2026-05-08):** age + allergy + pregnancy + renal/hepatic
//! tables hand-curated from FDA DailyMed, BNF, and Mayo Clinic Drug
//! Reference. Drug-drug pairs reuse `aim-interactions::TABLE` (35 pairs +
//! ongoing extension). For 200+ pairs see Task #2 expansion phase.
//!
//! **Not a replacement** for RxNav / DrugBank / pharmacist judgment.
//! Every clinical decision must be reviewed by a licensed prescriber.

use aim_interactions::{canon, check_regimen as drugdrug_check, Severity};
use serde::{Deserialize, Serialize};

pub const DISCLAIMER: &str = "AIM compatibility checker (v0.1, 2026-05-08). \
    Decision support only. Always cross-check against FDA DailyMed, RxNav, \
    or pharmacist before prescribing.";

// ── conflict shape ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ConflictKind {
    DrugDrug,
    Age,
    Allergy,
    Pregnancy,
    Renal,
    Hepatic,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Conflict {
    pub kind: ConflictKind,
    /// Drug under evaluation (canonicalised name).
    pub drug: String,
    /// Severity in `aim-interactions` vocabulary
    /// (contraindicated > major > moderate > minor > no_known).
    pub severity: Severity,
    /// Human-readable explanation (mechanism + recommendation).
    pub message: String,
    /// Where this rule comes from (DailyMed URL / PMID / BNF / Mayo).
    pub source: String,
    /// For DrugDrug — the other drug; otherwise `None`.
    pub other_drug: Option<String>,
}

// ── patient context ───────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct PatientCtx {
    pub age_years: Option<u32>,
    pub sex: Option<String>,
    pub pregnant: bool,
    pub breastfeeding: bool,
    /// Free-text allergy strings as they appear in MEMORY.md
    /// (e.g. "penicillin", "aspirin", "sulfa drugs", "peanut"). Matched
    /// against [`ALLERGY_RULES`] after canonicalisation.
    pub allergies: Vec<String>,
    /// Free-text condition strings (e.g. "CKD stage 3", "cirrhosis",
    /// "asthma"). Matched against [`RENAL_KEYWORDS`] / [`HEPATIC_KEYWORDS`].
    pub conditions: Vec<String>,
    /// Existing medications already on board (used as the second arm
    /// for drug-drug interactions).
    pub existing_meds: Vec<String>,
}

impl PatientCtx {
    pub fn new() -> Self {
        Self::default()
    }
}

// ── age contraindications ─────────────────────────────────────────────────

/// Static rule: `(drug_canon, max_age_years, reason, source)` — drug is
/// contraindicated **strictly below** the threshold age.
const AGE_BELOW_RULES: &[(&str, u32, Severity, &str, &str)] = &[
    ("acetylsalicylic_acid", 16, Severity::Contraindicated,
     "Reye's syndrome risk in viral illness in children/teens.",
     "FDA black-box; AAP guidelines"),
    ("tetracycline", 8, Severity::Contraindicated,
     "Permanent tooth discolouration and enamel hypoplasia.",
     "FDA DailyMed; AAP Red Book"),
    ("doxycycline", 8, Severity::Major,
     "Same class effect as tetracycline; short courses (<21 d) for severe \
      indications (rickettsial disease) usually acceptable per AAP 2013+.",
     "AAP Red Book 2018"),
    ("ciprofloxacin", 18, Severity::Major,
     "Cartilage / tendon toxicity in growing skeleton; reserve for serious \
      indications when alternatives unavailable.",
     "FDA DailyMed; EMA"),
    ("levofloxacin", 18, Severity::Major,
     "Same class effect as ciprofloxacin (fluoroquinolones).",
     "FDA DailyMed; EMA"),
    ("codeine", 12, Severity::Contraindicated,
     "Variable CYP2D6 metabolism → fatal respiratory depression in \
      ultra-rapid metabolisers (esp. post-tonsillectomy/adenoidectomy).",
     "FDA Drug Safety Communication 2013/2017"),
    ("tramadol", 12, Severity::Major,
     "Same CYP2D6 risk as codeine; FDA boxed warning for paediatric use.",
     "FDA Drug Safety Communication 2017"),
    ("aspirin", 16, Severity::Contraindicated,
     "Reye's syndrome (synonym for acetylsalicylic_acid).",
     "FDA black-box; AAP guidelines"),
    ("promethazine", 2, Severity::Contraindicated,
     "Fatal respiratory depression in children <2 years.",
     "FDA black-box 2004"),
    ("metoclopramide", 1, Severity::Major,
     "Tardive dyskinesia and acute dystonia; avoid in infants where \
      alternatives exist.",
     "FDA black-box 2009"),
];

/// Static rule: `(drug_canon, min_age_years, reason, source)` — drug should
/// be reviewed (caution) **at or above** this age.
const AGE_ABOVE_RULES: &[(&str, u32, Severity, &str, &str)] = &[
    ("diphenhydramine", 65, Severity::Moderate,
     "Beers Criteria: anticholinergic load → falls, confusion, urinary \
      retention.",
     "AGS Beers Criteria 2023"),
    ("amitriptyline", 65, Severity::Moderate,
     "Beers Criteria: strong anticholinergic + orthostatic hypotension.",
     "AGS Beers Criteria 2023"),
    ("nitrofurantoin", 65, Severity::Moderate,
     "Beers Criteria: pulmonary toxicity with prolonged use; avoid in CrCl <30.",
     "AGS Beers Criteria 2023"),
    ("benzodiazepine", 65, Severity::Major,
     "Beers Criteria: increased risk of falls, fractures, delirium; long \
      half-life agents to be avoided entirely.",
     "AGS Beers Criteria 2023"),
    ("diazepam", 65, Severity::Major,
     "Beers Criteria long-acting BZD; falls / cognitive impairment.",
     "AGS Beers Criteria 2023"),
];

fn check_age(drug_canon: &str, ctx: &PatientCtx) -> Option<Conflict> {
    let age = ctx.age_years?;
    for (name, threshold, sev, msg, src) in AGE_BELOW_RULES {
        if name == &drug_canon && age < *threshold {
            return Some(Conflict {
                kind: ConflictKind::Age,
                drug: drug_canon.into(),
                severity: *sev,
                message: format!(
                    "Patient is {} y/o; {} contraindicated below {}. {}",
                    age, name, threshold, msg
                ),
                source: (*src).into(),
                other_drug: None,
            });
        }
    }
    for (name, threshold, sev, msg, src) in AGE_ABOVE_RULES {
        if name == &drug_canon && age >= *threshold {
            return Some(Conflict {
                kind: ConflictKind::Age,
                drug: drug_canon.into(),
                severity: *sev,
                message: format!(
                    "Patient is {} y/o; {} flagged at {}+. {}",
                    age, name, threshold, msg
                ),
                source: (*src).into(),
                other_drug: None,
            });
        }
    }
    None
}

// ── allergies ─────────────────────────────────────────────────────────────

/// Static rule: `(allergy_pattern, drug_canon_match, severity, message, source)`.
/// `allergy_pattern` is a canonicalised allergy keyword; `drug_canon_match`
/// is matched as substring of the drug canon (so `penicillin` catches
/// `amoxicillin`, `ampicillin`, `piperacillin`).
const ALLERGY_RULES: &[(&str, &str, Severity, &str, &str)] = &[
    ("penicillin", "penicillin", Severity::Contraindicated,
     "Patient has penicillin allergy — anaphylaxis risk.",
     "Mayo Clinic Drug Allergy Reference"),
    ("penicillin", "amoxicillin", Severity::Contraindicated,
     "Amoxicillin is a penicillin-class antibiotic — same class allergy.",
     "Mayo Clinic Drug Allergy Reference"),
    ("penicillin", "ampicillin", Severity::Contraindicated,
     "Ampicillin is a penicillin-class antibiotic — same class allergy.",
     "Mayo Clinic Drug Allergy Reference"),
    ("penicillin", "piperacillin", Severity::Contraindicated,
     "Piperacillin is a penicillin-class antibiotic — same class allergy.",
     "Mayo Clinic Drug Allergy Reference"),
    ("penicillin", "cephalexin", Severity::Major,
     "Cephalosporin cross-reactivity ~1-3% in IgE-mediated penicillin allergy. \
      Avoid first-gen cephalosporins; later generations safer if no severe reaction.",
     "AAAAI Practice Parameter 2010"),
    ("penicillin", "cefazolin", Severity::Major,
     "Cephalosporin cross-reactivity (esp. shared side-chain).",
     "AAAAI Practice Parameter 2010"),
    ("sulfa", "sulfamethoxazole", Severity::Contraindicated,
     "Sulfa allergy — Stevens-Johnson / TEN risk with sulfonamide antibiotics.",
     "FDA DailyMed; AAAAI"),
    ("sulfa", "trimethoprim_sulfamethoxazole", Severity::Contraindicated,
     "Co-trimoxazole contains sulfamethoxazole — sulfa cross-react.",
     "FDA DailyMed"),
    ("aspirin", "acetylsalicylic_acid", Severity::Contraindicated,
     "ASA = aspirin; do not re-administer.",
     "self-evident"),
    ("nsaid", "ibuprofen", Severity::Contraindicated,
     "NSAID-class allergy / hypersensitivity — bronchospasm + urticaria.",
     "AAAAI Practice Parameter"),
    ("nsaid", "naproxen", Severity::Contraindicated,
     "NSAID class effect.",
     "AAAAI Practice Parameter"),
    ("nsaid", "diclofenac", Severity::Contraindicated,
     "NSAID class effect.",
     "AAAAI Practice Parameter"),
    ("nsaid", "ketorolac", Severity::Contraindicated,
     "NSAID class effect.",
     "AAAAI Practice Parameter"),
    ("nsaid", "acetylsalicylic_acid", Severity::Major,
     "ASA-induced respiratory disease (Samter's triad) — cross-react with NSAIDs.",
     "AAAAI Practice Parameter"),
    ("iodine", "iodinated_contrast", Severity::Major,
     "True 'iodine allergy' is rare; reactions usually to contrast osmolality. \
      Consider non-ionic low-osmolar agent + premedication.",
     "ACR Manual on Contrast Media v10.3"),
    ("statin", "simvastatin", Severity::Contraindicated,
     "Statin myopathy/rhabdomyolysis history — same class.",
     "FDA DailyMed; ACC/AHA 2018"),
    ("statin", "atorvastatin", Severity::Major,
     "Statin myopathy class effect — try lowest dose hydrophilic statin or \
      alternative agent (ezetimibe).",
     "ACC/AHA 2018"),
];

fn canon_allergy(s: &str) -> String {
    s.trim().to_lowercase().replace(['-', '_'], " ").replace("  ", " ")
}

fn check_allergy(drug_canon: &str, ctx: &PatientCtx) -> Vec<Conflict> {
    let mut out = Vec::new();
    if ctx.allergies.is_empty() {
        return out;
    }
    let allergies_lc: Vec<String> = ctx.allergies.iter().map(|a| canon_allergy(a)).collect();

    for (allergy_pat, drug_pat, sev, msg, src) in ALLERGY_RULES {
        if !drug_canon.contains(drug_pat) {
            continue;
        }
        let matched = allergies_lc.iter().any(|a| a.contains(allergy_pat));
        if matched {
            out.push(Conflict {
                kind: ConflictKind::Allergy,
                drug: drug_canon.into(),
                severity: *sev,
                message: (*msg).into(),
                source: (*src).into(),
                other_drug: None,
            });
        }
    }
    out
}

// ── pregnancy ─────────────────────────────────────────────────────────────

/// FDA Category X / known teratogens. `(drug_match, severity, message, source)`.
/// `drug_match` matched as substring of canon.
const PREGNANCY_RULES: &[(&str, Severity, &str, &str)] = &[
    ("warfarin", Severity::Contraindicated,
     "FDA Category X — fetal warfarin syndrome (1st trimester) + bleeding risk \
      throughout pregnancy. Switch to LMWH.",
     "FDA DailyMed"),
    ("isotretinoin", Severity::Contraindicated,
     "FDA Category X — severe teratogen (CNS, cardiac, craniofacial).",
     "iPLEDGE / FDA DailyMed"),
    ("methotrexate", Severity::Contraindicated,
     "FDA Category X — abortifacient + teratogen. Halt and switch to safer DMARD.",
     "FDA DailyMed"),
    ("ace_inhibitor", Severity::Contraindicated,
     "Category D (2nd/3rd trimester) — fetal renal dysgenesis, oligohydramnios.",
     "FDA DailyMed"),
    ("enalapril", Severity::Contraindicated,
     "ACE inhibitor — see ace_inhibitor pregnancy category D.",
     "FDA DailyMed"),
    ("lisinopril", Severity::Contraindicated,
     "ACE inhibitor — see ace_inhibitor pregnancy category D.",
     "FDA DailyMed"),
    ("losartan", Severity::Contraindicated,
     "ARB — same fetopathy as ACE inhibitors.",
     "FDA DailyMed"),
    ("statin", Severity::Contraindicated,
     "Statins — pregnancy contraindicated; cholesterol synthesis required \
      for fetal development.",
     "FDA DailyMed; SMFM"),
    ("simvastatin", Severity::Contraindicated,
     "Statin class — see statin pregnancy contraindication.",
     "FDA DailyMed"),
    ("atorvastatin", Severity::Contraindicated,
     "Statin class — see statin pregnancy contraindication.",
     "FDA DailyMed"),
    ("doxycycline", Severity::Major,
     "Tetracycline class — fetal tooth discolouration after 14 weeks.",
     "FDA DailyMed; AAP"),
    ("tetracycline", Severity::Major,
     "Fetal tooth discolouration after 14 weeks.",
     "FDA DailyMed; AAP"),
    ("valproate", Severity::Contraindicated,
     "Major teratogen — neural tube defects + neurodevelopmental harm.",
     "FDA / EMA boxed warning"),
    ("carbamazepine", Severity::Major,
     "Neural tube defects; supplement folate; consider safer alternative.",
     "FDA DailyMed"),
    ("phenytoin", Severity::Major,
     "Fetal hydantoin syndrome.",
     "FDA DailyMed"),
    ("ibuprofen", Severity::Major,
     "Avoid in 3rd trimester — premature ductus arteriosus closure, \
      oligohydramnios.",
     "FDA Drug Safety Communication 2020"),
    ("nsaid", Severity::Major,
     "NSAID class — avoid 3rd trimester (ductal closure).",
     "FDA Drug Safety Communication 2020"),
];

fn check_pregnancy(drug_canon: &str, ctx: &PatientCtx) -> Vec<Conflict> {
    if !ctx.pregnant {
        return Vec::new();
    }
    PREGNANCY_RULES
        .iter()
        .filter(|(pat, _, _, _)| drug_canon.contains(pat))
        .map(|(pat, sev, msg, src)| Conflict {
            kind: ConflictKind::Pregnancy,
            drug: drug_canon.into(),
            severity: *sev,
            message: format!("Pregnancy: {}. ({})", msg, pat),
            source: (*src).into(),
            other_drug: None,
        })
        .collect()
}

// ── renal / hepatic flags ─────────────────────────────────────────────────

const RENAL_KEYWORDS: &[&str] = &[
    "ckd", "chronic kidney", "renal failure", "egfr", "esrd", "dialysis",
    "kidney disease", "renal insufficiency", "creatinine clearance",
];

const HEPATIC_KEYWORDS: &[&str] = &[
    "cirrhosis", "hepatitis", "liver failure", "hepatic insufficiency",
    "child-pugh", "ascites", "hepatic encephalopathy",
];

/// Drugs needing renal-function review. `(drug_match, severity, message, source)`.
const RENAL_RULES: &[(&str, Severity, &str, &str)] = &[
    ("metformin", Severity::Major,
     "Avoid if eGFR <30; use caution at eGFR 30-45 (lactic acidosis risk).",
     "FDA DailyMed 2016"),
    ("nitrofurantoin", Severity::Major,
     "Avoid at CrCl <30 — therapeutic levels not achieved + neurotoxicity risk.",
     "FDA DailyMed; AGS Beers"),
    ("nsaid", Severity::Major,
     "NSAIDs reduce GFR; AKI risk in CKD; avoid in CKD stage 3+.",
     "KDIGO 2012"),
    ("ibuprofen", Severity::Major,
     "Avoid in CKD stage 3+; AKI risk.",
     "KDIGO 2012"),
    ("naproxen", Severity::Major,
     "Avoid in CKD stage 3+; AKI risk.",
     "KDIGO 2012"),
    ("gentamicin", Severity::Major,
     "Nephrotoxic — dose-adjust by CrCl; trough monitoring.",
     "FDA DailyMed"),
    ("vancomycin", Severity::Major,
     "Nephrotoxic — therapeutic drug monitoring required.",
     "IDSA 2020"),
    ("ace_inhibitor", Severity::Moderate,
     "Monitor K+ + creatinine after start; expected creatinine rise <30% acceptable.",
     "KDIGO 2012"),
];

const HEPATIC_RULES: &[(&str, Severity, &str, &str)] = &[
    ("paracetamol", Severity::Major,
     "Limit to 2 g/day in cirrhosis (vs 4 g normal); avoid in acute liver failure.",
     "AASLD 2014"),
    ("acetaminophen", Severity::Major,
     "Limit to 2 g/day in cirrhosis (vs 4 g normal); avoid in acute liver failure.",
     "AASLD 2014"),
    ("statin", Severity::Moderate,
     "Avoid in active liver disease / unexplained ALT >3× ULN.",
     "FDA DailyMed; ACC/AHA 2018"),
    ("simvastatin", Severity::Moderate,
     "Avoid in active liver disease.",
     "FDA DailyMed"),
    ("methotrexate", Severity::Major,
     "Hepatotoxic; avoid in chronic liver disease.",
     "FDA DailyMed"),
    ("isoniazid", Severity::Major,
     "Hepatotoxic; baseline + follow-up LFTs.",
     "ATS/CDC/IDSA 2017"),
];

fn check_renal_hepatic(drug_canon: &str, ctx: &PatientCtx) -> Vec<Conflict> {
    let mut out = Vec::new();

    let conditions_lc: Vec<String> = ctx
        .conditions
        .iter()
        .map(|c| c.to_lowercase())
        .collect();

    let has_renal = RENAL_KEYWORDS
        .iter()
        .any(|kw| conditions_lc.iter().any(|c| c.contains(kw)));
    let has_hepatic = HEPATIC_KEYWORDS
        .iter()
        .any(|kw| conditions_lc.iter().any(|c| c.contains(kw)));

    if has_renal {
        for (pat, sev, msg, src) in RENAL_RULES {
            if drug_canon.contains(pat) {
                out.push(Conflict {
                    kind: ConflictKind::Renal,
                    drug: drug_canon.into(),
                    severity: *sev,
                    message: format!("Renal disease in record: {}", msg),
                    source: (*src).into(),
                    other_drug: None,
                });
            }
        }
    }
    if has_hepatic {
        for (pat, sev, msg, src) in HEPATIC_RULES {
            if drug_canon.contains(pat) {
                out.push(Conflict {
                    kind: ConflictKind::Hepatic,
                    drug: drug_canon.into(),
                    severity: *sev,
                    message: format!("Hepatic disease in record: {}", msg),
                    source: (*src).into(),
                    other_drug: None,
                });
            }
        }
    }
    out
}

// ── drug-drug via aim-interactions ────────────────────────────────────────

fn check_drug_drug(new_drug: &str, ctx: &PatientCtx) -> Vec<Conflict> {
    let mut all: Vec<String> = vec![new_drug.to_string()];
    all.extend(ctx.existing_meds.iter().cloned());

    let interactions = drugdrug_check(&all);
    interactions
        .into_iter()
        .filter(|i| !matches!(i.severity, Severity::NoKnown))
        .map(|i| {
            let other = if canon(&i.drug_a) == canon(new_drug) {
                i.drug_b.clone()
            } else {
                i.drug_a.clone()
            };
            Conflict {
                kind: ConflictKind::DrugDrug,
                drug: new_drug.into(),
                severity: i.severity,
                message: format!("{} | {}", i.mechanism, i.recommendation),
                source: i.source,
                other_drug: Some(other),
            }
        })
        .collect()
}

// ── public API ────────────────────────────────────────────────────────────

/// Check **adding one new drug** to an existing regimen given patient
/// context. Returns all conflicts (drug-drug + age + allergy + pregnancy +
/// renal/hepatic) sorted by severity (worst first).
pub fn check_new_drug(new_drug: &str, ctx: &PatientCtx) -> Vec<Conflict> {
    let canon_drug = canon(new_drug);
    let mut out = Vec::new();

    out.extend(check_drug_drug(new_drug, ctx));
    if let Some(c) = check_age(&canon_drug, ctx) {
        out.push(c);
    }
    out.extend(check_allergy(&canon_drug, ctx));
    out.extend(check_pregnancy(&canon_drug, ctx));
    out.extend(check_renal_hepatic(&canon_drug, ctx));

    out.sort_by_key(|c| c.severity.order());
    out
}

/// Check an entire regimen (every pair + every drug against patient context).
pub fn check_regimen(drugs: &[String], ctx: &PatientCtx) -> Vec<Conflict> {
    let mut out = Vec::new();

    // Drug-drug among all drugs (not just one new vs existing).
    let interactions = drugdrug_check(drugs);
    for i in interactions {
        if !matches!(i.severity, Severity::NoKnown) {
            out.push(Conflict {
                kind: ConflictKind::DrugDrug,
                drug: i.drug_a.clone(),
                severity: i.severity,
                message: format!("{} | {}", i.mechanism, i.recommendation),
                source: i.source,
                other_drug: Some(i.drug_b),
            });
        }
    }

    // Per-drug: age, allergy, pregnancy, renal/hepatic.
    for d in drugs {
        let canon_d = canon(d);
        if let Some(c) = check_age(&canon_d, ctx) {
            out.push(c);
        }
        out.extend(check_allergy(&canon_d, ctx));
        out.extend(check_pregnancy(&canon_d, ctx));
        out.extend(check_renal_hepatic(&canon_d, ctx));
    }

    out.sort_by_key(|c| c.severity.order());
    out
}

// ── tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx() -> PatientCtx {
        PatientCtx::default()
    }

    #[test]
    fn aspirin_in_child_blocked() {
        let mut c = ctx();
        c.age_years = Some(10);
        let confs = check_new_drug("aspirin", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Age));
        assert!(confs[0].severity == Severity::Contraindicated);
    }

    #[test]
    fn aspirin_in_adult_no_age_conflict() {
        let mut c = ctx();
        c.age_years = Some(40);
        let confs = check_new_drug("aspirin", &c);
        // Maybe drug-drug exists if existing_meds has warfarin etc; here
        // existing_meds is empty so age should not flag.
        assert!(confs.iter().all(|x| x.kind != ConflictKind::Age));
    }

    #[test]
    fn penicillin_allergy_blocks_amoxicillin() {
        let mut c = ctx();
        c.allergies = vec!["penicillin".into()];
        let confs = check_new_drug("amoxicillin", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Allergy
            && x.severity == Severity::Contraindicated));
    }

    #[test]
    fn penicillin_allergy_warns_cephalexin() {
        let mut c = ctx();
        c.allergies = vec!["penicillin".into()];
        let confs = check_new_drug("cephalexin", &c);
        let allergy = confs.iter().find(|x| x.kind == ConflictKind::Allergy);
        assert!(allergy.is_some(), "expected cephalosporin cross-react");
        assert_eq!(allergy.unwrap().severity, Severity::Major);
    }

    #[test]
    fn warfarin_in_pregnancy_blocked() {
        let mut c = ctx();
        c.pregnant = true;
        let confs = check_new_drug("warfarin", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Pregnancy
            && x.severity == Severity::Contraindicated));
    }

    #[test]
    fn warfarin_no_pregnancy_when_not_pregnant() {
        let c = ctx();
        let confs = check_new_drug("warfarin", &c);
        assert!(confs.iter().all(|x| x.kind != ConflictKind::Pregnancy));
    }

    #[test]
    fn metformin_with_ckd_flagged() {
        let mut c = ctx();
        c.conditions = vec!["CKD stage 4".into()];
        let confs = check_new_drug("metformin", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Renal));
    }

    #[test]
    fn paracetamol_with_cirrhosis_flagged() {
        let mut c = ctx();
        c.conditions = vec!["cirrhosis Child-Pugh B".into()];
        let confs = check_new_drug("paracetamol", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Hepatic));
    }

    #[test]
    fn warfarin_plus_ibuprofen_drug_drug() {
        let mut c = ctx();
        c.existing_meds = vec!["warfarin".into()];
        let confs = check_new_drug("ibuprofen", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::DrugDrug
            && x.severity == Severity::Major));
    }

    #[test]
    fn check_regimen_combines_pair_and_per_drug_rules() {
        let mut c = ctx();
        c.age_years = Some(10);
        c.pregnant = false;
        let confs = check_regimen(
            &vec!["aspirin".into(), "warfarin".into(), "ibuprofen".into()],
            &c,
        );
        // Expect at least 1 Age (aspirin <16) + at least 1 DrugDrug
        // (warfarin × ibuprofen).
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Age));
        assert!(confs.iter().any(|x| x.kind == ConflictKind::DrugDrug));
        // Sorted: contraindicated/major first.
        assert!(confs[0].severity.order() <= 1);
    }

    #[test]
    fn no_conflicts_for_safe_combination() {
        let mut c = ctx();
        c.age_years = Some(40);
        let confs = check_new_drug("paracetamol", &c);
        // No age, no allergy, not pregnant, no conditions, no existing meds.
        assert!(confs.is_empty());
    }

    #[test]
    fn sulfa_allergy_blocks_co_trimoxazole() {
        let mut c = ctx();
        c.allergies = vec!["sulfa drugs".into()];
        let confs = check_new_drug("trimethoprim_sulfamethoxazole", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Allergy));
    }

    #[test]
    fn nsaid_allergy_blocks_ibuprofen() {
        let mut c = ctx();
        c.allergies = vec!["NSAID".into()];
        let confs = check_new_drug("ibuprofen", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Allergy));
    }

    #[test]
    fn elderly_diphenhydramine_warned() {
        let mut c = ctx();
        c.age_years = Some(78);
        let confs = check_new_drug("diphenhydramine", &c);
        assert!(confs.iter().any(|x| x.kind == ConflictKind::Age));
    }
}
