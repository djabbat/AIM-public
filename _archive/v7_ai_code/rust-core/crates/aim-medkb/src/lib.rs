//! Pure-logic helpers for aim-medkb, exposed as a library so they're testable
//! without spinning up the HTTP server.

use std::collections::HashMap;

pub fn canonicalise(name: &str, synonyms: &HashMap<String, String>) -> String {
    let s = name.trim().to_lowercase().replace('-', " ");
    let s: String = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if let Some(v) = synonyms.get(&s) { return v.clone(); }
    s.replace(' ', "_")
}

pub fn severity_rank(sev: &str) -> u8 {
    match sev {
        "contraindicated" => 0,
        "major" => 1,
        "moderate" => 2,
        "minor" => 3,
        _ => 4,
    }
}

pub fn rank_label(r: u8) -> &'static str {
    match r {
        0 => "contraindicated",
        1 => "major",
        2 => "moderate",
        3 => "minor",
        _ => "no_known",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn severity_rank_orders_correctly() {
        assert!(severity_rank("contraindicated") < severity_rank("major"));
        assert!(severity_rank("major") < severity_rank("moderate"));
        assert!(severity_rank("moderate") < severity_rank("minor"));
        assert!(severity_rank("unknown_label") >= 4);
    }

    #[test]
    fn rank_label_round_trips() {
        for s in ["contraindicated", "major", "moderate", "minor"] {
            let r = severity_rank(s);
            assert_eq!(rank_label(r), s);
        }
    }

    #[test]
    fn canonicalise_uses_synonym_table() {
        // canonicalise lowercases + trims input before lookup, so synonym
        // keys must be stored in canonical (lowercase) form.
        let mut syns = HashMap::new();
        syns.insert("paracetamol".into(), "acetaminophen".into());
        syns.insert("asa".into(), "aspirin".into());
        assert_eq!(canonicalise("Paracetamol", &syns), "acetaminophen");
        assert_eq!(canonicalise("ASA", &syns), "aspirin");
        // Unknown drugs round-trip with lowercase + spaces→underscores.
        assert_eq!(canonicalise("Ibuprofen", &syns), "ibuprofen");
        assert_eq!(canonicalise("Vitamin D3", &syns), "vitamin_d3");
    }
}
