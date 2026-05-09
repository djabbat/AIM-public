//! aim-session-visualiser — JSONL session log → human timeline + stats.
//!
//! Port of `agents/session_visualiser.py`. The generalist writes one
//! JSON event per line into a session file; this crate parses that
//! sequence and produces:
//!
//!   * a markdown timeline (one bullet per event, with offsets and Δ),
//!   * a per-tool stats summary (calls, errors, p50_ms, max_ms),
//!   * an "interesting events" list (errors, self-critique, interrupts).
//!
//! Pure parsing / aggregation — no filesystem and no time. Both
//! `timeline_from_lines` and `stats_from_lines` accept already-loaded
//! JSONL strings.

use std::collections::BTreeMap;

use chrono::DateTime;
use serde::{Deserialize, Serialize};

const INTERESTING: &[&str] = &[
    "final",
    "error",
    "tool_error",
    "self_critique_issue_found",
    "interrupted",
];

// ── timestamps ────────────────────────────────────────────────────────────

fn parse_ts(v: &serde_json::Value) -> Option<f64> {
    let raw = v.get("ts").or_else(|| v.get("timestamp"))?;
    if let Some(f) = raw.as_f64() {
        return Some(f);
    }
    if let Some(i) = raw.as_i64() {
        return Some(i as f64);
    }
    if let Some(s) = raw.as_str() {
        if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
            return Some(dt.timestamp_micros() as f64 / 1_000_000.0);
        }
        // Try the "no timezone" form Python's datetime.fromisoformat accepts.
        if let Ok(naive) =
            chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S")
        {
            return Some(naive.and_utc().timestamp() as f64);
        }
    }
    None
}

fn parse_lines(jsonl: &str) -> Vec<serde_json::Value> {
    let mut out = Vec::new();
    for raw in jsonl.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(line) {
            out.push(v);
        }
    }
    out
}

// ── timeline ──────────────────────────────────────────────────────────────

pub fn timeline_from_lines(name: &str, jsonl: &str) -> String {
    let events = parse_lines(jsonl);
    if events.is_empty() {
        return format!("(empty session at {})", name);
    }
    let start_ts = parse_ts(&events[0]);
    let mut lines = vec![format!("# Session timeline — {}", name), String::new()];
    let mut last_ts = start_ts;

    for ev in &events {
        let kind = ev
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("?")
            .to_string();
        let t = parse_ts(ev);
        let offset = match (t, start_ts) {
            (Some(t), Some(s)) => format!("+{:7.2}s", t - s),
            _ => String::new(),
        };
        let delta = match (t, last_ts) {
            (Some(t), Some(l)) => format!("  Δ{:+5.2}s", t - l),
            _ => String::new(),
        };
        if t.is_some() {
            last_ts = t;
        }

        let marker = match kind.as_str() {
            "error" | "tool_error" => "🛑",
            "final" => "✅",
            _ => "·",
        };

        let mut suffix = String::new();
        match kind.as_str() {
            "tool_call" | "tool_result" | "tool_error" => {
                let tool = ev
                    .get("tool")
                    .or_else(|| ev.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("?");
                suffix = format!(" tool={}", tool);
            }
            "final" => {
                let ans: String = ev
                    .get("answer")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .chars()
                    .take(60)
                    .collect();
                suffix = format!(" → {:?}", ans);
            }
            "error" => {
                let err: String = ev
                    .get("error")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .chars()
                    .take(60)
                    .collect();
                suffix = format!(" {}", err);
            }
            _ => {}
        }

        lines.push(format!(
            "  {} {:9}{}  {}{}",
            marker, offset, delta, kind, suffix
        ));
    }
    lines.join("\n")
}

// ── stats ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ToolStats {
    pub calls: u64,
    pub errors: u64,
    pub p50_ms: u64,
    pub max_ms: u64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SessionStats {
    pub n_events: u64,
    pub tools: BTreeMap<String, ToolStats>,
    pub interesting: Vec<serde_json::Value>,
}

pub fn stats_from_lines(jsonl: &str) -> SessionStats {
    let events = parse_lines(jsonl);
    if events.is_empty() {
        return SessionStats::default();
    }
    let mut by_tool_calls: BTreeMap<String, u64> = BTreeMap::new();
    let mut by_tool_errors: BTreeMap<String, u64> = BTreeMap::new();
    let mut durations: BTreeMap<String, Vec<u64>> = BTreeMap::new();
    let mut interesting: Vec<serde_json::Value> = Vec::new();

    let mut pending: Vec<(usize, String, f64)> = Vec::new();

    for (i, ev) in events.iter().enumerate() {
        let kind = ev.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let tool = ev
            .get("tool")
            .or_else(|| ev.get("name"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        match kind {
            "tool_call" if !tool.is_empty() => {
                if let Some(t) = parse_ts(ev) {
                    pending.push((i, tool.clone(), t));
                }
                *by_tool_calls.entry(tool).or_insert(0) += 1;
            }
            "tool_result" => {
                if let Some(t_now) = parse_ts(ev) {
                    if let Some(idx) =
                        pending.iter().rposition(|(_, name, _)| *name == tool)
                    {
                        let (_, _, started) = pending.remove(idx);
                        let dur_ms = ((t_now - started) * 1000.0).max(0.0) as u64;
                        durations.entry(tool).or_default().push(dur_ms);
                    }
                }
            }
            "tool_error" => {
                *by_tool_errors.entry(tool).or_insert(0) += 1;
            }
            _ => {}
        }
        if INTERESTING.contains(&kind) {
            interesting.push(ev.clone());
        }
    }

    let mut tools: BTreeMap<String, ToolStats> = BTreeMap::new();
    for (tool, n) in &by_tool_calls {
        let mut ds = durations.get(tool).cloned().unwrap_or_default();
        ds.sort_unstable();
        let p50 = if ds.is_empty() { 0 } else { ds[ds.len() / 2] };
        let mx = ds.iter().copied().max().unwrap_or(0);
        tools.insert(
            tool.clone(),
            ToolStats {
                calls: *n,
                errors: *by_tool_errors.get(tool).unwrap_or(&0),
                p50_ms: p50,
                max_ms: mx,
            },
        );
    }

    SessionStats {
        n_events: events.len() as u64,
        tools,
        interesting,
    }
}

pub fn summary_string(name: &str, jsonl: &str) -> String {
    let s = stats_from_lines(jsonl);
    let mut lines = vec![format!("Session {}: {} events", name, s.n_events)];
    let mut tools: Vec<(&String, &ToolStats)> = s.tools.iter().collect();
    tools.sort_by(|a, b| b.1.calls.cmp(&a.1.calls));
    for (tool, info) in tools {
        lines.push(format!(
            "  • {}: {} calls, {} errors, p50={}ms",
            tool, info.calls, info.errors, info.p50_ms
        ));
    }
    if !s.interesting.is_empty() {
        lines.push(format!("  ⚠  {} interesting events", s.interesting.len()));
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(ts: f64, kind: &str, tool: Option<&str>) -> String {
        let mut v = serde_json::json!({"ts": ts, "type": kind});
        if let Some(t) = tool {
            v["tool"] = serde_json::Value::String(t.into());
        }
        v.to_string()
    }

    // ── timeline ──────────────────────────────────────────────────────────

    #[test]
    fn timeline_empty_session() {
        let s = timeline_from_lines("run-x.jsonl", "");
        assert!(s.contains("(empty session at run-x.jsonl)"));
    }

    #[test]
    fn timeline_renders_offsets_and_kinds() {
        let body = format!(
            "{}\n{}\n{}",
            ev(1000.0, "tool_call", Some("read_file")),
            ev(1000.5, "tool_result", Some("read_file")),
            ev(1001.0, "final", None)
        );
        let s = timeline_from_lines("r.jsonl", &body);
        assert!(s.contains("Session timeline — r.jsonl"));
        assert!(s.contains("tool_call"));
        assert!(s.contains("tool_result"));
        assert!(s.contains("final"));
        assert!(s.contains("✅"));
    }

    #[test]
    fn timeline_marks_errors() {
        let body = format!(
            "{}\n{}",
            ev(0.0, "error", None),
            ev(1.0, "tool_error", Some("write_file")),
        );
        let s = timeline_from_lines("e.jsonl", &body);
        assert_eq!(s.matches("🛑").count(), 2);
    }

    #[test]
    fn timeline_truncates_long_answer() {
        let long = "x".repeat(200);
        let line = serde_json::json!({"ts":1.0,"type":"final","answer":long}).to_string();
        let s = timeline_from_lines("a.jsonl", &line);
        // Final marker shows 60-char snippet
        assert!(s.contains("xxxxxxx"));
        // Verify only 60 'x' inside the quoted snippet
        let count = s.matches('x').count();
        assert_eq!(count, 60);
    }

    #[test]
    fn timeline_skips_invalid_json() {
        let body = format!("not json\n{}", ev(0.0, "final", None));
        let s = timeline_from_lines("x.jsonl", &body);
        assert!(s.contains("final"));
    }

    // ── stats ─────────────────────────────────────────────────────────────

    #[test]
    fn stats_empty() {
        let s = stats_from_lines("");
        assert_eq!(s.n_events, 0);
        assert!(s.tools.is_empty());
    }

    #[test]
    fn stats_pairs_call_with_result_for_durations() {
        let body = format!(
            "{}\n{}\n{}\n{}",
            ev(0.0, "tool_call", Some("read_file")),
            ev(0.250, "tool_result", Some("read_file")),
            ev(1.0, "tool_call", Some("read_file")),
            ev(1.500, "tool_result", Some("read_file")),
        );
        let s = stats_from_lines(&body);
        let t = s.tools.get("read_file").unwrap();
        assert_eq!(t.calls, 2);
        assert_eq!(t.errors, 0);
        assert!(t.p50_ms >= 250 && t.p50_ms <= 500);
        assert!(t.max_ms >= 500);
    }

    #[test]
    fn stats_records_errors_by_tool() {
        let body = format!(
            "{}\n{}\n{}",
            ev(0.0, "tool_call", Some("write_file")),
            ev(0.1, "tool_error", Some("write_file")),
            ev(1.0, "tool_call", Some("read_file")),
        );
        let s = stats_from_lines(&body);
        assert_eq!(s.tools["write_file"].errors, 1);
        assert_eq!(s.tools["read_file"].errors, 0);
    }

    #[test]
    fn stats_collects_interesting_events() {
        let body = format!(
            "{}\n{}\n{}",
            ev(0.0, "tool_call", Some("x")),
            ev(1.0, "self_critique_issue_found", None),
            ev(2.0, "final", None),
        );
        let s = stats_from_lines(&body);
        assert_eq!(s.interesting.len(), 2);
    }

    #[test]
    fn stats_handles_unmatched_results_without_panic() {
        let body = format!(
            "{}\n{}",
            ev(0.0, "tool_result", Some("orphan")),
            ev(1.0, "tool_call", Some("normal")),
        );
        let s = stats_from_lines(&body);
        assert_eq!(s.tools["normal"].calls, 1);
        assert!(!s.tools.contains_key("orphan"));
    }

    // ── timestamps ────────────────────────────────────────────────────────

    #[test]
    fn timestamp_parsing_accepts_iso_and_unix() {
        let unix = serde_json::json!({"type":"x","ts":1234.5});
        assert_eq!(parse_ts(&unix), Some(1234.5));
        let iso =
            serde_json::json!({"type":"x","ts":"2026-05-05T12:00:00"});
        assert!(parse_ts(&iso).is_some());
        let missing = serde_json::json!({"type":"x"});
        assert_eq!(parse_ts(&missing), None);
    }

    // ── summary_string ────────────────────────────────────────────────────

    #[test]
    fn summary_string_format() {
        let body = format!(
            "{}\n{}\n{}",
            ev(0.0, "tool_call", Some("a")),
            ev(0.1, "tool_result", Some("a")),
            ev(1.0, "final", None),
        );
        let s = summary_string("run.jsonl", &body);
        assert!(s.starts_with("Session run.jsonl: 3 events"));
        assert!(s.contains("• a:"));
        assert!(s.contains("interesting events"));
    }
}
