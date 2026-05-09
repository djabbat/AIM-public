//! aim-intake — OCR / PDF / WhatsApp ingest entry-point.
//!
//! Port of `agents/intake.py`. The Python original shells out to
//! `pytesseract` / `rapidocr` / `pymupdf` / `pdfplumber`. Rust has no
//! mature, BSD-licensed equivalents; the port keeps every backend behind
//! a trait so production binaries can wire in subprocess shims (matching
//! the AIM/CLAUDE.md "Python only for legacy OCR/PDF" exception) while
//! tests use synthetic stubs.
//!
//! Provides:
//!   • [`extract_text`] — dispatch by extension
//!   • [`parse_whatsapp_name`] / [`parse_whatsapp_export`] — pure regex parsing
//!   • [`scan_inbox`] — INBOX directory enumeration
//!   • [`IntakeAgent`] — analyze_labs() with localized system prompts

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum IntakeError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("llm error: {0}")]
    Llm(String),
}

pub type Result<T> = std::result::Result<T, IntakeError>;

// ── supported extensions ────────────────────────────────────────────────────

pub static IMAGE_EXTS: &[&str] = &["png", "jpg", "jpeg", "bmp", "tiff", "webp"];
pub static PDF_EXTS: &[&str] = &["pdf"];
pub static TEXT_EXTS: &[&str] = &["txt", "csv", "md"];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum FileKind {
    Image,
    Pdf,
    Text,
    Unsupported,
}

impl FileKind {
    pub fn from_extension(ext: &str) -> Self {
        let lower = ext.to_lowercase();
        if IMAGE_EXTS.contains(&lower.as_str()) {
            Self::Image
        } else if PDF_EXTS.contains(&lower.as_str()) {
            Self::Pdf
        } else if TEXT_EXTS.contains(&lower.as_str()) {
            Self::Text
        } else {
            Self::Unsupported
        }
    }

    pub fn from_path(path: &Path) -> Self {
        path.extension()
            .and_then(|s| s.to_str())
            .map(Self::from_extension)
            .unwrap_or(Self::Unsupported)
    }
}

// ── extraction backends ─────────────────────────────────────────────────────

pub trait OcrBackend: Send + Sync {
    fn ocr(&self, path: &Path) -> Result<Option<String>>;
}

pub trait PdfBackend: Send + Sync {
    fn parse(&self, path: &Path) -> Result<Option<String>>;
}

/// Always-fails OCR backend (production may chain `tesseract` then
/// `rapidocr` shims; tests use this when no OCR is wired up).
pub struct UnavailableOcr;
impl OcrBackend for UnavailableOcr {
    fn ocr(&self, _path: &Path) -> Result<Option<String>> {
        Ok(None)
    }
}

pub struct UnavailablePdf;
impl PdfBackend for UnavailablePdf {
    fn parse(&self, _path: &Path) -> Result<Option<String>> {
        Ok(None)
    }
}

/// Dispatch by file kind. Mirrors Python `extract_text`:
///   • image → OCR backend; on `None` returns `[OCR недоступен: <name>]`
///   • pdf → PDF backend; on `None` returns `[PDF парсинг недоступен: <name>]`
///   • text → reads file (UTF-8 lossy)
///   • other → `[Неподдерживаемый формат: <ext>]`
pub fn extract_text(path: &Path, ocr: &dyn OcrBackend, pdf: &dyn PdfBackend) -> Result<String> {
    let kind = FileKind::from_path(path);
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("?");
    match kind {
        FileKind::Image => match ocr.ocr(path)? {
            Some(t) if !t.trim().is_empty() => Ok(t),
            _ => Ok(format!("[OCR недоступен: {}]", name)),
        },
        FileKind::Pdf => match pdf.parse(path)? {
            Some(t) if !t.trim().is_empty() => Ok(t),
            _ => Ok(format!("[PDF парсинг недоступен: {}]", name)),
        },
        FileKind::Text => Ok(std::fs::read_to_string(path).unwrap_or_else(|e| {
            format!("[Ошибка чтения: {}]", e)
        })),
        FileKind::Unsupported => Ok(format!(
            "[Неподдерживаемый формат: .{}]",
            path.extension()
                .and_then(|s| s.to_str())
                .unwrap_or("?")
        )),
    }
}

// ── WhatsApp parsing ────────────────────────────────────────────────────────

/// Matches "SURNAME P FIRSTNAME" with the latin/cyrillic/Georgian middle
/// initial (`P` / `П` / `პ`). Returns "SURNAME FIRSTNAME" or `None`.
pub fn parse_whatsapp_name(contact: &str) -> Option<String> {
    let re = Regex::new(r"(?i)^(.+?)\s+[PПპ]\s+(.+)$").ok()?;
    let cap = re.captures(contact.trim())?;
    Some(format!(
        "{} {}",
        cap.get(1)?.as_str().trim(),
        cap.get(2)?.as_str().trim()
    ))
}

static WHATSAPP_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?m)^\[?(\d{1,2}[./]\d{1,2}[./]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+([^:]+):\s+(.+)$",
    )
    .expect("whatsapp regex compiles")
});

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct WhatsAppPatient {
    pub name: String,
    pub messages: Vec<String>,
}

/// Parse WhatsApp export text. Returns one entry per recognised patient
/// (sender name parsable via [`parse_whatsapp_name`]).
pub fn parse_whatsapp_export(text: &str) -> Vec<WhatsAppPatient> {
    let mut by_name: HashMap<String, Vec<String>> = HashMap::new();
    let mut order: Vec<String> = Vec::new();
    for cap in WHATSAPP_LINE_RE.captures_iter(text) {
        let sender = match cap.get(3) {
            Some(m) => m.as_str().trim(),
            None => continue,
        };
        let content = match cap.get(4) {
            Some(m) => m.as_str().trim(),
            None => continue,
        };
        if let Some(name) = parse_whatsapp_name(sender) {
            if !by_name.contains_key(&name) {
                order.push(name.clone());
            }
            by_name.entry(name).or_default().push(content.to_string());
        }
    }
    order
        .into_iter()
        .map(|name| {
            let messages = by_name.remove(&name).unwrap_or_default();
            WhatsAppPatient { name, messages }
        })
        .collect()
}

// ── inbox scan ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InboxEntry {
    pub path: PathBuf,
    pub text: String,
    pub kind: FileKind,
}

/// Walk `inbox` (one level deep), extract text for each supported file.
/// Returns empty vec if the directory is missing or empty.
pub fn scan_inbox(
    inbox: &Path,
    ocr: &dyn OcrBackend,
    pdf: &dyn PdfBackend,
) -> Result<Vec<InboxEntry>> {
    if !inbox.exists() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    let mut entries: Vec<PathBuf> = std::fs::read_dir(inbox)?
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().map(|t| t.is_file()).unwrap_or(false))
        .map(|e| e.path())
        .filter(|p| FileKind::from_path(p) != FileKind::Unsupported)
        .collect();
    entries.sort();
    for path in entries {
        let kind = FileKind::from_path(&path);
        let text = extract_text(&path, ocr, pdf)?;
        out.push(InboxEntry { path, text, kind });
    }
    Ok(out)
}

// ── analyze_labs ────────────────────────────────────────────────────────────

pub trait Llm: Send + Sync {
    fn ask(&self, system: &str, prompt: &str, lang: &str) -> Result<String>;
}

pub trait Localizer: Send + Sync {
    fn t(&self, key: &str, lang: &str) -> String;
}

pub struct DefaultLocalizer;
impl Localizer for DefaultLocalizer {
    fn t(&self, key: &str, _lang: &str) -> String {
        match key {
            "error" => "(error)".into(),
            other => other.into(),
        }
    }
}

pub struct IntakeAgent<'a> {
    pub llm: &'a dyn Llm,
    pub localizer: &'a dyn Localizer,
}

impl<'a> IntakeAgent<'a> {
    pub fn new(llm: &'a dyn Llm, localizer: &'a dyn Localizer) -> Self {
        Self { llm, localizer }
    }

    pub fn analyze_labs(&self, text: &str, lang: &str) -> Result<String> {
        if text.trim().is_empty() {
            return Ok(self.localizer.t("error", lang));
        }
        let system = match lang {
            "ru" => "Ты — клинический специалист по лабораторной диагностике. Проанализируй медицинские данные. Выдели отклонения, укажи клиническое значение. Disclaimer в конце обязателен.",
            _ => "You are a clinical laboratory diagnostics specialist. Analyze the medical data. Highlight deviations, state clinical significance. Disclaimer at the end is mandatory.",
        };
        let prompt = format!("Медицинские данные для анализа:\n\n{}", text);
        self.llm.ask(system, &prompt, lang)
    }

    /// Run a file through extract_text → analyze_labs. If extraction returns
    /// a `[…]` diagnostic, propagate it without invoking the LLM.
    pub fn process_file(
        &self,
        path: &Path,
        ocr: &dyn OcrBackend,
        pdf: &dyn PdfBackend,
        lang: &str,
    ) -> Result<String> {
        if !path.exists() {
            return Ok(format!("Файл не найден: {}", path.display()));
        }
        let raw = extract_text(path, ocr, pdf)?;
        if raw.starts_with('[') {
            return Ok(raw);
        }
        self.analyze_labs(&raw, lang)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use tempfile::TempDir;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct ConstOcr(&'static str);
    impl OcrBackend for ConstOcr {
        fn ocr(&self, _path: &Path) -> Result<Option<String>> {
            Ok(Some(self.0.into()))
        }
    }

    struct ConstPdf(&'static str);
    impl PdfBackend for ConstPdf {
        fn parse(&self, _path: &Path) -> Result<Option<String>> {
            Ok(Some(self.0.into()))
        }
    }

    struct CountingLlm {
        canned: String,
        calls: Mutex<Vec<(String, String, String)>>,
    }
    impl CountingLlm {
        fn new(canned: &str) -> Self {
            Self {
                canned: canned.into(),
                calls: Mutex::new(Vec::new()),
            }
        }
    }
    impl Llm for CountingLlm {
        fn ask(&self, system: &str, prompt: &str, lang: &str) -> Result<String> {
            self.calls.lock().push((system.into(), prompt.into(), lang.into()));
            Ok(self.canned.clone())
        }
    }

    // ── FileKind ────────────────────────────────────────────────────────────

    #[test]
    fn file_kind_recognises_each_family() {
        assert_eq!(FileKind::from_extension("png"), FileKind::Image);
        assert_eq!(FileKind::from_extension("PNG"), FileKind::Image);
        assert_eq!(FileKind::from_extension("pdf"), FileKind::Pdf);
        assert_eq!(FileKind::from_extension("md"), FileKind::Text);
        assert_eq!(FileKind::from_extension("docx"), FileKind::Unsupported);
    }

    #[test]
    fn file_kind_from_path_uses_extension() {
        assert_eq!(FileKind::from_path(Path::new("a/b.JPG")), FileKind::Image);
        assert_eq!(FileKind::from_path(Path::new("noext")), FileKind::Unsupported);
    }

    // ── extract_text ────────────────────────────────────────────────────────

    #[test]
    fn extract_text_for_text_file() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.txt");
        std::fs::write(&p, "hello\nworld").unwrap();
        let s = extract_text(&p, &UnavailableOcr, &UnavailablePdf).unwrap();
        assert_eq!(s, "hello\nworld");
    }

    #[test]
    fn extract_text_image_uses_ocr_backend() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("scan.png");
        std::fs::write(&p, b"\x89PNG").unwrap();
        let s = extract_text(&p, &ConstOcr("scanned text"), &UnavailablePdf).unwrap();
        assert_eq!(s, "scanned text");
    }

    #[test]
    fn extract_text_image_unavailable_returns_diagnostic() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("scan.png");
        std::fs::write(&p, b"\x89PNG").unwrap();
        let s = extract_text(&p, &UnavailableOcr, &UnavailablePdf).unwrap();
        assert!(s.contains("[OCR недоступен"));
        assert!(s.contains("scan.png"));
    }

    #[test]
    fn extract_text_pdf_uses_pdf_backend() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("doc.pdf");
        std::fs::write(&p, "%PDF").unwrap();
        let s = extract_text(&p, &UnavailableOcr, &ConstPdf("page text")).unwrap();
        assert_eq!(s, "page text");
    }

    #[test]
    fn extract_text_unsupported_returns_diagnostic() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.docx");
        std::fs::write(&p, "x").unwrap();
        let s = extract_text(&p, &UnavailableOcr, &UnavailablePdf).unwrap();
        assert!(s.contains("Неподдерживаемый формат"));
    }

    // ── WhatsApp ────────────────────────────────────────────────────────────

    #[test]
    fn parse_name_with_latin_p() {
        assert_eq!(
            parse_whatsapp_name("DOE P JOHN"),
            Some("DOE JOHN".to_string())
        );
    }

    #[test]
    fn parse_name_with_cyrillic_p() {
        assert_eq!(
            parse_whatsapp_name("ИВАНОВ П ПЁТР"),
            Some("ИВАНОВ ПЁТР".to_string())
        );
    }

    #[test]
    fn parse_name_with_georgian_p() {
        assert_eq!(
            parse_whatsapp_name("გელაშვილი პ თინა"),
            Some("გელაშვილი თინა".to_string())
        );
    }

    #[test]
    fn parse_name_returns_none_for_no_marker() {
        assert!(parse_whatsapp_name("Just Name").is_none());
    }

    #[test]
    fn parse_export_groups_messages_by_name() {
        let raw = "[01/02/2026, 12:00] DOE P JOHN: hello\n\
                   [01/02/2026, 12:01] DOE P JOHN: how are you\n\
                   [01/02/2026, 12:02] Random User: ignored\n\
                   [01/02/2026, 12:03] SMITH P JANE: hi";
        let patients = parse_whatsapp_export(raw);
        assert_eq!(patients.len(), 2);
        let doe = patients.iter().find(|p| p.name.contains("DOE")).unwrap();
        assert_eq!(doe.messages.len(), 2);
    }

    #[test]
    fn parse_export_empty_returns_empty() {
        assert!(parse_whatsapp_export("").is_empty());
    }

    // ── scan_inbox ──────────────────────────────────────────────────────────

    #[test]
    fn scan_inbox_skips_unsupported_and_subdirs() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("a.txt"), "ok").unwrap();
        std::fs::write(tmp.path().join("b.docx"), "ignored").unwrap();
        std::fs::create_dir_all(tmp.path().join("sub")).unwrap();
        std::fs::write(tmp.path().join("sub/inside.txt"), "deep").unwrap();
        let entries = scan_inbox(tmp.path(), &UnavailableOcr, &UnavailablePdf).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].kind, FileKind::Text);
    }

    #[test]
    fn scan_inbox_missing_dir_returns_empty() {
        let tmp = TempDir::new().unwrap();
        let missing = tmp.path().join("nope");
        let entries = scan_inbox(&missing, &UnavailableOcr, &UnavailablePdf).unwrap();
        assert!(entries.is_empty());
    }

    // ── IntakeAgent ─────────────────────────────────────────────────────────

    #[test]
    fn analyze_labs_empty_returns_localized_error() {
        let llm = CountingLlm::new("ignored");
        let agent = IntakeAgent::new(&llm, &DefaultLocalizer);
        assert_eq!(agent.analyze_labs("   ", "ru").unwrap(), "(error)");
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn analyze_labs_uses_lang_specific_system() {
        let llm = CountingLlm::new("interpretation");
        let agent = IntakeAgent::new(&llm, &DefaultLocalizer);
        agent.analyze_labs("Hb 130", "ru").unwrap();
        assert!(llm.calls.lock()[0].0.contains("клинический"));
        agent.analyze_labs("Hb 130", "en").unwrap();
        assert!(llm.calls.lock()[1].0.contains("clinical"));
    }

    #[test]
    fn process_file_missing_path_returns_diagnostic() {
        let llm = CountingLlm::new("ignored");
        let agent = IntakeAgent::new(&llm, &DefaultLocalizer);
        let r = agent
            .process_file(
                Path::new("/tmp/nonexistent_42_file.txt"),
                &UnavailableOcr,
                &UnavailablePdf,
                "ru",
            )
            .unwrap();
        assert!(r.contains("Файл не найден"));
    }

    #[test]
    fn process_file_propagates_extraction_error_diagnostic() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.png");
        std::fs::write(&p, b"\x89PNG").unwrap();
        let llm = CountingLlm::new("ignored");
        let agent = IntakeAgent::new(&llm, &DefaultLocalizer);
        let r = agent.process_file(&p, &UnavailableOcr, &UnavailablePdf, "ru").unwrap();
        assert!(r.starts_with("[OCR недоступен"));
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn process_file_text_runs_through_analyze_labs() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.txt");
        std::fs::write(&p, "Hb 130\nGlu 5.4").unwrap();
        let llm = CountingLlm::new("interp");
        let agent = IntakeAgent::new(&llm, &DefaultLocalizer);
        let r = agent.process_file(&p, &UnavailableOcr, &UnavailablePdf, "ru").unwrap();
        assert_eq!(r, "interp");
        let prompt = &llm.calls.lock()[0].1;
        assert!(prompt.contains("Hb 130"));
    }
}
