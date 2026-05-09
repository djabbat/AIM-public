//! aim-telegram-bot — command parser + auth state + key-cmd outcomes.
//!
//! Port of the deterministic core of `telegram_bot.py`. The HTTP +
//! python-telegram-bot wiring stays in the binary; here we keep:
//!
//!   * `parse_command(text)` — split "/cmd a b c" into (cmd, args)
//!   * `tg_uid(int)` — Python uses string form of user_id
//!   * `consume_link_code(code)` — local-mode acceptance rule
//!   * Reply-string composers for /setkey / /clearkey / /whichkey
//!     so messaging stays consistent and unit-testable.

use std::collections::BTreeMap;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

pub const KEY_PROVIDERS: &[&str] = &["deepseek", "groq", "anthropic", "gemini"];

pub fn provider_link(provider: &str) -> Option<&'static str> {
    match provider {
        "deepseek" => Some("https://platform.deepseek.com/api_keys"),
        "groq" => Some("https://console.groq.com/keys"),
        "anthropic" => Some("https://console.anthropic.com/settings/keys"),
        "gemini" => Some("https://aistudio.google.com/apikey  (free, no card)"),
        _ => None,
    }
}

pub fn tg_uid(telegram_id: i64) -> String {
    telegram_id.to_string()
}

// ── command parsing ───────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ParsedCommand {
    pub cmd: String,
    pub args: Vec<String>,
}

pub fn parse_command(text: &str) -> Option<ParsedCommand> {
    let trimmed = text.trim();
    if !trimmed.starts_with('/') {
        return None;
    }
    let mut parts = trimmed.split_whitespace();
    let head = parts.next()?;
    let cmd = head.trim_start_matches('/');
    if cmd.is_empty() {
        return None;
    }
    // Strip @botname suffix: "/start@MyBot"
    let cmd = cmd.split('@').next().unwrap_or(cmd);
    let args: Vec<String> = parts.map(|s| s.to_string()).collect();
    Some(ParsedCommand {
        cmd: cmd.to_string(),
        args,
    })
}

// ── /link consume ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct LinkedUser {
    pub id: u64,
    pub username: String,
    pub role: String,
}

pub fn local_consume_link_code(code: &str) -> Option<LinkedUser> {
    let trimmed = code.trim();
    if trimmed.len() == 6 && trimmed.chars().all(|c| c.is_ascii_digit()) {
        Some(LinkedUser {
            id: 0,
            username: "local".into(),
            role: "user".into(),
        })
    } else {
        None
    }
}

// ── /setkey / /clearkey / /whichkey replies ──────────────────────────────

pub fn setkey_usage() -> String {
    let mut lines = vec![
        "Использование: /setkey <provider> <api_key>".to_string(),
        String::new(),
        "Provider — где ВЫ сами получаете свой ключ:".to_string(),
    ];
    for p in KEY_PROVIDERS {
        lines.push(format!("  • {:<10} {}", p, provider_link(p).unwrap_or("")));
    }
    lines.push(String::new());
    lines.push("Ключ хранится локально на ноде, в зашифрованном по chmod 0600 файле.".into());
    lines.push("Биллинг идёт на ВАШ провайдерский аккаунт.".into());
    lines.push("Бот никогда не использует чужой ключ.".into());
    lines.join("\n")
}

pub fn setkey_success(provider: &str) -> String {
    format!(
        "✅ Ключ для {} сохранён локально на ноде.\n   Биллинг → ваш аккаунт у провайдера.\n   Сменить:  /setkey {} <новый_ключ>\n   Удалить:  /clearkey {}\n   Сводка:   /whichkey",
        provider, provider, provider
    )
}

pub fn unknown_provider_error(provider: &str) -> String {
    format!(
        "Неизвестный provider: {:?}.\nДоступны: {}",
        provider,
        KEY_PROVIDERS.join(", ")
    )
}

pub fn clearkey_all_success() -> String {
    "✅ Все ваши ключи удалены с этой ноды.\nБот больше не может делать LLM-вызовы от вашего имени, пока вы не зарегистрируете новый ключ через /setkey.".to_string()
}

pub fn clearkey_one_success(provider: &str) -> String {
    format!("✅ Ключ {} удалён.", provider)
}

pub fn whichkey_summary(active: &[String]) -> String {
    if active.is_empty() {
        return "У вас не зарегистрировано ни одного ключа. /setkey <provider> <api_key>"
            .to_string();
    }
    let mut lines = vec!["Ваши провайдеры (значения не показываются):".to_string()];
    for p in KEY_PROVIDERS {
        let mark = if active.iter().any(|a| a == p) {
            "✓"
        } else {
            "·"
        };
        lines.push(format!("  {} {}", mark, p));
    }
    lines.join("\n")
}

// ── state machine ─────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum State {
    Idle,
    AwaitingPatient,
    AwaitingDocument,
    AwaitingDrugs,
    AwaitingTranslation,
}

#[derive(Default)]
pub struct StateStore {
    inner: Mutex<BTreeMap<i64, State>>,
}

impl StateStore {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn get(&self, uid: i64) -> State {
        self.inner.lock().get(&uid).copied().unwrap_or(State::Idle)
    }
    pub fn set(&self, uid: i64, state: State) {
        self.inner.lock().insert(uid, state);
    }
    pub fn reset(&self, uid: i64) {
        self.inner.lock().insert(uid, State::Idle);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── parse_command ─────────────────────────────────────────────────────

    #[test]
    fn parse_simple_cmd() {
        let p = parse_command("/start").unwrap();
        assert_eq!(p.cmd, "start");
        assert!(p.args.is_empty());
    }

    #[test]
    fn parse_cmd_with_args() {
        let p = parse_command("/setkey deepseek sk-abc").unwrap();
        assert_eq!(p.cmd, "setkey");
        assert_eq!(p.args, vec!["deepseek", "sk-abc"]);
    }

    #[test]
    fn parse_cmd_strips_botname() {
        let p = parse_command("/start@MyAimBot hello").unwrap();
        assert_eq!(p.cmd, "start");
        assert_eq!(p.args, vec!["hello"]);
    }

    #[test]
    fn parse_non_cmd_returns_none() {
        assert!(parse_command("hello world").is_none());
        assert!(parse_command("").is_none());
        assert!(parse_command("/").is_none());
    }

    // ── link code ────────────────────────────────────────────────────────

    #[test]
    fn link_accepts_6_digit_local() {
        let u = local_consume_link_code("123456").unwrap();
        assert_eq!(u.username, "local");
    }

    #[test]
    fn link_rejects_short_or_alpha() {
        assert!(local_consume_link_code("12345").is_none());
        assert!(local_consume_link_code("abcdef").is_none());
        assert!(local_consume_link_code("12345a").is_none());
    }

    // ── replies ───────────────────────────────────────────────────────────

    #[test]
    fn setkey_usage_lists_providers() {
        let s = setkey_usage();
        for p in KEY_PROVIDERS {
            assert!(s.contains(p));
        }
        assert!(s.contains("биллинг") || s.contains("Биллинг"));
    }

    #[test]
    fn setkey_success_mentions_provider() {
        let s = setkey_success("deepseek");
        assert!(s.contains("deepseek"));
        assert!(s.contains("✅"));
    }

    #[test]
    fn unknown_provider_lists_options() {
        let s = unknown_provider_error("openai");
        assert!(s.contains("openai"));
        assert!(s.contains("deepseek"));
    }

    #[test]
    fn whichkey_empty() {
        let s = whichkey_summary(&[]);
        assert!(s.contains("/setkey"));
    }

    #[test]
    fn whichkey_with_partial_keys() {
        let s = whichkey_summary(&["deepseek".into(), "groq".into()]);
        assert!(s.contains("✓ deepseek"));
        assert!(s.contains("✓ groq"));
        assert!(s.contains("· anthropic"));
        assert!(s.contains("· gemini"));
    }

    // ── state ─────────────────────────────────────────────────────────────

    #[test]
    fn state_default_idle() {
        let s = StateStore::new();
        assert_eq!(s.get(1), State::Idle);
    }

    #[test]
    fn state_set_and_get() {
        let s = StateStore::new();
        s.set(42, State::AwaitingPatient);
        assert_eq!(s.get(42), State::AwaitingPatient);
        assert_eq!(s.get(43), State::Idle);
    }

    #[test]
    fn state_reset() {
        let s = StateStore::new();
        s.set(7, State::AwaitingDrugs);
        s.reset(7);
        assert_eq!(s.get(7), State::Idle);
    }

    #[test]
    fn tg_uid_string_form() {
        assert_eq!(tg_uid(123456789), "123456789");
    }

    #[test]
    fn provider_link_known() {
        assert!(provider_link("deepseek").unwrap().contains("deepseek"));
        assert!(provider_link("openai").is_none());
    }
}
