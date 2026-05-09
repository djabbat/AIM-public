//! aim-ai-gap-detector — S11.
//!
//! Walk session JSONL logs (`~/.cache/aim/sessions/*.jsonl`) for tasks
//! where AIM gave up — final answer matches a surrender pattern. Cluster
//! surrenders into capability gaps with a heuristic next-step suggestion.
//!
//! Rust port of `AI/ai/gap_detector.py`. Surrender regex set + tokeniser
//! match the Python predecessor.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Surrender {
    pub session: String,
    pub task: String,
    pub answer: String,
    pub ts: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Gap {
    pub theme: Vec<String>,
    pub surrenders: Vec<Surrender>,
    pub representative: String,
    pub suggestion: String,
}

impl Gap {
    pub fn n(&self) -> usize {
        self.surrenders.len()
    }
}

pub fn sessions_dir() -> PathBuf {
    if let Ok(s) = std::env::var("AIM_SESSIONS_DIR") {
        return PathBuf::from(s);
    }
    if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
        return PathBuf::from(xdg).join("aim").join("sessions");
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".cache").join("aim").join("sessions")
}

// ── surrender detection ─────────────────────────────────────────

pub fn is_surrender(answer: &str) -> bool {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static PATS: Lazy<Vec<Regex>> = Lazy::new(|| {
        let raw = vec![
            r"(?i)\bI\s+(?:cannot|can'?t)\b",
            r"(?i)\bI\s+(?:don'?t|do\s+not)\s+have\s+access\b",
            r"(?i)\bI'?m\s+(?:not\s+able|unable)\b",
            r"(?i)\boutside\s+my\s+capabilities\b",
            r"(?i)\bI'?m\s+sorry\s+I\b",
            r"(?i)\(interrupted\)",
            r"(?i)\bне\s+могу\b",
            r"(?i)\bу\s+меня\s+нет\s+доступа\b",
            r"(?i)\bне\s+умею\b",
        ];
        raw.into_iter().map(|p| Regex::new(p).unwrap()).collect()
    });
    if answer.trim_start().starts_with("ERROR:") {
        return true;
    }
    PATS.iter().any(|re| re.is_match(answer))
}

// ── token helpers ───────────────────────────────────────────────

const FILLERS: &[&str] = &[
    "the", "and", "for", "with", "that", "this", "from", "they", "your",
    "have", "should", "would", "must", "make", "more", "когда", "если",
    "также", "может", "очень", "уже", "будет",
];

fn tokens(s: &str) -> BTreeSet<String> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"[A-Za-zА-Яа-яЁё][\w\-]{3,}").unwrap());
    let f: BTreeSet<&'static str> = FILLERS.iter().copied().collect();
    RE.find_iter(s)
        .map(|m| m.as_str().to_lowercase())
        .filter(|t| !f.contains(t.as_str()))
        .collect()
}

fn jaccard(a: &BTreeSet<String>, b: &BTreeSet<String>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    inter / union.max(1.0)
}

// ── walk session JSONL ──────────────────────────────────────────

pub fn surrenders_in_dir(dir: &Path) -> Vec<Surrender> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut paths: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("jsonl"))
        .collect();
    paths.sort();

    let mut out: Vec<Surrender> = Vec::new();
    for p in paths {
        let session = p
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown")
            .to_string();
        let Ok(text) = std::fs::read_to_string(&p) else {
            continue;
        };
        let mut current_task: Option<String> = None;
        let mut current_ts: Option<String> = None;
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let ev: serde_json::Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let kind = ev.get("type").and_then(|v| v.as_str()).unwrap_or("");
            match kind {
                "start" => {
                    if let Some(t) = ev.get("task").and_then(|v| v.as_str()) {
                        current_task = Some(t.to_string());
                    }
                    if let Some(ts) = ev.get("ts").and_then(|v| v.as_str()) {
                        current_ts = Some(ts.to_string());
                    }
                }
                "final" | "error" => {
                    let answer = ev
                        .get("answer")
                        .or_else(|| ev.get("error"))
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if is_surrender(answer) {
                        let task: String = current_task
                            .clone()
                            .unwrap_or_default()
                            .chars()
                            .take(300)
                            .collect();
                        let ans: String = answer.chars().take(300).collect();
                        out.push(Surrender {
                            session: session.clone(),
                            task,
                            answer: ans,
                            ts: current_ts.clone(),
                        });
                    }
                }
                _ => {}
            }
        }
    }
    out
}

pub fn surrenders() -> Vec<Surrender> {
    surrenders_in_dir(&sessions_dir())
}

// ── cluster surrenders into gaps ────────────────────────────────

fn suggestion_for(theme: &[String], rep: &str) -> String {
    if theme.is_empty() {
        let preview: String = rep.chars().take(120).collect();
        return format!("Investigate failures on: {preview}");
    }
    let head: String = theme.iter().take(4).cloned().collect::<Vec<_>>().join(", ");
    let low = theme.join(" ").to_lowercase();
    if ["access", "permission", "auth", "право", "доступ"]
        .iter()
        .any(|k| low.contains(k))
    {
        return format!(
            "Likely missing tool / scope: {head}. Add MCP server or expand bash whitelist."
        );
    }
    if ["pubmed", "citation", "doi", "pmid"]
        .iter()
        .any(|k| low.contains(k))
    {
        return format!(
            "Citation / grounding gap: {head}. Add literature lookup before emit."
        );
    }
    if ["language", "translate", "georgian", "грузин"]
        .iter()
        .any(|k| low.contains(k))
    {
        return format!("Translation gap: {head}. Wire i18n delegate or DeepSeek.");
    }
    format!("Prompt patch candidate: '{head}' — see clusters in S10.")
}

pub fn gaps(surrender_list: &[Surrender], threshold: f64) -> Vec<Gap> {
    if surrender_list.is_empty() {
        return Vec::new();
    }
    let items: Vec<(usize, BTreeSet<String>)> = surrender_list
        .iter()
        .enumerate()
        .map(|(i, s)| {
            let toks = tokens(&format!("{} {}", s.task, s.answer));
            (i, toks)
        })
        .collect();
    let mut clusters: Vec<Vec<(usize, BTreeSet<String>)>> = Vec::new();
    for (idx, toks) in items {
        let mut attached = false;
        'outer: for cl in clusters.iter_mut() {
            for (_, ct) in cl.iter() {
                if jaccard(&toks, ct) >= threshold {
                    cl.push((idx, toks.clone()));
                    attached = true;
                    break 'outer;
                }
            }
        }
        if !attached {
            clusters.push(vec![(idx, toks)]);
        }
    }
    let mut out: Vec<Gap> = clusters
        .into_iter()
        .map(|cl| {
            let mut counter: HashMap<String, u32> = HashMap::new();
            for (_, ts) in &cl {
                for t in ts {
                    *counter.entry(t.clone()).or_insert(0) += 1;
                }
            }
            let cutoff = (cl.len() / 2).max(1) as u32;
            let mut common: Vec<(String, u32)> = counter
                .into_iter()
                .filter(|(_, c)| *c >= cutoff)
                .collect();
            common.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
            let theme: Vec<String> =
                common.into_iter().take(6).map(|(t, _)| t).collect();
            let surrenders: Vec<Surrender> =
                cl.iter().map(|(i, _)| surrender_list[*i].clone()).collect();
            let rep = surrenders
                .iter()
                .max_by_key(|s| s.task.len())
                .map(|s| s.task.clone())
                .unwrap_or_default();
            let suggestion = suggestion_for(&theme, &rep);
            Gap {
                theme,
                surrenders,
                representative: rep,
                suggestion,
            }
        })
        .collect();
    out.sort_by(|a, b| b.n().cmp(&a.n()));
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn surrender_pattern_matches() {
        assert!(is_surrender("I cannot help with that"));
        assert!(is_surrender("I can't access this"));
        assert!(is_surrender("I'm not able to do that"));
        assert!(is_surrender("Sorry, that's outside my capabilities"));
        assert!(is_surrender("(interrupted)"));
        assert!(is_surrender("ERROR: timeout"));
        assert!(is_surrender("Извините, я не могу"));
        assert!(is_surrender("у меня нет доступа"));
        assert!(!is_surrender("Здесь обычный успешный ответ."));
        assert!(!is_surrender("Sure, here's the result."));
    }

    #[test]
    fn empty_dir_no_surrenders() {
        let d = tempdir().unwrap();
        let s = surrenders_in_dir(d.path());
        assert!(s.is_empty());
    }

    #[test]
    fn jsonl_surrenders_detected() {
        let d = tempdir().unwrap();
        let p = d.path().join("session-a.jsonl");
        std::fs::write(
            &p,
            r#"{"type":"start","task":"translate Georgian text","ts":"2026-05-04T00:00:00Z"}
{"type":"final","answer":"I cannot help with Georgian translation"}
"#,
        )
        .unwrap();
        let s = surrenders_in_dir(d.path());
        assert_eq!(s.len(), 1);
        assert_eq!(s[0].session, "session-a");
        assert!(s[0].task.contains("Georgian"));
    }

    #[test]
    fn jsonl_success_not_surrender() {
        let d = tempdir().unwrap();
        let p = d.path().join("session-b.jsonl");
        std::fs::write(
            &p,
            r#"{"type":"start","task":"add 2 + 2"}
{"type":"final","answer":"4"}
"#,
        )
        .unwrap();
        assert!(surrenders_in_dir(d.path()).is_empty());
    }

    #[test]
    fn cluster_two_similar_surrenders() {
        let surr = vec![
            Surrender {
                session: "s1".into(),
                task: "translate Georgian abstract".into(),
                answer: "I cannot help with Georgian translation".into(),
                ts: None,
            },
            Surrender {
                session: "s2".into(),
                task: "Georgian medical translation".into(),
                answer: "I'm not able to translate Georgian".into(),
                ts: None,
            },
        ];
        let g = gaps(&surr, 0.20);
        assert_eq!(g.len(), 1);
        assert_eq!(g[0].n(), 2);
        assert!(g[0].suggestion.contains("Translation gap"));
    }

    #[test]
    fn citation_cluster_yields_citation_suggestion() {
        // Three matching surrenders so theme ranks pubmed/citation
        // above any "access" tokens.
        let surr = vec![
            Surrender {
                session: "p1".into(),
                task: "find pubmed citation".into(),
                answer: "no pubmed found".into(),
                ts: None,
            },
            Surrender {
                session: "p2".into(),
                task: "another pubmed citation lookup".into(),
                answer: "could not retrieve pubmed paper".into(),
                ts: None,
            },
        ];
        let g = gaps(&surr, 0.20);
        assert_eq!(g.len(), 1);
        assert!(
            g[0].suggestion.contains("Citation"),
            "got: {}",
            g[0].suggestion
        );
    }

    #[test]
    fn empty_surrenders_no_gaps() {
        assert!(gaps(&[], 0.20).is_empty());
    }

    #[test]
    fn surrender_with_access_keyword_gets_tool_suggestion() {
        let surr = vec![
            Surrender {
                session: "a".into(),
                task: "access permission required for storage".into(),
                answer: "I don't have access permission".into(),
                ts: None,
            },
            Surrender {
                session: "b".into(),
                task: "permission denied for storage access".into(),
                answer: "I cannot access this storage".into(),
                ts: None,
            },
        ];
        let g = gaps(&surr, 0.20);
        assert_eq!(g.len(), 1);
        assert!(
            g[0].suggestion.contains("missing tool"),
            "got: {}",
            g[0].suggestion
        );
    }
}
