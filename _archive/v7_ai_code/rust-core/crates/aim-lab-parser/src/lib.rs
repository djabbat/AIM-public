//! aim-lab-parser — extract analyte values from OCR'd lab reports.
//!
//! Inputs are `*_text.txt` files produced by `agents/intake.py`'s OCR
//! pipeline (tesseract / rapidocr / pymupdf / pdfplumber). The text is
//! polyglot (Russian / English / Georgian) but lab abbreviations are
//! universally Latin (HGB, WBC, MCV, etc.) — that's the anchor we use.
//!
//! Strategy:
//! 1. For each line, find a known abbreviation token.
//! 2. Take the **first numeric value** that follows on the same or next
//!    line (≤ 60 chars away).
//! 3. Optionally capture the unit token (next non-numeric, non-comparison).
//! 4. Emit `Vec<ParsedLab>` — caller decides how to evaluate against
//!    `lab_reference.py` LAB_RANGES.
//!
//! Reference range matching is **out of scope** for this crate; that
//! belongs to `lab_reference.py` (Python) or a future `aim-lab-reference`
//! Rust port. This parser is the structured-data extraction layer only.
//!
//! v0.1 covers ~25 universal CBC + biochem abbreviations; extensible by
//! adding to [`KNOWN_ANALYTES`].

use regex::Regex;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ParsedLab {
    /// Internal key matching `lab_reference.py` LAB_RANGES key when known
    /// (e.g. `hemoglobin_f`, `wbc`, `creatinine`).
    pub analyte_key: String,
    /// Lab abbreviation as found in the report (e.g. `HGB`, `WBC`, `MCV`).
    pub abbreviation: String,
    pub value: f64,
    pub unit_raw: Option<String>,
    /// Line offset within the source text (for UI "show source" links).
    pub line_no: usize,
}

/// Maps Latin abbreviation (uppercase) → `(analyte_key, default_unit)`.
/// `analyte_key` corresponds to `lab_reference.py::LAB_RANGES`.
/// Sex-specific keys (`hemoglobin_m` / `hemoglobin_f`) are aliased to a
/// generic `hemoglobin` key here; caller resolves sex from PatientCtx.
const KNOWN_ANALYTES: &[(&str, &str, &str)] = &[
    // ── CBC ───────────────────────────────────────────────────────────────
    ("HGB", "hemoglobin", "g/L"),
    ("HB", "hemoglobin", "g/L"),
    ("HCT", "hematocrit", "%"),
    ("RBC", "rbc", "×10¹²/L"),
    ("WBC", "wbc", "×10⁹/L"),
    ("MCV", "mcv", "fL"),
    ("MCH", "mch", "pg"),
    ("MCHC", "mchc", "g/L"),
    ("RDW-SD", "rdw_sd", "fL"),
    ("RDW-CV", "rdw_cv", "%"),
    ("RDW", "rdw_cv", "%"),
    ("PLT", "platelets", "×10⁹/L"),
    ("MPV", "mpv", "fL"),
    ("NEUT", "neutrophils", "×10⁹/L"),
    ("LYMPH", "lymphocytes", "×10⁹/L"),
    ("MONO", "monocytes", "×10⁹/L"),
    ("EOS", "eosinophils", "×10⁹/L"),
    ("BASO", "basophils", "×10⁹/L"),
    ("IG", "immature_granulocytes", "×10⁹/L"),
    ("ESR", "esr", "mm/h"),
    // ── Basic biochem ─────────────────────────────────────────────────────
    ("GLU", "glucose", "mmol/L"),
    ("UREA", "urea", "mmol/L"),
    ("BUN", "bun", "mmol/L"),
    ("CRE", "creatinine", "μmol/L"),
    ("CREA", "creatinine", "μmol/L"),
    ("CRP", "crp", "mg/L"),
    ("ALT", "alt", "U/L"),
    ("AST", "ast", "U/L"),
    ("GGT", "ggt", "U/L"),
    ("ALP", "alp", "U/L"),
    ("LDH", "ldh", "U/L"),
    ("BIL", "bilirubin_total", "μmol/L"),
    ("TBIL", "bilirubin_total", "μmol/L"),
    ("DBIL", "bilirubin_direct", "μmol/L"),
    ("ALB", "albumin", "g/L"),
    ("TP", "total_protein", "g/L"),
    ("CHOL", "cholesterol_total", "mmol/L"),
    ("HDL", "hdl", "mmol/L"),
    ("LDL", "ldl", "mmol/L"),
    ("TG", "triglycerides", "mmol/L"),
    ("TSH", "tsh", "mIU/L"),
    ("FT4", "ft4", "pmol/L"),
    ("FT3", "ft3", "pmol/L"),
    ("HBA1C", "hba1c", "%"),
    ("HCG", "hcg", "IU/L"),
    ("FE", "iron", "μmol/L"),
    ("FERR", "ferritin", "μg/L"),
    ("B12", "vitamin_b12", "pmol/L"),
    ("D25", "vitamin_d25", "nmol/L"),
];

/// Build a lookup table at first call. We use a sorted pairs slice and a
/// linear scan because the table is small (~50 entries) — O(N) is fine
/// vs the cost of pulling in `once_cell` for a HashMap.
fn lookup(abbrev: &str) -> Option<(&'static str, &'static str)> {
    let upper = abbrev.to_uppercase();
    KNOWN_ANALYTES
        .iter()
        .find(|(a, _, _)| *a == upper)
        .map(|(_, key, unit)| (*key, *unit))
}

// ── parser ────────────────────────────────────────────────────────────────

/// Parse a chunk of OCR text into structured lab values.
pub fn parse(text: &str) -> Vec<ParsedLab> {
    // Allow underscores, dashes, dots, slashes, percent in unit token; but
    // nothing fancy.
    let abbrev_re =
        Regex::new(r"\b([A-Z][A-Z0-9\-]{1,8})\b").expect("static regex compiles");
    // Numbers: 13.7, 4.30, 12, 1.35, 13,7 (some labs use comma decimal)
    let num_re = Regex::new(r"(-?\d+(?:[.,]\d+)?)").expect("static regex compiles");

    let mut out: Vec<ParsedLab> = Vec::new();
    let lines: Vec<&str> = text.lines().collect();

    for (line_no, line) in lines.iter().enumerate() {
        // Find every abbreviation match on this line; if recognised, look
        // for the next number.
        for ab_match in abbrev_re.find_iter(line) {
            let abbrev = ab_match.as_str();
            let (key, default_unit) = match lookup(abbrev) {
                Some(p) => p,
                None => continue,
            };

            // Look for the first numeric token after the abbreviation.
            let after = &line[ab_match.end()..];
            let number = num_re.find(after).or_else(|| {
                // Same-line search came up empty: peek next line (some
                // reports break the line before the value).
                if line_no + 1 < lines.len() {
                    num_re.find(lines[line_no + 1])
                } else {
                    None
                }
            });

            let number_match = match number {
                Some(m) => m,
                None => continue,
            };

            let raw = number_match.as_str().replace(',', ".");
            let value: f64 = match raw.parse() {
                Ok(v) => v,
                Err(_) => continue,
            };

            // Unit hint: take the token immediately after the number (on
            // same line if number was same-line; otherwise from next).
            let unit_source = if number_match.start() < after.len() {
                &after[number_match.end()..]
            } else if line_no + 1 < lines.len() {
                lines[line_no + 1]
            } else {
                ""
            };
            let unit_raw = first_unit_token(unit_source).map(|s| s.to_string());

            // Skip duplicates: if this same analyte_key already captured,
            // keep the first hit (often appears twice — abs count + %).
            if out.iter().any(|p| p.analyte_key == key) {
                continue;
            }

            out.push(ParsedLab {
                analyte_key: key.to_string(),
                abbreviation: abbrev.to_string(),
                value,
                unit_raw: unit_raw.or_else(|| Some(default_unit.into())),
                line_no,
            });
        }
    }

    out
}

/// Pluck the first non-numeric word that looks like a unit token.
/// Filters out comparison operators, punctuation, and reference range
/// numbers ("4.10 - 5.40").
fn first_unit_token(s: &str) -> Option<&str> {
    s.split_whitespace()
        .find(|tok| {
            !tok.is_empty()
                && !tok.starts_with('-')
                && !tok.starts_with('<')
                && !tok.starts_with('>')
                && !tok.starts_with('≤')
                && !tok.starts_with('≥')
                && !tok.chars().next().map(|c| c.is_ascii_digit()).unwrap_or(false)
        })
}

// ── tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_georgian_cbc_block() {
        // Real fragment from Beridze_Keti_2026_03_12 OCR.
        let text = "ერითროციტები RBC 4.30 /პლ 4.10 - 5.40\n\
                    ჰემოგლობინი HGB 13.7 გ/დლ 11.5 - 16.0\n\
                    ჰემატოკრიტი HCT 40.3 % 36.0 - 48.0\n\
                    ლეიკოციტები WBC 10.74 /ნლ 3.90 - 10.40\n\
                    თრომბოციტები PLT 279 /ნლ 176 - 391\n\
                    ESR 2 მმ/სთ ≤ 20";
        let labs = parse(text);
        let by_key = |k: &str| labs.iter().find(|p| p.analyte_key == k);

        assert_eq!(by_key("rbc").map(|p| p.value), Some(4.30));
        assert_eq!(by_key("hemoglobin").map(|p| p.value), Some(13.7));
        assert_eq!(by_key("hematocrit").map(|p| p.value), Some(40.3));
        assert_eq!(by_key("wbc").map(|p| p.value), Some(10.74));
        assert_eq!(by_key("platelets").map(|p| p.value), Some(279.0));
        assert_eq!(by_key("esr").map(|p| p.value), Some(2.0));
    }

    #[test]
    fn parses_basic_biochem_block() {
        let text = "ALT 25 U/L 0-40\n\
                    AST 22 U/L 0-40\n\
                    Glucose GLU 5.6 mmol/L 4.1-6.1\n\
                    Creatinine CRE 78 μmol/L\n\
                    HBA1C 6.2 %";
        let labs = parse(text);
        let g = |k: &str| labs.iter().find(|p| p.analyte_key == k).map(|p| p.value);
        assert_eq!(g("alt"), Some(25.0));
        assert_eq!(g("ast"), Some(22.0));
        assert_eq!(g("glucose"), Some(5.6));
        assert_eq!(g("creatinine"), Some(78.0));
        assert_eq!(g("hba1c"), Some(6.2));
    }

    #[test]
    fn handles_comma_decimal() {
        let text = "HGB 13,7 g/dL\n";
        let labs = parse(text);
        assert_eq!(labs.len(), 1);
        assert_eq!(labs[0].value, 13.7);
    }

    #[test]
    fn skips_unknown_abbrevs() {
        let text = "BL.6 SOMETHING_XYZ 100 unit\nABCDE 5\n";
        let labs = parse(text);
        // BL is not in KNOWN_ANALYTES; SOMETHING_XYZ too long; ABCDE not known.
        assert!(labs.is_empty());
    }

    #[test]
    fn deduplicates_repeated_abbreviations() {
        // NEUT often appears twice (absolute count + percentage).
        let text = "NEUT 5.29 /nL\nNEUT 49.2 %\n";
        let labs = parse(text);
        let n = labs.iter().filter(|p| p.analyte_key == "neutrophils").count();
        assert_eq!(n, 1);
    }

    #[test]
    fn empty_text_returns_empty() {
        let labs = parse("");
        assert!(labs.is_empty());
    }

    #[test]
    fn line_no_tracked() {
        let text = "header\n\nHGB 13.5 g/dL\n";
        let labs = parse(text);
        assert_eq!(labs.len(), 1);
        assert_eq!(labs[0].line_no, 2);
    }
}
