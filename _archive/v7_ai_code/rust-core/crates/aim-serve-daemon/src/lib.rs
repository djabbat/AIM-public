//! aim-serve-daemon — long-running orchestrator scheduler.
//!
//! Port of `agents/serve_daemon.py`. Handles schedule parsing
//! (`daily@HH:MM` / `weekly@DOW@HH:MM` / `every@Nm`), due-detection
//! against a pluggable [`Clock`] and [`StateStore`], and JSON request
//! dispatch via a pluggable [`RequestHandler`]. The actual Unix socket
//! and signal handling stay in the binary; everything testable is here.

use std::collections::BTreeMap;
use std::sync::Arc;

use chrono::{DateTime, Datelike, Timelike, Utc, Weekday};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

// ── schedule ───────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Schedule {
    Daily { h: u32, m: u32 },
    Weekly { dow: Weekday, h: u32, m: u32 },
    Every { minutes: u64 },
}

#[derive(Debug, Error)]
pub enum ScheduleError {
    #[error("unrecognised schedule: {0}")]
    Unrecognised(String),
    #[error("bad time component in {0}")]
    BadTime(String),
    #[error("bad day-of-week in {0}")]
    BadDow(String),
}

pub fn parse_schedule(spec: &str) -> Result<Schedule, ScheduleError> {
    let s = spec.trim();
    if let Some(rest) = s.strip_prefix("daily@") {
        let (hh, mm) = rest
            .split_once(':')
            .ok_or_else(|| ScheduleError::BadTime(spec.to_string()))?;
        let h: u32 = hh
            .parse()
            .map_err(|_| ScheduleError::BadTime(spec.to_string()))?;
        let m: u32 = mm
            .parse()
            .map_err(|_| ScheduleError::BadTime(spec.to_string()))?;
        return Ok(Schedule::Daily { h, m });
    }
    if let Some(rest) = s.strip_prefix("weekly@") {
        let (dow_s, hhmm) = rest
            .split_once('@')
            .ok_or_else(|| ScheduleError::Unrecognised(spec.to_string()))?;
        let dow = parse_dow(dow_s).ok_or_else(|| ScheduleError::BadDow(spec.to_string()))?;
        let (hh, mm) = hhmm
            .split_once(':')
            .ok_or_else(|| ScheduleError::BadTime(spec.to_string()))?;
        let h: u32 = hh
            .parse()
            .map_err(|_| ScheduleError::BadTime(spec.to_string()))?;
        let m: u32 = mm
            .parse()
            .map_err(|_| ScheduleError::BadTime(spec.to_string()))?;
        return Ok(Schedule::Weekly { dow, h, m });
    }
    if let Some(rest) = s.strip_prefix("every@") {
        if let Some(num) = rest.strip_suffix('m') {
            let minutes: u64 = num
                .parse()
                .map_err(|_| ScheduleError::Unrecognised(spec.to_string()))?;
            return Ok(Schedule::Every { minutes });
        }
    }
    Err(ScheduleError::Unrecognised(spec.to_string()))
}

fn parse_dow(name: &str) -> Option<Weekday> {
    let lc = name.to_lowercase();
    let key: String = lc.chars().take(3).collect();
    match key.as_str() {
        "mon" => Some(Weekday::Mon),
        "tue" => Some(Weekday::Tue),
        "wed" => Some(Weekday::Wed),
        "thu" => Some(Weekday::Thu),
        "fri" => Some(Weekday::Fri),
        "sat" => Some(Weekday::Sat),
        "sun" => Some(Weekday::Sun),
        _ => None,
    }
}

pub fn is_due(spec: &Schedule, last_run: Option<DateTime<Utc>>, now: DateTime<Utc>) -> bool {
    match spec {
        Schedule::Every { minutes } => match last_run {
            None => true,
            Some(t) => (now - t).num_seconds() >= (*minutes as i64) * 60,
        },
        Schedule::Daily { h, m } => {
            let target = now
                .with_hour(*h)
                .and_then(|d| d.with_minute(*m))
                .and_then(|d| d.with_second(0))
                .and_then(|d| d.with_nanosecond(0));
            let target = match target {
                Some(t) => t,
                None => return false,
            };
            if now < target {
                return false;
            }
            match last_run {
                None => true,
                Some(t) => t < target,
            }
        }
        Schedule::Weekly { dow, h, m } => {
            if now.weekday() != *dow {
                return false;
            }
            let target = now
                .with_hour(*h)
                .and_then(|d| d.with_minute(*m))
                .and_then(|d| d.with_second(0))
                .and_then(|d| d.with_nanosecond(0));
            let target = match target {
                Some(t) => t,
                None => return false,
            };
            if now < target {
                return false;
            }
            match last_run {
                None => true,
                Some(t) => t < target,
            }
        }
    }
}

// ── job + tick ─────────────────────────────────────────────────────────────

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct ManualClock {
    inner: Mutex<DateTime<Utc>>,
}

impl ManualClock {
    pub fn new(start: DateTime<Utc>) -> Self {
        Self { inner: Mutex::new(start) }
    }
    pub fn set(&self, t: DateTime<Utc>) {
        *self.inner.lock() = t;
    }
}

impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.inner.lock()
    }
}

pub trait StateStore: Send + Sync {
    fn last_run(&self, job: &str) -> Option<DateTime<Utc>>;
    fn set_last_run(&self, job: &str, t: DateTime<Utc>);
}

pub struct InMemState {
    inner: Mutex<BTreeMap<String, DateTime<Utc>>>,
}

impl Default for InMemState {
    fn default() -> Self {
        Self {
            inner: Mutex::new(BTreeMap::new()),
        }
    }
}

impl InMemState {
    pub fn new() -> Self {
        Self::default()
    }
}

impl StateStore for InMemState {
    fn last_run(&self, job: &str) -> Option<DateTime<Utc>> {
        self.inner.lock().get(job).copied()
    }
    fn set_last_run(&self, job: &str, t: DateTime<Utc>) {
        self.inner.lock().insert(job.to_string(), t);
    }
}

pub type JobFn = Arc<dyn Fn() -> Result<(), String> + Send + Sync>;

pub struct Job {
    pub name: String,
    pub schedule: Schedule,
    pub description: String,
    pub run: JobFn,
}

impl Job {
    pub fn new<S: Into<String>>(name: S, schedule: Schedule, run: JobFn) -> Self {
        Self {
            name: name.into(),
            schedule,
            description: String::new(),
            run,
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct TickReport {
    pub fired: Vec<String>,
    pub failed: Vec<String>,
}

pub fn tick(jobs: &[Job], clock: &dyn Clock, state: &dyn StateStore) -> TickReport {
    let mut report = TickReport::default();
    let now = clock.now();
    for job in jobs {
        let last = state.last_run(&job.name);
        if !is_due(&job.schedule, last, now) {
            continue;
        }
        match (job.run)() {
            Ok(()) => {
                report.fired.push(job.name.clone());
                let stamp = now
                    .with_nanosecond(0)
                    .unwrap_or(now);
                state.set_last_run(&job.name, stamp);
            }
            Err(_) => {
                report.failed.push(job.name.clone());
            }
        }
    }
    report
}

// ── request dispatch ───────────────────────────────────────────────────────

pub trait RequestHandler: Send + Sync {
    fn do_action(&self, args: &[String]) -> serde_json::Value;
}

pub fn handle_request(
    raw: &str,
    handler: &dyn RequestHandler,
    jobs: &[Job],
    clock: &dyn Clock,
    state: &dyn StateStore,
) -> String {
    let msg: serde_json::Value = match serde_json::from_str(raw) {
        Ok(v) => v,
        Err(_) => {
            return serde_json::json!({"error": "invalid JSON"}).to_string();
        }
    };
    let cmd = msg.get("cmd").and_then(|v| v.as_str()).unwrap_or("");
    match cmd {
        "ping" => serde_json::json!({"pong": true}).to_string(),
        "do" => {
            let args: Vec<String> = msg
                .get("args")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();
            let out = handler.do_action(&args);
            out.to_string()
        }
        "tick" => {
            let r = tick(jobs, clock, state);
            serde_json::json!({"fired": r.fired}).to_string()
        }
        other => serde_json::json!({"error": format!("unknown cmd {:?}", other)}).to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use std::sync::atomic::{AtomicU32, Ordering};

    fn ts(y: i32, m: u32, d: u32, h: u32, mi: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, mi, 0).unwrap()
    }

    // ── parse_schedule ─────────────────────────────────────────────────────

    #[test]
    fn parse_daily() {
        assert_eq!(
            parse_schedule("daily@09:00").unwrap(),
            Schedule::Daily { h: 9, m: 0 }
        );
    }

    #[test]
    fn parse_weekly() {
        assert_eq!(
            parse_schedule("weekly@sun@09:00").unwrap(),
            Schedule::Weekly {
                dow: Weekday::Sun,
                h: 9,
                m: 0
            }
        );
    }

    #[test]
    fn parse_every() {
        assert_eq!(
            parse_schedule("every@30m").unwrap(),
            Schedule::Every { minutes: 30 }
        );
    }

    #[test]
    fn parse_dow_lower_and_upper() {
        assert_eq!(parse_dow("MON"), Some(Weekday::Mon));
        assert_eq!(parse_dow("Wednesday"), Some(Weekday::Wed));
        assert_eq!(parse_dow("xyz"), None);
    }

    #[test]
    fn parse_unrecognised() {
        assert!(parse_schedule("never").is_err());
        assert!(parse_schedule("daily@").is_err());
        assert!(parse_schedule("every@99h").is_err());
    }

    // ── is_due ─────────────────────────────────────────────────────────────

    #[test]
    fn every_first_run_is_due() {
        let s = Schedule::Every { minutes: 30 };
        assert!(is_due(&s, None, ts(2026, 5, 5, 12, 0)));
    }

    #[test]
    fn every_within_interval_not_due() {
        let s = Schedule::Every { minutes: 30 };
        let last = ts(2026, 5, 5, 12, 0);
        assert!(!is_due(&s, Some(last), ts(2026, 5, 5, 12, 15)));
    }

    #[test]
    fn every_after_interval_due() {
        let s = Schedule::Every { minutes: 30 };
        let last = ts(2026, 5, 5, 12, 0);
        assert!(is_due(&s, Some(last), ts(2026, 5, 5, 12, 31)));
    }

    #[test]
    fn daily_before_target_not_due() {
        let s = Schedule::Daily { h: 9, m: 0 };
        assert!(!is_due(&s, None, ts(2026, 5, 5, 8, 59)));
    }

    #[test]
    fn daily_after_target_first_run_due() {
        let s = Schedule::Daily { h: 9, m: 0 };
        assert!(is_due(&s, None, ts(2026, 5, 5, 9, 0)));
        assert!(is_due(&s, None, ts(2026, 5, 5, 23, 30)));
    }

    #[test]
    fn daily_already_ran_today_not_due() {
        let s = Schedule::Daily { h: 9, m: 0 };
        let last = ts(2026, 5, 5, 9, 1);
        assert!(!is_due(&s, Some(last), ts(2026, 5, 5, 12, 0)));
    }

    #[test]
    fn daily_ran_yesterday_due_today() {
        let s = Schedule::Daily { h: 9, m: 0 };
        let last = ts(2026, 5, 4, 9, 1);
        assert!(is_due(&s, Some(last), ts(2026, 5, 5, 9, 0)));
    }

    #[test]
    fn weekly_only_on_dow() {
        // 2026-05-03 is a Sunday
        let s = Schedule::Weekly {
            dow: Weekday::Sun,
            h: 9,
            m: 0,
        };
        assert!(is_due(&s, None, ts(2026, 5, 3, 9, 0)));
        assert!(!is_due(&s, None, ts(2026, 5, 4, 9, 0))); // monday
    }

    // ── tick ───────────────────────────────────────────────────────────────

    #[test]
    fn tick_fires_due_jobs_and_updates_state() {
        let counter = Arc::new(AtomicU32::new(0));
        let c2 = counter.clone();
        let job = Job::new(
            "every-min",
            Schedule::Every { minutes: 1 },
            Arc::new(move || {
                c2.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }),
        );
        let clock = ManualClock::new(ts(2026, 5, 5, 12, 0));
        let state = InMemState::new();
        let r = tick(&[job], &clock, &state);
        assert_eq!(r.fired, vec!["every-min".to_string()]);
        assert_eq!(counter.load(Ordering::SeqCst), 1);
        assert_eq!(state.last_run("every-min"), Some(ts(2026, 5, 5, 12, 0)));
    }

    #[test]
    fn tick_does_not_double_fire_within_interval() {
        let counter = Arc::new(AtomicU32::new(0));
        let c2 = counter.clone();
        let job = Job::new(
            "every-30",
            Schedule::Every { minutes: 30 },
            Arc::new(move || {
                c2.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }),
        );
        let clock = ManualClock::new(ts(2026, 5, 5, 12, 0));
        let state = InMemState::new();
        tick(std::slice::from_ref(&job), &clock, &state);
        clock.set(ts(2026, 5, 5, 12, 10));
        let r = tick(&[job], &clock, &state);
        assert!(r.fired.is_empty());
        assert_eq!(counter.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn tick_records_failure_separately() {
        let job = Job::new(
            "boom",
            Schedule::Every { minutes: 1 },
            Arc::new(|| Err("nope".into())),
        );
        let clock = ManualClock::new(ts(2026, 5, 5, 12, 0));
        let state = InMemState::new();
        let r = tick(&[job], &clock, &state);
        assert_eq!(r.failed, vec!["boom".to_string()]);
        assert!(r.fired.is_empty());
        assert!(state.last_run("boom").is_none()); // failure does not stamp
    }

    // ── handle_request ─────────────────────────────────────────────────────

    struct StubHandler;
    impl RequestHandler for StubHandler {
        fn do_action(&self, args: &[String]) -> serde_json::Value {
            serde_json::json!({"echo": args.join(" ")})
        }
    }

    #[test]
    fn request_ping() {
        let resp = handle_request(
            r#"{"cmd":"ping"}"#,
            &StubHandler,
            &[],
            &ManualClock::new(ts(2026, 5, 5, 12, 0)),
            &InMemState::new(),
        );
        let v: serde_json::Value = serde_json::from_str(&resp).unwrap();
        assert_eq!(v["pong"], serde_json::Value::Bool(true));
    }

    #[test]
    fn request_invalid_json() {
        let resp = handle_request(
            "not json",
            &StubHandler,
            &[],
            &ManualClock::new(ts(2026, 5, 5, 12, 0)),
            &InMemState::new(),
        );
        let v: serde_json::Value = serde_json::from_str(&resp).unwrap();
        assert!(v["error"].is_string());
    }

    #[test]
    fn request_do_passes_args() {
        let resp = handle_request(
            r#"{"cmd":"do","args":["hello","world"]}"#,
            &StubHandler,
            &[],
            &ManualClock::new(ts(2026, 5, 5, 12, 0)),
            &InMemState::new(),
        );
        let v: serde_json::Value = serde_json::from_str(&resp).unwrap();
        assert_eq!(v["echo"], "hello world");
    }

    #[test]
    fn request_tick_runs_jobs() {
        let counter = Arc::new(AtomicU32::new(0));
        let c2 = counter.clone();
        let job = Job::new(
            "j1",
            Schedule::Every { minutes: 1 },
            Arc::new(move || {
                c2.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }),
        );
        let resp = handle_request(
            r#"{"cmd":"tick"}"#,
            &StubHandler,
            &[job],
            &ManualClock::new(ts(2026, 5, 5, 12, 0)),
            &InMemState::new(),
        );
        let v: serde_json::Value = serde_json::from_str(&resp).unwrap();
        assert_eq!(v["fired"][0], "j1");
        assert_eq!(counter.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn request_unknown_cmd() {
        let resp = handle_request(
            r#"{"cmd":"xyzzy"}"#,
            &StubHandler,
            &[],
            &ManualClock::new(ts(2026, 5, 5, 12, 0)),
            &InMemState::new(),
        );
        let v: serde_json::Value = serde_json::from_str(&resp).unwrap();
        assert!(v["error"].as_str().unwrap().contains("xyzzy"));
    }
}
