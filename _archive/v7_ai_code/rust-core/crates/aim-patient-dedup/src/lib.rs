//! aim-patient-dedup — patient encounter dedup detector (DD1).
//!
//! Port of `agents/patient_dedup.py`. Walks `Patients/<Surname_Name_DOB>/`
//! folders and flags pairs that look like the same person under different
//! spellings (homograph mixes, sentinel DOB).

use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};
use thiserror::Error;
use unicode_normalization::UnicodeNormalization;

#[derive(Debug, Error)]
pub enum DedupError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, DedupError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Cluster {
    pub fingerprint: String,
    pub folders: Vec<String>,
    pub likely_dob: Option<String>,
}

impl Cluster {
    pub fn n_folders(&self) -> usize {
        self.folders.len()
    }
}

// ── fingerprint ─────────────────────────────────────────────────────────────

/// Latin → Cyrillic homograph map for common confusables.
fn latin_to_cyrillic(c: char) -> Option<char> {
    Some(match c {
        'a' => 'а',
        'c' => 'с',
        'e' => 'е',
        'o' => 'о',
        'p' => 'р',
        'x' => 'х',
        'y' => 'у',
        'h' => 'н',
        'k' => 'к',
        'i' => 'і',
        _ => return None,
    })
}

fn cyrillic_to_latin(c: char) -> Option<char> {
    Some(match c {
        'а' => 'a',
        'с' => 'c',
        'е' => 'e',
        'о' => 'o',
        'р' => 'p',
        'х' => 'x',
        'у' => 'y',
        'н' => 'h',
        'к' => 'k',
        'і' => 'i',
        _ => return None,
    })
}

fn is_letter_kept(c: char) -> bool {
    matches!(c,
        'a'..='z'
        | 'а'..='я'
        | 'ё'
        | 'ґ'
        | 'Ґ'
        | 'і'
        | 'ї'
        | '-'
    )
}

/// Coerce 'Иванoв' (homograph mix) into a stable form. Pure-Latin /
/// pure-Cyrillic names are left alone.
pub fn normalise_name(name: &str) -> String {
    let nfc: String = name.nfc().collect::<String>().to_lowercase();
    let cleaned: String = nfc.chars().filter(|c| is_letter_kept(*c)).collect();
    if cleaned.is_empty() {
        return cleaned;
    }
    let cyr = cleaned
        .chars()
        .filter(|c| ('а'..='я').contains(c) || matches!(c, 'ё' | 'і' | 'ї'))
        .count();
    let lat = cleaned
        .chars()
        .filter(|c| c.is_ascii_lowercase())
        .count();

    let folded: String = if cyr > 0 && lat > 0 {
        if cyr >= lat {
            // fold Latin lookalikes → Cyrillic
            cleaned
                .chars()
                .map(|c| latin_to_cyrillic(c).unwrap_or(c))
                .collect()
        } else {
            cleaned
                .chars()
                .map(|c| cyrillic_to_latin(c).unwrap_or(c))
                .collect()
        }
    } else {
        cleaned
    };

    folded.chars().take(30).collect()
}

/// Decompose `Surname_Name_YYYY_MM_DD` into a stable fingerprint.
/// Returns `(canonical, name_only_canonical, dob_iso_or_none)`.
pub fn fingerprint(folder_name: &str) -> (String, String, Option<String>) {
    let parts: Vec<&str> = folder_name.split('_').collect();
    let mut dob: Option<String> = None;
    let mut name_parts: &[&str] = &parts;
    let owned_name_parts: Vec<&str>;
    if parts.len() >= 5 {
        let last3 = &parts[parts.len() - 3..];
        if last3[0].len() == 4
            && last3[0].chars().all(|c| c.is_ascii_digit())
            && last3[1].len() == 2
            && last3[1].chars().all(|c| c.is_ascii_digit())
            && last3[2].len() == 2
            && last3[2].chars().all(|c| c.is_ascii_digit())
        {
            dob = Some(format!("{}-{}-{}", last3[0], last3[1], last3[2]));
            owned_name_parts = parts[..parts.len() - 3].to_vec();
            name_parts = &owned_name_parts;
        }
    }
    let name_canon: String = name_parts
        .iter()
        .filter(|p| !p.is_empty())
        .map(|p| normalise_name(p))
        .collect::<Vec<_>>()
        .join("_");
    let canonical = format!("{}|{}", name_canon, dob.as_deref().unwrap_or(""));
    let name_only = format!("{}|", name_canon);
    (canonical, name_only, dob)
}

// ── duplicate scan ─────────────────────────────────────────────────────────

/// Scan a directory for patient sub-folders and return clusters.
/// Folder named `INBOX` is skipped (matches Python).
pub fn duplicates_in_dir(base: &Path) -> Result<Vec<Cluster>> {
    if !base.exists() {
        return Ok(Vec::new());
    }
    let mut folders: Vec<String> = Vec::new();
    for entry in std::fs::read_dir(base)? {
        let e = entry?;
        if !e.file_type()?.is_dir() {
            continue;
        }
        let name = e.file_name().to_string_lossy().to_string();
        if name == "INBOX" {
            continue;
        }
        folders.push(name);
    }
    Ok(duplicates(&folders))
}

/// Pure-data variant: takes a list of folder names directly.
pub fn duplicates(folders: &[String]) -> Vec<Cluster> {
    let mut by_canonical: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut by_name_only: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut dob_for: BTreeMap<String, Option<String>> = BTreeMap::new();

    for folder in folders {
        let (canon, name_only, dob) = fingerprint(folder);
        by_canonical
            .entry(canon)
            .or_default()
            .push(folder.clone());
        by_name_only
            .entry(name_only)
            .or_default()
            .push(folder.clone());
        dob_for.insert(folder.clone(), dob);
    }

    let mut out: Vec<Cluster> = Vec::new();

    // Strong matches
    for (canon, group) in &by_canonical {
        if group.len() < 2 {
            continue;
        }
        let mut sorted = group.clone();
        sorted.sort();
        let dob = dob_for.get(&sorted[0]).cloned().flatten();
        out.push(Cluster {
            fingerprint: canon.clone(),
            folders: sorted,
            likely_dob: dob,
        });
    }

    // Soft matches: same name canon, varying DOBs
    for (name_only, group) in &by_name_only {
        if group.len() < 2 {
            continue;
        }
        let already_strong = out.iter().any(|c| {
            let group_set: std::collections::HashSet<&String> = group.iter().collect();
            let cluster_set: std::collections::HashSet<&String> = c.folders.iter().collect();
            group_set.is_subset(&cluster_set)
        });
        if already_strong {
            continue;
        }
        let dobs: std::collections::HashSet<Option<String>> = group
            .iter()
            .map(|f| dob_for.get(f).cloned().flatten())
            .collect();
        let has_sentinel = dobs.iter().any(|d| d.as_deref() == Some("2000-01-01"));
        if !has_sentinel && dobs.len() > 1 {
            continue;
        }
        let mut sorted = group.clone();
        sorted.sort();
        out.push(Cluster {
            fingerprint: name_only.clone(),
            folders: sorted,
            likely_dob: None,
        });
    }
    out
}

pub fn summary(clusters: &[Cluster]) -> String {
    if clusters.is_empty() {
        return "(no duplicate patient folders detected)".into();
    }
    let mut parts = vec![format!(
        "👥 Duplicate patient folders ({} clusters)",
        clusters.len()
    )];
    for c in clusters.iter().take(8) {
        parts.push(format!(
            "  • {} folders share fingerprint {:?}",
            c.n_folders(),
            c.fingerprint
        ));
        for f in &c.folders {
            parts.push(format!("    - {}", f));
        }
    }
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    // ── normalise_name ─────────────────────────────────────────────────────

    #[test]
    fn normalise_pure_cyrillic_unchanged() {
        assert_eq!(normalise_name("Иванов"), "иванов");
    }

    #[test]
    fn normalise_pure_latin_unchanged() {
        assert_eq!(normalise_name("Smith"), "smith");
    }

    #[test]
    fn normalise_strips_non_letters() {
        assert_eq!(normalise_name("Smith-Jones"), "smith-jones");
        assert_eq!(normalise_name("O'Brien"), "obrien");
    }

    #[test]
    fn normalise_homograph_mix_folds_to_majority() {
        // Иванoв with Latin 'o' → fold to Cyrillic 'о' (majority is Cyrillic)
        let mixed = "Иванoв";
        let n = normalise_name(mixed);
        // result should be all Cyrillic
        assert!(n.chars().all(|c| !c.is_ascii_lowercase() || c == '-'));
        assert_eq!(n.chars().count(), 6);
    }

    #[test]
    fn normalise_caps_at_30_chars() {
        let long = "a".repeat(50);
        assert_eq!(normalise_name(&long).chars().count(), 30);
    }

    #[test]
    fn normalise_empty_input() {
        assert_eq!(normalise_name(""), "");
        assert_eq!(normalise_name("   "), "");
    }

    // ── fingerprint ────────────────────────────────────────────────────────

    #[test]
    fn fingerprint_parses_dob_when_present() {
        let (canon, name_only, dob) = fingerprint("Smith_John_1980_05_15");
        assert_eq!(dob.as_deref(), Some("1980-05-15"));
        assert!(canon.ends_with("|1980-05-15"));
        assert_eq!(name_only, "smith_john|");
    }

    #[test]
    fn fingerprint_handles_no_dob() {
        let (canon, name_only, dob) = fingerprint("Smith_John");
        assert!(dob.is_none());
        assert_eq!(canon, "smith_john|");
        assert_eq!(name_only, "smith_john|");
    }

    #[test]
    fn fingerprint_normalises_homographs() {
        let (canon_a, _, _) = fingerprint("Ivanov_Petr_1980_05_15");
        let (canon_b, _, _) = fingerprint("Ivanоv_Petr_1980_05_15"); // 'о' = Cyrillic
        // Both should normalise to the same Latin-only form
        // (lat majority → fold Cyrillic 'о' back to Latin 'o')
        assert_eq!(canon_a, canon_b);
    }

    #[test]
    fn fingerprint_partial_date_fields_not_treated_as_dob() {
        let (_, _, dob) = fingerprint("Test_Name_198_05_15"); // 3-digit year
        assert!(dob.is_none());
    }

    // ── duplicates ─────────────────────────────────────────────────────────

    #[test]
    fn duplicates_strong_match_same_dob() {
        let folders = s(&[
            "Smith_John_1980_05_15",
            "smith_john_1980_05_15",
            "Other_Person_1990_01_01",
        ]);
        let clusters = duplicates(&folders);
        assert_eq!(clusters.len(), 1);
        assert_eq!(clusters[0].folders.len(), 2);
        assert_eq!(clusters[0].likely_dob.as_deref(), Some("1980-05-15"));
    }

    #[test]
    fn duplicates_soft_match_with_sentinel_dob() {
        let folders = s(&[
            "Doe_Jane_1985_03_22",
            "Doe_Jane_2000_01_01", // sentinel
        ]);
        let clusters = duplicates(&folders);
        assert_eq!(clusters.len(), 1);
        assert!(clusters[0].fingerprint.ends_with("|"));
    }

    #[test]
    fn duplicates_no_match_distinct_dobs_no_sentinel() {
        let folders = s(&[
            "Doe_Jane_1985_03_22",
            "Doe_Jane_1990_07_11",
        ]);
        let clusters = duplicates(&folders);
        // Same name, distinct known DOBs → likely truly different patients
        assert!(clusters.is_empty());
    }

    #[test]
    fn duplicates_homograph_pair_clusters() {
        let folders = s(&[
            "Ivanov_Petr_1980_05_15",
            "Ivanоv_Petr_1980_05_15", // homograph 'о'
        ]);
        let clusters = duplicates(&folders);
        assert_eq!(clusters.len(), 1);
        assert_eq!(clusters[0].folders.len(), 2);
    }

    #[test]
    fn duplicates_unique_folder_no_cluster() {
        let folders = s(&["Lone_Patient_1990_01_01"]);
        assert!(duplicates(&folders).is_empty());
    }

    #[test]
    fn duplicates_empty_input() {
        let folders: Vec<String> = Vec::new();
        assert!(duplicates(&folders).is_empty());
    }

    // ── duplicates_in_dir ───────────────────────────────────────────────────

    #[test]
    fn duplicates_in_dir_skips_inbox_and_files() {
        let tmp = TempDir::new().unwrap();
        std::fs::create_dir_all(tmp.path().join("Smith_John_1980_05_15")).unwrap();
        std::fs::create_dir_all(tmp.path().join("smith_john_1980_05_15")).unwrap();
        std::fs::create_dir_all(tmp.path().join("INBOX")).unwrap();
        std::fs::write(tmp.path().join("notes.txt"), "ignored").unwrap();
        let clusters = duplicates_in_dir(tmp.path()).unwrap();
        assert_eq!(clusters.len(), 1);
        assert_eq!(clusters[0].folders.len(), 2);
    }

    #[test]
    fn duplicates_in_dir_missing_returns_empty() {
        let tmp = TempDir::new().unwrap();
        let v = duplicates_in_dir(&tmp.path().join("nope")).unwrap();
        assert!(v.is_empty());
    }

    // ── summary ────────────────────────────────────────────────────────────

    #[test]
    fn summary_empty_message() {
        assert_eq!(summary(&[]), "(no duplicate patient folders detected)");
    }

    #[test]
    fn summary_renders_clusters() {
        let c = vec![Cluster {
            fingerprint: "smith_john|1980-05-15".into(),
            folders: vec!["a".into(), "b".into()],
            likely_dob: Some("1980-05-15".into()),
        }];
        let s = summary(&c);
        assert!(s.contains("👥 Duplicate patient folders"));
        assert!(s.contains("smith_john"));
        assert!(s.contains("- a"));
        assert!(s.contains("- b"));
    }
}
