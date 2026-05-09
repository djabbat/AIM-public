//! aim-unicode-guard — Unicode hygiene at every user/LLM boundary (UN1).
//!
//! Port of `agents/unicode_guard.py`. Three quick utilities used wherever
//! AIM accepts a name / label / project string from the user or an LLM:
//!
//! - [`normalise`] — NFC + strip zero-width / control characters
//! - [`mixed_scripts`] — flag strings that mix Cyrillic + Latin in ways
//!   that probably aren't intentional (e.g. `"Иванoв"` with a Latin `o`)
//! - [`safe`] — high-level: returns the normalised text + warnings
//!
//! Catches a real attack vector: a single Latin lookalike letter inside
//! a Cyrillic name silently changes the patient identifier, breaking
//! dedup and search.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use unicode_normalization::UnicodeNormalization;

const INVISIBLE_CHARS: &[char] = &[
    '\u{200B}', // zero-width space
    '\u{200C}', // zero-width non-joiner
    '\u{200D}', // zero-width joiner
    '\u{200E}', // LTR mark
    '\u{200F}', // RTL mark
    '\u{2060}', // word-joiner
    '\u{00AD}', // soft hyphen
    '\u{FEFF}', // BOM / zero-width no-break space
];

const SCRIPT_PREFIXES: &[(&str, &str)] = &[
    ("CYRILLIC", "cyrillic"),
    ("LATIN", "latin"),
    ("GEORGIAN", "georgian"),
    ("GREEK", "greek"),
    ("ARABIC", "arabic"),
    ("HEBREW", "hebrew"),
    ("CJK", "cjk"),
    ("HIRAGANA", "japanese"),
    ("KATAKANA", "japanese"),
    ("HANGUL", "korean"),
    ("DEVANAGARI", "devanagari"),
];

fn is_invisible(c: char) -> bool {
    INVISIBLE_CHARS.contains(&c)
}

fn is_control_or_format(c: char) -> bool {
    use unicode_normalization::char::is_combining_mark;
    let _ = is_combining_mark; // unused but keeps the dep root visible
    matches!(
        c,
        '\u{0000}'..='\u{001F}' | '\u{007F}'..='\u{009F}' | '\u{2028}' | '\u{2029}' | '\u{FEFF}'
    ) && c != '\n'
        && c != '\t'
}

/// NFC-normalise + strip zero-width / control characters (except `\n`/`\t`).
pub fn normalise(s: &str) -> String {
    let nfc: String = s.nfc().collect();
    nfc.chars()
        .filter(|c| !is_invisible(*c) && !is_control_or_format(*c))
        .collect()
}

fn script_of(c: char) -> Option<&'static str> {
    if !c.is_alphabetic() {
        return None;
    }
    let name = unicode_names2::name(c)?.to_string();
    let head = name.split_whitespace().next()?;
    for (prefix, label) in SCRIPT_PREFIXES {
        if head == *prefix {
            return Some(label);
        }
    }
    None
}

/// Count letters by script: `{cyrillic: 5, latin: 1}` for a name like
/// "Иванoв" (one Latin `o`).
pub fn mixed_scripts(s: &str) -> BTreeMap<String, u32> {
    let mut out: BTreeMap<String, u32> = BTreeMap::new();
    for c in s.chars() {
        if let Some(label) = script_of(c) {
            *out.entry(label.to_string()).or_insert(0) += 1;
        }
    }
    out
}

/// True when the string mixes ≥2 scripts AND the minority script(s)
/// account for less than 30% of letters — typical lookalike-attack
/// signature.
pub fn is_suspicious(s: &str) -> bool {
    let counts = mixed_scripts(s);
    if counts.len() < 2 {
        return false;
    }
    let total: u32 = counts.values().sum();
    if total == 0 {
        return false;
    }
    let mut sorted: Vec<u32> = counts.values().copied().collect();
    sorted.sort_by(|a, b| b.cmp(a));
    let minority: u32 = sorted.iter().skip(1).sum();
    minority > 0 && (minority as f64) < (total as f64) * 0.30
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SafetyResult {
    pub text: String,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct SafeOpts {
    pub allow_mixed: bool,
}

/// High-level entry point: NFC-normalise, strip invisibles, and append
/// human-readable warnings about the changes.
pub fn safe(s: &str, opts: &SafeOpts) -> SafetyResult {
    let mut warnings: Vec<String> = Vec::new();
    let nfc: String = s.nfc().collect();
    if nfc != s {
        warnings.push("normalised to NFC".into());
    }
    let out = normalise(s);
    if out != nfc {
        warnings.push("stripped invisible/control characters".into());
    }
    if !opts.allow_mixed && is_suspicious(&out) {
        let scripts = mixed_scripts(&out);
        let mut entries: Vec<(String, u32)> = scripts.into_iter().collect();
        entries.sort_by(|a, b| b.1.cmp(&a.1));
        let body = entries
            .into_iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join(", ");
        warnings.push(format!("mixed scripts {body}"));
    }
    SafetyResult {
        text: out,
        warnings,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalise_strips_zero_width() {
        let s = "Hello\u{200B}World\u{FEFF}!";
        assert_eq!(normalise(s), "HelloWorld!");
    }

    #[test]
    fn normalise_keeps_newline_and_tab() {
        let s = "line1\nline2\tcol";
        assert_eq!(normalise(s), "line1\nline2\tcol");
    }

    #[test]
    fn normalise_strips_soft_hyphen() {
        let s = "co\u{00AD}operate";
        assert_eq!(normalise(s), "cooperate");
    }

    #[test]
    fn normalise_combines_decomposed_to_nfc() {
        // Combining acute over plain "e" → NFC normalizes to "é"
        let decomposed = "e\u{0301}";
        assert_eq!(normalise(decomposed), "é");
    }

    #[test]
    fn mixed_scripts_pure_cyrillic() {
        let counts = mixed_scripts("Иванов");
        assert_eq!(counts.get("cyrillic"), Some(&6));
        assert_eq!(counts.get("latin"), None);
    }

    #[test]
    fn mixed_scripts_pure_latin() {
        let counts = mixed_scripts("Smith");
        assert_eq!(counts.get("latin"), Some(&5));
        assert_eq!(counts.get("cyrillic"), None);
    }

    #[test]
    fn mixed_scripts_lookalike_attack() {
        // "Иванoв" — Latin "o" inside a Cyrillic surname
        let counts = mixed_scripts("Иванoв");
        assert_eq!(counts.get("cyrillic"), Some(&5));
        assert_eq!(counts.get("latin"), Some(&1));
    }

    #[test]
    fn mixed_scripts_georgian() {
        let counts = mixed_scripts("ტყემალაძე");
        assert!(counts.get("georgian").copied().unwrap_or(0) >= 7);
    }

    #[test]
    fn is_suspicious_lookalike_minority_under_30pct() {
        // 1 latin / 6 total = 16.7% < 30% → suspicious
        assert!(is_suspicious("Иванoв"));
    }

    #[test]
    fn is_suspicious_mixed_balanced_not_suspicious() {
        // Roughly even Cyrillic + Latin = legitimate bilingual label
        assert!(!is_suspicious("Иван Smith"));
    }

    #[test]
    fn is_suspicious_single_script_ok() {
        assert!(!is_suspicious("Tkemaladze"));
        assert!(!is_suspicious("Ткемаладзе"));
        assert!(!is_suspicious(""));
    }

    #[test]
    fn safe_emits_nfc_warning() {
        let r = safe("e\u{0301}clair", &SafeOpts::default());
        assert_eq!(r.text, "éclair");
        assert!(r.warnings.iter().any(|w| w.contains("NFC")));
    }

    #[test]
    fn safe_emits_strip_warning() {
        let r = safe("hi\u{200B}there", &SafeOpts::default());
        assert_eq!(r.text, "hithere");
        assert!(r.warnings.iter().any(|w| w.contains("invisible")));
    }

    #[test]
    fn safe_emits_mixed_script_warning() {
        let r = safe("Иванoв", &SafeOpts::default());
        assert_eq!(r.text, "Иванoв");
        assert!(r.warnings.iter().any(|w| w.contains("mixed scripts")));
        let warn = r
            .warnings
            .iter()
            .find(|w| w.contains("mixed scripts"))
            .unwrap();
        // Higher count comes first
        assert!(warn.contains("cyrillic=5"));
        assert!(warn.contains("latin=1"));
        let cyr_pos = warn.find("cyrillic").unwrap();
        let lat_pos = warn.find("latin").unwrap();
        assert!(cyr_pos < lat_pos, "majority script must come first");
    }

    #[test]
    fn safe_allow_mixed_suppresses_warning() {
        let r = safe(
            "Иванoв",
            &SafeOpts {
                allow_mixed: true,
            },
        );
        assert!(!r.warnings.iter().any(|w| w.contains("mixed scripts")));
    }

    #[test]
    fn safe_clean_input_no_warnings() {
        let r = safe("Tkemaladze", &SafeOpts::default());
        assert!(r.warnings.is_empty());
        assert_eq!(r.text, "Tkemaladze");
    }

    #[test]
    fn safe_text_preserved_when_no_change_needed() {
        let r = safe("плохой запрос", &SafeOpts::default());
        assert_eq!(r.text, "плохой запрос");
    }
}
