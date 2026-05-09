//! aim-kpi-tracker — per-project KPI tracking (K1).
//!
//! Port of `agents/kpi_tracker.py`. Project YAMLs may declare a `kpis:`
//! block with `id`, `target`, `unit`, `target_kind` (floor/ceiling) and a
//! `history:` array of `{date, value}` points. This crate loads, computes
//! progress + status, renders the morning-brief dashboard, and appends
//! new points back to the YAML.
//!
//! ## Public API
//! - [`load_kpis`] — read a project YAML's `kpis:` block
//! - [`record`] — append a new `(date, value)` point to a named KPI
//! - [`summary`] — render the 📈 dashboard string
//! - [`KPI::progress`], [`KPI::status`], [`KPI::velocity_per_week`]

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum KpiError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("KPI {0:?} not declared in project YAML")]
    UnknownKpi(String),
    #[error("project YAML not found: {0}")]
    NoProject(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TargetKind {
    /// Higher is better — target is the *floor* we want to clear.
    Floor,
    /// Lower is better — target is the *ceiling* we want to stay under.
    Ceiling,
}

impl Default for TargetKind {
    fn default() -> Self {
        TargetKind::Floor
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct KPIPoint {
    pub date: NaiveDate,
    pub value: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KPI {
    pub id: String,
    pub target: f64,
    #[serde(default)]
    pub unit: String,
    #[serde(default)]
    pub target_kind: TargetKind,
    #[serde(default)]
    pub history: Vec<KPIPoint>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Met,
    Near,
    Behind,
    Ok,
    Warn,
    Breach,
    Unknown,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Status::Met => "met",
            Status::Near => "near",
            Status::Behind => "behind",
            Status::Ok => "ok",
            Status::Warn => "warn",
            Status::Breach => "breach",
            Status::Unknown => "unknown",
        }
    }
}

impl KPI {
    /// Latest value across `history`, sorted by date.
    pub fn current(&self) -> Option<f64> {
        if self.history.is_empty() {
            return None;
        }
        let mut sorted = self.history.clone();
        sorted.sort_by_key(|p| p.date);
        Some(sorted.last().unwrap().value)
    }

    /// Fractional progress in `[0.0, 1.0+]`. None when the target is 0 or
    /// no history exists. For `Ceiling` KPIs progress decays from 1.0
    /// toward 0 as we breach.
    pub fn progress(&self) -> Option<f64> {
        let cur = self.current()?;
        if self.target == 0.0 {
            return None;
        }
        match self.target_kind {
            TargetKind::Floor => Some(cur / self.target),
            TargetKind::Ceiling => {
                let breach = (cur - self.target).max(0.0);
                Some((1.0 - breach / self.target.abs()).max(0.0))
            }
        }
    }

    /// Coarse health label.
    pub fn status(&self) -> Status {
        let Some(cur) = self.current() else {
            return Status::Unknown;
        };
        if self.target == 0.0 {
            return Status::Unknown;
        }
        match self.target_kind {
            TargetKind::Ceiling => {
                let util = cur / self.target;
                if util > 1.0 {
                    Status::Breach
                } else if util >= 0.85 {
                    Status::Warn
                } else {
                    Status::Ok
                }
            }
            TargetKind::Floor => {
                let p = cur / self.target;
                if p >= 1.0 {
                    Status::Met
                } else if p >= 0.85 {
                    Status::Near
                } else {
                    Status::Behind
                }
            }
        }
    }

    /// Average rate of change per week across history. Useful for floor
    /// KPIs to spot whether velocity is sufficient to hit the target.
    pub fn velocity_per_week(&self) -> Option<f64> {
        if self.history.len() < 2 {
            return None;
        }
        let mut sorted = self.history.clone();
        sorted.sort_by_key(|p| p.date);
        let first = &sorted[0];
        let last = &sorted[sorted.len() - 1];
        let d_value = last.value - first.value;
        let d_days = (last.date - first.date).num_days();
        if d_days <= 0 {
            return None;
        }
        Some(d_value / (d_days as f64 / 7.0))
    }
}

// ── persistence ───────────────────────────────────────────────────────────

fn parse_point(v: &serde_yaml::Value) -> Option<KPIPoint> {
    let m = v.as_mapping()?;
    let date = m.get("date").and_then(|x| x.as_str())?;
    let date_prefix: String = date.chars().take(10).collect();
    let date = NaiveDate::parse_from_str(&date_prefix, "%Y-%m-%d").ok()?;
    let val = m.get("value").and_then(|x| x.as_f64().or_else(|| x.as_i64().map(|n| n as f64)))?;
    Some(KPIPoint { date, value: val })
}

/// Read a project YAML's `kpis:` block. Skips KPIs whose `target` is
/// non-numeric and history points whose `date`/`value` is malformed
/// (matches Python's lenient parse).
pub fn load_kpis(project_yaml: &Path) -> Result<Vec<KPI>, KpiError> {
    if !project_yaml.exists() {
        return Ok(Vec::new());
    }
    let raw = std::fs::read_to_string(project_yaml)?;
    let parsed: serde_yaml::Value = match serde_yaml::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("kpi yaml parse failed: {e}");
            return Ok(Vec::new());
        }
    };
    let map = match parsed.as_mapping() {
        Some(m) => m,
        None => return Ok(Vec::new()),
    };
    let kpis_seq = match map.get("kpis").and_then(|v| v.as_sequence()) {
        Some(s) => s,
        None => return Ok(Vec::new()),
    };

    let mut out = Vec::new();
    for k in kpis_seq {
        let km = match k.as_mapping() {
            Some(m) => m,
            None => continue,
        };
        let target = match km
            .get("target")
            .and_then(|v| v.as_f64().or_else(|| v.as_i64().map(|n| n as f64)))
        {
            Some(t) => t,
            None => {
                tracing::warn!(
                    "kpi {:?}: target not numeric — skipped",
                    km.get("id").and_then(|v| v.as_str()).unwrap_or("")
                );
                continue;
            }
        };
        let id = km
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let unit = km
            .get("unit")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let target_kind = match km.get("target_kind").and_then(|v| v.as_str()) {
            Some("ceiling") => TargetKind::Ceiling,
            _ => TargetKind::Floor,
        };
        let mut history = Vec::new();
        if let Some(hist) = km.get("history").and_then(|v| v.as_sequence()) {
            for p in hist {
                if let Some(pt) = parse_point(p) {
                    history.push(pt);
                }
            }
        }
        out.push(KPI {
            id,
            target,
            unit,
            target_kind,
            history,
        });
    }
    Ok(out)
}

/// Append a `(date, value)` point to the named KPI in the project YAML.
/// Matches the Python — preserves all sibling YAML keys via Mapping
/// round-trip.
pub fn record(
    project_yaml: &Path,
    kpi_id: &str,
    value: f64,
    date: NaiveDate,
) -> Result<(), KpiError> {
    if !project_yaml.exists() {
        return Err(KpiError::NoProject(project_yaml.display().to_string()));
    }
    let raw = std::fs::read_to_string(project_yaml)?;
    let mut parsed: serde_yaml::Value = serde_yaml::from_str(&raw)?;

    let map = parsed
        .as_mapping_mut()
        .ok_or_else(|| KpiError::Yaml(serde_yaml::from_str::<()>("expected mapping").unwrap_err()))?;

    let kpis = map
        .entry(serde_yaml::Value::String("kpis".into()))
        .or_insert_with(|| serde_yaml::Value::Sequence(Vec::new()));
    let seq = match kpis.as_sequence_mut() {
        Some(s) => s,
        None => return Err(KpiError::UnknownKpi(kpi_id.to_string())),
    };

    let mut found = false;
    for k in seq.iter_mut() {
        let km = match k.as_mapping_mut() {
            Some(m) => m,
            None => continue,
        };
        let id_match = km
            .get("id")
            .and_then(|v| v.as_str())
            .map(|s| s == kpi_id)
            .unwrap_or(false);
        if !id_match {
            continue;
        }
        found = true;
        let history_key = serde_yaml::Value::String("history".into());
        let history = km
            .entry(history_key)
            .or_insert_with(|| serde_yaml::Value::Sequence(Vec::new()));
        let hist_seq = match history.as_sequence_mut() {
            Some(s) => s,
            None => return Err(KpiError::UnknownKpi(kpi_id.to_string())),
        };
        let mut new_point = serde_yaml::Mapping::new();
        new_point.insert(
            serde_yaml::Value::String("date".into()),
            serde_yaml::Value::String(date.format("%Y-%m-%d").to_string()),
        );
        new_point.insert(
            serde_yaml::Value::String("value".into()),
            serde_yaml::to_value(value).unwrap_or(serde_yaml::Value::Number(serde_yaml::Number::from(0))),
        );
        hist_seq.push(serde_yaml::Value::Mapping(new_point));
        break;
    }
    if !found {
        return Err(KpiError::UnknownKpi(kpi_id.to_string()));
    }
    let body = serde_yaml::to_string(&parsed)?;
    std::fs::write(project_yaml, body)?;
    Ok(())
}

// ── presentation ──────────────────────────────────────────────────────────

fn bar(progress: Option<f64>, width: usize) -> String {
    let p = match progress {
        Some(p) if p >= 0.0 => p.min(1.0),
        _ => return "(?)".to_string(),
    };
    let filled = (p * width as f64).round() as usize;
    let mut s = String::with_capacity(width + 2);
    s.push('[');
    for _ in 0..filled.min(width) {
        s.push('█');
    }
    for _ in 0..width.saturating_sub(filled) {
        s.push('·');
    }
    s.push(']');
    s
}

fn fmt_g(x: f64) -> String {
    // Mirror Python's `f"{x:g}"` (significant-figure trim)
    if x.fract() == 0.0 && x.abs() < 1e16 {
        format!("{}", x as i64)
    } else {
        format!("{x}")
    }
}

pub fn summary(project: &str, kpis: &[KPI]) -> String {
    if kpis.is_empty() {
        return String::new();
    }
    let mut lines = vec![format!("📈 KPIs — {project}")];
    for k in kpis {
        let cur_str = match k.current() {
            Some(c) => format!("{}{}", fmt_g(c), k.unit),
            None => "—".to_string(),
        };
        let target_str = format!("{}{}", fmt_g(k.target), k.unit);
        let bar_str = match k.progress() {
            Some(_) => bar(k.progress(), 16),
            None => "(no data)".to_string(),
        };
        let v_str = match k.velocity_per_week() {
            Some(v) if v > 0.0 => format!("  +{v:.1}/w"),
            Some(v) => format!("  {v:.1}/w"),
            None => String::new(),
        };
        lines.push(format!(
            "  • {}: {} / {}  {} {}{}",
            k.id,
            cur_str,
            target_str,
            bar_str,
            k.status().as_str(),
            v_str
        ));
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn d(y: i32, m: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, day).unwrap()
    }

    fn write_yaml(dir: &TempDir, body: &str) -> std::path::PathBuf {
        let p = dir.path().join("proj.yaml");
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn load_basic_floor_kpi() {
        let dir = TempDir::new().unwrap();
        let p = write_yaml(
            &dir,
            r#"kpis:
  - id: pubmed-publications
    target: 8
    unit: count
    history:
      - {date: 2026-04-01, value: 5}
      - {date: 2026-05-01, value: 7}
"#,
        );
        let kpis = load_kpis(&p).unwrap();
        assert_eq!(kpis.len(), 1);
        let k = &kpis[0];
        assert_eq!(k.id, "pubmed-publications");
        assert_eq!(k.target, 8.0);
        assert_eq!(k.history.len(), 2);
        assert_eq!(k.current(), Some(7.0));
        assert!((k.progress().unwrap() - 0.875).abs() < 1e-9);
        assert_eq!(k.status(), Status::Near);
    }

    #[test]
    fn load_ceiling_kpi() {
        let dir = TempDir::new().unwrap();
        let p = write_yaml(
            &dir,
            r#"kpis:
  - id: weekly-llm-cost
    target: 25.0
    target_kind: ceiling
    unit: usd
    history:
      - {date: 2026-05-01, value: 30.0}
"#,
        );
        let kpis = load_kpis(&p).unwrap();
        let k = &kpis[0];
        assert_eq!(k.target_kind, TargetKind::Ceiling);
        assert_eq!(k.status(), Status::Breach);
    }

    #[test]
    fn ceiling_warn_at_85_percent() {
        let kpi = KPI {
            id: "x".into(),
            target: 100.0,
            unit: "".into(),
            target_kind: TargetKind::Ceiling,
            history: vec![KPIPoint {
                date: d(2026, 5, 4),
                value: 90.0,
            }],
        };
        assert_eq!(kpi.status(), Status::Warn);
    }

    #[test]
    fn ceiling_ok_when_below() {
        let kpi = KPI {
            id: "x".into(),
            target: 100.0,
            unit: "".into(),
            target_kind: TargetKind::Ceiling,
            history: vec![KPIPoint {
                date: d(2026, 5, 4),
                value: 50.0,
            }],
        };
        assert_eq!(kpi.status(), Status::Ok);
    }

    #[test]
    fn floor_met_at_target() {
        let kpi = KPI {
            id: "x".into(),
            target: 8.0,
            unit: "".into(),
            target_kind: TargetKind::Floor,
            history: vec![KPIPoint {
                date: d(2026, 5, 4),
                value: 8.0,
            }],
        };
        assert_eq!(kpi.status(), Status::Met);
    }

    #[test]
    fn current_uses_latest_date_not_last_inserted() {
        let kpi = KPI {
            id: "x".into(),
            target: 10.0,
            unit: "".into(),
            target_kind: TargetKind::Floor,
            history: vec![
                KPIPoint {
                    date: d(2026, 5, 1),
                    value: 7.0,
                },
                KPIPoint {
                    date: d(2026, 4, 1),
                    value: 5.0,
                },
            ],
        };
        assert_eq!(kpi.current(), Some(7.0));
    }

    #[test]
    fn velocity_positive_floor_kpi() {
        let kpi = KPI {
            id: "x".into(),
            target: 10.0,
            unit: "".into(),
            target_kind: TargetKind::Floor,
            history: vec![
                KPIPoint {
                    date: d(2026, 4, 1),
                    value: 5.0,
                },
                KPIPoint {
                    date: d(2026, 5, 1),
                    value: 7.0,
                },
            ],
        };
        let v = kpi.velocity_per_week().unwrap();
        // 2 over 30 days = 2 / (30/7) ≈ 0.467 / w
        assert!((v - 2.0 / (30.0 / 7.0)).abs() < 1e-9);
    }

    #[test]
    fn velocity_none_with_single_point() {
        let kpi = KPI {
            id: "x".into(),
            target: 10.0,
            unit: "".into(),
            target_kind: TargetKind::Floor,
            history: vec![KPIPoint {
                date: d(2026, 5, 1),
                value: 5.0,
            }],
        };
        assert!(kpi.velocity_per_week().is_none());
    }

    #[test]
    fn record_appends_to_history_preserving_yaml() {
        let dir = TempDir::new().unwrap();
        let p = write_yaml(
            &dir,
            r#"name: TestProj
kpis:
  - id: pubmed-publications
    target: 8
    history:
      - {date: 2026-04-01, value: 5}
phase: DRAFT
"#,
        );
        record(&p, "pubmed-publications", 6.0, d(2026, 5, 4)).unwrap();
        let raw = std::fs::read_to_string(&p).unwrap();
        // Sibling keys must survive the round-trip
        assert!(raw.contains("name: TestProj"));
        assert!(raw.contains("phase: DRAFT"));
        let kpis = load_kpis(&p).unwrap();
        assert_eq!(kpis[0].history.len(), 2);
        assert_eq!(kpis[0].current(), Some(6.0));
    }

    #[test]
    fn record_unknown_kpi_errors() {
        let dir = TempDir::new().unwrap();
        let p = write_yaml(
            &dir,
            r#"kpis:
  - id: a
    target: 1
"#,
        );
        let err = record(&p, "ghost", 1.0, d(2026, 5, 4)).unwrap_err();
        assert!(matches!(err, KpiError::UnknownKpi(_)));
    }

    #[test]
    fn load_skips_non_numeric_target() {
        let dir = TempDir::new().unwrap();
        let p = write_yaml(
            &dir,
            r#"kpis:
  - id: bad
    target: "not a number"
  - id: good
    target: 5
"#,
        );
        let kpis = load_kpis(&p).unwrap();
        assert_eq!(kpis.len(), 1);
        assert_eq!(kpis[0].id, "good");
    }

    #[test]
    fn load_skips_malformed_history_points() {
        let dir = TempDir::new().unwrap();
        let p = write_yaml(
            &dir,
            r#"kpis:
  - id: x
    target: 10
    history:
      - {date: not-a-date, value: 5}
      - {date: 2026-05-04, value: 7}
"#,
        );
        let kpis = load_kpis(&p).unwrap();
        assert_eq!(kpis[0].history.len(), 1);
        assert_eq!(kpis[0].current(), Some(7.0));
    }

    #[test]
    fn summary_renders_dashboard() {
        let kpis = vec![KPI {
            id: "pubmed".into(),
            target: 8.0,
            unit: "".into(),
            target_kind: TargetKind::Floor,
            history: vec![KPIPoint {
                date: d(2026, 5, 4),
                value: 7.0,
            }],
        }];
        let s = summary("FCLC", &kpis);
        assert!(s.contains("📈 KPIs — FCLC"));
        assert!(s.contains("pubmed"));
        assert!(s.contains("near"));
    }

    #[test]
    fn summary_empty_returns_empty_string() {
        assert_eq!(summary("X", &[]), "");
    }

    #[test]
    fn bar_full_and_empty() {
        let s = bar(Some(0.0), 10);
        assert_eq!(s, "[··········]");
        let s = bar(Some(1.0), 10);
        assert_eq!(s, "[██████████]");
        let s = bar(None, 10);
        assert_eq!(s, "(?)");
    }
}
