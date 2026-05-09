//! aim-doctor-calibration — confidence calibration tracker (D2).
//!
//! Port of `agents/doctor_calibration.py`. Records probabilistic
//! predictions, scores them when outcomes land, aggregates Brier score +
//! per-bucket calibration to detect over/underconfidence.
//!
//! Storage sits behind [`PredictionStore`] so the metric machinery is
//! testable without sqlite.

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CalibrationError {
    #[error("invalid prediction: {0}")]
    Invalid(String),
    #[error("store error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, CalibrationError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Prediction {
    pub id: i64,
    pub ts: DateTime<Utc>,
    pub case_id: Option<String>,
    pub domain: Option<String>,
    pub label: String,
    pub confidence: f64,
    pub rationale: Option<String>,
    /// `Some(true)` = correct, `Some(false)` = wrong, `None` = pending.
    pub outcome: Option<bool>,
    pub outcome_at: Option<DateTime<Utc>>,
    pub outcome_source: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct PredictionInput {
    pub label: String,
    pub confidence: f64,
    pub case_id: Option<String>,
    pub domain: Option<String>,
    pub rationale: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CalibrationMetrics {
    pub n: usize,
    pub accuracy: Option<f64>,
    pub mean_confidence: Option<f64>,
    pub brier: Option<f64>,
    pub bias: Option<f64>,
    pub buckets: Vec<Bucket>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Bucket {
    pub range: String,
    pub n: usize,
    pub accuracy: f64,
    pub mean_conf: f64,
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait PredictionStore: Send + Sync {
    fn insert(&self, ts: DateTime<Utc>, p: &PredictionInput) -> Result<i64>;
    /// Update outcome only when currently NULL. Returns `true` if updated.
    fn resolve(&self, id: i64, outcome: bool, at: DateTime<Utc>, source: &str) -> Result<bool>;
    fn pending(&self, limit: usize) -> Result<Vec<Prediction>>;
    /// All resolved predictions whose `ts >= since`.
    fn resolved_since(&self, since: DateTime<Utc>) -> Result<Vec<Prediction>>;
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct FixedClock(pub DateTime<Utc>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

// ── service ────────────────────────────────────────────────────────────────

pub struct Calibration<'a> {
    pub store: &'a dyn PredictionStore,
    pub clock: &'a dyn Clock,
}

impl<'a> Calibration<'a> {
    pub fn new(store: &'a dyn PredictionStore, clock: &'a dyn Clock) -> Self {
        Self { store, clock }
    }

    /// Persist a prediction. Returns its row id.
    pub fn record(&self, mut p: PredictionInput) -> Result<i64> {
        if p.label.is_empty() {
            return Err(CalibrationError::Invalid("label is required".into()));
        }
        if !(0.0..=1.0).contains(&p.confidence) {
            return Err(CalibrationError::Invalid(format!(
                "confidence must be in [0,1], got {}",
                p.confidence
            )));
        }
        if p.domain.is_none() {
            p.domain = Some("diagnosis".into());
        }
        self.store.insert(self.clock.now(), &p)
    }

    pub fn resolve(&self, id: i64, outcome: bool, source: &str) -> Result<bool> {
        self.store.resolve(id, outcome, self.clock.now(), source)
    }

    pub fn pending(&self, limit: usize) -> Result<Vec<Prediction>> {
        self.store.pending(limit)
    }

    /// Aggregate Brier score + per-bucket calibration. `domain=None`
    /// means "all domains". Mirrors Python `metrics()` exactly.
    pub fn metrics(&self, window_days: i64, domain: Option<&str>) -> Result<CalibrationMetrics> {
        let cutoff = self.clock.now() - Duration::days(window_days);
        let mut rows = self.store.resolved_since(cutoff)?;
        if let Some(d) = domain {
            rows.retain(|p| p.domain.as_deref() == Some(d));
        }
        let n = rows.len();
        if n == 0 {
            return Ok(CalibrationMetrics::default());
        }

        let outcomes: Vec<f64> = rows
            .iter()
            .map(|p| if p.outcome.unwrap_or(false) { 1.0 } else { 0.0 })
            .collect();
        let accuracy: f64 = outcomes.iter().sum::<f64>() / n as f64;
        let mean_conf: f64 =
            rows.iter().map(|p| p.confidence).sum::<f64>() / n as f64;
        let brier: f64 = rows
            .iter()
            .zip(outcomes.iter())
            .map(|(p, o)| (p.confidence - o).powi(2))
            .sum::<f64>()
            / n as f64;

        let edges: &[f64] = &[0.0, 0.2, 0.4, 0.6, 0.8, 1.0001];
        let mut buckets: Vec<Bucket> = Vec::new();
        for i in 0..edges.len() - 1 {
            let lo = edges[i];
            let hi = edges[i + 1];
            let chunk: Vec<&Prediction> = rows
                .iter()
                .filter(|p| (lo..hi).contains(&p.confidence))
                .collect();
            if chunk.is_empty() {
                continue;
            }
            let m = chunk.len();
            let acc: f64 = chunk
                .iter()
                .map(|p| if p.outcome.unwrap_or(false) { 1.0 } else { 0.0 })
                .sum::<f64>()
                / m as f64;
            let mc: f64 = chunk.iter().map(|p| p.confidence).sum::<f64>() / m as f64;
            let display_hi = hi.min(1.0);
            buckets.push(Bucket {
                range: format!("[{:.1},{:.1})", lo, display_hi),
                n: m,
                accuracy: acc,
                mean_conf: mc,
            });
        }

        Ok(CalibrationMetrics {
            n,
            accuracy: Some(accuracy),
            mean_confidence: Some(mean_conf),
            brier: Some(brier),
            bias: Some(mean_conf - accuracy),
            buckets,
        })
    }

    pub fn summary(&self, window_days: i64) -> Result<String> {
        let m = self.metrics(window_days, None)?;
        if m.n == 0 {
            return Ok("(no resolved predictions in window)".into());
        }
        let acc = m.accuracy.unwrap_or(0.0);
        let mc = m.mean_confidence.unwrap_or(0.0);
        let brier = m.brier.unwrap_or(0.0);
        let bias = m.bias.unwrap_or(0.0);
        let label = if bias > 0.05 {
            "overconfident"
        } else if bias < -0.05 {
            "underconfident"
        } else {
            "well-calibrated"
        };
        let mut lines: Vec<String> = vec![
            format!("📊 Calibration — last {}d, n={}", window_days, m.n),
            format!("  accuracy        = {:.3}", acc),
            format!("  mean confidence = {:.3}", mc),
            format!("  Brier score     = {:.3}", brier),
            format!("  bias            = {:+.3}  ({})", bias, label),
        ];
        if !m.buckets.is_empty() {
            lines.push("  per-bucket:".into());
            for b in &m.buckets {
                lines.push(format!(
                    "    {:11}  n={:3}  acc={:.2}  conf={:.2}",
                    b.range, b.n, b.accuracy, b.mean_conf
                ));
            }
        }
        Ok(lines.join("\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use std::collections::HashMap;

    #[derive(Default)]
    struct InMemStore {
        rows: Mutex<HashMap<i64, Prediction>>,
        next_id: Mutex<i64>,
    }
    impl InMemStore {
        fn dump(&self) -> Vec<Prediction> {
            self.rows.lock().values().cloned().collect()
        }
    }
    impl PredictionStore for InMemStore {
        fn insert(&self, ts: DateTime<Utc>, p: &PredictionInput) -> Result<i64> {
            let mut id = self.next_id.lock();
            *id += 1;
            let row_id = *id;
            self.rows.lock().insert(
                row_id,
                Prediction {
                    id: row_id,
                    ts,
                    case_id: p.case_id.clone(),
                    domain: p.domain.clone(),
                    label: p.label.clone(),
                    confidence: p.confidence,
                    rationale: p.rationale.clone(),
                    outcome: None,
                    outcome_at: None,
                    outcome_source: None,
                },
            );
            Ok(row_id)
        }
        fn resolve(
            &self,
            id: i64,
            outcome: bool,
            at: DateTime<Utc>,
            source: &str,
        ) -> Result<bool> {
            let mut m = self.rows.lock();
            match m.get_mut(&id) {
                Some(r) if r.outcome.is_none() => {
                    r.outcome = Some(outcome);
                    r.outcome_at = Some(at);
                    r.outcome_source = Some(source.into());
                    Ok(true)
                }
                _ => Ok(false),
            }
        }
        fn pending(&self, limit: usize) -> Result<Vec<Prediction>> {
            let mut v: Vec<Prediction> = self
                .rows
                .lock()
                .values()
                .filter(|p| p.outcome.is_none())
                .cloned()
                .collect();
            v.sort_by_key(|p| p.ts);
            v.truncate(limit);
            Ok(v)
        }
        fn resolved_since(&self, since: DateTime<Utc>) -> Result<Vec<Prediction>> {
            let mut v: Vec<Prediction> = self
                .rows
                .lock()
                .values()
                .filter(|p| p.outcome.is_some() && p.ts >= since)
                .cloned()
                .collect();
            v.sort_by(|a, b| b.ts.cmp(&a.ts));
            Ok(v)
        }
    }

    fn ts(secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(secs, 0).unwrap()
    }

    fn input(label: &str, conf: f64, domain: &str) -> PredictionInput {
        PredictionInput {
            label: label.into(),
            confidence: conf,
            case_id: None,
            domain: Some(domain.into()),
            rationale: None,
        }
    }

    // ── record ──────────────────────────────────────────────────────────────

    #[test]
    fn record_persists_with_clock_timestamp() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(1_700_000_000));
        let cal = Calibration::new(&store, &clock);
        let id = cal.record(input("STEMI", 0.7, "diagnosis")).unwrap();
        let row = store.rows.lock().get(&id).cloned().unwrap();
        assert_eq!(row.label, "STEMI");
        assert_eq!(row.ts, ts(1_700_000_000));
        assert_eq!(row.outcome, None);
    }

    #[test]
    fn record_rejects_empty_label() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(0));
        let cal = Calibration::new(&store, &clock);
        let mut p = input("", 0.5, "diagnosis");
        p.label = String::new();
        assert!(cal.record(p).is_err());
    }

    #[test]
    fn record_rejects_out_of_range_confidence() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(0));
        let cal = Calibration::new(&store, &clock);
        assert!(cal.record(input("x", -0.1, "diagnosis")).is_err());
        assert!(cal.record(input("x", 1.5, "diagnosis")).is_err());
    }

    #[test]
    fn record_defaults_domain_to_diagnosis() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(0));
        let cal = Calibration::new(&store, &clock);
        let id = cal
            .record(PredictionInput {
                label: "x".into(),
                confidence: 0.5,
                domain: None,
                ..Default::default()
            })
            .unwrap();
        assert_eq!(
            store.rows.lock().get(&id).unwrap().domain.as_deref(),
            Some("diagnosis")
        );
    }

    // ── resolve ─────────────────────────────────────────────────────────────

    #[test]
    fn resolve_marks_outcome_first_time_only() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(1_700_000_000));
        let cal = Calibration::new(&store, &clock);
        let id = cal.record(input("x", 0.7, "diagnosis")).unwrap();
        assert!(cal.resolve(id, true, "ehr").unwrap());
        // second resolve attempt → false (already set)
        assert!(!cal.resolve(id, false, "manual").unwrap());
        let row = store.rows.lock().get(&id).cloned().unwrap();
        assert_eq!(row.outcome, Some(true));
        assert_eq!(row.outcome_source.as_deref(), Some("ehr"));
    }

    // ── pending / metrics empty ────────────────────────────────────────────

    #[test]
    fn metrics_returns_zero_when_no_resolved() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(1_700_000_000));
        let cal = Calibration::new(&store, &clock);
        cal.record(input("x", 0.5, "diagnosis")).unwrap();
        let m = cal.metrics(30, None).unwrap();
        assert_eq!(m.n, 0);
        assert!(m.accuracy.is_none());
        assert!(m.buckets.is_empty());
    }

    // ── metrics calculations ───────────────────────────────────────────────

    fn well_calibrated_dataset() -> InMemStore {
        let store = InMemStore::default();
        // Manually insert resolved rows with known confidence and outcome
        for (conf, outcome, dom) in [
            (0.1, false, "diagnosis"),
            (0.1, false, "diagnosis"),
            (0.5, true, "diagnosis"),
            (0.5, false, "diagnosis"),
            (0.9, true, "diagnosis"),
            (0.9, true, "diagnosis"),
        ] {
            let mut id = store.next_id.lock();
            *id += 1;
            let i = *id;
            store.rows.lock().insert(
                i,
                Prediction {
                    id: i,
                    ts: ts(1_700_000_000),
                    case_id: None,
                    domain: Some(dom.into()),
                    label: format!("p{}", i),
                    confidence: conf,
                    rationale: None,
                    outcome: Some(outcome),
                    outcome_at: Some(ts(1_700_000_001)),
                    outcome_source: Some("test".into()),
                },
            );
        }
        store
    }

    #[test]
    fn metrics_computes_accuracy_brier_bias() {
        let store = well_calibrated_dataset();
        let clock = FixedClock(ts(1_700_000_000) + Duration::days(1));
        let cal = Calibration::new(&store, &clock);
        let m = cal.metrics(30, None).unwrap();
        assert_eq!(m.n, 6);
        // 3 correct out of 6
        assert!((m.accuracy.unwrap() - 0.5).abs() < 1e-9);
        // mean conf = (0.1+0.1+0.5+0.5+0.9+0.9)/6 = 0.5
        assert!((m.mean_confidence.unwrap() - 0.5).abs() < 1e-9);
        // bias = mean_conf - accuracy = 0
        assert!((m.bias.unwrap()).abs() < 1e-9);
        // brier = mean of (conf - outcome)^2 → calculated:
        // (0.01+0.01+0.25+0.25+0.01+0.01)/6 = 0.54/6 = 0.09
        assert!((m.brier.unwrap() - 0.09).abs() < 1e-9);
    }

    #[test]
    fn metrics_buckets_use_python_edges() {
        let store = well_calibrated_dataset();
        let clock = FixedClock(ts(1_700_000_000) + Duration::days(1));
        let cal = Calibration::new(&store, &clock);
        let m = cal.metrics(30, None).unwrap();
        // edges 0.0, 0.2, 0.4, 0.6, 0.8, 1.0001 → buckets [0,0.2), [0.4,0.6), [0.8,1.0]
        // confidences 0.1, 0.1 → bucket 0
        // 0.5, 0.5 → bucket [0.4, 0.6)
        // 0.9, 0.9 → bucket [0.8, 1.0)
        let ranges: Vec<&str> = m.buckets.iter().map(|b| b.range.as_str()).collect();
        assert!(ranges.iter().any(|r| r.starts_with("[0.0,0.2)")));
        assert!(ranges.iter().any(|r| r.starts_with("[0.4,0.6)")));
        assert!(ranges.iter().any(|r| r.starts_with("[0.8,1.0)")));
        // 3 occupied buckets total
        assert_eq!(m.buckets.len(), 3);
    }

    #[test]
    fn metrics_filters_by_domain() {
        let store = InMemStore::default();
        for (conf, outcome, dom) in [
            (0.9, true, "diagnosis"),
            (0.9, true, "diagnosis"),
            (0.1, false, "treatment"),
        ] {
            let mut id = store.next_id.lock();
            *id += 1;
            let i = *id;
            store.rows.lock().insert(
                i,
                Prediction {
                    id: i,
                    ts: ts(1_700_000_000),
                    domain: Some(dom.into()),
                    label: "p".into(),
                    confidence: conf,
                    outcome: Some(outcome),
                    ..Default::default()
                },
            );
        }
        let clock = FixedClock(ts(1_700_000_000) + Duration::days(1));
        let cal = Calibration::new(&store, &clock);
        let m = cal.metrics(30, Some("diagnosis")).unwrap();
        assert_eq!(m.n, 2);
        assert_eq!(m.accuracy.unwrap(), 1.0);
    }

    // ── summary ────────────────────────────────────────────────────────────

    #[test]
    fn summary_reports_overconfident_label() {
        let store = InMemStore::default();
        // mean conf 0.9, accuracy 0.5 → bias = +0.4 (overconfident)
        for (conf, outcome) in [(0.9, true), (0.9, false)] {
            let mut id = store.next_id.lock();
            *id += 1;
            let i = *id;
            store.rows.lock().insert(
                i,
                Prediction {
                    id: i,
                    ts: ts(1_700_000_000),
                    domain: Some("diagnosis".into()),
                    label: "p".into(),
                    confidence: conf,
                    outcome: Some(outcome),
                    ..Default::default()
                },
            );
        }
        let clock = FixedClock(ts(1_700_000_000) + Duration::days(1));
        let cal = Calibration::new(&store, &clock);
        let s = cal.summary(30).unwrap();
        assert!(s.contains("overconfident"));
        assert!(s.contains("Brier score"));
        assert!(s.contains("per-bucket"));
    }

    #[test]
    fn summary_no_data_returns_canned_message() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(1_700_000_000));
        let cal = Calibration::new(&store, &clock);
        assert_eq!(
            cal.summary(30).unwrap(),
            "(no resolved predictions in window)"
        );
    }

    // ── pending ────────────────────────────────────────────────────────────

    #[test]
    fn pending_lists_unresolved() {
        let store = InMemStore::default();
        let clock = FixedClock(ts(1_700_000_000));
        let cal = Calibration::new(&store, &clock);
        let id1 = cal.record(input("a", 0.5, "diagnosis")).unwrap();
        cal.record(input("b", 0.5, "diagnosis")).unwrap();
        cal.resolve(id1, true, "x").unwrap();
        let pending = cal.pending(50).unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].label, "b");
        // Witness no leak from store.dump
        assert_eq!(store.dump().len(), 2);
    }
}
