//! aim-ai-eval-synthesiser — S8.
//!
//! Synthesise YAML eval cases from observed failures. Closes the
//! reflexion → pattern → eval-synth → S1 evals → prompt-evolver loop.
//!
//! This crate covers two synthesis paths:
//!
//! 1. [`synthesise_from_reflexion`] — short verbal "what to do
//!    differently" notes → free-form `contains_all` rubric over key
//!    terms.
//!
//! 2. [`synthesise_from_finding`] — structured findings of one of:
//!    - `Finding::ToolFailureRate { tool }` →
//!      forbids: [`"ERROR:"`, `"as an AI"`, `"I cannot"`] +
//!      min_length: 100
//!    - `Finding::SlowTool { tool }` → max_length: 4000 (force concise)
//!    - `Finding::ErrorTypeFrequency { error_kind }` →
//!      forbids: [`error_kind`]
//!    - `Finding::SequentialPair { tool_a, tool_b }` →
//!      contains_all: [tool_a, tool_b]
//!
//! Rust port of `AI/ai/eval_synthesiser.py`. The Python predecessor
//! pulls findings from `agents.pattern_miner.mine` directly; the Rust
//! port keeps the synthesiser pure and lets callers pass findings.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseSpec {
    pub id: String,
    pub task: String,
    pub rubrics: Rubrics,
    pub tags: Vec<String>,
    pub source: String,
    pub weight: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Rubrics {
    pub min_length: Option<u32>,
    pub max_length: Option<u32>,
    pub contains_all: Option<Vec<String>>,
    pub forbids: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Finding {
    ToolFailureRate {
        tool: String,
    },
    SlowTool {
        tool: String,
    },
    ErrorTypeFrequency {
        error_kind: String,
    },
    SequentialPair {
        tool_a: String,
        tool_b: String,
    },
    RedundantMemoryQuery {
        keywords: Vec<String>,
    },
}

pub fn slug(s: &str) -> String {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-z0-9]+").unwrap());
    let cleaned = RE
        .replace_all(&s.to_lowercase(), "-")
        .trim_matches('-')
        .to_string();
    if cleaned.is_empty() {
        use sha2::Digest;
        let mut h = sha2::Sha256::new();
        h.update(s.as_bytes());
        return hex::encode(&h.finalize()[..4]);
    }
    cleaned.chars().take(24).collect()
}

pub fn synthesise_from_finding(f: &Finding) -> CaseSpec {
    match f {
        Finding::ToolFailureRate { tool } => CaseSpec {
            id: format!("auto-fail-{}", slug(tool)),
            task: format!(
                "You must complete a task that previously caused `{tool}` to fail at least 30% of the time. Plan the call carefully; do NOT emit ERROR: prefixes or fall back to apology language."
            ),
            rubrics: Rubrics {
                forbids: Some(vec![
                    "ERROR:".into(),
                    "as an AI".into(),
                    "I cannot".into(),
                ]),
                min_length: Some(100),
                ..Default::default()
            },
            tags: vec!["regression".into(), "auto".into(), "tool-fail".into()],
            source: format!("pattern:tool_failure_rate:{tool}"),
            weight: 1.0,
        },
        Finding::SlowTool { tool } => CaseSpec {
            id: format!("auto-slow-{}", slug(tool)),
            task: format!(
                "Use `{tool}` to answer concisely. Wall-clock budget is tight; respond in ≤ 4000 characters; do not bring in unrelated context."
            ),
            rubrics: Rubrics {
                max_length: Some(4000),
                ..Default::default()
            },
            tags: vec!["regression".into(), "auto".into(), "slow-tool".into()],
            source: format!("pattern:slow_tool:{tool}"),
            weight: 0.6,
        },
        Finding::ErrorTypeFrequency { error_kind } => CaseSpec {
            id: format!("auto-err-{}", slug(error_kind)),
            task: format!(
                "Avoid producing an `{error_kind}` failure mode that has shown up repeatedly in recent sessions."
            ),
            rubrics: Rubrics {
                forbids: Some(vec![error_kind.clone()]),
                ..Default::default()
            },
            tags: vec!["regression".into(), "auto".into(), "error-recur".into()],
            source: format!("pattern:error_type:{error_kind}"),
            weight: 0.8,
        },
        Finding::SequentialPair { tool_a, tool_b } => CaseSpec {
            id: format!("auto-seq-{}-{}", slug(tool_a), slug(tool_b)),
            task: format!(
                "Solve a task that benefits from chaining `{tool_a}` followed by `{tool_b}` — both calls must appear in the answer."
            ),
            rubrics: Rubrics {
                contains_all: Some(vec![tool_a.clone(), tool_b.clone()]),
                ..Default::default()
            },
            tags: vec!["synthesis".into(), "auto".into(), "tool-chain".into()],
            source: format!("pattern:seq_pair:{tool_a}+{tool_b}"),
            weight: 0.7,
        },
        Finding::RedundantMemoryQuery { keywords } => {
            let kw_slug = keywords
                .iter()
                .take(3)
                .map(|s| slug(s))
                .collect::<Vec<_>>()
                .join("-");
            CaseSpec {
                id: format!("auto-mem-{kw_slug}"),
                task: format!(
                    "Solve a task involving {} without re-querying memory more than once."
                ,
                    keywords.join(", ")
                ),
                rubrics: Rubrics {
                    contains_all: Some(keywords.clone()),
                    ..Default::default()
                },
                tags: vec!["regression".into(), "auto".into(), "memory-redundant".into()],
                source: "pattern:redundant_memory_query".into(),
                weight: 0.5,
            }
        }
    }
}

pub fn synthesise_from_reflexion(text: &str, slug_hint: Option<&str>) -> Option<CaseSpec> {
    let trimmed = text.trim();
    if trimmed.len() < 20 {
        return None;
    }
    let key_terms = extract_key_terms(trimmed);
    if key_terms.is_empty() {
        return None;
    }
    let id_slug: String = match slug_hint {
        Some(h) => slug(h),
        None => {
            use sha2::Digest;
            let mut h = sha2::Sha256::new();
            h.update(trimmed.as_bytes());
            hex::encode(&h.finalize()[..6])
        }
    };
    Some(CaseSpec {
        id: format!("auto-rfx-{id_slug}"),
        task: format!(
            "Apply the lesson from prior reflexion: {} — produce an answer that demonstrates the corrected behaviour.",
            short(trimmed, 200)
        ),
        rubrics: Rubrics {
            contains_all: Some(key_terms.into_iter().take(5).collect()),
            min_length: Some(120),
            ..Default::default()
        },
        tags: vec!["reflexion".into(), "auto".into()],
        source: "reflexion".into(),
        weight: 0.5,
    })
}

fn extract_key_terms(text: &str) -> Vec<String> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"\b([A-Za-zА-Яа-я][\w\-]{4,30})\b").unwrap());
    let fillers: BTreeSet<&'static str> = [
        "after", "again", "always", "around", "because", "before", "could",
        "every", "first", "from", "have", "here", "into", "must", "never",
        "right", "should", "still", "their", "them", "there", "this",
        "those", "until", "what", "when", "where", "which", "while", "with",
        "would", "your",
    ]
    .iter()
    .copied()
    .collect();
    let mut counts: std::collections::HashMap<String, u32> = Default::default();
    for cap in RE.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            let t = m.as_str().to_lowercase();
            if fillers.contains(t.as_str()) {
                continue;
            }
            *counts.entry(t).or_insert(0) += 1;
        }
    }
    let mut sorted: Vec<(String, u32)> = counts.into_iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    sorted.into_iter().take(8).map(|(t, _)| t).collect()
}

fn short(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(n.saturating_sub(1)).collect();
        out.push('…');
        out
    }
}

// ── YAML rendering ──────────────────────────────────────────────

pub fn yaml_dump(spec: &CaseSpec) -> String {
    let mut lines: Vec<String> = Vec::new();
    lines.push(format!("id: {}", spec.id));
    lines.push("task: |".into());
    for line in spec.task.split('\n') {
        lines.push(format!("  {line}"));
    }
    let tags: Vec<String> = spec
        .tags
        .iter()
        .map(|t| serde_json::to_string(t).unwrap())
        .collect();
    lines.push(format!("tags: [{}]", tags.join(", ")));
    lines.push(format!("weight: {}", spec.weight));
    lines.push("rubrics:".into());
    if let Some(m) = spec.rubrics.min_length {
        lines.push(format!("  min_length: {m}"));
    }
    if let Some(m) = spec.rubrics.max_length {
        lines.push(format!("  max_length: {m}"));
    }
    if let Some(v) = &spec.rubrics.contains_all {
        let arr: Vec<String> = v.iter().map(|s| serde_json::to_string(s).unwrap()).collect();
        lines.push(format!("  contains_all: [{}]", arr.join(", ")));
    }
    if let Some(v) = &spec.rubrics.forbids {
        let arr: Vec<String> = v.iter().map(|s| serde_json::to_string(s).unwrap()).collect();
        lines.push(format!("  forbids: [{}]", arr.join(", ")));
    }
    lines.push(format!("# auto-generated source: {}", spec.source));
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

pub fn cases_dir(explicit: Option<&Path>) -> PathBuf {
    if let Some(p) = explicit {
        return p.to_path_buf();
    }
    if let Ok(s) = std::env::var("AI_SYNTH_CASES_DIR") {
        return PathBuf::from(s);
    }
    if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
        return PathBuf::from(xdg).join("aim").join("synth_cases");
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".cache").join("aim").join("synth_cases")
}

pub fn write_case(spec: &CaseSpec, dest: Option<&Path>, overwrite: bool) -> std::io::Result<Option<PathBuf>> {
    let dir = cases_dir(dest);
    std::fs::create_dir_all(&dir)?;
    let p = dir.join(format!("{}.yaml", spec.id));
    if p.exists() && !overwrite {
        return Ok(None);
    }
    std::fs::write(&p, yaml_dump(spec))?;
    Ok(Some(p))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn slug_basic() {
        assert_eq!(slug("Hello, World!"), "hello-world");
        assert_eq!(slug("agents/foo.py"), "agents-foo-py");
    }

    #[test]
    fn slug_falls_back_to_hash_when_empty() {
        let s = slug("!!!");
        assert!(!s.is_empty());
        assert!(s.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn synth_tool_failure() {
        let c = synthesise_from_finding(&Finding::ToolFailureRate {
            tool: "verify_pmid".into(),
        });
        assert_eq!(c.id, "auto-fail-verify-pmid");
        let forbids = c.rubrics.forbids.unwrap();
        assert!(forbids.iter().any(|s| s == "ERROR:"));
        assert!(c.tags.contains(&"tool-fail".to_string()));
    }

    #[test]
    fn synth_slow_tool_caps_max_length() {
        let c = synthesise_from_finding(&Finding::SlowTool {
            tool: "web_search".into(),
        });
        assert_eq!(c.rubrics.max_length, Some(4000));
    }

    #[test]
    fn synth_error_type() {
        let c = synthesise_from_finding(&Finding::ErrorTypeFrequency {
            error_kind: "timeout".into(),
        });
        assert!(c.rubrics.forbids.unwrap().contains(&"timeout".to_string()));
    }

    #[test]
    fn synth_seq_pair() {
        let c = synthesise_from_finding(&Finding::SequentialPair {
            tool_a: "search".into(),
            tool_b: "fetch".into(),
        });
        let ca = c.rubrics.contains_all.unwrap();
        assert_eq!(ca, vec!["search".to_string(), "fetch".to_string()]);
    }

    #[test]
    fn synth_redundant_memory() {
        let c = synthesise_from_finding(&Finding::RedundantMemoryQuery {
            keywords: vec!["telomere".into(), "centriole".into()],
        });
        let ca = c.rubrics.contains_all.unwrap();
        assert!(ca.contains(&"telomere".to_string()));
    }

    #[test]
    fn synth_reflexion_short_text_returns_none() {
        assert!(synthesise_from_reflexion("too short", None).is_none());
    }

    #[test]
    fn synth_reflexion_extracts_key_terms() {
        let c = synthesise_from_reflexion(
            "When verifying centriole damage findings, always confirm via pubmed citations before emit.",
            None,
        )
        .unwrap();
        let ca = c.rubrics.contains_all.unwrap();
        assert!(
            ca.iter().any(|t| t.contains("centriole") || t.contains("pubmed")),
            "got: {ca:?}"
        );
    }

    #[test]
    fn yaml_dump_roundtrip() {
        let c = synthesise_from_finding(&Finding::ToolFailureRate {
            tool: "x".into(),
        });
        let y = yaml_dump(&c);
        assert!(y.contains("id: auto-fail-x"));
        assert!(y.contains("rubrics:"));
        assert!(y.contains("forbids:"));
        assert!(y.contains("# auto-generated source:"));
    }

    #[test]
    fn write_case_idempotent() {
        let d = tempdir().unwrap();
        let c = synthesise_from_finding(&Finding::ToolFailureRate {
            tool: "y".into(),
        });
        let p1 = write_case(&c, Some(d.path()), false).unwrap();
        assert!(p1.is_some());
        let p2 = write_case(&c, Some(d.path()), false).unwrap();
        assert!(p2.is_none(), "second write without overwrite must skip");
        let p3 = write_case(&c, Some(d.path()), true).unwrap();
        assert!(p3.is_some());
    }
}
