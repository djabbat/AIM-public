//! aim-patient-inbox-watcher — INBOX → patient folder router.
//!
//! Port of `agents/patient_inbox_watcher.py`. The Python module walks
//! `Patients/INBOX/`, runs OCR, picks Surname + Name + DOB out of the
//! text, and moves the file into `Patients/<Surname>_<Name>_<DOB>/`.
//!
//! This crate keeps the parser + folder-naming + sentinel logic, all
//! of which are pure functions. The actual filesystem walk and OCR
//! call go through pluggable traits ([`OcrEngine`], [`Filesystem`]).

use chrono::NaiveDate;
use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};

// ── regexes ────────────────────────────────────────────────────────────────

static WORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b[А-ЯҐЁ][а-яёҐґії\-]{2,30}\b").expect("WORD_RE")
});

static DOB_LABEL_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)(?:год\s+рождения|дата\s+рождения|д[\.\s]р[\.\s]?|дата:|date\s+of\s+birth|DOB)[\s:]*?(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](\d{2,4})",
    )
    .expect("DOB_LABEL_RE")
});

static GENERIC_DATE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](19[3-9]\d|20[0-1]\d)\b").expect("GENERIC_DATE_RE")
});

static UNSAFE_NAME_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"[^A-Za-zА-Яа-яҐЁёї_\-]+").expect("UNSAFE_NAME_RE")
});

const NAME_STOPWORDS: &[&str] = &[
    "пациент",
    "пациентка",
    "анализ",
    "анализы",
    "результат",
    "результаты",
    "доктор",
    "клиника",
    "лаборатория",
    "медкарта",
    "карта",
    "образец",
    "patient",
    "subject",
    "doctor",
    "clinic",
    "lab",
    "results",
];

const OCR_EXTS: &[&str] = &[".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"];

// ── classification ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Classification {
    pub surname: Option<String>,
    pub name: Option<String>,
    pub dob: Option<NaiveDate>,
    pub text_excerpt: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub enum Outcome {
    Moved,
    MovedDryRun,
    Ambiguous,
    OcrFailed,
    NotFound,
}

impl Outcome {
    pub fn as_str(&self) -> &'static str {
        match self {
            Outcome::Moved => "moved",
            Outcome::MovedDryRun => "moved (dry-run)",
            Outcome::Ambiguous => "ambiguous",
            Outcome::OcrFailed => "ocr_failed",
            Outcome::NotFound => "not_found",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Action {
    pub file: String,
    pub moved_to: Option<String>,
    pub outcome: Outcome,
    pub classification: Option<Classification>,
}

// ── traits ─────────────────────────────────────────────────────────────────

pub trait OcrEngine: Send + Sync {
    /// Returns plain text, or `None` if OCR could not produce anything.
    fn extract(&self, file: &str) -> Option<String>;
}

pub trait Filesystem: Send + Sync {
    fn exists(&self, path: &str) -> bool;
    /// Returns just the filenames living directly under `dir` (no subdirs).
    fn list_dir(&self, dir: &str) -> Vec<String>;
    fn join(&self, parent: &str, child: &str) -> String;
}

#[derive(Default)]
pub struct StubFs {
    pub files: std::collections::BTreeSet<String>,
}

impl StubFs {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn add(&mut self, path: &str) {
        self.files.insert(path.to_string());
    }
}

impl Filesystem for StubFs {
    fn exists(&self, path: &str) -> bool {
        self.files.contains(path)
    }
    fn list_dir(&self, dir: &str) -> Vec<String> {
        let prefix = if dir.ends_with('/') {
            dir.to_string()
        } else {
            format!("{}/", dir)
        };
        let mut out: Vec<String> = self
            .files
            .iter()
            .filter_map(|p| {
                p.strip_prefix(&prefix).and_then(|rest| {
                    if rest.contains('/') {
                        None
                    } else {
                        Some(rest.to_string())
                    }
                })
            })
            .collect();
        out.sort();
        out
    }
    fn join(&self, parent: &str, child: &str) -> String {
        if parent.ends_with('/') {
            format!("{}{}", parent, child)
        } else {
            format!("{}/{}", parent, child)
        }
    }
}

// ── pure helpers ───────────────────────────────────────────────────────────

pub fn has_ocr_ext(file: &str) -> bool {
    let lower = file.to_lowercase();
    OCR_EXTS.iter().any(|ext| lower.ends_with(ext))
}

pub fn normalise_dob(d: u32, m: u32, y: u32) -> Option<NaiveDate> {
    let year = if y < 100 {
        if y > 30 {
            y + 1900
        } else {
            y + 2000
        }
    } else {
        y
    };
    if !(1900..=2100).contains(&year) {
        return None;
    }
    if !(1..=12).contains(&m) || !(1..=31).contains(&d) {
        return None;
    }
    NaiveDate::from_ymd_opt(year as i32, m, d)
}

pub fn extract_name_pair(text: &str) -> (Option<String>, Option<String>) {
    let words: Vec<&str> = WORD_RE.find_iter(text).map(|m| m.as_str()).collect();
    for i in 0..words.len().saturating_sub(1) {
        let a = words[i];
        let b = words[i + 1];
        if NAME_STOPWORDS.contains(&a.to_lowercase().as_str())
            || NAME_STOPWORDS.contains(&b.to_lowercase().as_str())
        {
            continue;
        }
        return (Some(a.to_string()), Some(b.to_string()));
    }
    (None, None)
}

pub fn extract_dob(text: &str) -> Option<NaiveDate> {
    if let Some(c) = DOB_LABEL_RE.captures(text) {
        let d: u32 = c.get(1)?.as_str().parse().ok()?;
        let m: u32 = c.get(2)?.as_str().parse().ok()?;
        let y: u32 = c.get(3)?.as_str().parse().ok()?;
        if let Some(dob) = normalise_dob(d, m, y) {
            return Some(dob);
        }
    }
    if let Some(c) = GENERIC_DATE_RE.captures(text) {
        let d: u32 = c.get(1)?.as_str().parse().ok()?;
        let m: u32 = c.get(2)?.as_str().parse().ok()?;
        let y: u32 = c.get(3)?.as_str().parse().ok()?;
        return normalise_dob(d, m, y);
    }
    None
}

pub fn classify_text(text: &str) -> Classification {
    let (surname, name) = extract_name_pair(text);
    let dob = extract_dob(text);
    let excerpt: String = text.chars().take(400).collect();
    Classification {
        surname,
        name,
        dob,
        text_excerpt: excerpt,
    }
}

pub fn safe_segment(s: &str, max: usize) -> String {
    let cleaned = UNSAFE_NAME_RE.replace_all(s.trim(), "_");
    cleaned.chars().take(max).collect()
}

pub fn patient_folder_name(c: &Classification) -> String {
    let surname = c.surname.clone().unwrap_or_else(|| "Unknown".into());
    let name = c.name.clone().unwrap_or_else(|| "Unknown".into());
    let safe_surname = safe_segment(&surname, 40);
    let safe_name = safe_segment(&name, 40);
    let slug_dob = match c.dob {
        Some(d) => d.format("%Y_%m_%d").to_string(),
        None => "2000_01_01".to_string(),
    };
    format!("{}_{}_{}", safe_surname, safe_name, slug_dob)
}

// ── orchestration ──────────────────────────────────────────────────────────

pub fn classify_file(file: &str, ocr: &dyn OcrEngine) -> Option<Classification> {
    let text = ocr.extract(file)?;
    if text.trim().is_empty() {
        return None;
    }
    Some(classify_text(&text))
}

pub fn process_one(
    file: &str,
    ocr: &dyn OcrEngine,
    fs: &dyn Filesystem,
    patients_dir: &str,
    dry_run: bool,
) -> Action {
    if !fs.exists(file) {
        return Action {
            file: file.to_string(),
            moved_to: None,
            outcome: Outcome::NotFound,
            classification: None,
        };
    }
    let cls = match classify_file(file, ocr) {
        Some(c) => c,
        None => {
            return Action {
                file: file.to_string(),
                moved_to: None,
                outcome: Outcome::OcrFailed,
                classification: None,
            };
        }
    };
    if cls.surname.is_none() || cls.name.is_none() {
        return Action {
            file: file.to_string(),
            moved_to: None,
            outcome: Outcome::Ambiguous,
            classification: Some(cls),
        };
    }
    let folder = patient_folder_name(&cls);
    let target_dir = fs.join(patients_dir, &folder);
    let basename = std::path::Path::new(file)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(file);
    let target = fs.join(&target_dir, basename);
    Action {
        file: file.to_string(),
        moved_to: Some(target),
        outcome: if dry_run { Outcome::MovedDryRun } else { Outcome::Moved },
        classification: Some(cls),
    }
}

pub fn candidates(fs: &dyn Filesystem, inbox_dir: &str) -> Vec<String> {
    let mut out: Vec<String> = fs
        .list_dir(inbox_dir)
        .into_iter()
        .filter(|name| has_ocr_ext(name))
        .map(|name| fs.join(inbox_dir, &name))
        .collect();
    out.sort();
    out
}

pub fn process_inbox(
    fs: &dyn Filesystem,
    ocr: &dyn OcrEngine,
    patients_dir: &str,
    inbox_dir: &str,
    dry_run: bool,
) -> Vec<Action> {
    candidates(fs, inbox_dir)
        .into_iter()
        .map(|p| process_one(&p, ocr, fs, patients_dir, dry_run))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::sync::Mutex;

    struct MapOcr {
        m: Mutex<BTreeMap<String, String>>,
    }
    impl MapOcr {
        fn new() -> Self {
            Self { m: Mutex::new(BTreeMap::new()) }
        }
        fn set(&self, file: &str, text: &str) {
            self.m.lock().unwrap().insert(file.to_string(), text.to_string());
        }
    }
    impl OcrEngine for MapOcr {
        fn extract(&self, file: &str) -> Option<String> {
            self.m.lock().unwrap().get(file).cloned()
        }
    }

    // ── extension matcher ─────────────────────────────────────────────────

    #[test]
    fn ext_matches_case_insensitive() {
        assert!(has_ocr_ext("scan.pdf"));
        assert!(has_ocr_ext("Photo.JPG"));
        assert!(!has_ocr_ext("notes.md"));
    }

    // ── DOB normalisation ─────────────────────────────────────────────────

    #[test]
    fn dob_normalises_two_digit_year() {
        assert_eq!(
            normalise_dob(15, 6, 81).unwrap(),
            NaiveDate::from_ymd_opt(1981, 6, 15).unwrap()
        );
        assert_eq!(
            normalise_dob(15, 6, 5).unwrap(),
            NaiveDate::from_ymd_opt(2005, 6, 15).unwrap()
        );
    }

    #[test]
    fn dob_rejects_out_of_range() {
        assert!(normalise_dob(32, 13, 1980).is_none());
        assert!(normalise_dob(15, 6, 1850).is_none());
    }

    // ── name extraction ───────────────────────────────────────────────────

    #[test]
    fn name_extracts_first_non_stopword_pair() {
        let txt = "Пациент: Феридзе Майя\nАнализ крови от 01.05.1981";
        let (s, n) = extract_name_pair(txt);
        assert_eq!(s.as_deref(), Some("Феридзе"));
        assert_eq!(n.as_deref(), Some("Майя"));
    }

    #[test]
    fn name_skips_stopwords() {
        let txt = "Пациентка Иванова Анна\nДоктор Петров";
        let (s, n) = extract_name_pair(txt);
        assert_eq!(s.as_deref(), Some("Иванова"));
        assert_eq!(n.as_deref(), Some("Анна"));
    }

    #[test]
    fn name_returns_none_when_no_pair() {
        let (s, n) = extract_name_pair("text without uppercased cyrillic words");
        assert!(s.is_none());
        assert!(n.is_none());
    }

    // ── DOB extraction ────────────────────────────────────────────────────

    #[test]
    fn dob_extracts_labelled_form() {
        let txt = "Дата рождения: 15.06.1981";
        let dob = extract_dob(txt).unwrap();
        assert_eq!(dob, NaiveDate::from_ymd_opt(1981, 6, 15).unwrap());
    }

    #[test]
    fn dob_falls_back_to_generic_date() {
        let txt = "Анализ крови, забор 01.05.1981, отчёт сегодня";
        let dob = extract_dob(txt).unwrap();
        assert_eq!(dob, NaiveDate::from_ymd_opt(1981, 5, 1).unwrap());
    }

    #[test]
    fn dob_none_when_no_match() {
        assert!(extract_dob("nothing parseable here").is_none());
    }

    // ── folder naming ─────────────────────────────────────────────────────

    #[test]
    fn folder_name_uses_dob_when_known() {
        let c = Classification {
            surname: Some("Феридзе".into()),
            name: Some("Майя".into()),
            dob: NaiveDate::from_ymd_opt(1981, 5, 1),
            text_excerpt: String::new(),
        };
        assert_eq!(patient_folder_name(&c), "Феридзе_Майя_1981_05_01");
    }

    #[test]
    fn folder_name_uses_sentinel_when_dob_unknown() {
        let c = Classification {
            surname: Some("Иванов".into()),
            name: Some("Иван".into()),
            dob: None,
            text_excerpt: String::new(),
        };
        assert_eq!(patient_folder_name(&c), "Иванов_Иван_2000_01_01");
    }

    #[test]
    fn folder_name_strips_unsafe_chars() {
        let c = Classification {
            surname: Some("Smith/Jones".into()),
            name: Some("J.R.".into()),
            dob: NaiveDate::from_ymd_opt(2000, 1, 1),
            text_excerpt: String::new(),
        };
        let n = patient_folder_name(&c);
        assert!(n.starts_with("Smith_Jones_"));
        assert!(n.contains("J_R_") || n.contains("J_R"));
    }

    #[test]
    fn folder_name_truncates_to_40() {
        let c = Classification {
            surname: Some("Ё".repeat(60)),
            name: Some("Я".repeat(60)),
            dob: None,
            text_excerpt: String::new(),
        };
        let n = patient_folder_name(&c);
        let parts: Vec<&str> = n.split('_').collect();
        // surname (40) + name (40) + 3 date segments (Y, m, d)
        assert!(parts[0].chars().count() <= 40);
        assert!(parts[1].chars().count() <= 40);
    }

    // ── orchestration ─────────────────────────────────────────────────────

    #[test]
    fn process_one_returns_not_found_when_missing() {
        let ocr = MapOcr::new();
        let fs = StubFs::new();
        let r = process_one("/X/y.pdf", &ocr, &fs, "/Patients", true);
        assert_eq!(r.outcome, Outcome::NotFound);
    }

    #[test]
    fn process_one_returns_ocr_failed_when_no_text() {
        let ocr = MapOcr::new();
        let mut fs = StubFs::new();
        fs.add("/Patients/INBOX/scan.pdf");
        let r = process_one("/Patients/INBOX/scan.pdf", &ocr, &fs, "/Patients", true);
        assert_eq!(r.outcome, Outcome::OcrFailed);
    }

    #[test]
    fn process_one_returns_ambiguous_when_no_name() {
        let ocr = MapOcr::new();
        ocr.set(
            "/Patients/INBOX/scan.pdf",
            "Just some boring text without any names",
        );
        let mut fs = StubFs::new();
        fs.add("/Patients/INBOX/scan.pdf");
        let r = process_one("/Patients/INBOX/scan.pdf", &ocr, &fs, "/Patients", true);
        assert_eq!(r.outcome, Outcome::Ambiguous);
        assert!(r.classification.is_some());
    }

    #[test]
    fn process_one_dry_run_emits_target_path() {
        let ocr = MapOcr::new();
        ocr.set(
            "/Patients/INBOX/scan.pdf",
            "Пациент Феридзе Майя\nДата рождения: 15.06.1981",
        );
        let mut fs = StubFs::new();
        fs.add("/Patients/INBOX/scan.pdf");
        let r = process_one("/Patients/INBOX/scan.pdf", &ocr, &fs, "/Patients", true);
        assert_eq!(r.outcome, Outcome::MovedDryRun);
        let target = r.moved_to.unwrap();
        assert_eq!(target, "/Patients/Феридзе_Майя_1981_06_15/scan.pdf");
    }

    #[test]
    fn candidates_filters_by_extension() {
        let mut fs = StubFs::new();
        fs.add("/Patients/INBOX/scan.pdf");
        fs.add("/Patients/INBOX/report.docx");
        fs.add("/Patients/INBOX/photo.JPG");
        fs.add("/Patients/INBOX/sub/nested.pdf"); // ignored: subdir
        let c = candidates(&fs, "/Patients/INBOX");
        assert_eq!(c.len(), 2);
        assert!(c.iter().any(|p| p.ends_with("scan.pdf")));
        assert!(c.iter().any(|p| p.ends_with("photo.JPG")));
    }

    #[test]
    fn process_inbox_walks_all_candidates() {
        let mut fs = StubFs::new();
        fs.add("/Patients/INBOX/a.pdf");
        fs.add("/Patients/INBOX/b.pdf");
        let ocr = MapOcr::new();
        ocr.set(
            "/Patients/INBOX/a.pdf",
            "Пациент Сидоров Пётр\nДата рождения: 10.10.1970",
        );
        ocr.set("/Patients/INBOX/b.pdf", "no names here");
        let actions = process_inbox(&fs, &ocr, "/Patients", "/Patients/INBOX", true);
        assert_eq!(actions.len(), 2);
        let by_file: BTreeMap<&str, &Action> =
            actions.iter().map(|a| (a.file.as_str(), a)).collect();
        assert_eq!(by_file["/Patients/INBOX/a.pdf"].outcome, Outcome::MovedDryRun);
        assert_eq!(by_file["/Patients/INBOX/b.pdf"].outcome, Outcome::Ambiguous);
    }
}
