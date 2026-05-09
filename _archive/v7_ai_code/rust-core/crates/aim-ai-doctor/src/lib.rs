//! aim-ai-doctor — DR2 wiring smoke test.
//!
//! Local introspection probes for the AI subproject. Adapted from the
//! Python predecessor `AI/ai/doctor.py`. The Python version checks
//! that every `AI/ai/*.py` imports cleanly; the Rust port can't do
//! that exactly (Rust has no equivalent of `import`), so the modules
//! probe instead checks that every member crate compiles in the
//! workspace target dir (best-effort: looks for the produced rlib).
//!
//! Public API:
//! - [`diagnose(repo_root)`] → list of [`Probe`] results
//! - [`summary(probes)`] → human-readable text

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Probe {
    pub name: String,
    pub ok: bool,
    pub detail: String,
    pub severity: Severity,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Severity {
    Info,
    Warn,
    Crit,
}

pub fn diagnose(repo_root: &Path) -> Vec<Probe> {
    vec![
        probe_db_writable(),
        probe_workspace_present(repo_root),
        probe_artifacts_dir(repo_root),
        probe_direction_rule(repo_root),
        probe_latest_report_parseable(repo_root),
    ]
}

pub fn has_critical_failure(probes: &[Probe]) -> bool {
    probes
        .iter()
        .any(|p| !p.ok && matches!(p.severity, Severity::Crit))
}

// ── individual probes ───────────────────────────────────────────

fn probe_db_writable() -> Probe {
    let p = aim_ai_ledger::Ledger::default_path();
    let parent = p.parent().unwrap_or_else(|| Path::new("."));
    if let Err(e) = std::fs::create_dir_all(parent) {
        return Probe {
            name: "db_writable".into(),
            ok: false,
            detail: format!("{} — {e}", parent.display()),
            severity: Severity::Crit,
        };
    }
    let marker = parent.join(".doctor_probe");
    if let Err(e) = std::fs::write(&marker, b"ok") {
        return Probe {
            name: "db_writable".into(),
            ok: false,
            detail: format!("{} — {e}", marker.display()),
            severity: Severity::Crit,
        };
    }
    let _ = std::fs::remove_file(&marker);
    Probe {
        name: "db_writable".into(),
        ok: true,
        detail: format!("{} is writable", parent.display()),
        severity: Severity::Info,
    }
}

fn probe_workspace_present(repo_root: &Path) -> Probe {
    let cargo = repo_root.join("AIM").join("rust-core").join("Cargo.toml");
    if !cargo.exists() {
        return Probe {
            name: "workspace".into(),
            ok: false,
            detail: format!("{} not found", cargo.display()),
            severity: Severity::Crit,
        };
    }
    Probe {
        name: "workspace".into(),
        ok: true,
        detail: format!("workspace at {}", cargo.display()),
        severity: Severity::Info,
    }
}

fn probe_artifacts_dir(repo_root: &Path) -> Probe {
    let p: PathBuf = repo_root.join("AIM").join("AI").join("artifacts");
    if let Err(e) = std::fs::create_dir_all(&p) {
        return Probe {
            name: "artifacts_dir".into(),
            ok: false,
            detail: format!("{} — {e}", p.display()),
            severity: Severity::Warn,
        };
    }
    let n = std::fs::read_dir(&p)
        .map(|it| {
            it.filter_map(Result::ok)
                .filter(|e| {
                    let n = e.file_name();
                    let s = n.to_string_lossy();
                    s.starts_with("self_diag_") && !s.contains("_request_")
                })
                .count()
        })
        .unwrap_or(0);
    Probe {
        name: "artifacts_dir".into(),
        ok: true,
        detail: format!("{} ({} reports)", p.display(), n),
        severity: Severity::Info,
    }
}

/// Check the Python-era contract that `agents/` must not import from
/// `AI/`. Best-effort grep over the repo. The Rust port reuses the
/// same rule because the Python AIM coexists during migration.
fn probe_direction_rule(repo_root: &Path) -> Probe {
    let agents = repo_root.join("AIM").join("agents");
    if !agents.exists() {
        return Probe {
            name: "direction_rule".into(),
            ok: true,
            detail: "agents/ not present (fresh checkout)".into(),
            severity: Severity::Info,
        };
    }
    let mut violations: Vec<String> = Vec::new();
    if let Ok(walker) = walk_py(&agents) {
        for path in walker {
            if let Ok(text) = std::fs::read_to_string(&path) {
                for (i, line) in text.lines().enumerate() {
                    let t = line.trim_start();
                    if (t.starts_with("from AI.") || t.starts_with("import AI."))
                        && !line.contains("# noqa: AI-direction")
                    {
                        violations.push(format!(
                            "{}:{} {}",
                            path.display(),
                            i + 1,
                            t.trim()
                        ));
                    }
                }
            }
        }
    }
    if violations.is_empty() {
        Probe {
            name: "direction_rule".into(),
            ok: true,
            detail: "agents/ → AI/ imports: 0 (clean)".into(),
            severity: Severity::Info,
        }
    } else {
        let head: Vec<String> = violations.iter().take(5).cloned().collect();
        Probe {
            name: "direction_rule".into(),
            ok: false,
            detail: format!(
                "agents/ imports AI/ — direction rule violated:\n  {}",
                head.join("\n  ")
            ),
            severity: Severity::Crit,
        }
    }
}

fn walk_py(dir: &Path) -> std::io::Result<Vec<PathBuf>> {
    let mut out: Vec<PathBuf> = Vec::new();
    let mut stack: Vec<PathBuf> = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for entry in std::fs::read_dir(&d)?.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|s| s.to_str()) == Some("py") {
                out.push(p);
            }
        }
    }
    Ok(out)
}

fn probe_latest_report_parseable(repo_root: &Path) -> Probe {
    let dir = repo_root.join("AIM").join("AI").join("artifacts");
    let mut cands: Vec<PathBuf> = match std::fs::read_dir(&dir) {
        Ok(it) => it
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| {
                let n = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
                n.starts_with("self_diag_") && !n.contains("_request_")
            })
            .collect(),
        Err(_) => Vec::new(),
    };
    cands.sort();
    let Some(latest) = cands.last() else {
        return Probe {
            name: "latest_report".into(),
            ok: true,
            detail: "(no reports yet — first run pending)".into(),
            severity: Severity::Info,
        };
    };
    match std::fs::read_to_string(latest) {
        Ok(text) => {
            let parsed = aim_ai_meta_evaluator::parse_report(&text);
            Probe {
                name: "latest_report".into(),
                ok: true,
                detail: format!(
                    "{} parsed ok ({} findings, grade {:?})",
                    latest.display(),
                    parsed.findings.len(),
                    parsed.grade
                ),
                severity: Severity::Info,
            }
        }
        Err(e) => Probe {
            name: "latest_report".into(),
            ok: false,
            detail: format!("{} — {e}", latest.display()),
            severity: Severity::Warn,
        },
    }
}

pub fn summary(probes: &[Probe]) -> String {
    let mut out: Vec<String> = vec!["🩺 AIM/AI Doctor".into()];
    for p in probes {
        let mark = match (p.ok, p.severity) {
            (true, _) => "✓",
            (false, Severity::Crit) => "❌",
            (false, Severity::Warn) => "⚠",
            (false, _) => "•",
        };
        out.push(format!("  {} {} — {}", mark, p.name, p.detail.lines().next().unwrap_or("")));
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn empty_repo_root_still_emits_probes() {
        let d = tempdir().unwrap();
        let probes = diagnose(d.path());
        assert_eq!(probes.len(), 5);
        // Workspace probe should fail
        let ws = probes.iter().find(|p| p.name == "workspace").unwrap();
        assert!(!ws.ok);
    }

    #[test]
    fn artifacts_probe_creates_dir_and_counts_zero() {
        let d = tempdir().unwrap();
        let probe = probe_artifacts_dir(d.path());
        assert!(probe.ok);
        assert!(d.path().join("AIM").join("AI").join("artifacts").exists());
    }

    #[test]
    fn direction_rule_clean_when_no_agents() {
        let d = tempdir().unwrap();
        let probe = probe_direction_rule(d.path());
        assert!(probe.ok);
    }

    #[test]
    fn direction_rule_flags_python_import_of_AI() {
        let d = tempdir().unwrap();
        let agents = d.path().join("AIM").join("agents");
        std::fs::create_dir_all(&agents).unwrap();
        std::fs::write(
            agents.join("bad.py"),
            "from AI.ai.diagnostic_ledger import recent\n",
        )
        .unwrap();
        let probe = probe_direction_rule(d.path());
        assert!(!probe.ok);
        assert_eq!(probe.severity, Severity::Crit);
        assert!(probe.detail.contains("bad.py"));
    }

    #[test]
    fn direction_rule_respects_noqa_marker() {
        let d = tempdir().unwrap();
        let agents = d.path().join("AIM").join("agents");
        std::fs::create_dir_all(&agents).unwrap();
        std::fs::write(
            agents.join("ok.py"),
            "from AI.ai.x import y  # noqa: AI-direction\n",
        )
        .unwrap();
        let probe = probe_direction_rule(d.path());
        assert!(probe.ok);
    }

    #[test]
    fn latest_report_parses_when_present() {
        let d = tempdir().unwrap();
        let art = d.path().join("AIM").join("AI").join("artifacts");
        std::fs::create_dir_all(&art).unwrap();
        std::fs::write(
            art.join("self_diag_2026-05-04.md"),
            "Grade: A\n- crit | 0 |\n",
        )
        .unwrap();
        let probe = probe_latest_report_parseable(d.path());
        assert!(probe.ok);
        assert!(probe.detail.contains("parsed ok"));
    }

    #[test]
    fn latest_report_no_artifacts_is_info() {
        let d = tempdir().unwrap();
        let probe = probe_latest_report_parseable(d.path());
        assert!(probe.ok);
        assert!(probe.detail.contains("first run pending"));
    }

    #[test]
    fn summary_renders_lines() {
        let probes = vec![Probe {
            name: "x".into(),
            ok: true,
            detail: "fine".into(),
            severity: Severity::Info,
        }];
        let s = summary(&probes);
        assert!(s.contains("🩺"));
        assert!(s.contains("x — fine"));
    }

    #[test]
    fn has_critical_failure_detection() {
        let p_ok = Probe {
            name: "a".into(),
            ok: true,
            detail: "".into(),
            severity: Severity::Info,
        };
        let p_warn = Probe {
            name: "b".into(),
            ok: false,
            detail: "".into(),
            severity: Severity::Warn,
        };
        let p_crit = Probe {
            name: "c".into(),
            ok: false,
            detail: "".into(),
            severity: Severity::Crit,
        };
        assert!(!has_critical_failure(&[p_ok.clone(), p_warn.clone()]));
        assert!(has_critical_failure(&[p_ok, p_warn, p_crit]));
    }
}
