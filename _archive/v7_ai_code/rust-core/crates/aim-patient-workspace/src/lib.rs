//! aim-patient-workspace — unified Patient-as-Project view.
//!
//! Per project rule (`feedback_project_core` + `feedback_upgrade_md_rule`),
//! каждый пациент — это проект со своим 11-файловым ядром. Этот crate
//! агрегирует `MEMORY.md` (через `aim-patient-owner::PatientOwner`) +
//! сканирует папку пациента на core files, lab/PDF/OCR файлы, события,
//! и сериализует в один `PatientView` JSON для Phoenix LiveView.
//!
//! Контракт: НЕ изменяет файлы пациента (read-only view). Записи делают
//! отдельные shim'ы (intake / pam_tracker / codesign_log / events).

use std::path::{Path, PathBuf};

use aim_patient_memory::{
    ActivationPoint, CoachingGoal, Condition, Demographics, Medication, PatientMemory,
};
use aim_patient_owner::{patients_dir, OwnerError, PatientOwner};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum WorkspaceError {
    #[error("patient not found: {0}")]
    NotFound(String),
    #[error("owner: {0}")]
    Owner(#[from] OwnerError),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

// ── 11-file core, adapted to patient-as-project ───────────────────────────

/// Список core-файлов для patient-as-project. Семантика:
/// - **MEMORY**: текущее состояние (demographics/allergies/meds/conditions)
/// - **THEORY**: clinical theory of case (working dx, differential, mechanism)
/// - **CONCEPT**: case formulation overview
/// - **STRATEGY**: treatment plan, decision rationale
/// - **PARAMETERS**: lab values trends, vitals, PAM history (numeric)
/// - **TODO**: pending tasks (next labs, recheck, follow-up calls)
/// - **CHANGELOG**: chronological clinical events log
/// - **KNOWLEDGE**: cited references (PMIDs, DOIs)
/// - **MAP**: relationships matrix (med↔condition↔allergy)
/// - **REMINDER**: physician's per-patient reminders
/// - **NEEDTOWRITE**: questions/observations to discuss next visit
/// - **AI_LOG**: kernel decision log (auto-generated)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreFile {
    Memory,
    Theory,
    Concept,
    Strategy,
    Parameters,
    Todo,
    Changelog,
    Knowledge,
    Map,
    Reminder,
    NeedToWrite,
    AiLog,
}

impl CoreFile {
    pub const fn filename(self) -> &'static str {
        match self {
            CoreFile::Memory => "MEMORY.md",
            CoreFile::Theory => "THEORY.md",
            CoreFile::Concept => "CONCEPT.md",
            CoreFile::Strategy => "STRATEGY.md",
            CoreFile::Parameters => "PARAMETERS.md",
            CoreFile::Todo => "TODO.md",
            CoreFile::Changelog => "CHANGELOG.md",
            CoreFile::Knowledge => "KNOWLEDGE.md",
            CoreFile::Map => "MAP.md",
            CoreFile::Reminder => "REMINDER.md",
            CoreFile::NeedToWrite => "NEEDTOWRITE.md",
            CoreFile::AiLog => "AI_LOG.md",
        }
    }

    pub const fn key(self) -> &'static str {
        match self {
            CoreFile::Memory => "memory",
            CoreFile::Theory => "theory",
            CoreFile::Concept => "concept",
            CoreFile::Strategy => "strategy",
            CoreFile::Parameters => "parameters",
            CoreFile::Todo => "todo",
            CoreFile::Changelog => "changelog",
            CoreFile::Knowledge => "knowledge",
            CoreFile::Map => "map",
            CoreFile::Reminder => "reminder",
            CoreFile::NeedToWrite => "needtowrite",
            CoreFile::AiLog => "ai_log",
        }
    }

    pub const fn all() -> &'static [CoreFile] {
        &[
            CoreFile::Memory,
            CoreFile::Theory,
            CoreFile::Concept,
            CoreFile::Strategy,
            CoreFile::Parameters,
            CoreFile::Todo,
            CoreFile::Changelog,
            CoreFile::Knowledge,
            CoreFile::Map,
            CoreFile::Reminder,
            CoreFile::NeedToWrite,
            CoreFile::AiLog,
        ]
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoreFileStatus {
    pub key: String,
    pub filename: String,
    pub present: bool,
    pub size_bytes: u64,
    pub mtime_iso: Option<String>,
}

// ── Lab/file scanning ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum FileKind {
    /// `*_text.txt` — extracted OCR / PDF text (paired with source)
    OcrText,
    /// `*.pdf` — original lab PDF or report
    Pdf,
    /// `*.jpg`, `*.jpeg`, `*.png` — lab photo
    Image,
    /// `_ai_*` / `_report_*` — AI-generated artefact
    AiArtefact,
    /// any other recognised file
    Other,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LabFile {
    pub filename: String,
    pub kind: FileKind,
    pub size_bytes: u64,
    pub mtime_iso: Option<String>,
    /// True if a `<base>_text.txt` companion exists (OCR done).
    pub has_ocr_pair: bool,
}

// ── Activation summary (PAM) ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActivationSummary {
    pub current_score: Option<f64>,
    pub current_level: Option<u8>,
    pub history_count: usize,
    pub last_measured: Option<String>,
}

// ── PatientView — top-level JSON shape ────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PatientView {
    pub id: String,
    pub demographics: Demographics,
    pub allergies: Vec<String>,
    pub medications: Vec<Medication>,
    pub conditions: Vec<Condition>,
    pub history: Vec<String>,
    pub red_flags: Vec<String>,
    pub phase: String,
    pub primary_complaint_undiagnosed: bool,
    pub has_confirmed_dx: bool,
    pub activation: ActivationSummary,
    pub coaching_goals: Vec<CoachingGoal>,
    /// Status of each of the 11 patient-as-project core files.
    pub core_files: Vec<CoreFileStatus>,
    /// Source file count summary by kind.
    pub lab_files: Vec<LabFile>,
    /// Number of lines in `_events.jsonl` (0 if absent).
    pub events_count: u64,
    /// MEMORY.md mtime ISO date.
    pub last_updated: Option<String>,
    /// Folder absolute path (for UI "open in file manager" actions).
    pub folder_path: String,
}

// ── Builder ────────────────────────────────────────────────────────────────

pub struct WorkspaceBuilder {
    patients_root: PathBuf,
}

impl WorkspaceBuilder {
    pub fn new(patients_root: impl Into<PathBuf>) -> Self {
        Self {
            patients_root: patients_root.into(),
        }
    }

    pub fn from_env() -> Self {
        Self::new(patients_dir())
    }

    pub fn patient_dir(&self, id: &str) -> PathBuf {
        self.patients_root.join(id)
    }

    /// Build a `PatientView` for one patient. Errors only on I/O failures
    /// or absence of `MEMORY.md`. Missing optional core files are reported
    /// as `present: false`, not as errors.
    pub fn build(&self, id: &str) -> Result<PatientView, WorkspaceError> {
        let dir = self.patient_dir(id);
        if !dir.is_dir() {
            return Err(WorkspaceError::NotFound(id.into()));
        }

        let owner = PatientOwner::new(&self.patients_root);
        let mem: PatientMemory = owner.load(id)?;

        let core_files = scan_core_files(&dir);
        let lab_files = scan_lab_files(&dir);
        let events_count = count_events(&dir);
        let last_updated = mtime_iso(&dir.join("MEMORY.md"));

        let activation = ActivationSummary {
            current_score: mem.current_activation_score,
            current_level: mem.current_activation_level,
            history_count: mem.activation_history.len(),
            last_measured: latest_activation(&mem.activation_history),
        };

        Ok(PatientView {
            id: mem.id,
            demographics: mem.demographics,
            allergies: mem.allergies,
            medications: mem.medications,
            conditions: mem.conditions,
            history: mem.history,
            red_flags: mem.red_flags,
            phase: mem.phase,
            primary_complaint_undiagnosed: mem.primary_complaint_undiagnosed,
            has_confirmed_dx: mem.has_confirmed_dx,
            activation,
            coaching_goals: mem.coaching_goals,
            core_files,
            lab_files,
            events_count,
            last_updated,
            folder_path: dir.to_string_lossy().into_owned(),
        })
    }

    /// Sorted list of patient ids (deferred to `aim-patient-owner` to keep
    /// behaviour identical with the existing `/patients` index).
    pub fn list(&self) -> Vec<String> {
        PatientOwner::new(&self.patients_root).list_patients()
    }
}

// ── Helpers ────────────────────────────────────────────────────────────────

fn scan_core_files(dir: &Path) -> Vec<CoreFileStatus> {
    CoreFile::all()
        .iter()
        .map(|cf| {
            let path = dir.join(cf.filename());
            let (present, size, mtime) = match std::fs::metadata(&path) {
                Ok(meta) => (
                    true,
                    meta.len(),
                    meta.modified().ok().and_then(systime_to_iso),
                ),
                Err(_) => (false, 0, None),
            };
            CoreFileStatus {
                key: cf.key().into(),
                filename: cf.filename().into(),
                present,
                size_bytes: size,
                mtime_iso: mtime,
            }
        })
        .collect()
}

fn scan_lab_files(dir: &Path) -> Vec<LabFile> {
    let mut out: Vec<LabFile> = Vec::new();
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return out,
    };

    // First pass: collect filenames to detect OCR pairing.
    let mut all_names: Vec<String> = Vec::new();
    let mut entries_vec: Vec<std::fs::DirEntry> = Vec::new();
    for entry in entries.flatten() {
        if entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            if let Some(name) = entry.file_name().to_str() {
                all_names.push(name.to_string());
                entries_vec.push(entry);
            }
        }
    }

    for entry in entries_vec {
        let name = match entry.file_name().to_str() {
            Some(n) => n.to_string(),
            None => continue,
        };

        // Skip core files — they are tracked separately.
        if CoreFile::all().iter().any(|cf| cf.filename() == name) {
            continue;
        }
        // Skip JSONL state stores (events / pam history / codesign log).
        if name.ends_with(".jsonl") {
            continue;
        }
        // Skip backups.
        if name.contains(".bak-") {
            continue;
        }

        let lower = name.to_lowercase();
        let kind = if name.starts_with('_') {
            FileKind::AiArtefact
        } else if lower.ends_with("_text.txt") {
            FileKind::OcrText
        } else if lower.ends_with(".pdf") {
            FileKind::Pdf
        } else if lower.ends_with(".jpg") || lower.ends_with(".jpeg") || lower.ends_with(".png") {
            FileKind::Image
        } else {
            FileKind::Other
        };

        // OCR pair: `foo.pdf` matches `foo_text.txt` (or `foo.jpg` ↔ `foo_text.txt`).
        let has_ocr_pair = match kind {
            FileKind::Pdf | FileKind::Image => {
                let stem = name
                    .rsplit_once('.')
                    .map(|(s, _)| s.to_string())
                    .unwrap_or_else(|| name.clone());
                let candidate = format!("{stem}_text.txt");
                all_names.iter().any(|n| n == &candidate)
            }
            _ => false,
        };

        let meta = entry.metadata().ok();
        let size_bytes = meta.as_ref().map(|m| m.len()).unwrap_or(0);
        let mtime_iso = meta
            .as_ref()
            .and_then(|m| m.modified().ok())
            .and_then(systime_to_iso);

        out.push(LabFile {
            filename: name,
            kind,
            size_bytes,
            mtime_iso,
            has_ocr_pair,
        });
    }

    // Stable order: by mtime desc when available, else alphabetic.
    out.sort_by(|a, b| match (&b.mtime_iso, &a.mtime_iso) {
        (Some(b), Some(a)) => b.cmp(a),
        _ => a.filename.cmp(&b.filename),
    });
    out
}

fn count_events(dir: &Path) -> u64 {
    let path = dir.join("_events.jsonl");
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return 0,
    };
    content.lines().filter(|l| !l.trim().is_empty()).count() as u64
}

fn latest_activation(hist: &[ActivationPoint]) -> Option<String> {
    hist.iter()
        .max_by_key(|p| p.date)
        .map(|p| p.date.format("%Y-%m-%d").to_string())
}

fn mtime_iso(p: &Path) -> Option<String> {
    std::fs::metadata(p)
        .ok()
        .and_then(|m| m.modified().ok())
        .and_then(systime_to_iso)
}

fn systime_to_iso(t: std::time::SystemTime) -> Option<String> {
    let dt: chrono::DateTime<chrono::Utc> = t.into();
    Some(dt.format("%Y-%m-%dT%H:%M:%SZ").to_string())
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use aim_patient_memory::{
        write_memory, Demographics, Medication, NoopIndex, PatientMemory,
    };
    use chrono::TimeZone;
    use std::fs;
    use tempfile::TempDir;

    fn ts() -> chrono::DateTime<chrono::Utc> {
        chrono::Utc.with_ymd_and_hms(2026, 5, 6, 0, 0, 0).unwrap()
    }

    fn write_minimal(root: &Path, id: &str, build: impl FnOnce(&mut PatientMemory)) {
        let mut mem = PatientMemory::new(id);
        build(&mut mem);
        let clk = aim_patient_memory::FixedClock(ts());
        let idx = NoopIndex;
        write_memory(root, &mem, &clk, &idx).unwrap();
    }

    #[test]
    fn build_returns_not_found_for_missing_dir() {
        let tmp = TempDir::new().unwrap();
        let b = WorkspaceBuilder::new(tmp.path());
        let err = b.build("ghost").unwrap_err();
        assert!(matches!(err, WorkspaceError::NotFound(_)));
    }

    #[test]
    fn build_returns_view_with_memory_only() {
        let tmp = TempDir::new().unwrap();
        write_minimal(tmp.path(), "Doe_Jane_1990_01_01", |m| {
            m.demographics = Demographics {
                age: Some(35),
                sex: Some("F".into()),
                country: Some("GE".into()),
            };
            m.allergies = vec!["penicillin".into()];
            m.medications = vec![Medication {
                name: "ibuprofen".into(),
                dose: Some("200mg".into()),
                freq: Some("BID".into()),
            }];
            m.phase = "INTAKE".into();
        });

        let view = WorkspaceBuilder::new(tmp.path())
            .build("Doe_Jane_1990_01_01")
            .unwrap();
        assert_eq!(view.id, "Doe_Jane_1990_01_01");
        assert_eq!(view.demographics.age, Some(35));
        assert_eq!(view.allergies, vec!["penicillin".to_string()]);
        assert_eq!(view.medications.len(), 1);
        assert_eq!(view.phase, "INTAKE");
        assert_eq!(view.events_count, 0);

        // Core file presence: only MEMORY should be reported as present.
        let memory = view.core_files.iter().find(|c| c.key == "memory").unwrap();
        assert!(memory.present);
        let theory = view.core_files.iter().find(|c| c.key == "theory").unwrap();
        assert!(!theory.present);
        // 12 entries (the full 11-file core + AI_LOG).
        assert_eq!(view.core_files.len(), CoreFile::all().len());
    }

    #[test]
    fn detects_extra_core_files() {
        let tmp = TempDir::new().unwrap();
        write_minimal(tmp.path(), "X_Y_2000_01_01", |_m| {});
        let dir = tmp.path().join("X_Y_2000_01_01");
        fs::write(dir.join("THEORY.md"), "# theory\n").unwrap();
        fs::write(dir.join("STRATEGY.md"), "# strategy\n").unwrap();
        fs::write(dir.join("AI_LOG.md"), "log\n").unwrap();

        let view = WorkspaceBuilder::new(tmp.path())
            .build("X_Y_2000_01_01")
            .unwrap();
        let theory = view.core_files.iter().find(|c| c.key == "theory").unwrap();
        let strategy = view.core_files.iter().find(|c| c.key == "strategy").unwrap();
        let ai_log = view.core_files.iter().find(|c| c.key == "ai_log").unwrap();
        assert!(theory.present);
        assert!(strategy.present);
        assert!(ai_log.present);
    }

    #[test]
    fn scans_lab_files_with_ocr_pairing() {
        let tmp = TempDir::new().unwrap();
        write_minimal(tmp.path(), "P_1980_01_01", |_m| {});
        let dir = tmp.path().join("P_1980_01_01");
        fs::write(dir.join("CBC.pdf"), b"%PDF-1.4 fake").unwrap();
        fs::write(dir.join("CBC_text.txt"), "Hgb 13").unwrap();
        fs::write(dir.join("Hand.jpg"), b"\xff\xd8\xff").unwrap();
        fs::write(dir.join("note.txt"), "note").unwrap();
        fs::write(dir.join("_ai_analysis.txt"), "analysis").unwrap();
        fs::write(dir.join("_events.jsonl"), "{}\n{}\n").unwrap();

        let view = WorkspaceBuilder::new(tmp.path())
            .build("P_1980_01_01")
            .unwrap();

        // _events.jsonl excluded from lab_files; it's a state store.
        assert!(view.lab_files.iter().all(|f| f.filename != "_events.jsonl"));
        // Found CBC.pdf with OCR pair, CBC_text.txt, Hand.jpg without pair.
        let pdf = view.lab_files.iter().find(|f| f.filename == "CBC.pdf").unwrap();
        assert_eq!(pdf.kind, FileKind::Pdf);
        assert!(pdf.has_ocr_pair);
        let txt = view.lab_files.iter().find(|f| f.filename == "CBC_text.txt").unwrap();
        assert_eq!(txt.kind, FileKind::OcrText);
        let img = view.lab_files.iter().find(|f| f.filename == "Hand.jpg").unwrap();
        assert_eq!(img.kind, FileKind::Image);
        assert!(!img.has_ocr_pair);
        let ai = view.lab_files.iter().find(|f| f.filename == "_ai_analysis.txt").unwrap();
        assert_eq!(ai.kind, FileKind::AiArtefact);

        assert_eq!(view.events_count, 2);
    }

    #[test]
    fn list_delegates_to_owner() {
        let tmp = TempDir::new().unwrap();
        write_minimal(tmp.path(), "A_2000_01_01", |_m| {});
        write_minimal(tmp.path(), "B_2000_01_01", |_m| {});
        let b = WorkspaceBuilder::new(tmp.path());
        let l = b.list();
        assert_eq!(l, vec!["A_2000_01_01".to_string(), "B_2000_01_01".to_string()]);
    }
}
