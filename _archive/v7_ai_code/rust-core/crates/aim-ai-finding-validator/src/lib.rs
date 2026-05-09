//! aim-ai-finding-validator — FV1.
//!
//! Heuristic auto-validator for diagnostic findings. Cheap pattern
//! rules that flag a finding as a false-positive when its claim is
//! contradicted by the actual file content.
//!
//! Rust port of `AI/ai/finding_validator.py`. The five canonical
//! contradiction rules are preserved:
//! 1. claim_negates_existing_sql
//! 2. claim_negates_typed_return
//! 3. claim_negates_existence_guard
//! 4. claim_negates_citation_guard
//! 5. claim_negates_lock

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum Status {
    FalsePositive,
    Unverified,
    True,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Verdict {
    pub status: Status,
    pub rule: String,
    pub evidence: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FindingAudit {
    /// First 120 chars of the finding line.
    pub excerpt: String,
    pub file_ref: Option<String>,
    pub verdict: Verdict,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditReport {
    pub n_findings: u64,
    pub n_false: u64,
    pub n_unverified: u64,
    pub n_true: u64,
    pub audits: Vec<FindingAudit>,
}

struct Rule {
    /// claim regex
    claim: regex::Regex,
    /// contradiction-in-file regex
    contradict: regex::Regex,
    rule: &'static str,
    evidence: &'static str,
}

fn rules() -> &'static Vec<Rule> {
    use once_cell::sync::Lazy;
    use regex::RegexBuilder;
    static RULES: Lazy<Vec<Rule>> = Lazy::new(|| {
        let mk = |s: &str| -> regex::Regex {
            RegexBuilder::new(s)
                .case_insensitive(true)
                .build()
                .expect("valid regex")
        };
        vec![
            Rule {
                claim: mk(r"no\s+(UNIQUE|PRIMARY KEY|CREATE TABLE)"),
                contradict: mk(
                    r"CREATE\s+(?:UNIQUE\s+)?(?:INDEX|TABLE)|UNIQUE\s+INDEX|PRIMARY\s+KEY",
                ),
                rule: "claim_negates_existing_sql",
                evidence: "claim says SQL artifact missing, but file contains it",
            },
            Rule {
                claim: mk(
                    r"returns\s+None\s+implicitly|no\s+return\s+type|inconsistent\s+return\s+type",
                ),
                contradict: mk(
                    r"->\s*(?:Optional\[)?(?:list|dict|set|tuple|str|int|float|bool|Path|[A-Z]\w+)",
                ),
                rule: "claim_negates_typed_return",
                evidence:
                    "claim says return type missing, but function has -> annotation",
            },
            Rule {
                claim: mk(
                    r"crashes?\s+(?:on|with)\s+(?:missing|FileNotFoundError|absent)|no\s+FileNotFoundError\s+handling|production\s+crash\s+on\s+missing",
                ),
                contradict: mk(
                    r#"if\s+not\s+\S+\.exists\(\)|except\s+\(?FileNotFoundError|except\s+OSError|errors=["']replace["']"#,
                ),
                rule: "claim_negates_existence_guard",
                evidence:
                    "claim says missing-file crashes, but file has explicit exists() / OSError guard",
            },
            Rule {
                claim: mk(r"no\s+citation_guard|no\s+verify_no_fabricated|unverified\s+emit"),
                contradict: mk(
                    r"citation_guard|_verify_no_fabricated_citations|verify\(strict=True\)",
                ),
                rule: "claim_negates_citation_guard",
                evidence: "claim says citation guard missing, but file imports / calls it",
            },
            Rule {
                claim: mk(r"no\s+(?:thread\s+)?lock|no\s+thread\s+safety|race\s+condition"),
                contradict: mk(r"threading\.RLock|threading\.Lock|with\s+_LOCK|Mutex::new"),
                rule: "claim_negates_lock",
                evidence: "claim says no lock, but file uses threading.Lock or Mutex::new",
            },
        ]
    });
    &RULES
}

pub fn classify(claim_text: &str, file_path: &Path) -> Verdict {
    if !file_path.exists() {
        return Verdict {
            status: Status::Unverified,
            rule: "no_file".into(),
            evidence: format!("file not found: {}", file_path.display()),
        };
    }
    let content = match std::fs::read_to_string(file_path) {
        Ok(c) => c,
        Err(e) => {
            return Verdict {
                status: Status::Unverified,
                rule: "read_error".into(),
                evidence: format!("{e}"),
            };
        }
    };
    for r in rules() {
        if r.claim.is_match(claim_text) && r.contradict.is_match(&content) {
            return Verdict {
                status: Status::FalsePositive,
                rule: r.rule.into(),
                evidence: r.evidence.into(),
            };
        }
    }
    Verdict {
        status: Status::Unverified,
        rule: "no_match".into(),
        evidence: "no rule fired; claim cannot be auto-rejected".into(),
    }
}

// ── markdown parsing ────────────────────────────────────────────

fn extract_file_ref(line: &str) -> Option<String> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static BOLD: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"\*\*`?([\w./_\-]+\.py)`?\*\*").unwrap());
    static BACKTICK: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"`([\w./_\-]+\.py)(?::\d+)?(?::\w+)?`").unwrap());
    if let Some(c) = BOLD.captures(line) {
        return Some(c.get(1)?.as_str().to_string());
    }
    if let Some(c) = BACKTICK.captures(line) {
        return Some(c.get(1)?.as_str().to_string());
    }
    None
}

fn split_into_findings(report_text: &str) -> Vec<&str> {
    use once_cell::sync::Lazy;
    use regex::RegexBuilder;
    static SEV: Lazy<regex::Regex> = Lazy::new(|| {
        RegexBuilder::new(r"→\s*\*\*(crit|high|med|low)\*\*")
            .case_insensitive(true)
            .build()
            .unwrap()
    });
    report_text
        .lines()
        .filter(|l| SEV.is_match(l))
        .collect()
}

pub fn audit_report(report_text: &str, repo_root: &Path) -> AuditReport {
    let lines = split_into_findings(report_text);
    let mut audits: Vec<FindingAudit> = Vec::new();
    let mut n_false = 0u64;
    let mut n_unverified = 0u64;
    let mut n_true = 0u64;

    for line in lines {
        let trimmed = line.trim();
        let excerpt: String = trimmed.chars().take(120).collect();
        let Some(ref_str) = extract_file_ref(trimmed) else {
            audits.push(FindingAudit {
                excerpt,
                file_ref: None,
                verdict: Verdict {
                    status: Status::Unverified,
                    rule: "no_file_ref".into(),
                    evidence: "line had severity but no file ref".into(),
                },
            });
            n_unverified += 1;
            continue;
        };

        let candidates: Vec<PathBuf> = vec![
            repo_root.join(&ref_str),
            repo_root
                .join("AI")
                .join("ai")
                .join(Path::new(&ref_str).file_name().unwrap_or_default()),
            repo_root
                .join("agents")
                .join(Path::new(&ref_str).file_name().unwrap_or_default()),
        ];
        let path = candidates
            .iter()
            .find(|p| p.exists())
            .cloned()
            .unwrap_or_else(|| candidates[0].clone());
        let v = classify(trimmed, &path);
        match v.status {
            Status::FalsePositive => n_false += 1,
            Status::True => n_true += 1,
            Status::Unverified => n_unverified += 1,
        }
        audits.push(FindingAudit {
            excerpt,
            file_ref: Some(ref_str),
            verdict: v,
        });
    }
    AuditReport {
        n_findings: audits.len() as u64,
        n_false,
        n_unverified,
        n_true,
        audits,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn write(d: &Path, name: &str, body: &str) -> PathBuf {
        let p = d.join(name);
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn classify_no_file_unverified() {
        let v = classify(
            "no UNIQUE constraint here",
            Path::new("/nonexistent/path.py"),
        );
        assert_eq!(v.status, Status::Unverified);
        assert_eq!(v.rule, "no_file");
    }

    #[test]
    fn unique_index_contradicts_no_unique_claim() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "x.py",
            r#"conn.execute("CREATE UNIQUE INDEX idx ON t(a)")"#,
        );
        let v = classify("file lacks no UNIQUE constraint", &p);
        assert_eq!(v.status, Status::FalsePositive);
        assert_eq!(v.rule, "claim_negates_existing_sql");
    }

    #[test]
    fn typed_return_contradicts_no_return_type_claim() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "x.py",
            "def foo() -> Optional[list]:\n    return [1]\n",
        );
        let v = classify("function returns None implicitly", &p);
        assert_eq!(v.status, Status::FalsePositive);
        assert_eq!(v.rule, "claim_negates_typed_return");
    }

    #[test]
    fn existence_guard_contradicts_crash_claim() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "x.py",
            "if not p.exists():\n    return\n",
        );
        let v = classify("production crash on missing path", &p);
        assert_eq!(v.status, Status::FalsePositive);
        assert_eq!(v.rule, "claim_negates_existence_guard");
    }

    #[test]
    fn lock_contradicts_no_lock_claim_python() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "x.py",
            "_LOCK = threading.RLock()\nwith _LOCK:\n    pass\n",
        );
        let v = classify("no thread safety here", &p);
        assert_eq!(v.status, Status::FalsePositive);
    }

    #[test]
    fn lock_contradicts_no_lock_claim_rust() {
        let d = tempdir().unwrap();
        let p = write(d.path(), "x.rs", "let m = Mutex::new(0u32);\n");
        let v = classify("no thread safety in this file", &p);
        assert_eq!(v.status, Status::FalsePositive);
    }

    #[test]
    fn no_match_returns_unverified() {
        let d = tempdir().unwrap();
        let p = write(d.path(), "x.py", "def add(a,b): return a+b\n");
        let v = classify("looks suspicious to me", &p);
        assert_eq!(v.status, Status::Unverified);
        assert_eq!(v.rule, "no_match");
    }

    #[test]
    fn audit_report_finds_severity_lines() {
        let report = "Some intro\n- finding A → **crit** in `agents/foo.py:42`\n- bullet B → **high** with **`AI/ai/run.py`** and so on\n";
        let d = tempdir().unwrap();
        let r = audit_report(report, d.path());
        assert_eq!(r.n_findings, 2);
    }

    #[test]
    fn audit_report_handles_line_without_ref() {
        let report = "Issue → **crit** without any file path here\n";
        let d = tempdir().unwrap();
        let r = audit_report(report, d.path());
        assert_eq!(r.n_findings, 1);
        assert!(r.audits[0].file_ref.is_none());
        assert_eq!(r.n_unverified, 1);
    }
}
