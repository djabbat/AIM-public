//! aim-memory-tui — terminal UI **state machine** for AIM memory.
//!
//! Port of `agents/memory_tui.py`. The Python original is a curses
//! script with stateful key dispatch tightly coupled to ncurses I/O.
//!
//! In Rust we extract the **pure state machine** so it's testable
//! without a TTY. A future `aim` binary will glue this state to a
//! `ratatui`/`crossterm` event loop. Helpers (`truncate`,
//! `parse_frontmatter`, `set_priority`, `priority_cycle_next`) port
//! the Python utility functions one-to-one.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum TuiError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, TuiError>;

// ── priority cycle ──────────────────────────────────────────────────────────

pub const PRIORITY_CYCLE: &[&str] = &["CRITICAL", "HIGH", "NORMAL", "LOW", "EPHEMERAL"];

/// Returns the next priority in the cycle. Unknown priorities map to NORMAL,
/// then advance from there — same logic as Python `idx = ... if cur in ... else 2`.
pub fn priority_cycle_next(current: &str) -> &'static str {
    let upper = current.to_uppercase();
    let idx = PRIORITY_CYCLE
        .iter()
        .position(|&p| p == upper)
        .unwrap_or(2);
    PRIORITY_CYCLE[(idx + 1) % PRIORITY_CYCLE.len()]
}

pub fn priority_value(p: &str) -> i64 {
    match p.to_uppercase().as_str() {
        "CRITICAL" => 100,
        "HIGH" => 70,
        "NORMAL" => 40,
        "LOW" => 10,
        "EPHEMERAL" => 1,
        _ => 40,
    }
}

// ── truncate ────────────────────────────────────────────────────────────────

/// Mirrors Python `_truncate`: collapse newlines/CRs to spaces, ellipsise to `n`.
/// `n` is interpreted as a count of `char`s (not bytes), matching Python `len()`.
pub fn truncate(s: &str, n: usize) -> String {
    let cleaned: String = s
        .chars()
        .map(|c| if c == '\n' || c == '\r' { ' ' } else { c })
        .collect();
    if cleaned.chars().count() <= n {
        cleaned
    } else if n == 0 {
        String::new()
    } else {
        let head: String = cleaned.chars().take(n - 1).collect();
        format!("{}…", head)
    }
}

// ── frontmatter helpers ─────────────────────────────────────────────────────

/// Parse the leading `---\n…\n---` block. Best-effort, like Python.
pub fn read_frontmatter_text(text: &str) -> Vec<(String, String)> {
    let Some(rest) = text.strip_prefix("---") else {
        return Vec::new();
    };
    let Some(rest) = strip_inline_ws(rest).strip_prefix('\n') else {
        return Vec::new();
    };
    let Some(end) = rest.find("\n---") else {
        return Vec::new();
    };
    let block = &rest[..end];
    let mut out = Vec::new();
    for line in block.lines() {
        if let Some((k, v)) = line.split_once(':') {
            out.push((k.trim().to_string(), v.trim().to_string()));
        }
    }
    out
}

pub fn read_frontmatter_file(path: &Path) -> Vec<(String, String)> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return Vec::new();
    };
    read_frontmatter_text(&text)
}

fn strip_inline_ws(s: &str) -> &str {
    let mut idx = 0;
    for (i, ch) in s.char_indices() {
        if ch == ' ' || ch == '\t' {
            idx = i + ch.len_utf8();
        } else {
            return &s[idx..];
        }
    }
    &s[idx..]
}

/// Rewrite a memory file's frontmatter to set `priority: <new>` (replacing
/// any existing `priority` line, case-insensitive). Returns `Ok(true)` on
/// rewrite, `Ok(false)` if the file lacks a frontmatter block.
pub fn set_priority(path: &Path, new_priority: &str) -> Result<bool> {
    if !path.exists() {
        return Ok(false);
    }
    let text = std::fs::read_to_string(path)?;
    let Some(rest) = text.strip_prefix("---") else {
        return Ok(false);
    };
    let Some(rest_after_marker) = strip_inline_ws(rest).strip_prefix('\n') else {
        return Ok(false);
    };
    let head_len = text.len() - rest_after_marker.len();
    let head = &text[..head_len];
    let Some(close_pos) = rest_after_marker.find("\n---") else {
        return Ok(false);
    };
    let fm_block = &rest_after_marker[..close_pos];
    let after_fm = &rest_after_marker[close_pos..];
    // after_fm starts with "\n---" — find end of marker line
    let after_dashes = &after_fm[4..];
    let after_ws = strip_inline_ws(after_dashes);
    let after_nl = after_ws.strip_prefix('\n').unwrap_or(after_ws);
    let marker_end = after_fm.len() - after_nl.len();
    let tail_marker = &after_fm[..marker_end];
    let body = after_nl;

    let mut new_lines: Vec<String> = fm_block
        .lines()
        .filter(|l| !l.to_lowercase().starts_with("priority"))
        .map(String::from)
        .collect();
    new_lines.push(format!("priority: {}", new_priority));
    new_lines.push(format!("priority_value: {}", priority_value(new_priority)));
    let new_fm = new_lines.join("\n");

    let new_text = format!("{}{}{}{}", head, new_fm, tail_marker, body);
    std::fs::write(path, new_text)?;
    Ok(true)
}

/// Walk `base` looking for any file whose name equals `name`. Returns the
/// first match (no ordering guarantee — matches Python `next(rglob(...))`).
pub fn locate_memory_file(base: &Path, name: &str) -> Option<PathBuf> {
    if !base.exists() {
        return None;
    }
    walkdir_first(base, name)
}

fn walkdir_first(dir: &Path, target: &str) -> Option<PathBuf> {
    let entries = std::fs::read_dir(dir).ok()?;
    let mut subdirs = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let ft = entry.file_type().ok()?;
        if ft.is_file() {
            if path
                .file_name()
                .and_then(|s| s.to_str())
                .map(|n| n == target)
                .unwrap_or(false)
            {
                return Some(path);
            }
        } else if ft.is_dir() {
            subdirs.push(path);
        }
    }
    for sub in subdirs {
        if let Some(found) = walkdir_first(&sub, target) {
            return Some(found);
        }
    }
    None
}

// ── state machine ───────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Pane {
    Search,
    List,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum SearchMode {
    Flat,
    Graph,
}

impl SearchMode {
    pub fn toggle(&mut self) {
        *self = match self {
            Self::Flat => Self::Graph,
            Self::Graph => Self::Flat,
        };
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Hit {
    pub file: String,
    pub text: String,
    pub distance: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TuiState {
    pub query: String,
    pub mode: SearchMode,
    pub hits: Vec<Hit>,
    pub cursor: usize,
    pub pane: Pane,
    pub msg: String,
}

impl Default for TuiState {
    fn default() -> Self {
        Self {
            query: String::new(),
            mode: SearchMode::Flat,
            hits: Vec::new(),
            cursor: 0,
            pane: Pane::Search,
            msg: "/ search · Enter open · e edit · d delete · p priority · g mode · q quit".into(),
        }
    }
}

/// All possible state transitions. The driver translates `getch()` → these.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    Char(char),
    Backspace,
    Enter,
    Up,
    Down,
    PageUp,
    PageDown,
    Tab,
    FocusSearch,
    ToggleMode,
    Reload,
    Quit,
}

/// Outcome of dispatching an action — caller binds side effects.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Effect {
    None,
    Quit,
    RunSearch,
    Reload,
}

impl TuiState {
    /// Apply a state transition. Returns the [`Effect`] the driver should
    /// realize (run a search, exit, etc). Pure: doesn't touch I/O.
    pub fn apply(&mut self, action: Action) -> Effect {
        if matches!(action, Action::Quit) {
            return Effect::Quit;
        }
        match self.pane {
            Pane::Search => self.apply_search(action),
            Pane::List => self.apply_list(action),
        }
    }

    fn apply_search(&mut self, action: Action) -> Effect {
        match action {
            Action::Enter => {
                self.cursor = 0;
                self.pane = Pane::List;
                Effect::RunSearch
            }
            Action::Backspace => {
                self.query.pop();
                Effect::None
            }
            Action::Tab => {
                self.pane = Pane::List;
                Effect::None
            }
            Action::Char(c) if (c as u32) >= 32 => {
                self.query.push(c);
                Effect::None
            }
            _ => Effect::None,
        }
    }

    fn apply_list(&mut self, action: Action) -> Effect {
        match action {
            Action::FocusSearch | Action::Tab => {
                self.pane = Pane::Search;
                Effect::None
            }
            Action::Down if !self.hits.is_empty() => {
                self.cursor = (self.cursor + 1).min(self.hits.len() - 1);
                Effect::None
            }
            Action::Up if !self.hits.is_empty() => {
                self.cursor = self.cursor.saturating_sub(1);
                Effect::None
            }
            Action::PageDown if !self.hits.is_empty() => {
                self.cursor = (self.cursor + 10).min(self.hits.len() - 1);
                Effect::None
            }
            Action::PageUp if !self.hits.is_empty() => {
                self.cursor = self.cursor.saturating_sub(10);
                Effect::None
            }
            Action::ToggleMode => {
                self.mode.toggle();
                self.cursor = 0;
                Effect::RunSearch
            }
            Action::Reload => Effect::Reload,
            _ => Effect::None,
        }
    }

    /// Driver calls this after running a search to install fresh hits.
    /// Cursor is clamped to the new range.
    pub fn install_hits(&mut self, hits: Vec<Hit>) {
        self.hits = hits;
        self.cursor = self
            .cursor
            .min(self.hits.len().saturating_sub(1).max(0));
        if self.hits.is_empty() {
            self.cursor = 0;
        }
    }

    pub fn selected(&self) -> Option<&Hit> {
        self.hits.get(self.cursor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    // ── priority cycle ──────────────────────────────────────────────────────

    #[test]
    fn priority_cycle_full_loop() {
        assert_eq!(priority_cycle_next("CRITICAL"), "HIGH");
        assert_eq!(priority_cycle_next("HIGH"), "NORMAL");
        assert_eq!(priority_cycle_next("NORMAL"), "LOW");
        assert_eq!(priority_cycle_next("LOW"), "EPHEMERAL");
        assert_eq!(priority_cycle_next("EPHEMERAL"), "CRITICAL");
    }

    #[test]
    fn priority_cycle_unknown_falls_back_to_normal_position() {
        // unknown → idx=2 (NORMAL) → next is LOW
        assert_eq!(priority_cycle_next("WHATEVER"), "LOW");
    }

    #[test]
    fn priority_cycle_case_insensitive() {
        assert_eq!(priority_cycle_next("high"), "NORMAL");
        assert_eq!(priority_cycle_next("Critical"), "HIGH");
    }

    #[test]
    fn priority_value_known_levels() {
        assert_eq!(priority_value("CRITICAL"), 100);
        assert_eq!(priority_value("HIGH"), 70);
        assert_eq!(priority_value("NORMAL"), 40);
        assert_eq!(priority_value("LOW"), 10);
        assert_eq!(priority_value("EPHEMERAL"), 1);
        assert_eq!(priority_value("garbage"), 40);
    }

    // ── truncate ────────────────────────────────────────────────────────────

    #[test]
    fn truncate_short_string_passes_through() {
        assert_eq!(truncate("hello", 10), "hello");
    }

    #[test]
    fn truncate_long_string_ellipsises() {
        assert_eq!(truncate("hello world", 7), "hello …");
    }

    #[test]
    fn truncate_collapses_newlines() {
        assert_eq!(truncate("a\nb\rc", 10), "a b c");
    }

    #[test]
    fn truncate_unicode_counts_chars_not_bytes() {
        assert_eq!(truncate("Иванов", 10), "Иванов");
        assert_eq!(truncate("Иванов работал", 7).chars().count(), 7);
    }

    #[test]
    fn truncate_zero_returns_empty() {
        assert_eq!(truncate("anything", 0), "");
    }

    // ── frontmatter ─────────────────────────────────────────────────────────

    #[test]
    fn read_frontmatter_text_basic() {
        let fm = read_frontmatter_text("---\nname: foo\npriority: HIGH\n---\nbody\n");
        assert_eq!(fm.len(), 2);
        assert_eq!(fm[0], ("name".into(), "foo".into()));
        assert_eq!(fm[1], ("priority".into(), "HIGH".into()));
    }

    #[test]
    fn read_frontmatter_text_missing_returns_empty() {
        assert!(read_frontmatter_text("just body").is_empty());
        assert!(read_frontmatter_text("---\nno close\n").is_empty());
    }

    #[test]
    fn read_frontmatter_file_missing_path() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("nope.md");
        assert!(read_frontmatter_file(&p).is_empty());
    }

    // ── set_priority ────────────────────────────────────────────────────────

    #[test]
    fn set_priority_replaces_existing_line() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(
            &p,
            "---\nname: foo\npriority: NORMAL\n---\nthe body\n",
        )
        .unwrap();
        assert!(set_priority(&p, "HIGH").unwrap());
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(text.contains("priority: HIGH"));
        assert!(text.contains("priority_value: 70"));
        assert!(!text.contains("priority: NORMAL"));
        assert!(text.contains("the body"));
    }

    #[test]
    fn set_priority_adds_when_missing() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(&p, "---\nname: foo\n---\nthe body\n").unwrap();
        assert!(set_priority(&p, "CRITICAL").unwrap());
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(text.contains("priority: CRITICAL"));
        assert!(text.contains("priority_value: 100"));
    }

    #[test]
    fn set_priority_returns_false_when_no_frontmatter() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.md");
        std::fs::write(&p, "no frontmatter").unwrap();
        assert!(!set_priority(&p, "HIGH").unwrap());
    }

    #[test]
    fn set_priority_returns_false_when_path_missing() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("missing.md");
        assert!(!set_priority(&p, "HIGH").unwrap());
    }

    // ── locate_memory_file ──────────────────────────────────────────────────

    #[test]
    fn locate_finds_file_in_subdir() {
        let tmp = TempDir::new().unwrap();
        let sub = tmp.path().join("a/b");
        std::fs::create_dir_all(&sub).unwrap();
        let p = sub.join("target.md");
        std::fs::write(&p, "x").unwrap();
        let found = locate_memory_file(tmp.path(), "target.md").unwrap();
        assert_eq!(found.canonicalize().unwrap(), p.canonicalize().unwrap());
    }

    #[test]
    fn locate_returns_none_when_missing() {
        let tmp = TempDir::new().unwrap();
        assert!(locate_memory_file(tmp.path(), "nope.md").is_none());
    }

    #[test]
    fn locate_returns_none_when_base_missing() {
        let tmp = TempDir::new().unwrap();
        let missing = tmp.path().join("does_not_exist");
        assert!(locate_memory_file(&missing, "any.md").is_none());
    }

    // ── state machine ───────────────────────────────────────────────────────

    fn fresh_hits(n: usize) -> Vec<Hit> {
        (0..n)
            .map(|i| Hit {
                file: format!("f{}.md", i),
                text: format!("body {}", i),
                distance: 0.1 * (i as f64),
            })
            .collect()
    }

    #[test]
    fn search_pane_chars_extend_query() {
        let mut s = TuiState::default();
        s.apply(Action::Char('h'));
        s.apply(Action::Char('i'));
        assert_eq!(s.query, "hi");
    }

    #[test]
    fn search_pane_backspace_pops_char() {
        let mut s = TuiState::default();
        s.query = "abc".into();
        s.apply(Action::Backspace);
        assert_eq!(s.query, "ab");
    }

    #[test]
    fn search_pane_enter_emits_run_search_and_switches_pane() {
        let mut s = TuiState::default();
        s.query = "Q".into();
        let e = s.apply(Action::Enter);
        assert_eq!(e, Effect::RunSearch);
        assert_eq!(s.pane, Pane::List);
    }

    #[test]
    fn list_pane_down_advances_cursor_clamped() {
        let mut s = TuiState::default();
        s.pane = Pane::List;
        s.install_hits(fresh_hits(3));
        s.apply(Action::Down);
        s.apply(Action::Down);
        s.apply(Action::Down); // clamped
        assert_eq!(s.cursor, 2);
    }

    #[test]
    fn list_pane_up_clamps_at_zero() {
        let mut s = TuiState::default();
        s.pane = Pane::List;
        s.install_hits(fresh_hits(3));
        s.cursor = 1;
        s.apply(Action::Up);
        s.apply(Action::Up);
        assert_eq!(s.cursor, 0);
    }

    #[test]
    fn list_pane_pagedown_jumps_ten() {
        let mut s = TuiState::default();
        s.pane = Pane::List;
        s.install_hits(fresh_hits(20));
        s.apply(Action::PageDown);
        assert_eq!(s.cursor, 10);
    }

    #[test]
    fn toggle_mode_emits_run_search_and_flips() {
        let mut s = TuiState::default();
        s.pane = Pane::List;
        let e = s.apply(Action::ToggleMode);
        assert_eq!(s.mode, SearchMode::Graph);
        assert_eq!(e, Effect::RunSearch);
    }

    #[test]
    fn quit_emits_quit_regardless_of_pane() {
        for pane in [Pane::Search, Pane::List] {
            let mut s = TuiState::default();
            s.pane = pane;
            assert_eq!(s.apply(Action::Quit), Effect::Quit);
        }
    }

    #[test]
    fn focus_search_from_list_switches_pane() {
        let mut s = TuiState::default();
        s.pane = Pane::List;
        s.apply(Action::FocusSearch);
        assert_eq!(s.pane, Pane::Search);
    }

    #[test]
    fn install_hits_clamps_cursor() {
        let mut s = TuiState::default();
        s.cursor = 50;
        s.install_hits(fresh_hits(3));
        assert!(s.cursor < 3);
    }

    #[test]
    fn install_hits_resets_cursor_when_empty() {
        let mut s = TuiState::default();
        s.cursor = 50;
        s.install_hits(Vec::new());
        assert_eq!(s.cursor, 0);
    }

    #[test]
    fn selected_returns_current_hit() {
        let mut s = TuiState::default();
        s.install_hits(fresh_hits(3));
        s.cursor = 1;
        assert_eq!(s.selected().unwrap().file, "f1.md");
    }

    #[test]
    fn selected_returns_none_when_empty() {
        let s = TuiState::default();
        assert!(s.selected().is_none());
    }

    #[test]
    fn list_pane_keys_noop_when_no_hits() {
        let mut s = TuiState::default();
        s.pane = Pane::List;
        s.apply(Action::Down);
        s.apply(Action::PageDown);
        s.apply(Action::Up);
        assert_eq!(s.cursor, 0);
    }

    #[test]
    fn search_mode_default_is_flat() {
        assert_eq!(TuiState::default().mode, SearchMode::Flat);
    }
}
