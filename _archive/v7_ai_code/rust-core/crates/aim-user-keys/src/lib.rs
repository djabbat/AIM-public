//! aim-user-keys — per-user LLM provider key resolver.
//!
//! Port of `user_keys.py`. Two-layer resolution: per-user override
//! (thread-local equivalent here is per-context override) → env
//! variable. Pluggable [`KeyStore`] so tests don't write to disk.

use std::collections::BTreeMap;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

pub const PROVIDERS: &[&str] = &["deepseek", "groq", "anthropic", "gemini"];

pub fn env_var(provider: &str) -> Option<&'static str> {
    match provider {
        "deepseek" => Some("DEEPSEEK_API_KEY"),
        "groq" => Some("GROQ_API_KEY"),
        "anthropic" => Some("ANTHROPIC_API_KEY"),
        "gemini" => Some("GEMINI_API_KEY"),
        _ => None,
    }
}

pub fn is_known_provider(provider: &str) -> bool {
    PROVIDERS.iter().any(|p| *p == provider)
}

pub fn mask(value: &str) -> String {
    if value.is_empty() {
        return "(unset)".into();
    }
    let len = value.chars().count();
    if len <= 8 {
        return "*".repeat(len);
    }
    let prefix: String = value.chars().take(4).collect();
    let suffix: String = value.chars().skip(len - 4).collect();
    format!("{}…{}", prefix, suffix)
}

// ── store ─────────────────────────────────────────────────────────────────

pub trait KeyStore: Send + Sync {
    fn get_user(&self, uid: &str) -> BTreeMap<String, String>;
    fn set_user(&self, uid: &str, keys: BTreeMap<String, String>);
    fn clear_user(&self, uid: &str);
    fn list_users(&self) -> Vec<String>;
}

#[derive(Default)]
pub struct InMemKeyStore {
    inner: Mutex<BTreeMap<String, BTreeMap<String, String>>>,
}

impl InMemKeyStore {
    pub fn new() -> Self {
        Self::default()
    }
}

impl KeyStore for InMemKeyStore {
    fn get_user(&self, uid: &str) -> BTreeMap<String, String> {
        self.inner.lock().get(uid).cloned().unwrap_or_default()
    }
    fn set_user(&self, uid: &str, keys: BTreeMap<String, String>) {
        let mut g = self.inner.lock();
        if keys.is_empty() {
            g.remove(uid);
        } else {
            g.insert(uid.to_string(), keys);
        }
    }
    fn clear_user(&self, uid: &str) {
        self.inner.lock().remove(uid);
    }
    fn list_users(&self) -> Vec<String> {
        self.inner.lock().keys().cloned().collect()
    }
}

// ── mutators ──────────────────────────────────────────────────────────────

#[derive(Debug, PartialEq, Eq)]
pub enum SetKeysError {
    UnknownProviders(Vec<String>),
}

pub fn set_keys(
    store: &dyn KeyStore,
    uid: &str,
    incoming: &[(String, String)],
) -> Result<(), SetKeysError> {
    let bad: Vec<String> = incoming
        .iter()
        .map(|(p, _)| p.clone())
        .filter(|p| !is_known_provider(p))
        .collect();
    if !bad.is_empty() {
        return Err(SetKeysError::UnknownProviders(bad));
    }
    let mut current = store.get_user(uid);
    for (p, k) in incoming {
        if !k.is_empty() {
            current.insert(p.clone(), k.clone());
        }
    }
    store.set_user(uid, current);
    Ok(())
}

pub fn clear_keys(store: &dyn KeyStore, uid: &str, providers: &[String]) {
    if providers.is_empty() {
        store.clear_user(uid);
        return;
    }
    let mut current = store.get_user(uid);
    for p in providers {
        current.remove(p);
    }
    if current.is_empty() {
        store.clear_user(uid);
    } else {
        store.set_user(uid, current);
    }
}

pub fn which_provider_keys(store: &dyn KeyStore, uid: &str) -> Vec<String> {
    let mut keys: Vec<String> = store.get_user(uid).keys().cloned().collect();
    keys.sort();
    keys
}

// ── resolver ──────────────────────────────────────────────────────────────

pub fn resolve_key<F>(
    provider: &str,
    override_keys: Option<&BTreeMap<String, String>>,
    env_lookup: F,
) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    if !is_known_provider(provider) {
        return None;
    }
    if let Some(over) = override_keys {
        if let Some(v) = over.get(provider) {
            if !v.is_empty() {
                return Some(v.clone());
            }
        }
    }
    let var = env_var(provider)?;
    env_lookup(var).filter(|s| !s.is_empty())
}

// ── ENV file write planning (key_setup.py port) ───────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EnvFileWrite {
    /// Full new content for `~/.aim_env`.
    pub new_content: String,
    /// Variable names that ended up changed.
    pub written: Vec<String>,
}

/// Plan a rewrite of `~/.aim_env` so it has each `(name, value)` pair
/// from `changes`, while preserving comments, blank lines, and any
/// other variables.
///
/// Mirrors the Python `_write_env_file` function: replace in place
/// when the variable already exists, append at end otherwise.
pub fn plan_env_write(existing: &str, changes: &[(String, String)]) -> EnvFileWrite {
    let mut new_lines: Vec<String> = Vec::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    for line in existing.lines() {
        let stripped = line.trim();
        if stripped.is_empty() || stripped.starts_with('#') {
            new_lines.push(line.to_string());
            continue;
        }
        if let Some((name_raw, _)) = stripped.split_once('=') {
            let name = name_raw.trim();
            // Same allowed-var regex as Python: ^[A-Z_][A-Z0-9_]*$
            let valid = !name.is_empty()
                && name.chars().enumerate().all(|(i, c)| {
                    if i == 0 {
                        c.is_ascii_uppercase() || c == '_'
                    } else {
                        c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_'
                    }
                });
            if !valid {
                new_lines.push(line.to_string());
                continue;
            }
            if let Some((_, v)) = changes.iter().find(|(k, _)| k == name) {
                new_lines.push(format!("{}={}", name, v));
                seen.insert(name.to_string());
                continue;
            }
            new_lines.push(line.to_string());
        } else {
            new_lines.push(line.to_string());
        }
    }
    for (k, v) in changes {
        if !seen.contains(k) {
            new_lines.push(format!("{}={}", k, v));
            seen.insert(k.clone());
        }
    }
    let body = new_lines.join("\n");
    let trimmed = body.trim_end().to_string();
    EnvFileWrite {
        new_content: format!("{}\n", trimmed),
        written: changes.iter().map(|(k, _)| k.clone()).collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── basics ────────────────────────────────────────────────────────────

    #[test]
    fn known_providers() {
        assert!(is_known_provider("deepseek"));
        assert!(is_known_provider("gemini"));
        assert!(!is_known_provider("openai"));
    }

    #[test]
    fn env_var_mapping() {
        assert_eq!(env_var("deepseek"), Some("DEEPSEEK_API_KEY"));
        assert_eq!(env_var("anthropic"), Some("ANTHROPIC_API_KEY"));
        assert_eq!(env_var("unknown"), None);
    }

    #[test]
    fn mask_rules() {
        assert_eq!(mask(""), "(unset)");
        assert_eq!(mask("abc"), "***");
        assert_eq!(mask("12345678"), "********");
        assert_eq!(mask("sk-abcdefgh1234"), "sk-a…1234");
    }

    // ── set/clear/which ──────────────────────────────────────────────────

    #[test]
    fn set_keys_round_trip() {
        let store = InMemKeyStore::new();
        let pairs = vec![
            ("deepseek".to_string(), "sk-1".to_string()),
            ("groq".to_string(), "gsk-1".to_string()),
        ];
        set_keys(&store, "u", &pairs).unwrap();
        let got = store.get_user("u");
        assert_eq!(got.get("deepseek").map(String::as_str), Some("sk-1"));
        assert_eq!(got.get("groq").map(String::as_str), Some("gsk-1"));
    }

    #[test]
    fn set_keys_rejects_unknown_provider() {
        let store = InMemKeyStore::new();
        let pairs = vec![("openai".into(), "k".into())];
        let err = set_keys(&store, "u", &pairs).unwrap_err();
        assert_eq!(err, SetKeysError::UnknownProviders(vec!["openai".into()]));
    }

    #[test]
    fn set_keys_ignores_empty_values() {
        let store = InMemKeyStore::new();
        set_keys(&store, "u", &[("deepseek".into(), "k".into())]).unwrap();
        set_keys(&store, "u", &[("groq".into(), "".into())]).unwrap();
        let got = store.get_user("u");
        assert_eq!(got.len(), 1);
        assert!(got.contains_key("deepseek"));
    }

    #[test]
    fn clear_keys_removes_specific() {
        let store = InMemKeyStore::new();
        set_keys(
            &store,
            "u",
            &[
                ("deepseek".into(), "sk".into()),
                ("groq".into(), "gsk".into()),
            ],
        )
        .unwrap();
        clear_keys(&store, "u", &["deepseek".into()]);
        let got = store.get_user("u");
        assert_eq!(got.len(), 1);
        assert!(got.contains_key("groq"));
    }

    #[test]
    fn clear_keys_with_no_providers_clears_user() {
        let store = InMemKeyStore::new();
        set_keys(&store, "u", &[("deepseek".into(), "sk".into())]).unwrap();
        clear_keys(&store, "u", &[]);
        assert!(store.list_users().is_empty());
    }

    #[test]
    fn which_provider_keys_sorted() {
        let store = InMemKeyStore::new();
        set_keys(
            &store,
            "u",
            &[
                ("groq".into(), "g".into()),
                ("deepseek".into(), "d".into()),
            ],
        )
        .unwrap();
        let got = which_provider_keys(&store, "u");
        assert_eq!(got, vec!["deepseek", "groq"]);
    }

    // ── resolver ──────────────────────────────────────────────────────────

    #[test]
    fn resolver_prefers_override_over_env() {
        let mut over = BTreeMap::new();
        over.insert("deepseek".into(), "override-key".into());
        let r = resolve_key("deepseek", Some(&over), |_| Some("env-key".into()));
        assert_eq!(r, Some("override-key".into()));
    }

    #[test]
    fn resolver_falls_back_to_env() {
        let r = resolve_key("deepseek", None, |k| {
            if k == "DEEPSEEK_API_KEY" {
                Some("env-key".into())
            } else {
                None
            }
        });
        assert_eq!(r, Some("env-key".into()));
    }

    #[test]
    fn resolver_empty_string_in_env_is_none() {
        let r = resolve_key("deepseek", None, |_| Some("".into()));
        assert!(r.is_none());
    }

    #[test]
    fn resolver_unknown_provider() {
        let r = resolve_key("openai", None, |_| Some("k".into()));
        assert!(r.is_none());
    }

    // ── env-file rewrite ──────────────────────────────────────────────────

    #[test]
    fn env_write_replaces_existing_var() {
        let existing = "# my keys\nDEEPSEEK_API_KEY=old-key\nGROQ_API_KEY=gsk-1\n";
        let plan = plan_env_write(
            existing,
            &[("DEEPSEEK_API_KEY".into(), "new-key".into())],
        );
        assert!(plan.new_content.contains("DEEPSEEK_API_KEY=new-key"));
        assert!(plan.new_content.contains("GROQ_API_KEY=gsk-1"));
        assert!(plan.new_content.contains("# my keys"));
    }

    #[test]
    fn env_write_appends_new_var() {
        let plan = plan_env_write(
            "DEEPSEEK_API_KEY=sk\n",
            &[("ANTHROPIC_API_KEY".into(), "ant".into())],
        );
        assert!(plan.new_content.contains("DEEPSEEK_API_KEY=sk"));
        assert!(plan.new_content.contains("ANTHROPIC_API_KEY=ant"));
    }

    #[test]
    fn env_write_preserves_comments_and_blanks() {
        let plan = plan_env_write(
            "# header comment\n\nFOO=bar\n",
            &[("FOO".into(), "baz".into())],
        );
        assert!(plan.new_content.starts_with("# header comment"));
        assert!(plan.new_content.contains("FOO=baz"));
    }
}
