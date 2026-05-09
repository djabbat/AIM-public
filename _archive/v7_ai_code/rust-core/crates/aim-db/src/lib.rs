//! aim-db — schema constants + format helpers from `db.py`.
//!
//! The Python module wraps sqlite3; here we keep the deterministic
//! pieces — folder formatting, hash key, schema SQL, tiering
//! constants — and let the binary drive `rusqlite` / `sqlx` against
//! the schema.

use serde::{Deserialize, Serialize};

pub const DOB_PLACEHOLDER: &str = "2000_01_01";
pub const HOT_DAYS: u32 = 7;
pub const WARM_DAYS: u32 = 90;

pub const SCHEMA: &str = include_str!("schema.sql");

pub fn format_patient_folder(name: &str, dob: Option<&str>) -> String {
    let safe_name = name.trim().replace(' ', "_");
    let dob_part = match dob {
        None => DOB_PLACEHOLDER.to_string(),
        Some(d) if d.trim().is_empty() => DOB_PLACEHOLDER.to_string(),
        Some(d) => {
            let normal = d.trim().replace(['-', '.', '/'], "_");
            let parts: Vec<&str> = normal.split('_').collect();
            if parts.len() != 3 {
                DOB_PLACEHOLDER.to_string()
            } else if parts[0].len() == 4 {
                format!(
                    "{}_{}_{}",
                    parts[0],
                    pad2(parts[1]),
                    pad2(parts[2])
                )
            } else if parts[2].len() == 4 {
                format!(
                    "{}_{}_{}",
                    parts[2],
                    pad2(parts[1]),
                    pad2(parts[0])
                )
            } else {
                DOB_PLACEHOLDER.to_string()
            }
        }
    };
    format!("{}_{}", safe_name, dob_part)
}

fn pad2(s: &str) -> String {
    if s.len() < 2 {
        format!("{:0>2}", s)
    } else {
        s.to_string()
    }
}

pub fn make_cache_hash(prompt: &str, model: &str) -> String {
    use sha2::{Digest, Sha256};
    let combined = format!("{}::{}", model, prompt);
    let mut hasher = Sha256::new();
    hasher.update(combined.as_bytes());
    let bytes = hasher.finalize();
    let hex: String = bytes.iter().map(|b| format!("{:02x}", b)).collect();
    hex.chars().take(32).collect()
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TierStats {
    pub hot: u64,
    pub warm: u64,
    pub cold: u64,
    pub hot_days: u32,
    pub warm_days: u32,
}

impl TierStats {
    pub fn new(hot: u64, warm: u64, cold: u64) -> Self {
        Self {
            hot,
            warm,
            cold,
            hot_days: HOT_DAYS,
            warm_days: WARM_DAYS,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn folder_uses_placeholder_when_dob_missing() {
        assert_eq!(format_patient_folder("Иванов Иван", None), "Иванов_Иван_2000_01_01");
    }

    #[test]
    fn folder_normalises_yyyy_mm_dd_dashes() {
        assert_eq!(format_patient_folder("Smith John", Some("1981-06-15")), "Smith_John_1981_06_15");
    }

    #[test]
    fn folder_normalises_dd_mm_yyyy_dots() {
        assert_eq!(format_patient_folder("Smith John", Some("15.06.1981")), "Smith_John_1981_06_15");
    }

    #[test]
    fn folder_normalises_slashes() {
        assert_eq!(format_patient_folder("Smith John", Some("1981/6/15")), "Smith_John_1981_06_15");
    }

    #[test]
    fn folder_falls_back_for_garbage_dob() {
        assert_eq!(format_patient_folder("Smith J", Some("abc")), "Smith_J_2000_01_01");
    }

    #[test]
    fn cache_hash_deterministic_and_32_chars() {
        let h = make_cache_hash("hello", "deepseek-v4-flash");
        assert_eq!(h.len(), 32);
        assert_eq!(h, make_cache_hash("hello", "deepseek-v4-flash"));
    }

    #[test]
    fn cache_hash_changes_with_model() {
        assert_ne!(
            make_cache_hash("p", "ds-flash"),
            make_cache_hash("p", "ds-pro")
        );
    }

    #[test]
    fn schema_contains_required_tables() {
        assert!(SCHEMA.contains("CREATE TABLE IF NOT EXISTS patients"));
        assert!(SCHEMA.contains("CREATE TABLE IF NOT EXISTS sessions"));
        assert!(SCHEMA.contains("CREATE TABLE IF NOT EXISTS messages"));
        assert!(SCHEMA.contains("CREATE TABLE IF NOT EXISTS llm_cache"));
        assert!(SCHEMA.contains("CREATE TABLE IF NOT EXISTS ai_events_archive"));
        assert!(SCHEMA.contains("CREATE TABLE IF NOT EXISTS ze_events"));
    }

    #[test]
    fn tier_stats_carries_constants() {
        let s = TierStats::new(10, 20, 30);
        assert_eq!(s.hot_days, 7);
        assert_eq!(s.warm_days, 90);
    }
}
