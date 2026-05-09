//! aim-interactions — drug-drug / drug-supplement interaction screen (v0.1).
//!
//! Port of `agents/interactions.py`. Hand-curated static table covering
//! the most common integrative-medicine pairs encountered in clinical
//! practice. Sources are PMID-verified or point to FDA DailyMed / RxNav.
//!
//! Decision support only — clinician judgment required.

use std::collections::{BTreeMap, BTreeSet};

use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};

pub const DISCLAIMER: &str =
    "AIM drug-interaction database is a curated stub (~30 high-impact \
pairs). NOT a replacement for RxNav / DrugBank / FDA DailyMed. \
Always cross-check before prescribing. AIM v0.1, 2026-04-21.";

// ── severity ────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Contraindicated,
    Major,
    Moderate,
    Minor,
    NoKnown,
}

impl Severity {
    pub fn order(&self) -> u8 {
        match self {
            Self::Contraindicated => 0,
            Self::Major => 1,
            Self::Moderate => 2,
            Self::Minor => 3,
            Self::NoKnown => 4,
        }
    }

    pub fn as_lower(&self) -> &'static str {
        match self {
            Self::Contraindicated => "contraindicated",
            Self::Major => "major",
            Self::Moderate => "moderate",
            Self::Minor => "minor",
            Self::NoKnown => "no_known",
        }
    }

    pub fn as_upper(&self) -> String {
        self.as_lower().to_uppercase()
    }
}

// ── interaction record ─────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Interaction {
    pub drug_a: String,
    pub drug_b: String,
    pub severity: Severity,
    pub mechanism: String,
    pub recommendation: String,
    pub source: String,
}

impl Interaction {
    pub fn disclaimer(&self) -> &'static str {
        DISCLAIMER
    }
}

// ── canonicalisation ───────────────────────────────────────────────────────

static SYNONYMS: Lazy<BTreeMap<&'static str, &'static str>> = Lazy::new(|| {
    let mut m = BTreeMap::new();
    m.insert("aspirin", "acetylsalicylic_acid");
    m.insert("asa", "acetylsalicylic_acid");
    m.insert("nsaid", "ibuprofen");
    m.insert("advil", "ibuprofen");
    m.insert("motrin", "ibuprofen");
    m.insert("tylenol", "paracetamol");
    m.insert("acetaminophen", "paracetamol");
    m.insert("coumadin", "warfarin");
    m.insert("glucophage", "metformin");
    m.insert("sprycel", "dasatinib");
    m.insert("vitamin k", "vitamin_k");
    m.insert("vit k", "vitamin_k");
    m.insert("vitamin e", "vitamin_e");
    m.insert("vit e", "vitamin_e");
    m.insert("st johns wort", "st_johns_wort");
    m.insert("st. john's wort", "st_johns_wort");
    m.insert("hypericum", "st_johns_wort");
    m.insert("fish oil", "omega3");
    m.insert("omega 3", "omega3");
    m.insert("omega-3", "omega3");
    m.insert("garlic", "allium_sativum");
    m.insert("ginkgo", "ginkgo_biloba");
    m
});

/// Canonicalise a drug/supplement name to lookup-key form.
pub fn canon(name: &str) -> String {
    if name.is_empty() {
        return String::new();
    }
    let lower = name.trim().to_lowercase().replace('-', " ");
    // collapse runs of whitespace
    let collapsed: String = lower.split_whitespace().collect::<Vec<_>>().join(" ");
    if let Some(&v) = SYNONYMS.get(collapsed.as_str()) {
        return v.to_string();
    }
    collapsed.replace(' ', "_")
}

// ── static table ───────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct Entry {
    severity: Severity,
    mechanism: &'static str,
    recommendation: &'static str,
    source: &'static str,
}

fn key(a: &str, b: &str) -> (String, String) {
    if a < b {
        (a.into(), b.into())
    } else {
        (b.into(), a.into())
    }
}

static TABLE: Lazy<BTreeMap<(String, String), Entry>> = Lazy::new(|| {
    let mut t: BTreeMap<(String, String), Entry> = BTreeMap::new();
    let pairs: &[(&str, &str, Severity, &str, &str, &str)] = &[
        // Senolytic combo
        ("dasatinib", "quercetin", Severity::Minor,
            "Senolytic combination; quercetin is a mild CYP3A4 inhibitor and may marginally increase dasatinib exposure. Clinically acceptable in single-dose / monthly pulsed protocols.",
            "Acceptable as intermittent senolytic pulse (Tkemaladze & Apkhazava 2019; Tkemaladze 2023). Avoid continuous daily co-administration; monitor CBC and LFTs if repeated.",
            "PMID:38510429"),
        // Anticoagulants
        ("warfarin", "ibuprofen", Severity::Major,
            "Additive bleeding risk: NSAID inhibits platelet aggregation and can cause GI mucosal injury while warfarin impairs coagulation.",
            "Avoid routine co-administration. If NSAID is essential, prefer shortest course + PPI; increase INR monitoring frequency.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        ("warfarin", "acetylsalicylic_acid", Severity::Major,
            "Additive antiplatelet + anticoagulant effect.",
            "Combine only for specific cardiology indications (e.g. mechanical valve + ACS) with close INR and bleeding surveillance.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        ("warfarin", "vitamin_k", Severity::Major,
            "Vitamin K directly antagonises warfarin's mechanism.",
            "Keep dietary/supplemental vitamin K intake stable. Avoid supplemental doses unless reversing over-anticoagulation.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        ("warfarin", "st_johns_wort", Severity::Major,
            "St John's wort induces CYP2C9 and CYP3A4, lowering warfarin plasma levels and INR — thrombosis risk.",
            "Avoid combination. If unavoidable, monitor INR weekly.",
            "PMID:14748826"),
        ("warfarin", "ginkgo_biloba", Severity::Moderate,
            "Ginkgo inhibits platelet-activating factor; additive bleeding.",
            "Avoid routine combination; monitor for bruising/bleeding.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        ("warfarin", "omega3", Severity::Moderate,
            "High-dose fish oil (>3 g/d) may prolong bleeding time.",
            "Doses <=1 g/d generally safe; above that, monitor INR and bleeding.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        ("warfarin", "allium_sativum", Severity::Moderate,
            "Garlic has mild antiplatelet activity; additive bleeding.",
            "Limit high-dose garlic extracts; monitor INR.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        ("warfarin", "vitamin_e", Severity::Moderate,
            "High-dose vitamin E (>400 IU/d) can potentiate anticoagulation.",
            "Keep vitamin E <400 IU/d; monitor INR if higher.",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=warfarin"),
        // Psychotropics
        ("ssri", "maoi", Severity::Contraindicated,
            "Serotonin syndrome via additive serotonergic activity.",
            "Contraindicated. Observe washout: >=14 d off MAOI before SSRI; >=5 wk off fluoxetine before MAOI.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("fluoxetine", "maoi", Severity::Contraindicated,
            "Serotonin syndrome; fluoxetine has long half-life.",
            "Contraindicated. Require >=5 weeks washout.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("sertraline", "maoi", Severity::Contraindicated,
            "Serotonin syndrome.",
            "Contraindicated. >=14 d washout both directions.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ssri", "tramadol", Severity::Major,
            "Additive serotonergic effect; lowered seizure threshold.",
            "Prefer non-serotonergic analgesic; if combined, low dose + monitor.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ssri", "st_johns_wort", Severity::Major,
            "Additive serotonergic activity → serotonin syndrome.",
            "Avoid combination.",
            "PMID:14748826"),
        // Cardio / renal
        ("ace_inhibitor", "potassium", Severity::Major,
            "Hyperkalaemia: ACEi reduces aldosterone-mediated K+ excretion.",
            "Avoid K+ supplements unless hypokalaemic; monitor serum K+.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ace_inhibitor", "spironolactone", Severity::Major,
            "Additive hyperkalaemia (both retain K+).",
            "Monitor K+ and creatinine every 1–2 wk after initiation.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ace_inhibitor", "nsaid", Severity::Moderate,
            "NSAID blunts ACEi antihypertensive effect; risk of AKI.",
            "Avoid chronic NSAID; if essential, monitor BP + creatinine.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ace_inhibitor", "ibuprofen", Severity::Moderate,
            "NSAID blunts ACEi antihypertensive effect; risk of AKI.",
            "Avoid chronic NSAID; if essential, monitor BP + creatinine.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("digoxin", "amiodarone", Severity::Major,
            "Amiodarone raises digoxin levels ~2×.",
            "Halve digoxin dose; monitor digoxin level + ECG.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("statin", "clarithromycin", Severity::Major,
            "CYP3A4 inhibition → statin rhabdomyolysis risk.",
            "Hold statin during macrolide course, or switch to azithromycin.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("simvastatin", "grapefruit", Severity::Major,
            "Intestinal CYP3A4 inhibition → simvastatin AUC up to 3–7×.",
            "Avoid grapefruit; or switch to pravastatin/rosuvastatin.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // Metabolic
        ("metformin", "alcohol", Severity::Moderate,
            "Acute/binge alcohol raises lactic acidosis risk.",
            "Avoid binge drinking; moderate intake acceptable with meals.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("metformin", "iodinated_contrast", Severity::Major,
            "Contrast-induced AKI + metformin accumulation → lactic acidosis.",
            "Hold metformin at time of contrast; resume 48 h after, if eGFR stable.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("insulin", "alcohol", Severity::Moderate,
            "Alcohol impairs hepatic gluconeogenesis → delayed hypoglycaemia.",
            "Advise food with alcohol; check glucose before sleep.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("levothyroxine", "calcium", Severity::Moderate,
            "Calcium binds T4 in gut, reduces absorption ~30%.",
            "Separate doses by >=4 h.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("levothyroxine", "iron", Severity::Moderate,
            "Iron binds T4 in gut, reduces absorption.",
            "Separate doses by >=4 h.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // Oncology / senolytics
        ("dasatinib", "chemotherapy", Severity::Major,
            "Additive myelosuppression; CYP3A4-mediated PK interactions with many cytotoxic regimens.",
            "Do not combine without oncologist supervision.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("senolytic", "chemotherapy", Severity::Major,
            "Unknown effect on tumour clearance; potential additive toxicity.",
            "Defer elective senolytic protocols until chemotherapy washout (>=4 wk) unless on clinical trial.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("dasatinib", "warfarin", Severity::Moderate,
            "Dasatinib may affect CYP3A4 and platelet function.",
            "Monitor INR and platelets during senolytic pulse.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // Common supplement pairs
        ("st_johns_wort", "oral_contraceptive", Severity::Major,
            "CYP3A4 induction reduces contraceptive levels; pregnancy risk.",
            "Use alternative contraception or stop St John's wort.",
            "PMID:14748826"),
        ("grapefruit", "amiodarone", Severity::Major,
            "CYP3A4 inhibition raises amiodarone AUC.",
            "Avoid grapefruit with amiodarone.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("quercetin", "warfarin", Severity::Moderate,
            "In-vitro CYP2C9 inhibition; possible INR rise at high doses.",
            "Monitor INR if quercetin >500 mg/d is added.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("omega3", "acetylsalicylic_acid", Severity::Minor,
            "Mild additive antiplatelet effect at high fish-oil doses.",
            "Clinically insignificant at <1 g/d fish oil.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ginkgo_biloba", "acetylsalicylic_acid", Severity::Moderate,
            "Additive antiplatelet effect.",
            "Avoid in patients with bleeding history; monitor otherwise.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // ── DOAC + drug interactions (extension v0.2, 2026-05-08) ──────────
        ("apixaban", "ketoconazole", Severity::Major,
            "Strong CYP3A4 + P-gp inhibition raises apixaban exposure 2-fold.",
            "Avoid combination; switch antifungal to fluconazole/terbinafine.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("rivaroxaban", "ketoconazole", Severity::Major,
            "Strong CYP3A4 + P-gp inhibition raises rivaroxaban exposure ~160%.",
            "Avoid combination.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("dabigatran", "ketoconazole", Severity::Major,
            "P-gp inhibition raises dabigatran exposure.",
            "Reduce dabigatran dose or avoid.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("apixaban", "rifampin", Severity::Major,
            "CYP3A4 + P-gp induction lowers apixaban concentration → thrombosis risk.",
            "Avoid combination.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("rivaroxaban", "rifampin", Severity::Major,
            "CYP3A4 + P-gp induction lowers rivaroxaban exposure ~50%.",
            "Avoid combination.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("apixaban", "ibuprofen", Severity::Major,
            "Additive bleeding risk (NSAID + DOAC).",
            "Avoid chronic NSAID; if essential, prefer shortest course + PPI; assess bleeding risk.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("rivaroxaban", "ibuprofen", Severity::Major,
            "Additive bleeding risk (NSAID + DOAC).",
            "Avoid chronic NSAID; if essential, prefer shortest course + PPI.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // ── Antibiotic + statin / cardiac ──────────────────────────────────
        ("erythromycin", "simvastatin", Severity::Major,
            "Strong CYP3A4 inhibition → simvastatin rhabdomyolysis risk.",
            "Hold simvastatin during macrolide course.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("erythromycin", "atorvastatin", Severity::Moderate,
            "CYP3A4 inhibition increases atorvastatin levels.",
            "Limit atorvastatin dose to 20 mg/d during course.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("clarithromycin", "warfarin", Severity::Major,
            "CYP3A4 inhibition + gut flora disruption → INR rise.",
            "Monitor INR every 3 days during course; expect dose reduction.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("clarithromycin", "amiodarone", Severity::Major,
            "QT prolongation additive; torsades risk.",
            "Avoid combination; consider azithromycin (lower QT effect).",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ciprofloxacin", "warfarin", Severity::Major,
            "CYP1A2/3A4 inhibition + altered gut flora → INR rise.",
            "Monitor INR every 2-3 days during course.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("metronidazole", "warfarin", Severity::Major,
            "CYP2C9 inhibition prolongs warfarin half-life → INR rise.",
            "Monitor INR every 2-3 days; reduce warfarin dose ~30%.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("trimethoprim_sulfamethoxazole", "warfarin", Severity::Major,
            "CYP2C9 inhibition → INR rise within days.",
            "Monitor INR closely; consider antibiotic alternative.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("fluconazole", "warfarin", Severity::Major,
            "CYP2C9 inhibition; INR rise even with single dose.",
            "Monitor INR; reduce warfarin dose 25-50% during course.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // ── Cardiology depth ──────────────────────────────────────────────
        ("amiodarone", "warfarin", Severity::Major,
            "CYP2C9/3A4 inhibition by amiodarone; INR rises over weeks.",
            "Reduce warfarin dose 30-50% on amiodarone start; monitor INR weekly initially.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("amiodarone", "simvastatin", Severity::Major,
            "CYP3A4 inhibition + risk of myopathy.",
            "Limit simvastatin to 20 mg/d.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("verapamil", "simvastatin", Severity::Moderate,
            "CYP3A4 inhibition increases statin AUC.",
            "Limit simvastatin to 10 mg/d.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("diltiazem", "simvastatin", Severity::Moderate,
            "CYP3A4 inhibition increases statin AUC.",
            "Limit simvastatin to 10 mg/d.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        // ── Psychotropic / opioid depth ───────────────────────────────────
        ("fluoxetine", "tramadol", Severity::Major,
            "Serotonin syndrome + lowered seizure threshold; CYP2D6 inhibition.",
            "Avoid combination; use non-serotonergic analgesic.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("sertraline", "tramadol", Severity::Major,
            "Serotonin syndrome risk.",
            "Avoid; use morphine/oxycodone if opioid required.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("escitalopram", "tramadol", Severity::Major,
            "Serotonin syndrome risk.",
            "Avoid combination.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("ssri", "warfarin", Severity::Moderate,
            "Increased bleeding risk via platelet serotonin uptake disruption.",
            "Monitor for bruising/GI bleed; consider PPI prophylaxis.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("benzodiazepine", "opioid", Severity::Major,
            "Additive CNS/respiratory depression; FDA black-box warning.",
            "Avoid combination unless no alternative; if essential, lowest doses + naloxone education.",
            "FDA Drug Safety Communication 2016"),
        ("benzodiazepine", "morphine", Severity::Major,
            "Additive CNS/respiratory depression.",
            "FDA black-box; avoid if possible.",
            "FDA Drug Safety Communication 2016"),
        ("benzodiazepine", "oxycodone", Severity::Major,
            "Additive CNS/respiratory depression.",
            "FDA black-box; avoid if possible.",
            "FDA Drug Safety Communication 2016"),
        ("alprazolam", "morphine", Severity::Major,
            "Additive CNS/respiratory depression.",
            "FDA black-box; avoid combination.",
            "FDA Drug Safety Communication 2016"),
        // ── PPI + drug interactions ───────────────────────────────────────
        ("omeprazole", "clopidogrel", Severity::Moderate,
            "CYP2C19 inhibition reduces clopidogrel active metabolite formation.",
            "Prefer pantoprazole (less CYP2C19 inhibition) or H2 blocker.",
            "FDA Drug Safety Communication 2009"),
        ("esomeprazole", "clopidogrel", Severity::Moderate,
            "CYP2C19 inhibition reduces clopidogrel activation.",
            "Prefer pantoprazole.",
            "FDA Drug Safety Communication 2009"),
        // ── Diabetes ──────────────────────────────────────────────────────
        ("metformin", "topiramate", Severity::Moderate,
            "Topiramate causes metabolic acidosis; risk increased with metformin.",
            "Monitor bicarbonate; consider alternative.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("insulin", "beta_blocker", Severity::Moderate,
            "Beta-blockers mask hypoglycaemia awareness symptoms.",
            "Counsel patient; consider cardioselective beta-blocker.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
        ("metformin", "cimetidine", Severity::Moderate,
            "Cimetidine reduces metformin clearance ~40%.",
            "Use famotidine or ranitidine; or reduce metformin.",
            "https://dailymed.nlm.nih.gov/dailymed/"),
    ];
    for (a, b, sev, mech, rec, src) in pairs {
        t.insert(
            key(a, b),
            Entry {
                severity: *sev,
                mechanism: mech,
                recommendation: rec,
                source: src,
            },
        );
    }
    t
});

// ── public API ─────────────────────────────────────────────────────────────

/// Look up a single pair. Same drug twice or empty input → `NoKnown`.
pub fn check_interaction(drug_a: &str, drug_b: &str) -> Interaction {
    let a = canon(drug_a);
    let b = canon(drug_b);

    if a.is_empty() || b.is_empty() {
        return Interaction {
            drug_a: drug_a.into(),
            drug_b: drug_b.into(),
            severity: Severity::NoKnown,
            mechanism: "Empty drug name supplied.".into(),
            recommendation: "Provide valid drug/supplement names.".into(),
            source: String::new(),
        };
    }

    if a == b {
        return Interaction {
            drug_a: drug_a.into(),
            drug_b: drug_b.into(),
            severity: Severity::NoKnown,
            mechanism: "Same drug listed twice.".into(),
            recommendation: "Deduplicate regimen; no self-interaction checked.".into(),
            source: String::new(),
        };
    }

    let k = key(&a, &b);
    if let Some(e) = TABLE.get(&k) {
        Interaction {
            drug_a: drug_a.into(),
            drug_b: drug_b.into(),
            severity: e.severity,
            mechanism: e.mechanism.into(),
            recommendation: e.recommendation.into(),
            source: e.source.into(),
        }
    } else {
        Interaction {
            drug_a: drug_a.into(),
            drug_b: drug_b.into(),
            severity: Severity::NoKnown,
            mechanism: "Pair not in local AIM interaction table.".into(),
            recommendation:
                "No known interaction on record. This does NOT guarantee safety — \
                 consult RxNav / DrugBank / FDA DailyMed for a full check."
                    .into(),
            source: String::new(),
        }
    }
}

/// Check every unordered pair in `drugs`. Sorted contraindicated → no_known.
pub fn check_regimen(drugs: &[String]) -> Vec<Interaction> {
    if drugs.len() < 2 {
        return Vec::new();
    }
    let mut out: Vec<Interaction> = Vec::new();
    for i in 0..drugs.len() {
        for j in (i + 1)..drugs.len() {
            out.push(check_interaction(&drugs[i], &drugs[j]));
        }
    }
    out.sort_by_key(|ix| ix.severity.order());
    out
}

/// Per-language prelude. Body is language-agnostic.
fn prelude(lang: &str) -> &'static str {
    match lang {
        "ru" => "Проверка лекарственных взаимодействий (стенд AIM v0.1)",
        "fr" => "Dépistage des interactions médicamenteuses (AIM v0.1)",
        "es" => "Cribado de interacciones medicamentosas (AIM v0.1)",
        "ar" => "فحص التفاعلات الدوائية (AIM v0.1)",
        "zh" => "药物相互作用筛查 (AIM v0.1)",
        "ka" => "წამლების ურთიერთქმედების სკრინინგი (AIM v0.1)",
        "kz" => "Дәрілік өзара әрекеттесулерді тексеру (AIM v0.1)",
        "da" => "Screening for lægemiddelinteraktioner (AIM v0.1)",
        _ => "Drug-interaction screen (AIM v0.1 stub)",
    }
}

pub fn format_regimen_report(
    interactions: &[Interaction],
    lang: &str,
    include_no_known: bool,
) -> String {
    let mut lines: Vec<String> = vec![
        prelude(lang).to_string(),
        "=".repeat(60),
    ];
    let mut shown = 0usize;
    for ix in interactions {
        if matches!(ix.severity, Severity::NoKnown) && !include_no_known {
            continue;
        }
        shown += 1;
        let src = if ix.source.is_empty() {
            "(none)".to_string()
        } else {
            ix.source.clone()
        };
        lines.push(format!(
            "[{}] {} + {}\n  mechanism      : {}\n  recommendation : {}\n  source         : {}",
            ix.severity.as_upper(),
            ix.drug_a,
            ix.drug_b,
            ix.mechanism,
            ix.recommendation,
            src,
        ));
    }
    if shown == 0 {
        lines.push("No flagged interactions in local table.".into());
    }
    lines.push("─".repeat(60));
    lines.push(DISCLAIMER.into());
    lines.join("\n")
}

/// All canonical drugs known to the table (for diagnostics).
pub fn known_drugs() -> Vec<String> {
    let mut s: BTreeSet<String> = BTreeSet::new();
    for (a, b) in TABLE.keys() {
        s.insert(a.clone());
        s.insert(b.clone());
    }
    s.into_iter().collect()
}

/// Dump every entry in the static table for diagnostic / parity testing.
/// Each tuple is `(drug_a, drug_b, severity, mechanism, recommendation, source)`.
pub fn dump_table() -> Vec<Interaction> {
    TABLE
        .iter()
        .map(|((a, b), e)| Interaction {
            drug_a: a.clone(),
            drug_b: b.clone(),
            severity: e.severity,
            mechanism: e.mechanism.into(),
            recommendation: e.recommendation.into(),
            source: e.source.into(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── canon ──────────────────────────────────────────────────────────────

    #[test]
    fn canon_lower_collapse_underscore() {
        assert_eq!(canon("Aspirin"), "acetylsalicylic_acid");
        assert_eq!(canon("Vit  K"), "vitamin_k");
        assert_eq!(canon("ibuprofen 200 mg"), "ibuprofen_200_mg");
    }

    #[test]
    fn canon_synonyms_resolve_to_canonical() {
        assert_eq!(canon("ASA"), "acetylsalicylic_acid");
        assert_eq!(canon("st johns wort"), "st_johns_wort");
        assert_eq!(canon("st. john's wort"), "st_johns_wort");
        assert_eq!(canon("hypericum"), "st_johns_wort");
        assert_eq!(canon("fish oil"), "omega3");
        assert_eq!(canon("omega-3"), "omega3");
        assert_eq!(canon("ginkgo"), "ginkgo_biloba");
    }

    #[test]
    fn canon_empty_returns_empty() {
        assert_eq!(canon(""), "");
    }

    // ── Severity ───────────────────────────────────────────────────────────

    #[test]
    fn severity_ordering() {
        assert!(Severity::Contraindicated.order() < Severity::Major.order());
        assert!(Severity::Major.order() < Severity::Moderate.order());
        assert!(Severity::Moderate.order() < Severity::Minor.order());
        assert!(Severity::Minor.order() < Severity::NoKnown.order());
    }

    // ── check_interaction ──────────────────────────────────────────────────

    #[test]
    fn check_interaction_known_pair() {
        let i = check_interaction("warfarin", "aspirin");
        assert_eq!(i.severity, Severity::Major);
        assert!(i.mechanism.contains("antiplatelet"));
        assert!(!i.source.is_empty());
    }

    #[test]
    fn check_interaction_order_invariant() {
        let i1 = check_interaction("warfarin", "ibuprofen");
        let i2 = check_interaction("ibuprofen", "warfarin");
        assert_eq!(i1.severity, i2.severity);
        assert_eq!(i1.mechanism, i2.mechanism);
    }

    #[test]
    fn check_interaction_unknown_pair_is_no_known() {
        let i = check_interaction("foo", "bar");
        assert_eq!(i.severity, Severity::NoKnown);
        assert!(i.mechanism.contains("Pair not in local"));
    }

    #[test]
    fn check_interaction_empty_input_is_no_known() {
        assert_eq!(check_interaction("", "warfarin").severity, Severity::NoKnown);
        assert_eq!(check_interaction("warfarin", "").severity, Severity::NoKnown);
    }

    #[test]
    fn check_interaction_same_drug_twice_is_no_known() {
        let i = check_interaction("warfarin", "warfarin");
        assert_eq!(i.severity, Severity::NoKnown);
        assert!(i.mechanism.contains("Same drug listed twice"));
    }

    #[test]
    fn check_interaction_synonyms_match() {
        let i = check_interaction("Coumadin", "ASA");
        assert_eq!(i.severity, Severity::Major);
    }

    #[test]
    fn check_interaction_contraindicated_pair() {
        let i = check_interaction("ssri", "maoi");
        assert_eq!(i.severity, Severity::Contraindicated);
    }

    // ── check_regimen ──────────────────────────────────────────────────────

    #[test]
    fn check_regimen_short_input_returns_empty() {
        assert!(check_regimen(&[]).is_empty());
        assert!(check_regimen(&vec!["warfarin".into()]).is_empty());
    }

    #[test]
    fn check_regimen_sorts_by_severity() {
        let drugs: Vec<String> = vec![
            "metformin".into(),       // unknown
            "warfarin".into(),
            "aspirin".into(),
            "alcohol".into(),         // metformin + alcohol → moderate
            "ssri".into(),
            "maoi".into(),            // ssri + maoi → contraindicated
        ];
        let v = check_regimen(&drugs);
        // first entry should be contraindicated
        assert_eq!(v[0].severity, Severity::Contraindicated);
        // sorted: each next is >= previous
        let mut prev = 0u8;
        for ix in &v {
            assert!(ix.severity.order() >= prev);
            prev = ix.severity.order();
        }
    }

    #[test]
    fn check_regimen_includes_all_pairs() {
        let drugs: Vec<String> = vec!["a".into(), "b".into(), "c".into(), "d".into()];
        let v = check_regimen(&drugs);
        // C(4, 2) = 6
        assert_eq!(v.len(), 6);
    }

    // ── format_regimen_report ──────────────────────────────────────────────

    #[test]
    fn format_report_renders_header_and_disclaimer() {
        let drugs = vec!["warfarin".into(), "aspirin".into()];
        let v = check_regimen(&drugs);
        let r = format_regimen_report(&v, "en", false);
        assert!(r.contains("Drug-interaction screen"));
        assert!(r.contains("[MAJOR]"));
        assert!(r.contains("warfarin"));
        // DISCLAIMER updated 2026-05-07 to match Python parity wording.
        assert!(r.contains("AIM drug-interaction database"));
    }

    #[test]
    fn format_report_localised_prelude() {
        let v: Vec<Interaction> = Vec::new();
        let r = format_regimen_report(&v, "ru", false);
        assert!(r.contains("Проверка лекарственных"));
        let r2 = format_regimen_report(&v, "ka", false);
        assert!(r2.contains("წამლების"));
    }

    #[test]
    fn format_report_hides_no_known_by_default() {
        let drugs = vec!["foo".into(), "bar".into()];
        let v = check_regimen(&drugs);
        let r = format_regimen_report(&v, "en", false);
        assert!(r.contains("No flagged interactions"));
        assert!(!r.contains("[NO_KNOWN]"));
    }

    #[test]
    fn format_report_shows_no_known_when_requested() {
        let drugs = vec!["foo".into(), "bar".into()];
        let v = check_regimen(&drugs);
        let r = format_regimen_report(&v, "en", true);
        assert!(r.contains("[NO_KNOWN]"));
    }

    #[test]
    fn format_report_renders_none_source_marker() {
        let drugs = vec!["foo".into(), "bar".into()];
        let v = check_regimen(&drugs);
        let r = format_regimen_report(&v, "en", true);
        assert!(r.contains("(none)"));
    }

    // ── known_drugs ────────────────────────────────────────────────────────

    #[test]
    fn known_drugs_includes_warfarin() {
        let v = known_drugs();
        assert!(v.contains(&"warfarin".to_string()));
        assert!(v.contains(&"acetylsalicylic_acid".to_string()));
        assert!(v.contains(&"st_johns_wort".to_string()));
    }
}
