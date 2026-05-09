use aim_medkb::{canonicalise, severity_rank, rank_label};
use std::collections::HashMap;

fn syns() -> HashMap<String, String> {
    let mut m = HashMap::new();
    m.insert("aspirin".into(), "acetylsalicylic_acid".into());
    m.insert("vitamin k".into(), "vitamin_k".into());
    m.insert("st johns wort".into(), "st_johns_wort".into());
    m.insert("tylenol".into(), "paracetamol".into());
    m
}

#[test]
fn synonym_lookup_basic() {
    let s = syns();
    assert_eq!(canonicalise("aspirin", &s), "acetylsalicylic_acid");
    assert_eq!(canonicalise("ASPIRIN", &s), "acetylsalicylic_acid");
    assert_eq!(canonicalise("Tylenol", &s), "paracetamol");
}

#[test]
fn synonym_lookup_handles_dashes_and_whitespace() {
    let s = syns();
    assert_eq!(canonicalise("St-Johns-Wort", &s), "st_johns_wort");
    assert_eq!(canonicalise("  vitamin  k  ", &s), "vitamin_k");
}

#[test]
fn unknown_drug_underscored() {
    let s = syns();
    assert_eq!(canonicalise("warfarin", &s), "warfarin");
    assert_eq!(canonicalise("ace inhibitor", &s), "ace_inhibitor");
}

#[test]
fn severity_ordering() {
    assert!(severity_rank("contraindicated") < severity_rank("major"));
    assert!(severity_rank("major") < severity_rank("moderate"));
    assert!(severity_rank("moderate") < severity_rank("minor"));
    assert!(severity_rank("minor") < severity_rank("no_known"));
    assert_eq!(severity_rank("garbage"), 4);
}

#[test]
fn rank_label_roundtrip() {
    for sev in &["contraindicated", "major", "moderate", "minor", "no_known"] {
        assert_eq!(rank_label(severity_rank(sev)), *sev);
    }
}

#[test]
fn data_files_exist_and_parse() {
    let lab = std::fs::read("data/lab_ranges.json").unwrap();
    let parsed: serde_json::Value = serde_json::from_slice(&lab).unwrap();
    assert!(parsed.as_object().unwrap().len() >= 60, "expected ≥60 analytes");

    let inter = std::fs::read("data/interactions.json").unwrap();
    let parsed: serde_json::Value = serde_json::from_slice(&inter).unwrap();
    let pairs = parsed["pairs"].as_array().unwrap();
    assert!(pairs.len() >= 30, "expected ≥30 pairs");
}
