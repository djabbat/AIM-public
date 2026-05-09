//! aim-telegram-extras — drop-in helpers for Telegram bot.
//!
//! Port of `agents/telegram_extras.py`. The Python original integrates
//! with `python-telegram-bot`; the Rust port focuses on the testable
//! pure-logic pieces:
//!
//! - `Throttle` — per-chat rate gate with configurable min gap
//! - `parse_review_callback` — decode the inline-keyboard `aim:*` payload
//! - `voice_temp_path` — deterministic filename for downloaded voice
//! - `ReviewKeyboard` — semantic representation of the 3-button keyboard
//!
//! The actual Bot API integration (HTTP / webhooks / handlers) belongs
//! in the binary that consumes this crate.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Duration;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum TelegramError {
    #[error("invalid callback: {0}")]
    InvalidCallback(String),
}

pub type Result<T> = std::result::Result<T, TelegramError>;

// ── throttle ────────────────────────────────────────────────────────────────

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct FixedClock(pub Mutex<DateTime<Utc>>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        *self.0.lock()
    }
}

pub struct Throttle<'a> {
    pub min_gap: Duration,
    pub clock: &'a dyn Clock,
    last_call: Mutex<BTreeMap<i64, DateTime<Utc>>>,
}

impl<'a> Throttle<'a> {
    pub fn new(min_gap: Duration, clock: &'a dyn Clock) -> Self {
        Self {
            min_gap,
            clock,
            last_call: Mutex::new(BTreeMap::new()),
        }
    }

    /// Returns `true` if `chat_id` is calling too fast — caller should
    /// drop the request. Records `now` as the new last-call time on
    /// pass-through.
    pub fn is_throttled(&self, chat_id: i64) -> bool {
        let now = self.clock.now();
        let mut map = self.last_call.lock();
        if let Some(&last) = map.get(&chat_id) {
            let elapsed = (now - last).to_std().unwrap_or(Duration::from_secs(0));
            if elapsed < self.min_gap {
                return true;
            }
        }
        map.insert(chat_id, now);
        false
    }

    /// Test convenience: peek the most recent timestamp for `chat_id`.
    pub fn peek(&self, chat_id: i64) -> Option<DateTime<Utc>> {
        self.last_call.lock().get(&chat_id).copied()
    }
}

// ── review keyboard ─────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReviewDecision {
    Accept,
    Reject,
    Comment,
}

impl ReviewDecision {
    pub fn callback_data(&self) -> &'static str {
        match self {
            Self::Accept => "aim:accept",
            Self::Reject => "aim:reject",
            Self::Comment => "aim:comment",
        }
    }

    pub fn label(&self) -> &'static str {
        match self {
            Self::Accept => "✅ Принять",
            Self::Reject => "❌ Отклонить",
            Self::Comment => "✏️ Комментарий",
        }
    }

    /// Reply that goes back to the user after they tap the button.
    pub fn ack_message(&self) -> &'static str {
        match self {
            Self::Accept => "✅ Принято.",
            Self::Reject => "❌ Отклонено. Перегенерирую…",
            Self::Comment => "✏️ Пришли комментарий следующим сообщением.",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct KeyboardRow {
    pub label: String,
    pub callback_data: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ReviewKeyboard {
    pub rows: Vec<KeyboardRow>,
}

impl ReviewKeyboard {
    pub fn standard() -> Self {
        Self {
            rows: vec![
                KeyboardRow {
                    label: ReviewDecision::Accept.label().into(),
                    callback_data: ReviewDecision::Accept.callback_data().into(),
                },
                KeyboardRow {
                    label: ReviewDecision::Reject.label().into(),
                    callback_data: ReviewDecision::Reject.callback_data().into(),
                },
                KeyboardRow {
                    label: ReviewDecision::Comment.label().into(),
                    callback_data: ReviewDecision::Comment.callback_data().into(),
                },
            ],
        }
    }
}

/// Decode an `aim:<decision>` callback payload.
pub fn parse_review_callback(callback_data: &str) -> Result<ReviewDecision> {
    let body = callback_data
        .strip_prefix("aim:")
        .ok_or_else(|| TelegramError::InvalidCallback(callback_data.into()))?;
    match body {
        "accept" => Ok(ReviewDecision::Accept),
        "reject" => Ok(ReviewDecision::Reject),
        "comment" => Ok(ReviewDecision::Comment),
        other => Err(TelegramError::InvalidCallback(format!(
            "unknown decision: {}",
            other
        ))),
    }
}

// ── voice file naming ──────────────────────────────────────────────────────

/// Compose the deterministic temp-file path for a downloaded voice
/// message. Mirrors Python `/tmp/aim_voice_{chat_id}_{epoch_seconds}.ogg`.
pub fn voice_temp_path(tmp_root: &std::path::Path, chat_id: i64, when: DateTime<Utc>) -> PathBuf {
    tmp_root.join(format!(
        "aim_voice_{}_{}.ogg",
        chat_id,
        when.timestamp()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn at(secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(secs, 0).unwrap()
    }

    fn fixed(t: DateTime<Utc>) -> FixedClock {
        FixedClock(Mutex::new(t))
    }

    // ── throttle ───────────────────────────────────────────────────────────

    #[test]
    fn throttle_first_call_passes() {
        let clk = fixed(at(1_700_000_000));
        let g = Throttle::new(Duration::from_secs(2), &clk);
        assert!(!g.is_throttled(42));
        assert_eq!(g.peek(42), Some(at(1_700_000_000)));
    }

    #[test]
    fn throttle_second_call_within_window_blocked() {
        let clk = fixed(at(1_700_000_000));
        let g = Throttle::new(Duration::from_secs(5), &clk);
        assert!(!g.is_throttled(42));
        // same time → throttled
        assert!(g.is_throttled(42));
    }

    #[test]
    fn throttle_call_after_window_passes() {
        let now = at(1_700_000_000);
        let clk = FixedClock(Mutex::new(now));
        let g = Throttle::new(Duration::from_secs(2), &clk);
        assert!(!g.is_throttled(42));
        // advance clock past window
        *clk.0.lock() = now + chrono::Duration::seconds(3);
        assert!(!g.is_throttled(42));
    }

    #[test]
    fn throttle_per_chat_isolation() {
        let clk = fixed(at(1_700_000_000));
        let g = Throttle::new(Duration::from_secs(60), &clk);
        assert!(!g.is_throttled(1));
        // different chat_id is not throttled even if first chat is
        assert!(!g.is_throttled(2));
        assert!(g.is_throttled(1));
        assert!(g.is_throttled(2));
    }

    // ── ReviewDecision ──────────────────────────────────────────────────────

    #[test]
    fn callback_data_matches_python() {
        assert_eq!(ReviewDecision::Accept.callback_data(), "aim:accept");
        assert_eq!(ReviewDecision::Reject.callback_data(), "aim:reject");
        assert_eq!(ReviewDecision::Comment.callback_data(), "aim:comment");
    }

    #[test]
    fn labels_match_python() {
        assert_eq!(ReviewDecision::Accept.label(), "✅ Принять");
        assert_eq!(ReviewDecision::Reject.label(), "❌ Отклонить");
        assert_eq!(ReviewDecision::Comment.label(), "✏️ Комментарий");
    }

    #[test]
    fn ack_messages_match_python() {
        assert!(ReviewDecision::Accept.ack_message().starts_with("✅"));
        assert!(ReviewDecision::Reject.ack_message().contains("Перегенерирую"));
        assert!(ReviewDecision::Comment.ack_message().contains("комментарий"));
    }

    // ── ReviewKeyboard ──────────────────────────────────────────────────────

    #[test]
    fn standard_keyboard_has_three_rows() {
        let kb = ReviewKeyboard::standard();
        assert_eq!(kb.rows.len(), 3);
        assert_eq!(kb.rows[0].callback_data, "aim:accept");
        assert_eq!(kb.rows[2].label, "✏️ Комментарий");
    }

    // ── parse_review_callback ──────────────────────────────────────────────

    #[test]
    fn parse_known_callbacks() {
        assert_eq!(
            parse_review_callback("aim:accept").unwrap(),
            ReviewDecision::Accept
        );
        assert_eq!(
            parse_review_callback("aim:reject").unwrap(),
            ReviewDecision::Reject
        );
        assert_eq!(
            parse_review_callback("aim:comment").unwrap(),
            ReviewDecision::Comment
        );
    }

    #[test]
    fn parse_rejects_missing_prefix() {
        assert!(parse_review_callback("accept").is_err());
        assert!(parse_review_callback("").is_err());
    }

    #[test]
    fn parse_rejects_unknown_decision() {
        let r = parse_review_callback("aim:flux");
        assert!(r.is_err());
        if let Err(TelegramError::InvalidCallback(s)) = r {
            assert!(s.contains("flux"));
        } else {
            panic!();
        }
    }

    // ── voice_temp_path ────────────────────────────────────────────────────

    #[test]
    fn voice_temp_path_format() {
        let p = voice_temp_path(std::path::Path::new("/tmp"), 42, at(1_700_000_123));
        assert_eq!(p, PathBuf::from("/tmp/aim_voice_42_1700000123.ogg"));
    }

    #[test]
    fn voice_temp_path_per_chat_id() {
        let p1 = voice_temp_path(std::path::Path::new("/tmp"), 1, at(0));
        let p2 = voice_temp_path(std::path::Path::new("/tmp"), 2, at(0));
        assert_ne!(p1, p2);
    }
}
