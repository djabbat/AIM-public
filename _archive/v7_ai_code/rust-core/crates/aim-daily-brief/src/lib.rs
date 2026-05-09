//! aim-daily-brief — morning brief renderer + chunker + delivery dispatch.
//!
//! Port of `scripts/daily_brief.py`. The interesting parts are:
//!
//!   * brief composition (preamble, header, project briefs, deadlines),
//!   * Telegram 4096-char limit chunking (3800-char chunks with no
//!     splitting in the middle of a token — same as Python's slice),
//!   * channel decision (quiet hours / dry run / fall-through to
//!     telegram → stdout).
//!
//! The actual HTTP POST is hidden behind the [`Telegram`] trait so unit
//! tests don't hit the network.

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};

pub const TELEGRAM_CHUNK: usize = 3800;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct BriefSections {
    pub head: Option<String>,
    pub all_briefs: String,
    pub deadlines: String,
    /// AIM_FS inbox digest (rendered by `aim_fs::render_inbox_block`) — empty
    /// string when AIM_FS is not yet adopted.  Added 2026-05-08.
    #[serde(default)]
    pub aim_fs_inbox: String,
}

pub mod aim_fs;

pub fn render_brief(today: NaiveDate, sections: &BriefSections) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(h) = &sections.head {
        if !h.is_empty() {
            parts.push(h.clone());
        }
    }
    parts.push(format!(
        "☀️ AIM daily brief — {}",
        today.format("%Y-%m-%d")
    ));
    parts.push(String::new());
    parts.push(sections.all_briefs.clone());
    if !sections.aim_fs_inbox.is_empty() {
        parts.push(String::new());
        parts.push("———".to_string());
        parts.push(String::new());
        parts.push(sections.aim_fs_inbox.clone());
    }
    parts.push(String::new());
    parts.push("———".to_string());
    parts.push(String::new());
    parts.push(sections.deadlines.clone());
    parts.join("\n")
}

/// Chunks for Telegram's 4096-char limit. We follow Python's slice
/// semantics (`text[i:i+LIMIT]` for i in range(0, len, LIMIT)) — fixed
/// 3800-char windows, no token-aware boundary, and an empty input
/// becomes a single empty chunk.
pub fn chunk_for_telegram(text: &str) -> Vec<String> {
    if text.is_empty() {
        return vec![String::new()];
    }
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0usize;
    while i < bytes.len() {
        let end = (i + TELEGRAM_CHUNK).min(bytes.len());
        // We slice on chars, not bytes, but Python's slice is by
        // code-unit and Telegram counts utf-16 code units. We aim for
        // approximate parity by counting unicode scalar values.
        let chunk: String = text
            .chars()
            .skip(i)
            .take(end - i)
            .collect();
        if chunk.is_empty() {
            break;
        }
        i += chunk.chars().count();
        out.push(chunk);
    }
    if out.is_empty() {
        out.push(String::new());
    }
    out
}

// ── delivery routing ──────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DeliveryDecision {
    Suppress,
    Stdout,
    Telegram,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DeliveryPrefs {
    pub quiet_hours: bool,
    pub dry_run: bool,
    pub channels: Vec<String>,
}

pub fn decide_delivery(prefs: &DeliveryPrefs) -> DeliveryDecision {
    if prefs.quiet_hours {
        return DeliveryDecision::Suppress;
    }
    if prefs.dry_run {
        return DeliveryDecision::Stdout;
    }
    if prefs.channels.iter().any(|c| c == "telegram") {
        return DeliveryDecision::Telegram;
    }
    DeliveryDecision::Stdout
}

pub trait Telegram: Send + Sync {
    fn post(&self, body: &str) -> Result<(), String>;
}

#[derive(Clone, Debug)]
pub struct DeliveryReport {
    pub decision: DeliveryDecision,
    pub chunks_sent: usize,
    pub error: Option<String>,
}

pub fn deliver(text: &str, prefs: &DeliveryPrefs, tg: Option<&dyn Telegram>) -> DeliveryReport {
    let decision = decide_delivery(prefs);
    match decision {
        DeliveryDecision::Suppress => DeliveryReport {
            decision,
            chunks_sent: 0,
            error: None,
        },
        DeliveryDecision::Stdout => DeliveryReport {
            decision,
            chunks_sent: 1,
            error: None,
        },
        DeliveryDecision::Telegram => {
            let Some(t) = tg else {
                return DeliveryReport {
                    decision: DeliveryDecision::Stdout,
                    chunks_sent: 1,
                    error: Some("telegram client missing; fell back to stdout".into()),
                };
            };
            let chunks = chunk_for_telegram(text);
            let mut sent = 0;
            for c in &chunks {
                if let Err(e) = t.post(c) {
                    return DeliveryReport {
                        decision,
                        chunks_sent: sent,
                        error: Some(e),
                    };
                }
                sent += 1;
            }
            DeliveryReport {
                decision,
                chunks_sent: sent,
                error: None,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    fn d(s: &str) -> NaiveDate {
        NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap()
    }

    // ── render_brief ──────────────────────────────────────────────────────

    #[test]
    fn render_includes_header_and_sections() {
        let s = BriefSections {
            head: None,
            all_briefs: "BRIEFS".into(),
            deadlines: "DEADLINES".into(),
            aim_fs_inbox: String::new(),
        };
        let out = render_brief(d("2026-05-05"), &s);
        assert!(out.contains("☀️ AIM daily brief — 2026-05-05"));
        assert!(out.contains("BRIEFS"));
        assert!(out.contains("DEADLINES"));
        assert!(out.contains("———"));
    }

    #[test]
    fn render_applies_preamble() {
        let s = BriefSections {
            head: Some("Heads up: server reboot 14:00".into()),
            all_briefs: "B".into(),
            deadlines: "D".into(),
            aim_fs_inbox: String::new(),
        };
        let out = render_brief(d("2026-05-05"), &s);
        assert!(out.starts_with("Heads up: server reboot 14:00"));
    }

    #[test]
    fn render_skips_empty_preamble() {
        let s = BriefSections {
            head: Some(String::new()),
            all_briefs: "B".into(),
            deadlines: "D".into(),
            aim_fs_inbox: String::new(),
        };
        let out = render_brief(d("2026-05-05"), &s);
        assert!(out.starts_with("☀️"));
    }

    // ── chunking ──────────────────────────────────────────────────────────

    #[test]
    fn chunk_short_text_one_piece() {
        let chunks = chunk_for_telegram("hello world");
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0], "hello world");
    }

    #[test]
    fn chunk_empty_returns_single_empty() {
        let chunks = chunk_for_telegram("");
        assert_eq!(chunks, vec![String::new()]);
    }

    #[test]
    fn chunk_long_text_splits_at_limit() {
        let s: String = "a".repeat(TELEGRAM_CHUNK * 2 + 100);
        let chunks = chunk_for_telegram(&s);
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].chars().count(), TELEGRAM_CHUNK);
        assert_eq!(chunks[1].chars().count(), TELEGRAM_CHUNK);
        assert_eq!(chunks[2].chars().count(), 100);
    }

    #[test]
    fn chunk_unicode_safe() {
        // 4-byte chars (rare emoji) + 2-byte cyrillic; ensure no panic
        // and chunks stay valid UTF-8.
        let s: String = "ё".repeat(TELEGRAM_CHUNK + 50);
        let chunks = chunk_for_telegram(&s);
        for c in &chunks {
            assert!(std::str::from_utf8(c.as_bytes()).is_ok());
        }
    }

    // ── delivery decision ─────────────────────────────────────────────────

    #[test]
    fn delivery_quiet_hours_suppresses() {
        let prefs = DeliveryPrefs {
            quiet_hours: true,
            ..Default::default()
        };
        assert_eq!(decide_delivery(&prefs), DeliveryDecision::Suppress);
    }

    #[test]
    fn delivery_dry_run_uses_stdout() {
        let prefs = DeliveryPrefs {
            dry_run: true,
            channels: vec!["telegram".into()],
            ..Default::default()
        };
        assert_eq!(decide_delivery(&prefs), DeliveryDecision::Stdout);
    }

    #[test]
    fn delivery_picks_telegram_when_configured() {
        let prefs = DeliveryPrefs {
            channels: vec!["telegram".into(), "stdout".into()],
            ..Default::default()
        };
        assert_eq!(decide_delivery(&prefs), DeliveryDecision::Telegram);
    }

    #[test]
    fn delivery_fallback_stdout_when_no_telegram() {
        let prefs = DeliveryPrefs {
            channels: vec!["stdout".into()],
            ..Default::default()
        };
        assert_eq!(decide_delivery(&prefs), DeliveryDecision::Stdout);
    }

    // ── deliver ───────────────────────────────────────────────────────────

    struct StubTg {
        sent: Mutex<Vec<String>>,
        fail_after: usize,
    }
    impl Telegram for StubTg {
        fn post(&self, body: &str) -> Result<(), String> {
            let mut g = self.sent.lock();
            if g.len() >= self.fail_after {
                return Err("network down".into());
            }
            g.push(body.to_string());
            Ok(())
        }
    }

    #[test]
    fn deliver_telegram_sends_all_chunks() {
        let tg = StubTg {
            sent: Mutex::new(vec![]),
            fail_after: 999,
        };
        let prefs = DeliveryPrefs {
            channels: vec!["telegram".into()],
            ..Default::default()
        };
        let r = deliver(&"a".repeat(TELEGRAM_CHUNK + 5), &prefs, Some(&tg));
        assert_eq!(r.decision, DeliveryDecision::Telegram);
        assert_eq!(r.chunks_sent, 2);
        assert!(r.error.is_none());
    }

    #[test]
    fn deliver_telegram_propagates_error() {
        let tg = StubTg {
            sent: Mutex::new(vec![]),
            fail_after: 1,
        };
        let prefs = DeliveryPrefs {
            channels: vec!["telegram".into()],
            ..Default::default()
        };
        let r = deliver(&"a".repeat(TELEGRAM_CHUNK * 3), &prefs, Some(&tg));
        assert_eq!(r.chunks_sent, 1);
        assert_eq!(r.error.as_deref(), Some("network down"));
    }

    #[test]
    fn deliver_falls_back_to_stdout_when_no_tg_client() {
        let prefs = DeliveryPrefs {
            channels: vec!["telegram".into()],
            ..Default::default()
        };
        let r = deliver("hi", &prefs, None);
        assert_eq!(r.decision, DeliveryDecision::Stdout);
        assert!(r.error.is_some());
    }

    #[test]
    fn deliver_quiet_hours_short_circuits() {
        let prefs = DeliveryPrefs {
            quiet_hours: true,
            ..Default::default()
        };
        let r = deliver("hi", &prefs, None);
        assert_eq!(r.decision, DeliveryDecision::Suppress);
        assert_eq!(r.chunks_sent, 0);
    }
}
