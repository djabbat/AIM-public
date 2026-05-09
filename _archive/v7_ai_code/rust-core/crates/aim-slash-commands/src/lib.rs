//! aim-slash-commands — slash-command router for AIM REPLs.
//!
//! Port of `agents/slash_commands.py`. The Python original ties handlers
//! directly to memory/cost/profile/etc Python modules. The Rust port
//! keeps the **dispatch + parsing** layer self-contained and pushes
//! handler bodies behind a [`Handler`] trait so consumers wire in only
//! the integrations they need.
//!
//! Includes:
//!   • [`is_slash`] / [`dispatch`] — the public surface
//!   • [`Registry`] — pluggable handler registry with help-text grouping
//!   • [`AddArgs::parse`] — `/add [--priority X] [--category Y] [--ttl N] <fact>`
//!   • Built-in flag-toggle handlers that mutate context (`/no-mem`,
//!     `/review`, etc.) one-shot for the next request

use std::collections::BTreeMap;
use std::sync::Arc;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SlashError {
    #[error("usage: {0}")]
    Usage(String),
    #[error("system exit requested")]
    Exit,
    #[error("handler failed: {0}")]
    Handler(String),
}

pub type SlashResult = std::result::Result<String, SlashError>;

// ── context ─────────────────────────────────────────────────────────────────

/// Per-session mutable context. Slash handlers can read or set keys on it
/// (matches the Python `ctx: dict`).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SlashContext {
    pub flags: BTreeMap<String, bool>,
    pub strings: BTreeMap<String, String>,
}

impl SlashContext {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set_flag(&mut self, name: &str, on: bool) {
        self.flags.insert(name.into(), on);
    }
    pub fn flag(&self, name: &str) -> bool {
        self.flags.get(name).copied().unwrap_or(false)
    }
    pub fn set_str(&mut self, name: &str, val: impl Into<String>) {
        self.strings.insert(name.into(), val.into());
    }
    pub fn get_str(&self, name: &str) -> Option<&str> {
        self.strings.get(name).map(String::as_str)
    }
}

// ── handler ─────────────────────────────────────────────────────────────────

pub trait Handler: Send + Sync {
    fn run(&self, args: &str, ctx: &mut SlashContext) -> SlashResult;
}

/// Closure-based handler adapter.
pub struct FnHandler {
    inner: Arc<dyn Fn(&str, &mut SlashContext) -> SlashResult + Send + Sync>,
}

impl FnHandler {
    pub fn new(
        f: impl Fn(&str, &mut SlashContext) -> SlashResult + Send + Sync + 'static,
    ) -> Self {
        Self { inner: Arc::new(f) }
    }
}

impl Handler for FnHandler {
    fn run(&self, args: &str, ctx: &mut SlashContext) -> SlashResult {
        (self.inner)(args, ctx)
    }
}

// ── command entry ───────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct Command {
    pub name: String,
    pub group: &'static str,
    pub desc: String,
    pub handler: Arc<dyn Handler>,
}

// ── registry ────────────────────────────────────────────────────────────────

pub const GROUP_MEMORY: &str = "Memory";
pub const GROUP_GRAPH: &str = "Graph";
pub const GROUP_SYSTEM: &str = "System";
pub const GROUP_PROFILE: &str = "Profile";
pub const GROUP_MISC: &str = "Misc";

pub const GROUP_ORDER: &[&str] = &[GROUP_MEMORY, GROUP_GRAPH, GROUP_SYSTEM, GROUP_PROFILE, GROUP_MISC];

pub struct Registry {
    commands: Mutex<BTreeMap<String, Command>>,
}

impl Registry {
    pub fn new() -> Self {
        Self {
            commands: Mutex::new(BTreeMap::new()),
        }
    }

    /// Pre-installed flag-toggle + meta commands. Handler implementations
    /// for memory/cost/health/etc are NOT included — wire those via
    /// `register()` from the calling binary.
    pub fn with_builtins() -> Self {
        let r = Self::new();
        // Toggle flags (set the named flag in ctx for the next request)
        for (name, flag) in [
            ("/no-mem", "no_mem"),
            ("/review", "review"),
            ("/parallel", "parallel"),
            ("/tree", "tree_plan"),
            ("/debate", "debate"),
            ("/full-mem", "full_memory"),
            ("/stream", "stream_review"),
            ("/edit-plan", "edit_plan"),
        ] {
            let f = flag.to_string();
            let f_for_msg = flag.to_string();
            r.register(Command {
                name: name.into(),
                group: GROUP_GRAPH,
                desc: format!("next request: enable {}", f),
                handler: Arc::new(FnHandler::new(move |_, ctx| {
                    ctx.set_flag(&f_for_msg, true);
                    Ok(format!("[ok] {} включён для следующего запроса", f_for_msg))
                })),
            });
        }
        // /help, /clear, /exit
        r.register(Command {
            name: "/help".into(),
            group: GROUP_MISC,
            desc: "show command list".into(),
            handler: Arc::new(FnHandler::new(|_, _| Ok(String::new()))),
            // overridden below by registry-aware handler
        });
        r.register(Command {
            name: "/clear".into(),
            group: GROUP_MISC,
            desc: "clear screen".into(),
            handler: Arc::new(FnHandler::new(|_, _| Ok("\x1b[2J\x1b[H".into()))),
        });
        let exit_handler = Arc::new(FnHandler::new(|_: &str, _: &mut SlashContext| {
            Err::<String, _>(SlashError::Exit)
        }));
        r.register(Command {
            name: "/exit".into(),
            group: GROUP_MISC,
            desc: "leave session".into(),
            handler: exit_handler.clone(),
        });
        r.register(Command {
            name: "/quit".into(),
            group: GROUP_MISC,
            desc: "leave session".into(),
            handler: exit_handler,
        });
        r
    }

    pub fn register(&self, cmd: Command) {
        self.commands.lock().insert(cmd.name.clone(), cmd);
    }

    pub fn names(&self) -> Vec<String> {
        self.commands.lock().keys().cloned().collect()
    }

    pub fn get(&self, name: &str) -> Option<Command> {
        self.commands.lock().get(name).cloned()
    }

    pub fn help_text(&self) -> String {
        let cmds = self.commands.lock();
        let mut by_group: BTreeMap<&str, Vec<&Command>> = BTreeMap::new();
        for c in cmds.values() {
            by_group.entry(c.group).or_default().push(c);
        }
        let mut out = String::new();
        for &grp in GROUP_ORDER {
            if let Some(list) = by_group.get(grp) {
                out.push_str(&format!("\n[{}]\n", grp));
                let mut sorted = list.clone();
                sorted.sort_by(|a, b| a.name.cmp(&b.name));
                for c in sorted {
                    out.push_str(&format!("  {:<14} {}\n", c.name, c.desc));
                }
            }
        }
        // Tail any groups that aren't in GROUP_ORDER
        for (grp, list) in by_group.iter() {
            if GROUP_ORDER.contains(grp) {
                continue;
            }
            out.push_str(&format!("\n[{}]\n", grp));
            let mut sorted = list.clone();
            sorted.sort_by(|a, b| a.name.cmp(&b.name));
            for c in sorted {
                out.push_str(&format!("  {:<14} {}\n", c.name, c.desc));
            }
        }
        out.trim_end().to_string()
    }
}

// ── public dispatch ─────────────────────────────────────────────────────────

/// `/cmd args` lines start with a single `/` (and `//` is escape — pass through).
pub fn is_slash(text: &str) -> bool {
    let t = text.trim_start();
    t.starts_with('/') && !t.starts_with("//")
}

/// Dispatch a slash line. Returns `Ok(None)` if `text` isn't a slash;
/// `Ok(Some(output))` on handler success; `Err(Exit)` on `/exit|/quit`;
/// `Err(Handler)` on other failures. Unknown commands return an error
/// string + help text wrapped in `Ok(Some(_))`.
pub fn dispatch(
    registry: &Registry,
    text: &str,
    ctx: &mut SlashContext,
) -> std::result::Result<Option<String>, SlashError> {
    if !is_slash(text) {
        return Ok(None);
    }
    let trimmed = text.trim();
    let (cmd_part, args) = match trimmed.split_once(' ') {
        Some((c, a)) => (c.to_string(), a.trim().to_string()),
        None => (trimmed.to_string(), String::new()),
    };
    let cmd_lower = cmd_part.to_lowercase();
    // /help is special: it consults the registry to build text
    if cmd_lower == "/help" {
        return Ok(Some(registry.help_text()));
    }
    let cmd = registry.get(&cmd_lower);
    let Some(cmd) = cmd else {
        return Ok(Some(format!(
            "❌ unknown command: {}\n{}",
            cmd_lower,
            registry.help_text()
        )));
    };
    match cmd.handler.run(&args, ctx) {
        Ok(s) => Ok(Some(s)),
        Err(SlashError::Exit) => Err(SlashError::Exit),
        Err(SlashError::Usage(u)) => Ok(Some(format!("usage: {}", u))),
        Err(SlashError::Handler(e)) => Ok(Some(format!("❌ {} failed: {}", cmd_lower, e))),
    }
}

// ── /add argument parser ────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AddArgs {
    pub priority: String,
    pub category: String,
    pub ttl_hours: Option<i64>,
    pub fact: String,
}

impl AddArgs {
    /// Parse `[--priority X] [--category Y] [--ttl N] <fact words…>`.
    pub fn parse(raw: &str) -> std::result::Result<Self, String> {
        let parts: Vec<String> = shlex::split(raw)
            .ok_or_else(|| "shlex parse failed".to_string())?;
        let mut priority = "NORMAL".to_string();
        let mut category = "general".to_string();
        let mut ttl_hours: Option<i64> = None;
        let mut fact_words: Vec<String> = Vec::new();
        let mut i = 0;
        while i < parts.len() {
            match parts[i].as_str() {
                "--priority" if i + 1 < parts.len() => {
                    priority = parts[i + 1].to_uppercase();
                    i += 2;
                }
                "--category" if i + 1 < parts.len() => {
                    category = parts[i + 1].clone();
                    i += 2;
                }
                "--ttl" if i + 1 < parts.len() => {
                    let n: i64 = parts[i + 1]
                        .parse()
                        .map_err(|e: std::num::ParseIntError| e.to_string())?;
                    ttl_hours = Some(n);
                    i += 2;
                }
                _ => {
                    fact_words.push(parts[i].clone());
                    i += 1;
                }
            }
        }
        let fact = fact_words.join(" ").trim().to_string();
        if fact.is_empty() {
            return Err("fact text empty".into());
        }
        Ok(Self {
            priority,
            category,
            ttl_hours,
            fact,
        })
    }
}

// ── /diff argument parser ──────────────────────────────────────────────────

pub fn parse_diff_args(raw: &str) -> std::result::Result<(String, String), String> {
    let parts: Vec<&str> = raw.split_whitespace().collect();
    if parts.len() != 2 {
        return Err("usage: /diff <ver_a> <ver_b>".into());
    }
    Ok((parts[0].to_string(), parts[1].to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── is_slash ────────────────────────────────────────────────────────────

    #[test]
    fn is_slash_recognises_leading_slash() {
        assert!(is_slash("/help"));
        assert!(is_slash("  /add foo"));
    }

    #[test]
    fn is_slash_rejects_double_slash_escape() {
        assert!(!is_slash("//literal"));
    }

    #[test]
    fn is_slash_rejects_plain_text() {
        assert!(!is_slash("hello"));
        assert!(!is_slash(""));
    }

    // ── AddArgs::parse ──────────────────────────────────────────────────────

    #[test]
    fn add_args_fact_only() {
        let r = AddArgs::parse("любимый цвет синий").unwrap();
        assert_eq!(r.fact, "любимый цвет синий");
        assert_eq!(r.priority, "NORMAL");
        assert_eq!(r.category, "general");
        assert!(r.ttl_hours.is_none());
    }

    #[test]
    fn add_args_with_all_flags() {
        let r = AddArgs::parse("--priority high --category contacts --ttl 720 фио Иванов").unwrap();
        assert_eq!(r.priority, "HIGH");
        assert_eq!(r.category, "contacts");
        assert_eq!(r.ttl_hours, Some(720));
        assert_eq!(r.fact, "фио Иванов");
    }

    #[test]
    fn add_args_empty_fact_errors() {
        assert!(AddArgs::parse("--priority high").is_err());
        assert!(AddArgs::parse("").is_err());
    }

    #[test]
    fn add_args_quoted_fact_kept_intact() {
        let r = AddArgs::parse(r#"--category x "two words""#).unwrap();
        assert_eq!(r.fact, "two words");
    }

    #[test]
    fn add_args_invalid_ttl_errors() {
        assert!(AddArgs::parse("--ttl notanint x").is_err());
    }

    // ── parse_diff_args ─────────────────────────────────────────────────────

    #[test]
    fn diff_args_two_tokens() {
        assert_eq!(
            parse_diff_args("v1 v2").unwrap(),
            ("v1".into(), "v2".into())
        );
    }

    #[test]
    fn diff_args_wrong_count_errors() {
        assert!(parse_diff_args("only-one").is_err());
        assert!(parse_diff_args("a b c").is_err());
    }

    // ── Registry / dispatch ─────────────────────────────────────────────────

    #[test]
    fn dispatch_returns_none_for_non_slash() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        assert_eq!(dispatch(&r, "hello world", &mut ctx).unwrap(), None);
    }

    #[test]
    fn dispatch_unknown_command_returns_help() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/nope", &mut ctx).unwrap().unwrap();
        assert!(out.contains("unknown command"));
        assert!(out.contains("/nope"));
        // help text follows
        assert!(out.contains("[Misc]"));
    }

    #[test]
    fn dispatch_help_renders_grouped_text() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/help", &mut ctx).unwrap().unwrap();
        assert!(out.contains("[Graph]"));
        assert!(out.contains("/no-mem"));
        assert!(out.contains("[Misc]"));
        assert!(out.contains("/exit"));
    }

    #[test]
    fn dispatch_toggle_sets_context_flag() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/no-mem", &mut ctx).unwrap().unwrap();
        assert!(ctx.flag("no_mem"));
        assert!(out.contains("включён"));
    }

    #[test]
    fn dispatch_review_toggle() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        dispatch(&r, "/review", &mut ctx).unwrap();
        assert!(ctx.flag("review"));
    }

    #[test]
    fn dispatch_clear_returns_ansi_sequence() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/clear", &mut ctx).unwrap().unwrap();
        assert!(out.contains("\x1b[2J"));
    }

    #[test]
    fn dispatch_exit_returns_exit_error() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        let err = dispatch(&r, "/exit", &mut ctx).unwrap_err();
        assert!(matches!(err, SlashError::Exit));
    }

    #[test]
    fn dispatch_quit_aliased_to_exit() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        let err = dispatch(&r, "/quit", &mut ctx).unwrap_err();
        assert!(matches!(err, SlashError::Exit));
    }

    #[test]
    fn dispatch_case_insensitive_command_name() {
        let r = Registry::with_builtins();
        let mut ctx = SlashContext::new();
        dispatch(&r, "/REVIEW", &mut ctx).unwrap();
        assert!(ctx.flag("review"));
    }

    // ── custom registration ─────────────────────────────────────────────────

    #[test]
    fn custom_handler_runs_and_receives_args() {
        let r = Registry::with_builtins();
        let captured = Arc::new(Mutex::new(String::new()));
        let c2 = captured.clone();
        r.register(Command {
            name: "/echo".into(),
            group: GROUP_SYSTEM,
            desc: "echo back".into(),
            handler: Arc::new(FnHandler::new(move |args, _| {
                *c2.lock() = args.to_string();
                Ok(format!("got: {}", args))
            })),
        });
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/echo hello world", &mut ctx).unwrap().unwrap();
        assert_eq!(out, "got: hello world");
        assert_eq!(*captured.lock(), "hello world");
    }

    #[test]
    fn handler_failure_reports_via_dispatch() {
        let r = Registry::with_builtins();
        r.register(Command {
            name: "/bad".into(),
            group: GROUP_SYSTEM,
            desc: "fails".into(),
            handler: Arc::new(FnHandler::new(|_, _| {
                Err(SlashError::Handler("kaboom".into()))
            })),
        });
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/bad", &mut ctx).unwrap().unwrap();
        assert!(out.contains("❌"));
        assert!(out.contains("/bad"));
        assert!(out.contains("kaboom"));
    }

    #[test]
    fn handler_usage_returns_usage_string() {
        let r = Registry::with_builtins();
        r.register(Command {
            name: "/needargs".into(),
            group: GROUP_SYSTEM,
            desc: "needs args".into(),
            handler: Arc::new(FnHandler::new(|_, _| {
                Err(SlashError::Usage("/needargs <thing>".into()))
            })),
        });
        let mut ctx = SlashContext::new();
        let out = dispatch(&r, "/needargs", &mut ctx).unwrap().unwrap();
        assert!(out.starts_with("usage:"));
        assert!(out.contains("/needargs <thing>"));
    }

    // ── help text grouping ──────────────────────────────────────────────────

    #[test]
    fn help_lists_groups_in_canonical_order() {
        let r = Registry::with_builtins();
        let h = r.help_text();
        let mem_pos = h.find("[Memory]").unwrap_or(usize::MAX);
        let graph_pos = h.find("[Graph]").unwrap();
        let misc_pos = h.find("[Misc]").unwrap();
        // [Graph] before [Misc]
        assert!(graph_pos < misc_pos);
        // Memory section may not exist if no handlers in group, that's ok
        let _ = mem_pos;
    }
}
