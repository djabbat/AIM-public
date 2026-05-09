//! aim-smart-context — importance-aware context truncation.
//!
//! Port of `agents/smart_context.py`. Alternative to LLM-compression: rank
//! chunks by a composite importance score, then keep top chunks until the
//! budget is filled. Lossless for the high-priority items, only drops the
//! low-importance tail. No LLM calls — all heuristic.
//!
//! ## Composite score (0–200)
//!
//! ```text
//! +priority_value     (0/10/40/70/100 from frontmatter)
//! +50 × similarity    (semantic relevance from retrieve())
//! +recency bonus      (≤30, today=30, 30+ days=0)
//! +entity bonus       (≤20, capitalised names + years + IDs)
//! +tag-match bonus    (≤30 if tags overlap with task tokens)
//! ```
//!
//! Falls back gracefully on missing metadata.

use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::OnceLock;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Chunk {
    /// File label rendered in the formatted blob header.
    #[serde(default)]
    pub file: String,
    pub text: String,
    /// One of: CRITICAL, HIGH, NORMAL, LOW, EPHEMERAL (case-insensitive).
    #[serde(default)]
    pub priority: Option<String>,
    /// Either a normalised similarity in [0,1] or `1 - distance`.
    #[serde(default)]
    pub similarity: Option<f64>,
    /// Internal vector-store distance, used when `similarity` is missing.
    #[serde(default, rename = "_distance")]
    pub distance: Option<f64>,
    /// ISO-8601 datetime; only the prefix is parsed.
    #[serde(default)]
    pub created: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    /// Filled by `truncate()` so the formatted blob can show it.
    #[serde(default)]
    pub importance: i32,
    /// Set by `truncate()` when the last chunk was soft-trimmed.
    #[serde(default)]
    pub truncated: bool,
}

const PRIORITY_CRITICAL: i32 = 100;
const PRIORITY_HIGH: i32 = 70;
const PRIORITY_NORMAL: i32 = 40;
const PRIORITY_LOW: i32 = 10;
const PRIORITY_EPHEMERAL: i32 = 1;

fn priority_value(p: &str) -> i32 {
    match p.to_uppercase().as_str() {
        "CRITICAL" => PRIORITY_CRITICAL,
        "HIGH" => PRIORITY_HIGH,
        "LOW" => PRIORITY_LOW,
        "EPHEMERAL" => PRIORITY_EPHEMERAL,
        _ => PRIORITY_NORMAL,
    }
}

static PERSON_RE: OnceLock<Regex> = OnceLock::new();
static YEAR_RE: OnceLock<Regex> = OnceLock::new();
static ID_RE: OnceLock<Regex> = OnceLock::new();
static TASK_TOKEN_RE: OnceLock<Regex> = OnceLock::new();

fn person_re() -> &'static Regex {
    PERSON_RE.get_or_init(|| {
        // Two-or-more capitalised words, hyphenated allowed
        Regex::new(r"\b[A-ZА-Я][a-zа-яё]+(?:[ -][A-ZА-Я][a-zа-яё]+){1,2}\b").unwrap()
    })
}
fn year_re() -> &'static Regex {
    YEAR_RE.get_or_init(|| Regex::new(r"\b(?:19|20|21)\d{2}\b").unwrap())
}
fn id_re() -> &'static Regex {
    ID_RE.get_or_init(|| Regex::new(r"\b(?:PMID|DOI|ORCID)\b[:\s]*[\w./-]+").unwrap())
}
fn task_token_re() -> &'static Regex {
    TASK_TOKEN_RE.get_or_init(|| Regex::new(r"[A-Za-zА-Яа-яёЁ0-9]{3,}").unwrap())
}

pub fn approx_tokens(s: &str) -> usize {
    (s.len() / 4).max(1)
}

pub fn entity_bonus(text: &str) -> i32 {
    let persons = person_re().find_iter(text).count() as i32 * 2;
    let years = year_re().find_iter(text).count() as i32;
    let ids = id_re().find_iter(text).count() as i32 * 4;
    let bonus = persons.min(10) + years.min(6) + ids.min(12);
    bonus.min(20)
}

pub fn recency_bonus(ts: Option<&str>, now: DateTime<Utc>) -> i32 {
    let ts = match ts {
        Some(s) if !s.trim().is_empty() => s,
        _ => return 0,
    };
    if let Ok(dt) = DateTime::parse_from_rfc3339(ts) {
        let age = (now - dt.with_timezone(&Utc)).num_days() as i32;
        return (30 - age).max(0);
    }
    if let Ok(prefix) = chrono::NaiveDateTime::parse_from_str(ts, "%Y-%m-%dT%H:%M:%S") {
        let age = (now - prefix.and_utc()).num_days() as i32;
        return (30 - age).max(0);
    }
    if let Ok(d) = chrono::NaiveDate::parse_from_str(&ts[..ts.len().min(10)], "%Y-%m-%d") {
        let age = (now.date_naive() - d).num_days() as i32;
        return (30 - age).max(0);
    }
    0
}

pub fn tag_match_bonus(tags: &[String], task_tokens: &HashSet<String>) -> i32 {
    if tags.is_empty() || task_tokens.is_empty() {
        return 0;
    }
    let mut hits = 0;
    for t in tags {
        if task_tokens.contains(&t.to_lowercase()) {
            hits += 1;
        }
    }
    (hits as i32 * 6).min(30)
}

pub fn task_tokens(task: &str) -> HashSet<String> {
    task_token_re()
        .find_iter(task)
        .map(|m| m.as_str().to_lowercase())
        .collect()
}

pub fn score_chunk(chunk: &Chunk, tokens: &HashSet<String>, now: DateTime<Utc>) -> i32 {
    let priority = chunk
        .priority
        .as_deref()
        .map(priority_value)
        .unwrap_or(PRIORITY_NORMAL);
    let sim = chunk
        .similarity
        .or_else(|| chunk.distance.map(|d| 1.0 - d))
        .unwrap_or(0.0)
        .clamp(0.0, 1.0);
    let sim_score = (50.0 * sim).round() as i32;
    priority
        + sim_score
        + recency_bonus(chunk.created.as_deref(), now)
        + entity_bonus(&chunk.text)
        + tag_match_bonus(&chunk.tags, tokens)
}

pub fn soft_truncate(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    // Take up to max_chars chars, snap to last sentence end past the midpoint.
    let mut cut: String = text.chars().take(max_chars).collect();
    if let Some(idx) = cut.rfind('.') {
        if idx > max_chars / 2 {
            cut.truncate(idx + 1);
        }
    }
    format!("{cut} […]")
}

pub fn format_blob(chunks: &[Chunk]) -> String {
    if chunks.is_empty() {
        return String::new();
    }
    let mut parts: Vec<String> = Vec::with_capacity(chunks.len());
    for c in chunks {
        let priority = c.priority.as_deref().unwrap_or("NORMAL");
        let head = format!(
            "[file={} importance={} priority={}]",
            if c.file.is_empty() { "?" } else { &c.file },
            c.importance,
            priority
        );
        parts.push(format!("{head}\n{}", c.text));
    }
    parts.join("\n\n---\n\n")
}

#[derive(Debug, Clone, Copy)]
pub struct TruncateOpts {
    pub max_tokens: usize,
    pub reserved_tokens: usize,
}

impl Default for TruncateOpts {
    fn default() -> Self {
        Self {
            max_tokens: 4000,
            reserved_tokens: 500,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TruncateResult {
    pub blob: String,
    pub kept: Vec<Chunk>,
}

/// Rank `chunks` by composite importance, keep the top entries that fit
/// within `max_tokens - reserved_tokens` token budget. Soft-truncates the
/// last chunk if it almost fits (≥200 chars worth of remaining budget).
///
/// `now` is injected so tests can drive the recency window deterministically.
pub fn truncate(
    chunks: Vec<Chunk>,
    task: &str,
    opts: TruncateOpts,
    now: DateTime<Utc>,
) -> TruncateResult {
    if chunks.is_empty() {
        return TruncateResult {
            blob: String::new(),
            kept: vec![],
        };
    }
    let tokens = task_tokens(task);
    let mut chunks = chunks;
    for c in &mut chunks {
        c.importance = score_chunk(c, &tokens, now);
    }
    chunks.sort_by(|a, b| b.importance.cmp(&a.importance));

    let budget = opts.max_tokens.saturating_sub(opts.reserved_tokens);
    let mut selected: Vec<Chunk> = Vec::new();
    let mut used = 0usize;

    for mut c in chunks.into_iter() {
        let n = approx_tokens(&c.text);
        if used + n <= budget {
            used += n;
            selected.push(c);
            continue;
        }
        let remaining = budget.saturating_sub(used);
        if remaining * 4 > 200 {
            let soft = soft_truncate(&c.text, remaining * 4);
            c.text = soft;
            c.truncated = true;
            let _ = approx_tokens(&c.text); // remaining budget exhausted
            selected.push(c);
        }
        break;
    }
    let blob = format_blob(&selected);
    TruncateResult {
        blob,
        kept: selected,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 4, 12, 0, 0).unwrap()
    }

    #[test]
    fn approx_tokens_floors_at_one() {
        assert_eq!(approx_tokens(""), 1);
        assert_eq!(approx_tokens("abc"), 1);
        assert_eq!(approx_tokens(&"x".repeat(40)), 10);
    }

    #[test]
    fn priority_value_maps_known_levels() {
        assert_eq!(priority_value("CRITICAL"), 100);
        assert_eq!(priority_value("high"), 70);
        assert_eq!(priority_value("LOW"), 10);
        assert_eq!(priority_value("EPHEMERAL"), 1);
        assert_eq!(priority_value("anything-else"), 40);
    }

    #[test]
    fn entity_bonus_caps_at_twenty() {
        let text = format!(
            "{}{}",
            "Jaba Tkemaladze ".repeat(5),
            "PMID: 36583780 PMID 12345 DOI: 10.1234/x ORCID: 0000-0001-8651-7243 1996 2026 2024 ".to_string()
        );
        let b = entity_bonus(&text);
        assert!(b <= 20);
        assert!(b >= 18, "got {b}");
    }

    #[test]
    fn entity_bonus_zero_on_plain_text() {
        assert_eq!(entity_bonus("just some plain words"), 0);
    }

    #[test]
    fn recency_bonus_today() {
        let ts = "2026-05-04T08:00:00+00:00";
        let r = recency_bonus(Some(ts), now());
        assert!(r >= 28 && r <= 30, "got {r}");
    }

    #[test]
    fn recency_bonus_old_capped_at_zero() {
        let ts = "2025-01-01T00:00:00+00:00";
        assert_eq!(recency_bonus(Some(ts), now()), 0);
    }

    #[test]
    fn recency_bonus_date_only_supported() {
        let r = recency_bonus(Some("2026-04-30"), now());
        assert!(r >= 25 && r <= 30, "got {r}");
    }

    #[test]
    fn recency_bonus_missing_returns_zero() {
        assert_eq!(recency_bonus(None, now()), 0);
        assert_eq!(recency_bonus(Some(""), now()), 0);
    }

    #[test]
    fn tag_match_counts_overlap() {
        let tokens: HashSet<String> = ["aging", "centriole"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        let tags = vec!["centriole".to_string(), "kinetics".to_string()];
        assert_eq!(tag_match_bonus(&tags, &tokens), 6);
    }

    #[test]
    fn tag_match_caps_at_thirty() {
        let tokens: HashSet<String> =
            (0..10).map(|i| format!("t{i}")).collect();
        let tags: Vec<String> = (0..10).map(|i| format!("t{i}")).collect();
        // 10 * 6 = 60, capped at 30
        assert_eq!(tag_match_bonus(&tags, &tokens), 30);
    }

    #[test]
    fn task_tokens_lowercase_minlength_3() {
        let t = task_tokens("Compare CDATA and MCOA papers in 2026");
        assert!(t.contains("compare"));
        assert!(t.contains("cdata"));
        assert!(t.contains("mcoa"));
        assert!(t.contains("2026"));
        // "in" too short
        assert!(!t.contains("in"));
    }

    #[test]
    fn score_chunk_ranges() {
        let chunk = Chunk {
            file: "x.md".into(),
            text: "Compare CDATA paper PMID: 12345 from 2026".into(),
            priority: Some("HIGH".into()),
            similarity: Some(0.8),
            tags: vec!["cdata".into()],
            ..Default::default()
        };
        let toks = task_tokens("CDATA review");
        let s = score_chunk(&chunk, &toks, now());
        // priority 70 + 50*0.8=40 + entity bonus + tag match = > 110
        assert!(s >= 110, "got {s}");
        assert!(s <= 200);
    }

    #[test]
    fn score_chunk_uses_distance_when_similarity_missing() {
        let chunk = Chunk {
            text: "x".into(),
            distance: Some(0.2), // similarity = 0.8
            ..Default::default()
        };
        let s = score_chunk(&chunk, &task_tokens(""), now());
        // Default priority 40 + 50*0.8=40 = 80
        assert_eq!(s, 80);
    }

    #[test]
    fn soft_truncate_keeps_last_sentence() {
        let text = "First sentence. Second sentence here. Third one extends past the cap.";
        // max_chars=42 captures up through the period of "Second sentence here."
        let out = soft_truncate(text, 42);
        assert!(out.ends_with(" […]"));
        assert!(out.contains("Second sentence here."));
        assert!(!out.contains("Third"));
    }

    #[test]
    fn soft_truncate_short_input_returned_unchanged() {
        let s = "hello";
        assert_eq!(soft_truncate(s, 100), "hello");
    }

    #[test]
    fn truncate_orders_by_importance_desc() {
        let chunks = vec![
            Chunk {
                file: "low.md".into(),
                text: "low pri text".into(),
                priority: Some("LOW".into()),
                ..Default::default()
            },
            Chunk {
                file: "crit.md".into(),
                text: "critical content".into(),
                priority: Some("CRITICAL".into()),
                ..Default::default()
            },
        ];
        let r = truncate(chunks, "", TruncateOpts::default(), now());
        assert_eq!(r.kept.len(), 2);
        assert_eq!(r.kept[0].file, "crit.md");
        assert_eq!(r.kept[1].file, "low.md");
    }

    #[test]
    fn truncate_drops_low_priority_when_budget_full() {
        let big = Chunk {
            file: "big.md".into(),
            text: "x".repeat(15_000), // ≈ 3750 tokens
            priority: Some("HIGH".into()),
            ..Default::default()
        };
        let small = Chunk {
            file: "small.md".into(),
            text: "y".repeat(2_000), // ≈ 500 tokens
            priority: Some("LOW".into()),
            ..Default::default()
        };
        let r = truncate(
            vec![big, small],
            "",
            TruncateOpts {
                max_tokens: 4000,
                reserved_tokens: 500,
            },
            now(),
        );
        assert_eq!(r.kept.len(), 1);
        assert_eq!(r.kept[0].file, "big.md");
    }

    #[test]
    fn truncate_soft_trims_when_almost_fits() {
        let big = Chunk {
            file: "big.md".into(),
            text: "x".repeat(20_000), // way over budget
            priority: Some("CRITICAL".into()),
            ..Default::default()
        };
        let r = truncate(
            vec![big],
            "",
            TruncateOpts {
                max_tokens: 4000,
                reserved_tokens: 500,
            },
            now(),
        );
        assert_eq!(r.kept.len(), 1);
        assert!(r.kept[0].truncated);
        assert!(r.kept[0].text.ends_with(" […]"));
    }

    #[test]
    fn truncate_empty_input_empty_output() {
        let r = truncate(vec![], "task", TruncateOpts::default(), now());
        assert!(r.blob.is_empty());
        assert!(r.kept.is_empty());
    }

    #[test]
    fn format_blob_includes_metadata() {
        let chunks = vec![Chunk {
            file: "FCLC/CONCEPT.md".into(),
            text: "hello".into(),
            priority: Some("HIGH".into()),
            importance: 110,
            ..Default::default()
        }];
        let s = format_blob(&chunks);
        assert!(s.contains("file=FCLC/CONCEPT.md"));
        assert!(s.contains("importance=110"));
        assert!(s.contains("priority=HIGH"));
        assert!(s.contains("hello"));
    }

    #[test]
    fn format_blob_separator_between_chunks() {
        let chunks = vec![
            Chunk {
                text: "first".into(),
                ..Default::default()
            },
            Chunk {
                text: "second".into(),
                ..Default::default()
            },
        ];
        let s = format_blob(&chunks);
        assert!(s.contains("\n\n---\n\n"));
        assert!(s.contains("first"));
        assert!(s.contains("second"));
    }
}
