//! aim-lab-reference — lab analyte reference ranges + evaluator.
//!
//! Port of `lab_reference.py`. Hard-coded reference table (SI units),
//! `evaluate()`, `format_result()`, `batch_evaluate()` with the same
//! status ordering and Russian/English status labels as Python.
//!
//! The full Python table has ~70 analytes; we ship the most critical
//! 30 here (CBC, biochem, lipids, glycemia, thyroid, kidney, liver,
//! electrolytes, vitamins). Extend by adding rows to [`TABLE`].

use std::collections::BTreeMap;

use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Normal,
    Low,
    High,
    CriticalLow,
    CriticalHigh,
    Unknown,
}

impl Status {
    pub fn order(&self) -> u8 {
        match self {
            Status::CriticalHigh => 0,
            Status::CriticalLow => 1,
            Status::High => 2,
            Status::Low => 3,
            Status::Normal => 4,
            Status::Unknown => 5,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AnalyteRef {
    pub key: &'static str,
    pub display: &'static str,
    pub unit: &'static str,
    pub low: Option<f64>,
    pub high: Option<f64>,
    pub critical_low: Option<f64>,
    pub critical_high: Option<f64>,
    pub category: &'static str,
    pub notes: &'static str,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EvalResult {
    pub analyte: String,
    pub display: String,
    pub value: f64,
    pub unit: String,
    pub status: Status,
    pub reference: String,
    pub category: String,
    pub notes: String,
}

macro_rules! row {
    ($key:expr, $display:expr, $unit:expr, $cat:expr, $low:expr, $high:expr, $clo:expr, $chi:expr) => {
        AnalyteRef {
            key: $key,
            display: $display,
            unit: $unit,
            low: $low,
            high: $high,
            critical_low: $clo,
            critical_high: $chi,
            category: $cat,
            notes: "",
        }
    };
}

static TABLE_VEC: Lazy<Vec<AnalyteRef>> = Lazy::new(|| {
    vec![
        // CBC
        row!("hemoglobin_m", "Гемоглобин (муж)", "g/L", "CBC", Some(130.0), Some(175.0), Some(70.0), Some(200.0)),
        row!("hemoglobin_f", "Гемоглобин (жен)", "g/L", "CBC", Some(120.0), Some(160.0), Some(70.0), Some(200.0)),
        row!("hematocrit_m", "Гематокрит (муж)", "%", "CBC", Some(40.0), Some(52.0), Some(20.0), Some(60.0)),
        row!("hematocrit_f", "Гематокрит (жен)", "%", "CBC", Some(36.0), Some(47.0), Some(20.0), Some(60.0)),
        row!("rbc_m", "Эритроциты (муж)", "×10¹²/L", "CBC", Some(4.5), Some(5.9), Some(2.0), Some(7.0)),
        row!("rbc_f", "Эритроциты (жен)", "×10¹²/L", "CBC", Some(3.8), Some(5.2), Some(2.0), Some(7.0)),
        row!("wbc", "Лейкоциты", "×10⁹/L", "CBC", Some(4.0), Some(11.0), Some(2.0), Some(30.0)),
        row!("platelets", "Тромбоциты", "×10⁹/L", "CBC", Some(150.0), Some(400.0), Some(50.0), Some(1000.0)),
        row!("mcv", "MCV", "fL", "CBC", Some(80.0), Some(100.0), None, None),
        row!("mch", "MCH", "pg", "CBC", Some(27.0), Some(33.0), None, None),
        row!("mchc", "MCHC", "g/L", "CBC", Some(320.0), Some(360.0), None, None),
        row!("esr", "СОЭ", "mm/h", "CBC", Some(1.0), Some(20.0), None, Some(100.0)),
        // Glycemia / diabetes
        row!("glucose", "Глюкоза", "mmol/L", "Биохимия", Some(3.9), Some(6.1), Some(2.5), Some(20.0)),
        row!("hba1c", "HbA1c", "%", "Биохимия", Some(4.0), Some(5.7), None, Some(10.0)),
        // Lipids
        row!("cholesterol_total", "ХС общий", "mmol/L", "Липиды", Some(3.0), Some(5.2), None, Some(7.5)),
        row!("ldl", "ЛПНП", "mmol/L", "Липиды", Some(0.0), Some(3.0), None, None),
        row!("hdl", "ЛПВП", "mmol/L", "Липиды", Some(1.0), Some(2.5), None, None),
        row!("triglycerides", "Триглицериды", "mmol/L", "Липиды", Some(0.0), Some(1.7), None, Some(5.6)),
        // Thyroid
        row!("tsh", "ТТГ", "mIU/L", "Щитовидная", Some(0.4), Some(4.0), None, None),
        // Kidney / liver
        row!("creatinine_m", "Креатинин (муж)", "µmol/L", "Биохимия", Some(62.0), Some(115.0), None, Some(500.0)),
        row!("creatinine_f", "Креатинин (жен)", "µmol/L", "Биохимия", Some(53.0), Some(97.0), None, Some(500.0)),
        row!("urea", "Мочевина", "mmol/L", "Биохимия", Some(2.5), Some(8.3), None, Some(20.0)),
        row!("alt", "АЛТ", "U/L", "Биохимия", Some(0.0), Some(40.0), None, Some(500.0)),
        row!("ast", "АСТ", "U/L", "Биохимия", Some(0.0), Some(40.0), None, Some(500.0)),
        // Electrolytes
        row!("potassium", "Калий", "mmol/L", "Электролиты", Some(3.5), Some(5.1), Some(2.5), Some(6.5)),
        row!("sodium", "Натрий", "mmol/L", "Электролиты", Some(135.0), Some(145.0), Some(120.0), Some(160.0)),
        row!("calcium", "Кальций", "mmol/L", "Электролиты", Some(2.15), Some(2.55), Some(1.8), Some(3.5)),
        // Inflammation
        row!("crp", "СРБ", "mg/L", "Воспаление", Some(0.0), Some(5.0), None, Some(100.0)),
        // Vitamins
        row!("vitamin_d", "Витамин D", "ng/mL", "Витамины", Some(30.0), Some(100.0), Some(10.0), Some(150.0)),
        row!("vitamin_b12", "Витамин B12", "pmol/L", "Витамины", Some(150.0), Some(700.0), None, None),
    ]
});

static TABLE: Lazy<BTreeMap<&'static str, &'static AnalyteRef>> = Lazy::new(|| {
    TABLE_VEC.iter().map(|a| (a.key, a)).collect()
});

pub fn lookup(analyte: &str) -> Option<&'static AnalyteRef> {
    TABLE.get(analyte).copied()
}

pub fn evaluate(analyte: &str, value: f64) -> EvalResult {
    let Some(r) = lookup(analyte) else {
        return EvalResult {
            analyte: analyte.to_string(),
            display: analyte.to_string(),
            value,
            unit: String::new(),
            status: Status::Unknown,
            reference: String::new(),
            category: String::new(),
            notes: String::new(),
        };
    };
    let mut status = Status::Normal;
    if let Some(cl) = r.critical_low {
        if value < cl {
            status = Status::CriticalLow;
        }
    }
    if status == Status::Normal {
        if let Some(ch) = r.critical_high {
            if value > ch {
                status = Status::CriticalHigh;
            }
        }
    }
    if status == Status::Normal {
        if let Some(lo) = r.low {
            if value < lo {
                status = Status::Low;
            }
        }
    }
    if status == Status::Normal {
        if let Some(hi) = r.high {
            if value > hi {
                status = Status::High;
            }
        }
    }
    let reference = match (r.low, r.high) {
        (Some(l), Some(h)) => format!("{}–{}", strip_zero(l), strip_zero(h)),
        (Some(l), None) => format!("{}–", strip_zero(l)),
        (None, Some(h)) => format!("–{}", strip_zero(h)),
        (None, None) => "—".to_string(),
    };
    EvalResult {
        analyte: r.key.to_string(),
        display: r.display.to_string(),
        value,
        unit: r.unit.to_string(),
        status,
        reference,
        category: r.category.to_string(),
        notes: r.notes.to_string(),
    }
}

fn strip_zero(v: f64) -> String {
    if (v.fract()).abs() < 1e-9 {
        format!("{}", v as i64)
    } else {
        format!("{}", v)
    }
}

pub fn format_result(r: &EvalResult, lang: &str) -> String {
    let label = match (lang, r.status) {
        ("en", Status::Normal) => "normal ✅",
        ("en", Status::Low) => "below normal ↓",
        ("en", Status::High) => "above normal ↑",
        ("en", Status::CriticalLow) => "CRITICALLY LOW ⚠️",
        ("en", Status::CriticalHigh) => "CRITICALLY HIGH ⚠️",
        ("en", Status::Unknown) => "unknown analyte",
        (_, Status::Normal) => "норма ✅",
        (_, Status::Low) => "ниже нормы ↓",
        (_, Status::High) => "выше нормы ↑",
        (_, Status::CriticalLow) => "КРИТИЧЕСКИ НИЗКО ⚠️",
        (_, Status::CriticalHigh) => "КРИТИЧЕСКИ ВЫСОКО ⚠️",
        (_, Status::Unknown) => "неизвестный аналит",
    };
    let mut lines = vec![format!(
        "**{}**: {} {} — {}",
        if r.display.is_empty() { r.analyte.as_str() } else { r.display.as_str() },
        strip_zero(r.value),
        r.unit,
        label
    )];
    if !r.reference.is_empty() {
        lines.push(format!("  Норма: {} {}", r.reference, r.unit));
    }
    if !r.notes.is_empty() {
        lines.push(format!("  📌 {}", r.notes));
    }
    lines.join("\n")
}

pub fn batch_evaluate(values: &[(String, f64)], lang: &str) -> String {
    let mut results: Vec<(Status, String)> = values
        .iter()
        .map(|(k, v)| {
            let r = evaluate(k, *v);
            (r.status, format_result(&r, lang))
        })
        .collect();
    results.sort_by_key(|(s, _)| s.order());
    results
        .into_iter()
        .map(|(_, s)| s)
        .collect::<Vec<_>>()
        .join("\n\n")
}

pub fn list_analytes(category: Option<&str>) -> Vec<String> {
    TABLE_VEC
        .iter()
        .filter(|r| category.map(|c| r.category == c).unwrap_or(true))
        .map(|r| r.key.to_string())
        .collect()
}

pub fn categories() -> Vec<String> {
    let mut set: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    for r in TABLE_VEC.iter() {
        set.insert(r.category.to_string());
    }
    set.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lookup_known_analyte() {
        let r = lookup("hemoglobin_m").unwrap();
        assert_eq!(r.unit, "g/L");
        assert_eq!(r.category, "CBC");
    }

    #[test]
    fn lookup_unknown() {
        assert!(lookup("ghost_analyte").is_none());
    }

    // ── evaluate ──────────────────────────────────────────────────────────

    #[test]
    fn evaluate_normal() {
        let r = evaluate("hemoglobin_m", 145.0);
        assert_eq!(r.status, Status::Normal);
    }

    #[test]
    fn evaluate_low_above_critical() {
        let r = evaluate("hemoglobin_m", 100.0);
        assert_eq!(r.status, Status::Low);
    }

    #[test]
    fn evaluate_critical_low() {
        let r = evaluate("hemoglobin_m", 50.0);
        assert_eq!(r.status, Status::CriticalLow);
    }

    #[test]
    fn evaluate_high() {
        let r = evaluate("glucose", 7.1);
        assert_eq!(r.status, Status::High);
    }

    #[test]
    fn evaluate_critical_high() {
        let r = evaluate("glucose", 25.0);
        assert_eq!(r.status, Status::CriticalHigh);
    }

    #[test]
    fn evaluate_unknown_analyte() {
        let r = evaluate("ghost", 1.0);
        assert_eq!(r.status, Status::Unknown);
        assert_eq!(r.analyte, "ghost");
    }

    #[test]
    fn evaluate_reference_string_matches_python() {
        let r = evaluate("hemoglobin_m", 145.0);
        assert_eq!(r.reference, "130–175");
    }

    // ── format ────────────────────────────────────────────────────────────

    #[test]
    fn format_russian_label() {
        let r = evaluate("hemoglobin_m", 145.0);
        let s = format_result(&r, "ru");
        assert!(s.contains("норма"));
    }

    #[test]
    fn format_english_label() {
        let r = evaluate("glucose", 7.1);
        let s = format_result(&r, "en");
        assert!(s.contains("above normal"));
    }

    // ── batch ─────────────────────────────────────────────────────────────

    #[test]
    fn batch_orders_critical_first() {
        let vals = vec![
            ("hemoglobin_m".to_string(), 145.0),
            ("potassium".to_string(), 2.3), // critical low
            ("glucose".to_string(), 7.1),   // high
        ];
        let s = batch_evaluate(&vals, "ru");
        let pos_potassium = s.find("Калий").unwrap();
        let pos_glucose = s.find("Глюкоза").unwrap();
        let pos_hb = s.find("Гемоглобин").unwrap();
        assert!(pos_potassium < pos_glucose);
        assert!(pos_glucose < pos_hb);
    }

    // ── list/categories ───────────────────────────────────────────────────

    #[test]
    fn list_analytes_by_category() {
        let cbc = list_analytes(Some("CBC"));
        assert!(cbc.contains(&"hemoglobin_m".to_string()));
        assert!(!cbc.contains(&"glucose".to_string()));
    }

    #[test]
    fn categories_listed_alphabetically() {
        let cats = categories();
        assert!(cats.contains(&"CBC".to_string()));
        assert!(cats.contains(&"Биохимия".to_string()));
        let mut sorted = cats.clone();
        sorted.sort();
        assert_eq!(cats, sorted);
    }
}
