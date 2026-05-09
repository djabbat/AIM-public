//! aim-pattern-miner — JSONL session log analyser (port of `agents/pattern_miner.py`).
//!
//! The generalist writes one JSONL line per event (`tool_call`, `tool_result`,
//! `final`, `self_critique_*`, `interrupted`) into
//! `~/.cache/aim/sessions/<run_id>.jsonl`. Once we have ~100 sessions worth of
//! logs, recurring patterns surface — flaky tools, repeated memory queries
//! that should be cached, slow models for specific task classes.
//!
//! This crate turns those logs into actionable findings. Output drives:
//! - Telegram weekly digest (P4 brief extension)
//! - S5 A/B routing decisions ("model X consistently slower for class Y")
//! - S3 prompt patches
//! - S2 tool synthesis ("the same shell+parse sequence appears 12× → name it")
//!
//! ## Public API
//! - [`iter_events`] — yields decoded JSON events from a directory
//! - [`mine`] — run every miner, sort by support
//! - [`summary`] — human-readable digest

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Finding {
    pub kind: String,
    pub summary: String,
    pub support: u32,
    pub sample: serde_json::Value,
}

/// Resolves `AIM_SESSIONS_DIR` env var (with `~` expansion) or defaults to
/// `~/.cache/aim/sessions`.
pub fn sessions_dir() -> PathBuf {
    if let Ok(env) = std::env::var("AIM_SESSIONS_DIR") {
        let trimmed = env.trim();
        if !trimmed.is_empty() {
            return expand_tilde(trimmed);
        }
    }
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".cache").join("aim").join("sessions")
}

fn expand_tilde(p: &str) -> PathBuf {
    if let Some(rest) = p.strip_prefix("~/") {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        home.join(rest)
    } else if p == "~" {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
    } else {
        PathBuf::from(p)
    }
}

/// Iterate JSON events from a directory of `*.jsonl` session logs.
///
/// Skips malformed lines silently (matches Python). If `window_days` is set,
/// drops events whose `ts`/`timestamp` field is older than the cutoff.
pub fn iter_events(dir: Option<&Path>, window_days: Option<i64>) -> Vec<serde_json::Value> {
    let owned;
    let d: &Path = match dir {
        Some(p) => p,
        None => {
            owned = sessions_dir();
            &owned
        }
    };
    if !d.exists() {
        return Vec::new();
    }

    let cutoff = window_days.map(|days| Utc::now() - Duration::days(days));

    let mut paths: Vec<PathBuf> = match std::fs::read_dir(d) {
        Ok(rd) => rd
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.extension().map(|x| x == "jsonl").unwrap_or(false))
            .collect(),
        Err(_) => return Vec::new(),
    };
    paths.sort();

    let mut out = Vec::new();
    for p in &paths {
        let raw = match std::fs::read_to_string(p) {
            Ok(s) => s,
            Err(e) => {
                tracing::debug!("skip {}: {e}", p.display());
                continue;
            }
        };
        for line in raw.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let ev: serde_json::Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(_) => continue,
            };
            if let Some(c) = cutoff {
                if !event_is_after(&ev, c) {
                    continue;
                }
            }
            out.push(ev);
        }
    }
    out
}

fn event_is_after(ev: &serde_json::Value, cutoff: DateTime<Utc>) -> bool {
    let ts = ev.get("ts").or_else(|| ev.get("timestamp"));
    let Some(ts) = ts else {
        // No timestamp — keep it (Python yields it as well, only string/numeric ts triggers gate)
        return true;
    };
    if let Some(s) = ts.as_str() {
        match DateTime::parse_from_rfc3339(s) {
            Ok(dt) => dt.with_timezone(&Utc) >= cutoff,
            Err(_) => false, // Python skipped these too
        }
    } else if let Some(f) = ts.as_f64() {
        let secs = f as i64;
        chrono::DateTime::<Utc>::from_timestamp(secs, 0)
            .map(|dt| dt >= cutoff)
            .unwrap_or(false)
    } else if let Some(n) = ts.as_i64() {
        chrono::DateTime::<Utc>::from_timestamp(n, 0)
            .map(|dt| dt >= cutoff)
            .unwrap_or(false)
    } else {
        true
    }
}

fn ev_str(ev: &serde_json::Value, key: &str) -> Option<String> {
    ev.get(key).and_then(|v| v.as_str()).map(String::from)
}

fn ev_tool_name(ev: &serde_json::Value) -> String {
    ev_str(ev, "tool")
        .or_else(|| ev_str(ev, "name"))
        .unwrap_or_else(|| "?".into())
}

fn ev_type(ev: &serde_json::Value) -> Option<&str> {
    ev.get("type").and_then(|v| v.as_str())
}

fn norm_args(args: Option<&serde_json::Value>) -> String {
    let Some(args) = args else {
        return String::new();
    };
    if let Some(map) = args.as_object() {
        let sorted: BTreeMap<&String, &serde_json::Value> = map.iter().collect();
        let mut parts = Vec::new();
        for (k, v) in sorted {
            let s = if v.is_object() || v.is_array() {
                let mut s = serde_json::to_string(v).unwrap_or_default();
                truncate(&mut s, 60);
                s
            } else {
                let mut s = match v {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                truncate(&mut s, 60);
                s
            };
            parts.push(format!("{}={}", k, s));
        }
        parts.join("|")
    } else {
        let mut s = args.to_string();
        truncate(&mut s, 80);
        s
    }
}

fn truncate(s: &mut String, max: usize) {
    if s.chars().count() <= max {
        return;
    }
    let mut end = 0;
    for (i, _) in s.char_indices().take(max) {
        end = i;
    }
    // Move past the last char we kept
    if let Some((i, c)) = s.char_indices().nth(max - 1) {
        end = i + c.len_utf8();
    }
    s.truncate(end);
}

// ── miners ────────────────────────────────────────────────────────────────

pub fn mine_tool_failure_rate(
    events: &[serde_json::Value],
    min_calls: u32,
    failure_threshold: f64,
) -> Vec<Finding> {
    let mut calls: HashMap<String, u32> = HashMap::new();
    let mut fails: HashMap<String, u32> = HashMap::new();
    let mut samples: HashMap<String, serde_json::Value> = HashMap::new();
    for ev in events {
        if ev_type(ev) != Some("tool_result") {
            continue;
        }
        let name = ev_tool_name(ev);
        *calls.entry(name.clone()).or_insert(0) += 1;
        let result = ev_str(ev, "result").unwrap_or_default();
        if result.trim_start().starts_with("ERROR:") || ev.get("error").is_some() {
            *fails.entry(name.clone()).or_insert(0) += 1;
            samples.entry(name).or_insert_with(|| ev.clone());
        }
    }
    let mut out = Vec::new();
    for (name, n) in &calls {
        if *n < min_calls {
            continue;
        }
        let f = *fails.get(name).unwrap_or(&0);
        let rate = f as f64 / *n as f64;
        if rate >= failure_threshold {
            out.push(Finding {
                kind: "tool_failure_rate".into(),
                summary: format!(
                    "tool '{}' fails {}/{} = {:.0}%",
                    name,
                    f,
                    n,
                    rate * 100.0
                ),
                support: f,
                sample: samples.get(name).cloned().unwrap_or_default(),
            });
        }
    }
    out
}

pub fn mine_slow_tool(
    events: &[serde_json::Value],
    min_calls: u32,
    slow_ms: i64,
) -> Vec<Finding> {
    let mut durations: HashMap<String, Vec<i64>> = HashMap::new();
    for ev in events {
        if ev_type(ev) != Some("tool_result") {
            continue;
        }
        let name = ev_tool_name(ev);
        let d = ev
            .get("duration_ms")
            .or_else(|| ev.get("latency_ms"))
            .and_then(|v| v.as_i64());
        if let Some(d) = d {
            durations.entry(name).or_default().push(d);
        }
    }
    let mut out = Vec::new();
    for (name, mut ds) in durations {
        if ds.len() < min_calls as usize {
            continue;
        }
        ds.sort();
        let n = ds.len();
        let p50 = ds[n / 2];
        let idx95 = ((n as f64 * 0.95) as usize).min(n - 1);
        let p95 = ds[idx95];
        if p95 >= slow_ms {
            out.push(Finding {
                kind: "slow_tool".into(),
                summary: format!(
                    "tool '{}' p95={}ms p50={}ms over {} calls",
                    name,
                    p95,
                    p50,
                    ds.len()
                ),
                support: ds.len() as u32,
                sample: serde_json::json!({ "name": name, "p50": p50, "p95": p95 }),
            });
        }
    }
    out
}

pub fn mine_redundant_memory_queries(
    events: &[serde_json::Value],
    min_repeats: u32,
) -> Vec<Finding> {
    let mut by_arg: HashMap<String, Vec<&serde_json::Value>> = HashMap::new();
    for ev in events {
        if ev_type(ev) != Some("tool_call") {
            continue;
        }
        let name = ev_tool_name(ev);
        if name != "memory_recall" && name != "memory_save" {
            continue;
        }
        let sig = norm_args(ev.get("args"));
        by_arg.entry(sig).or_default().push(ev);
    }
    let mut out = Vec::new();
    for (sig, evs) in by_arg {
        if evs.len() >= min_repeats as usize {
            out.push(Finding {
                kind: "redundant_memory_query".into(),
                summary: format!("memory query repeated {}× — cache it", evs.len()),
                support: evs.len() as u32,
                sample: serde_json::json!({ "args_fingerprint": sig }),
            });
        }
    }
    out
}

pub fn mine_sequential_pairs(events: &[serde_json::Value], min_pairs: u32) -> Vec<Finding> {
    let mut pairs: HashMap<(String, String), u32> = HashMap::new();
    let mut last: HashMap<String, String> = HashMap::new();
    for ev in events {
        if ev_type(ev) != Some("tool_call") {
            continue;
        }
        let sid = ev_str(ev, "session_id")
            .or_else(|| ev_str(ev, "run_id"))
            .unwrap_or_default();
        let name = ev_tool_name(ev);
        if let Some(prev) = last.get(&sid).cloned() {
            if prev != name {
                *pairs.entry((prev, name.clone())).or_insert(0) += 1;
            }
        }
        last.insert(sid, name);
    }
    let mut out = Vec::new();
    for ((a, b), n) in pairs {
        if n >= min_pairs {
            out.push(Finding {
                kind: "sequential_pair".into(),
                summary: format!("{} → {} appears in {} sessions; consider a macro", a, b, n),
                support: n,
                sample: serde_json::json!({ "a": a, "b": b }),
            });
        }
    }
    out
}

pub fn mine_error_type_frequency(events: &[serde_json::Value], min_repeats: u32) -> Vec<Finding> {
    let mut by_prefix: HashMap<String, u32> = HashMap::new();
    for ev in events {
        if ev_type(ev) != Some("tool_result") {
            continue;
        }
        let result = ev_str(ev, "result").unwrap_or_default();
        if !result.starts_with("ERROR:") {
            continue;
        }
        let prefix: Vec<&str> = result.splitn(4, ':').take(3).collect();
        let prefix = prefix.join(":");
        *by_prefix.entry(prefix).or_insert(0) += 1;
    }
    let mut out = Vec::new();
    for (prefix, n) in by_prefix {
        if n >= min_repeats {
            out.push(Finding {
                kind: "error_type_frequency".into(),
                summary: format!("error class '{}' fired {}× — root-cause it", prefix, n),
                support: n,
                sample: serde_json::json!({ "prefix": prefix }),
            });
        }
    }
    out
}

#[derive(Debug, Clone, Copy)]
pub struct MineOpts {
    pub min_calls: u32,
    pub failure_threshold: f64,
    pub slow_ms: i64,
    pub min_redundant: u32,
    pub min_pairs: u32,
    pub min_error_repeats: u32,
}

impl Default for MineOpts {
    fn default() -> Self {
        Self {
            min_calls: 5,
            failure_threshold: 0.30,
            slow_ms: 2000,
            min_redundant: 3,
            min_pairs: 3,
            min_error_repeats: 3,
        }
    }
}

/// Run every miner and return findings sorted by support desc.
pub fn mine(events: &[serde_json::Value], opts: &MineOpts) -> Vec<Finding> {
    let mut findings = Vec::new();
    findings.extend(mine_tool_failure_rate(
        events,
        opts.min_calls,
        opts.failure_threshold,
    ));
    findings.extend(mine_slow_tool(events, opts.min_calls, opts.slow_ms));
    findings.extend(mine_redundant_memory_queries(events, opts.min_redundant));
    findings.extend(mine_sequential_pairs(events, opts.min_pairs));
    findings.extend(mine_error_type_frequency(events, opts.min_error_repeats));
    findings.sort_by(|a, b| b.support.cmp(&a.support));
    findings
}

pub fn summary(window_days: i64, findings: &[Finding]) -> String {
    if findings.is_empty() {
        return format!("(no actionable patterns over last {window_days}d)");
    }
    let mut out = format!(
        "🔎 Pattern miner — last {window_days}d, {} findings",
        findings.len()
    );
    for f in findings {
        out.push_str(&format!("\n  • [{}] {}", f.kind, f.summary));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    fn ev_call(name: &str, args: serde_json::Value, sid: &str) -> serde_json::Value {
        json!({"type": "tool_call", "tool": name, "args": args, "session_id": sid})
    }

    fn ev_result(name: &str, dur: Option<i64>, result: &str) -> serde_json::Value {
        let mut v = json!({"type": "tool_result", "tool": name, "result": result});
        if let Some(d) = dur {
            v["duration_ms"] = json!(d);
        }
        v
    }

    #[test]
    fn tool_failure_rate_finds_flaky_tool() {
        let events: Vec<_> = (0..6)
            .map(|i| {
                if i < 4 {
                    ev_result("flaky", None, "ERROR: boom")
                } else {
                    ev_result("flaky", None, "ok")
                }
            })
            .collect();
        let f = mine_tool_failure_rate(&events, 5, 0.30);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].kind, "tool_failure_rate");
        assert_eq!(f[0].support, 4);
    }

    #[test]
    fn tool_failure_rate_skips_below_min() {
        let events = vec![ev_result("rare", None, "ERROR: x")];
        let f = mine_tool_failure_rate(&events, 5, 0.10);
        assert!(f.is_empty());
    }

    #[test]
    fn slow_tool_uses_p95() {
        let events: Vec<_> = (0..10)
            .map(|i| ev_result("slow", Some(i * 300), "ok"))
            .collect();
        let f = mine_slow_tool(&events, 5, 2000);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].kind, "slow_tool");
    }

    #[test]
    fn slow_tool_ignores_fast() {
        let events: Vec<_> = (0..10)
            .map(|i| ev_result("fast", Some(50 + i), "ok"))
            .collect();
        let f = mine_slow_tool(&events, 5, 2000);
        assert!(f.is_empty());
    }

    #[test]
    fn redundant_memory_query_groups_by_args() {
        let events: Vec<_> = (0..4)
            .map(|_| ev_call("memory_recall", json!({"q": "what is X"}), "s1"))
            .collect();
        let f = mine_redundant_memory_queries(&events, 3);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].support, 4);
    }

    #[test]
    fn sequential_pair_within_session() {
        let events = vec![
            ev_call("read_file", json!({}), "s1"),
            ev_call("grep", json!({}), "s1"),
            ev_call("read_file", json!({}), "s2"),
            ev_call("grep", json!({}), "s2"),
            ev_call("read_file", json!({}), "s3"),
            ev_call("grep", json!({}), "s3"),
        ];
        let f = mine_sequential_pairs(&events, 3);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].support, 3);
        assert_eq!(f[0].kind, "sequential_pair");
    }

    #[test]
    fn sequential_pair_skips_same_tool_repeated() {
        let events = vec![
            ev_call("grep", json!({}), "s1"),
            ev_call("grep", json!({}), "s1"),
        ];
        let f = mine_sequential_pairs(&events, 1);
        assert!(f.is_empty());
    }

    #[test]
    fn error_type_frequency_groups_prefix() {
        let events: Vec<_> = (0..3)
            .map(|_| ev_result("x", None, "ERROR:NetworkError:timeout connecting"))
            .collect();
        let f = mine_error_type_frequency(&events, 3);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].support, 3);
    }

    #[test]
    fn mine_runs_all_miners_and_sorts() {
        let mut events: Vec<serde_json::Value> = (0..6)
            .map(|i| {
                if i < 4 {
                    ev_result("a", None, "ERROR: ouch")
                } else {
                    ev_result("a", None, "ok")
                }
            })
            .collect();
        events.extend((0..3).map(|_| ev_call("memory_recall", json!({"q": "X"}), "s1")));
        let opts = MineOpts::default();
        let findings = mine(&events, &opts);
        // tool_failure_rate (support 4) > redundant_memory_query (support 3)
        assert!(findings.len() >= 2);
        assert_eq!(findings[0].kind, "tool_failure_rate");
    }

    #[test]
    fn summary_formats_findings() {
        let findings = vec![Finding {
            kind: "slow_tool".into(),
            summary: "tool 'x' p95=3000ms p50=100ms over 10 calls".into(),
            support: 10,
            sample: json!({}),
        }];
        let s = summary(7, &findings);
        assert!(s.contains("Pattern miner"));
        assert!(s.contains("slow_tool"));
    }

    #[test]
    fn iter_events_reads_jsonl_dir() {
        let dir = TempDir::new().unwrap();
        let p = dir.path().join("a.jsonl");
        std::fs::write(
            &p,
            "{\"type\":\"tool_call\",\"tool\":\"x\"}\n\n{\"type\":\"tool_result\",\"tool\":\"x\"}\n",
        )
        .unwrap();
        let events = iter_events(Some(dir.path()), None);
        assert_eq!(events.len(), 2);
    }

    #[test]
    fn iter_events_filters_by_window() {
        let dir = TempDir::new().unwrap();
        let p = dir.path().join("a.jsonl");
        let old = (Utc::now() - Duration::days(60)).to_rfc3339();
        let recent = (Utc::now() - Duration::days(1)).to_rfc3339();
        let body = format!(
            "{{\"type\":\"x\",\"ts\":\"{}\"}}\n{{\"type\":\"y\",\"ts\":\"{}\"}}\n",
            old, recent
        );
        std::fs::write(&p, body).unwrap();
        let events = iter_events(Some(dir.path()), Some(7));
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].get("type").unwrap(), "y");
    }

    #[test]
    fn iter_events_skips_malformed() {
        let dir = TempDir::new().unwrap();
        let p = dir.path().join("a.jsonl");
        std::fs::write(&p, "{\"valid\": 1}\nnot json\n{\"valid\": 2}\n").unwrap();
        let events = iter_events(Some(dir.path()), None);
        assert_eq!(events.len(), 2);
    }

    #[test]
    fn norm_args_sorts_keys_and_truncates() {
        let v = json!({ "z": "tail", "a": "head" });
        let s = norm_args(Some(&v));
        assert!(s.starts_with("a=head|z=tail"), "got {s}");
    }
}
