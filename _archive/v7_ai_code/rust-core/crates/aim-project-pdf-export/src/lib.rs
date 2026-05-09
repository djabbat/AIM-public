//! aim-project-pdf-export — markdown → HTML/PDF (PE1).
//!
//! Port of `agents/project_pdf_export.py`. Pipeline:
//!   morning_brief + readme → markdown → pandoc (or fallback HTML) → file.
//!
//! Pandoc is abstracted behind [`PandocBackend`] so the markdown→HTML
//! fallback + filename composition + content composition are testable
//! without pandoc on PATH.

use std::path::{Path, PathBuf};

use chrono::{DateTime, NaiveDate, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PdfError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("backend error: {0}")]
    Backend(String),
}

pub type Result<T> = std::result::Result<T, PdfError>;

// ── markdown composition ───────────────────────────────────────────────────

pub trait MarkdownSource: Send + Sync {
    fn morning_brief(&self, project: &str) -> Option<String>;
    fn readme(&self, project: &str) -> Option<String>;
}

pub struct EmptyMarkdownSource;
impl MarkdownSource for EmptyMarkdownSource {
    fn morning_brief(&self, _: &str) -> Option<String> {
        None
    }
    fn readme(&self, _: &str) -> Option<String> {
        None
    }
}

/// Concatenate brief + README into one markdown blob suitable for pandoc.
/// Mirrors Python `render_markdown`.
pub fn render_markdown(project: &str, today: NaiveDate, source: &dyn MarkdownSource) -> String {
    let mut parts: Vec<String> = Vec::new();
    parts.push(format!("# {} — snapshot {}\n", project, today));

    match source.morning_brief(project) {
        Some(b) => {
            parts.push("## Morning brief\n".into());
            parts.push("```".into());
            parts.push(b);
            parts.push("```\n".into());
        }
        None => parts.push("_(brief failed: source unavailable)_\n".into()),
    }

    match source.readme(project) {
        Some(r) => parts.push(r),
        None => parts.push("_(README generation failed: source unavailable)_\n".into()),
    }

    parts.join("\n")
}

// ── HTML fallback ──────────────────────────────────────────────────────────

pub fn html_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn inline(text: &str) -> String {
    let escaped = html_escape(text);
    // bold **…**
    let bold = Regex::new(r"\*\*([^*]+)\*\*").unwrap();
    let with_bold = bold.replace_all(&escaped, "<strong>$1</strong>").into_owned();
    // inline `code`
    let code = Regex::new(r"`([^`]+)`").unwrap();
    let with_code = code.replace_all(&with_bold, "<code>$1</code>").into_owned();
    // emphasis *…* (not part of **…**) — use lookarounds approximated
    let em = Regex::new(r"(^|[^*])\*([^*]+)\*(?:$|[^*])").unwrap();
    em.replace_all(&with_code, "$1<em>$2</em>").into_owned()
}

fn wrap_html(title: &str, body: &str) -> String {
    format!(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title>\
<style>body{{font-family:Helvetica,Arial,sans-serif;max-width:46em;margin:2em auto;padding:0 1em;line-height:1.45}}\
h1,h2,h3,h4{{margin-top:1.5em}}\
pre{{background:#f5f5f5;padding:0.6em;overflow-x:auto;border-radius:4px}}\
code{{font-family:ui-monospace,Menlo,monospace;font-size:0.9em}}\
li{{margin:0.2em 0}}</style></head><body>{body}</body></html>",
        title = html_escape(title),
        body = body
    )
}

/// Best-effort markdown→HTML when pandoc is missing.
/// Handles ATX headings (#-####), bullet lists, fenced code, paragraph
/// breaks, inline emphasis. Mirrors `_markdown_to_html_fallback`.
pub fn markdown_to_html_fallback(md: &str, title: &str) -> String {
    let mut out: Vec<String> = Vec::new();
    let mut in_code = false;
    let mut in_list = false;

    let heading_re = Regex::new(r"^(#{1,4})\s+(.*)$").unwrap();
    let bullet_re = Regex::new(r"^\s*[-•]\s+(.*)$").unwrap();

    fn close_list(out: &mut Vec<String>, in_list: &mut bool) {
        if *in_list {
            out.push("</ul>".into());
            *in_list = false;
        }
    }

    for raw in md.lines() {
        let line = raw.trim_end();
        if line.starts_with("```") {
            close_list(&mut out, &mut in_list);
            if !in_code {
                out.push("<pre><code>".into());
                in_code = true;
            } else {
                out.push("</code></pre>".into());
                in_code = false;
            }
            continue;
        }
        if in_code {
            out.push(html_escape(line));
            continue;
        }
        if let Some(c) = heading_re.captures(line) {
            close_list(&mut out, &mut in_list);
            let level = c.get(1).map(|m| m.as_str().len()).unwrap_or(1);
            let body = c.get(2).map(|m| m.as_str()).unwrap_or("");
            out.push(format!("<h{}>{}</h{}>", level, html_escape(body), level));
            continue;
        }
        if let Some(c) = bullet_re.captures(line) {
            if !in_list {
                out.push("<ul>".into());
                in_list = true;
            }
            let body = c.get(1).map(|m| m.as_str()).unwrap_or("");
            out.push(format!("<li>{}</li>", inline(body)));
            continue;
        }
        if line.trim().is_empty() {
            close_list(&mut out, &mut in_list);
            out.push(String::new());
            continue;
        }
        close_list(&mut out, &mut in_list);
        out.push(format!("<p>{}</p>", inline(line)));
    }
    if in_list {
        out.push("</ul>".into());
    }
    if in_code {
        out.push("</code></pre>".into());
    }

    let body = out.join("\n");
    wrap_html(title, &body)
}

// ── pandoc backend ─────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PandocTarget {
    Html5,
    Pdf,
}

pub trait PandocBackend: Send + Sync {
    /// `Ok(Some(bytes))` on success, `Ok(None)` if pandoc isn't on PATH,
    /// `Err(...)` for execution failure.
    fn render(&self, markdown: &str, title: &str, target: PandocTarget) -> Result<Option<Vec<u8>>>;
}

pub struct UnavailablePandoc;
impl PandocBackend for UnavailablePandoc {
    fn render(&self, _: &str, _: &str, _: PandocTarget) -> Result<Option<Vec<u8>>> {
        Ok(None)
    }
}

// ── output composition ─────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExportPaths {
    pub html: Option<PathBuf>,
    pub pdf: Option<PathBuf>,
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct FixedClock(pub DateTime<Utc>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

pub fn default_dest(project: &str, root: &Path, now: DateTime<Utc>, ext: &str) -> PathBuf {
    let stamp = now.format("%Y%m%d-%H%M%S").to_string();
    root.join(format!("{}-{}.{}", project, stamp, ext))
}

/// Export HTML. Tries pandoc first; falls back to pure-Rust HTML when
/// pandoc returns None or fails. Always succeeds.
pub fn export_html(
    project: &str,
    today: NaiveDate,
    source: &dyn MarkdownSource,
    pandoc: &dyn PandocBackend,
    dest: &Path,
) -> Result<PathBuf> {
    let md = render_markdown(project, today, source);
    let title = format!("{} — {}", project, today);
    let body = match pandoc.render(&md, &title, PandocTarget::Html5)? {
        Some(bytes) => String::from_utf8_lossy(&bytes).to_string(),
        None => markdown_to_html_fallback(&md, &title),
    };
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(dest, body)?;
    Ok(dest.to_path_buf())
}

/// Try pandoc → PDF. Returns `Ok(None)` when pandoc isn't available
/// (caller should fall back to `export_html`).
pub fn export_pdf(
    project: &str,
    today: NaiveDate,
    source: &dyn MarkdownSource,
    pandoc: &dyn PandocBackend,
    dest: &Path,
) -> Result<Option<PathBuf>> {
    let md = render_markdown(project, today, source);
    let title = format!("{} — {}", project, today);
    match pandoc.render(&md, &title, PandocTarget::Pdf)? {
        Some(bytes) => {
            if let Some(parent) = dest.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(dest, bytes)?;
            Ok(Some(dest.to_path_buf()))
        }
        None => Ok(None),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    struct StubSource {
        brief: Option<String>,
        readme: Option<String>,
    }
    impl MarkdownSource for StubSource {
        fn morning_brief(&self, _: &str) -> Option<String> {
            self.brief.clone()
        }
        fn readme(&self, _: &str) -> Option<String> {
            self.readme.clone()
        }
    }

    struct ConstantPandoc {
        bytes: Option<Vec<u8>>,
    }
    impl PandocBackend for ConstantPandoc {
        fn render(&self, _: &str, _: &str, _: PandocTarget) -> Result<Option<Vec<u8>>> {
            Ok(self.bytes.clone())
        }
    }

    fn today() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 5, 5).unwrap()
    }

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 5, 12, 30, 45).unwrap()
    }

    // ── render_markdown ────────────────────────────────────────────────────

    #[test]
    fn render_markdown_includes_title_and_sections() {
        let s = StubSource {
            brief: Some("brief body".into()),
            readme: Some("# README\nfoo".into()),
        };
        let md = render_markdown("FCLC", today(), &s);
        assert!(md.starts_with("# FCLC — snapshot 2026-05-05"));
        assert!(md.contains("## Morning brief"));
        assert!(md.contains("brief body"));
        assert!(md.contains("# README"));
    }

    #[test]
    fn render_markdown_emits_failure_marker_when_brief_missing() {
        let s = StubSource {
            brief: None,
            readme: Some("ok".into()),
        };
        let md = render_markdown("X", today(), &s);
        assert!(md.contains("brief failed"));
    }

    #[test]
    fn render_markdown_emits_failure_marker_when_readme_missing() {
        let s = StubSource {
            brief: Some("ok".into()),
            readme: None,
        };
        let md = render_markdown("X", today(), &s);
        assert!(md.contains("README generation failed"));
    }

    // ── html_escape ────────────────────────────────────────────────────────

    #[test]
    fn html_escape_special_chars() {
        assert_eq!(html_escape("a<b>"), "a&lt;b&gt;");
        assert_eq!(html_escape("\"q\""), "&quot;q&quot;");
        assert_eq!(html_escape("a&b"), "a&amp;b");
    }

    // ── markdown_to_html_fallback ──────────────────────────────────────────

    #[test]
    fn fallback_renders_headings() {
        let md = "# Big\n## Mid\n### Small";
        let html = markdown_to_html_fallback(md, "T");
        assert!(html.contains("<h1>Big</h1>"));
        assert!(html.contains("<h2>Mid</h2>"));
        assert!(html.contains("<h3>Small</h3>"));
    }

    #[test]
    fn fallback_renders_bullet_list() {
        let md = "- one\n- two\n- three";
        let html = markdown_to_html_fallback(md, "T");
        assert!(html.contains("<ul>"));
        assert!(html.contains("<li>one</li>"));
        assert!(html.contains("<li>three</li>"));
        assert!(html.contains("</ul>"));
    }

    #[test]
    fn fallback_renders_fenced_code() {
        let md = "```\nfn main() {}\n```";
        let html = markdown_to_html_fallback(md, "T");
        assert!(html.contains("<pre><code>"));
        assert!(html.contains("fn main() {}"));
        assert!(html.contains("</code></pre>"));
    }

    #[test]
    fn fallback_escapes_html_in_code_blocks() {
        let md = "```\n<script>x</script>\n```";
        let html = markdown_to_html_fallback(md, "T");
        assert!(html.contains("&lt;script&gt;"));
        assert!(!html.contains("<script>"));
    }

    #[test]
    fn fallback_inline_bold_and_code() {
        let md = "Hello **world** and `code` here";
        let html = markdown_to_html_fallback(md, "T");
        assert!(html.contains("<strong>world</strong>"));
        assert!(html.contains("<code>code</code>"));
    }

    #[test]
    fn fallback_wraps_paragraphs_in_p() {
        let md = "Plain paragraph.\n\nAnother one.";
        let html = markdown_to_html_fallback(md, "T");
        assert!(html.contains("<p>Plain paragraph.</p>"));
        assert!(html.contains("<p>Another one.</p>"));
    }

    #[test]
    fn fallback_includes_title_in_head() {
        let html = markdown_to_html_fallback("body", "FCLC report");
        assert!(html.contains("<title>FCLC report</title>"));
    }

    // ── default_dest ───────────────────────────────────────────────────────

    #[test]
    fn default_dest_renders_extension_and_timestamp() {
        let p = default_dest("FCLC", Path::new("/tmp/exports"), now(), "html");
        assert_eq!(
            p,
            PathBuf::from("/tmp/exports/FCLC-20260505-123045.html")
        );
        let p2 = default_dest("FCLC", Path::new("/tmp/exports"), now(), "pdf");
        assert!(p2.to_string_lossy().ends_with(".pdf"));
    }

    // ── export_html ────────────────────────────────────────────────────────

    #[test]
    fn export_html_uses_pandoc_when_available() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("out.html");
        let s = StubSource {
            brief: Some("b".into()),
            readme: Some("r".into()),
        };
        let pandoc = ConstantPandoc {
            bytes: Some(b"<html>pandoc body</html>".to_vec()),
        };
        let r = export_html("X", today(), &s, &pandoc, &dest).unwrap();
        let written = std::fs::read_to_string(&r).unwrap();
        assert!(written.contains("pandoc body"));
    }

    #[test]
    fn export_html_falls_back_when_pandoc_missing() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("out.html");
        let s = StubSource {
            brief: Some("brief content".into()),
            readme: Some("# Title\nbody text".into()),
        };
        let pandoc = UnavailablePandoc;
        export_html("X", today(), &s, &pandoc, &dest).unwrap();
        let written = std::fs::read_to_string(&dest).unwrap();
        assert!(written.contains("<title>"));
        assert!(written.contains("brief content"));
        assert!(written.contains("<h1>Title</h1>"));
    }

    // ── export_pdf ─────────────────────────────────────────────────────────

    #[test]
    fn export_pdf_writes_when_pandoc_succeeds() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("out.pdf");
        let s = StubSource {
            brief: Some("b".into()),
            readme: Some("r".into()),
        };
        let pandoc = ConstantPandoc {
            bytes: Some(b"%PDF-1.4 fake".to_vec()),
        };
        let r = export_pdf("X", today(), &s, &pandoc, &dest).unwrap().unwrap();
        assert!(r.exists());
        let bytes = std::fs::read(&r).unwrap();
        assert_eq!(&bytes, b"%PDF-1.4 fake");
    }

    #[test]
    fn export_pdf_returns_none_when_pandoc_unavailable() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("out.pdf");
        let s = StubSource {
            brief: Some("b".into()),
            readme: Some("r".into()),
        };
        let pandoc = UnavailablePandoc;
        let r = export_pdf("X", today(), &s, &pandoc, &dest).unwrap();
        assert!(r.is_none());
        assert!(!dest.exists());
    }
}
