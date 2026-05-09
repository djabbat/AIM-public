//! aim-analyze-claude-memory — pre-migration audit of Claude memory.
//!
//! Port of `scripts/analyze_claude_memory.py`. Inventories
//! `~/.claude/projects/-home-oem/memory/`, classifies files by prefix
//! (`feedback_`, `project_`, `user_`, `contact_`, `reference_`,
//! `fact_`, `pubmed_`), parses YAML-ish frontmatter, and produces a
//! JSON report + a human-readable summary.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

const PREFIXES: &[&str] = &[
    "feedback_",
    "project_",
    "user_",
    "contact_",
    "reference_",
    "fact_",
    "pubmed_",
];

pub fn classify(name: &str) -> &'static str {
    let n = name.to_lowercase();
    for p in PREFIXES {
        if n.starts_with(p) {
            return p.trim_end_matches('_');
        }
    }
    if n == "memory.md" {
        return "index";
    }
    "other"
}

/// Parses YAML-style frontmatter delimited by `---` lines.
/// Mirrors `re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)`.
pub fn parse_frontmatter(text: &str) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if !text.starts_with("---") {
        return out;
    }
    // strip the opening "---" line
    let after_open = match text.find('\n') {
        Some(i) => &text[i + 1..],
        None => return out,
    };
    let close_idx = match after_open.find("\n---") {
        Some(i) => i,
        None => return out,
    };
    let body = &after_open[..close_idx];
    for line in body.lines() {
        if let Some((k, v)) = line.split_once(':') {
            out.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    out
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct FileEntry {
    pub file: String,
    pub size_kb: f64,
    pub mtime: String,
    pub category: String,
    #[serde(rename = "type")]
    pub fm_type: String,
    pub name: String,
    pub description: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AnalysisInput {
    pub filename: String,
    pub size_bytes: i64,
    pub mtime: DateTime<Utc>,
    pub content: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Stats {
    pub scanned_at: String,
    pub source_dir: String,
    pub total_files: u64,
    pub total_size_kb: f64,
    pub categories: BTreeMap<String, u64>,
    pub types: BTreeMap<String, u64>,
    pub with_frontmatter: u64,
    pub files: Vec<FileEntry>,
    pub samples: Vec<Sample>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Sample {
    pub file: String,
    pub first_500_chars: String,
}

pub fn analyze(
    inputs: &[AnalysisInput],
    source_dir: &str,
    scanned_at: DateTime<Utc>,
) -> Stats {
    let mut s = Stats {
        scanned_at: scanned_at.format("%Y-%m-%dT%H:%M:%S").to_string(),
        source_dir: source_dir.to_string(),
        ..Default::default()
    };
    for inp in inputs {
        s.total_files += 1;
        let kb = (inp.size_bytes as f64) / 1024.0;
        s.total_size_kb += kb;
        let cat = classify(&inp.filename);
        *s.categories.entry(cat.to_string()).or_insert(0) += 1;
        let fm = parse_frontmatter(&inp.content);
        if !fm.is_empty() {
            s.with_frontmatter += 1;
            let ty = fm.get("type").cloned().unwrap_or_else(|| "unknown".into());
            *s.types.entry(ty).or_insert(0) += 1;
        }
        let description: String = fm
            .get("description")
            .cloned()
            .unwrap_or_default()
            .chars()
            .take(160)
            .collect();
        s.files.push(FileEntry {
            file: inp.filename.clone(),
            size_kb: round2(kb),
            mtime: inp.mtime.format("%Y-%m-%dT%H:%M:%S").to_string(),
            category: cat.to_string(),
            fm_type: fm.get("type").cloned().unwrap_or_default(),
            name: fm.get("name").cloned().unwrap_or_default(),
            description,
        });
        if s.samples.len() < 5 {
            let first: String = inp.content.chars().take(500).collect();
            s.samples.push(Sample {
                file: inp.filename.clone(),
                first_500_chars: first,
            });
        }
    }
    s.total_size_kb = round1(s.total_size_kb);
    s
}

fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

pub fn render_text_report(s: &Stats) -> String {
    let mut lines = vec![
        format!("AIM — Claude memory audit ({})", s.scanned_at),
        format!("  source:        {}", s.source_dir),
        format!("  files:         {}", s.total_files),
        format!("  size:          {:.1} KB", s.total_size_kb),
        format!(
            "  frontmatter:   {} of {}",
            s.with_frontmatter, s.total_files
        ),
        String::new(),
        "  by category (filename prefix):".to_string(),
    ];
    let mut cats: Vec<(&String, &u64)> = s.categories.iter().collect();
    cats.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in cats {
        lines.push(format!("    {:<12} {}", k, v));
    }
    lines.push(String::new());
    lines.push("  by type (frontmatter):".to_string());
    let mut types: Vec<(&String, &u64)> = s.types.iter().collect();
    types.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in types {
        lines.push(format!("    {:<12} {}", k, v));
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn dt(y: i32, m: u32, d: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, 12, 0, 0).unwrap()
    }

    fn make(name: &str, size: i64, content: &str) -> AnalysisInput {
        AnalysisInput {
            filename: name.into(),
            size_bytes: size,
            mtime: dt(2026, 5, 5),
            content: content.into(),
        }
    }

    // ── classify ──────────────────────────────────────────────────────────

    #[test]
    fn classify_known_prefixes() {
        assert_eq!(classify("feedback_x.md"), "feedback");
        assert_eq!(classify("project_y.md"), "project");
        assert_eq!(classify("user_role.md"), "user");
        assert_eq!(classify("contact_z.md"), "contact");
        assert_eq!(classify("reference_a.md"), "reference");
        assert_eq!(classify("fact_b.md"), "fact");
        assert_eq!(classify("pubmed_c.md"), "pubmed");
    }

    #[test]
    fn classify_memory_index() {
        assert_eq!(classify("MEMORY.md"), "index");
        assert_eq!(classify("memory.md"), "index");
    }

    #[test]
    fn classify_other_falls_back() {
        assert_eq!(classify("random.md"), "other");
        assert_eq!(classify("notes.md"), "other");
    }

    #[test]
    fn classify_case_insensitive() {
        assert_eq!(classify("FEEDBACK_x.md"), "feedback");
    }

    // ── frontmatter ───────────────────────────────────────────────────────

    #[test]
    fn parse_frontmatter_extracts_keys() {
        let text = "---\nname: x\ntype: project\ndescription: foo bar\n---\nbody";
        let fm = parse_frontmatter(text);
        assert_eq!(fm.get("name").map(String::as_str), Some("x"));
        assert_eq!(fm.get("type").map(String::as_str), Some("project"));
        assert_eq!(fm.get("description").map(String::as_str), Some("foo bar"));
    }

    #[test]
    fn parse_frontmatter_no_delimiter_returns_empty() {
        let fm = parse_frontmatter("just body text");
        assert!(fm.is_empty());
    }

    #[test]
    fn parse_frontmatter_open_without_close_returns_empty() {
        let fm = parse_frontmatter("---\nname: x\nbody without close");
        assert!(fm.is_empty());
    }

    // ── analyze ───────────────────────────────────────────────────────────

    #[test]
    fn analyze_aggregates_categories_and_types() {
        let inputs = vec![
            make("feedback_x.md", 1024, "---\ntype: feedback\n---\nbody"),
            make("feedback_y.md", 2048, "---\ntype: feedback\n---\nbody"),
            make("project_z.md", 512, "---\ntype: project\n---\nbody"),
            make("notes.md", 100, "no frontmatter"),
        ];
        let s = analyze(&inputs, "/m", dt(2026, 5, 5));
        assert_eq!(s.total_files, 4);
        assert_eq!(s.with_frontmatter, 3);
        assert_eq!(s.categories["feedback"], 2);
        assert_eq!(s.categories["project"], 1);
        assert_eq!(s.categories["other"], 1);
        assert_eq!(s.types["feedback"], 2);
        assert_eq!(s.types["project"], 1);
    }

    #[test]
    fn analyze_truncates_description_to_160() {
        let long = "x".repeat(300);
        let body = format!("---\ndescription: {}\n---\nbody", long);
        let inputs = vec![make("project_a.md", 100, &body)];
        let s = analyze(&inputs, "/m", dt(2026, 5, 5));
        assert_eq!(s.files[0].description.chars().count(), 160);
    }

    #[test]
    fn analyze_caps_samples_at_5() {
        let inputs: Vec<_> = (0..10)
            .map(|i| make(&format!("project_{}.md", i), 50, "body"))
            .collect();
        let s = analyze(&inputs, "/m", dt(2026, 5, 5));
        assert_eq!(s.samples.len(), 5);
    }

    #[test]
    fn analyze_size_kb_rounded_to_one_decimal() {
        let inputs = vec![make("project_x.md", 1234567, "body")];
        let s = analyze(&inputs, "/m", dt(2026, 5, 5));
        assert!((s.total_size_kb - 1205.6).abs() < 0.05);
    }

    // ── render ────────────────────────────────────────────────────────────

    #[test]
    fn render_text_report_orders_categories_descending() {
        let inputs = vec![
            make("feedback_a.md", 10, ""),
            make("feedback_b.md", 10, ""),
            make("feedback_c.md", 10, ""),
            make("project_a.md", 10, ""),
        ];
        let s = analyze(&inputs, "/m", dt(2026, 5, 5));
        let report = render_text_report(&s);
        let fb_idx = report.find("feedback").unwrap();
        let pj_idx = report.find("project").unwrap();
        assert!(fb_idx < pj_idx);
    }

    #[test]
    fn render_text_report_includes_size_in_kb() {
        let inputs = vec![make("project_x.md", 5120, "body")];
        let s = analyze(&inputs, "/path", dt(2026, 5, 5));
        let report = render_text_report(&s);
        assert!(report.contains("source:        /path"));
        assert!(report.contains("size:          5.0 KB"));
    }
}
