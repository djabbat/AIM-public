//! aim-ui-theme — Claude Code-inspired CLI palette, inverted to cool/cyan.
//!
//! Port of `agents/ui_theme.py`. The Python original wraps `rich` for
//! actual rendering. The Rust port exports the **palette + icon + style
//! map** so binaries using `crossterm` / `ratatui` (or any other TUI
//! crate) consume the same colors as the Python reference.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

// ── palette (verbatim hex from Python) ─────────────────────────────────────

pub mod palette {
    pub const BG: &str = "#0A0F1E";
    pub const SURFACE: &str = "#16213E";
    pub const BORDER: &str = "#1F3A68";

    pub const PRIMARY: &str = "#00D9FF";
    pub const PRIMARY_DIM: &str = "#0099BB";
    pub const ACCENT: &str = "#4A9EFF";
    pub const HIGHLIGHT: &str = "#80E5FF";

    pub const SUCCESS: &str = "#4AFF91";
    pub const WARNING: &str = "#80B0FF";
    pub const DANGER: &str = "#FF6B8A";
    pub const INFO: &str = "#A6C8FF";

    pub const TEXT: &str = "#E8F0FF";
    pub const DIM: &str = "#7A8AA0";
    pub const SUBTLE: &str = "#54657A";

    pub const USER: &str = "#80E5FF";
    pub const ASSISTANT: &str = "#E8F0FF";
    pub const SYSTEM: &str = "#7A8AA0";
    pub const TOOL: &str = "#4A9EFF";
    pub const PROCESS: &str = "#00D9FF";
}

// ── icons ──────────────────────────────────────────────────────────────────

pub mod icon {
    pub const USER: &str = "›";
    pub const ASSISTANT: &str = "✦";
    pub const TOOL: &str = "⚙";
    pub const PROCESS: &str = "⟳";
    pub const SUCCESS: &str = "✓";
    pub const WARNING: &str = "⚠";
    pub const ERROR: &str = "✗";
    pub const INFO: &str = "ℹ";
    pub const BULLET: &str = "•";
    pub const ARROW_R: &str = "→";
    pub const DIVIDER: &str = "─";
}

// ── semantic style ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Style {
    pub color: String,
    pub bold: bool,
}

impl Style {
    pub fn plain(color: &str) -> Self {
        Self {
            color: color.into(),
            bold: false,
        }
    }
    pub fn bold(color: &str) -> Self {
        Self {
            color: color.into(),
            bold: true,
        }
    }

    /// Render the style as a Rich-compatible string (`"bold #RRGGBB"` or
    /// `"#RRGGBB"`). Useful when a Python `rich`-driven binary consumes
    /// our palette via shell.
    pub fn rich_string(&self) -> String {
        if self.bold {
            format!("bold {}", self.color)
        } else {
            self.color.clone()
        }
    }
}

/// Map of semantic style names → palette entries. Mirrors `_RICH_STYLES`.
pub fn style_map() -> BTreeMap<&'static str, Style> {
    let mut m = BTreeMap::new();
    m.insert("primary", Style::plain(palette::PRIMARY));
    m.insert("accent", Style::plain(palette::ACCENT));
    m.insert("highlight", Style::plain(palette::HIGHLIGHT));
    m.insert("success", Style::plain(palette::SUCCESS));
    m.insert("warning", Style::plain(palette::WARNING));
    m.insert("danger", Style::plain(palette::DANGER));
    m.insert("info", Style::plain(palette::INFO));
    m.insert("dim", Style::plain(palette::DIM));
    m.insert("subtle", Style::plain(palette::SUBTLE));
    m.insert("text", Style::plain(palette::TEXT));
    m.insert("user", Style::plain(palette::USER));
    m.insert("assistant", Style::plain(palette::ASSISTANT));
    m.insert("system", Style::plain(palette::SYSTEM));
    m.insert("tool", Style::bold(palette::TOOL));
    m.insert("process", Style::bold(palette::PROCESS));
    m
}

pub fn lookup(name: &str) -> Option<Style> {
    style_map().get(name).cloned()
}

// ── ANSI helpers ───────────────────────────────────────────────────────────

/// Convert `#RRGGBB` to `(r, g, b)` triple. Returns `None` on bad input.
pub fn parse_hex(hex: &str) -> Option<(u8, u8, u8)> {
    let h = hex.strip_prefix('#')?;
    if h.len() != 6 {
        return None;
    }
    let r = u8::from_str_radix(&h[0..2], 16).ok()?;
    let g = u8::from_str_radix(&h[2..4], 16).ok()?;
    let b = u8::from_str_radix(&h[4..6], 16).ok()?;
    Some((r, g, b))
}

/// Build an ANSI 24-bit (truecolor) escape sequence for the foreground.
/// Production binaries can wrap their text: `format!("{}{}{}", ansi_fg(c), text, ansi_reset())`.
pub fn ansi_fg(hex: &str) -> String {
    match parse_hex(hex) {
        Some((r, g, b)) => format!("\x1b[38;2;{};{};{}m", r, g, b),
        None => String::new(),
    }
}

pub fn ansi_reset() -> &'static str {
    "\x1b[0m"
}

pub fn ansi_bold() -> &'static str {
    "\x1b[1m"
}

pub fn render_styled(style: &Style, text: &str) -> String {
    let bold_prefix = if style.bold { ansi_bold() } else { "" };
    format!(
        "{}{}{}{}",
        bold_prefix,
        ansi_fg(&style.color),
        text,
        ansi_reset()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── palette ────────────────────────────────────────────────────────────

    #[test]
    fn palette_constants_match_python() {
        assert_eq!(palette::PRIMARY, "#00D9FF");
        assert_eq!(palette::SUCCESS, "#4AFF91");
        assert_eq!(palette::DANGER, "#FF6B8A");
        assert_eq!(palette::TEXT, "#E8F0FF");
    }

    #[test]
    fn palette_all_entries_well_formed_hex() {
        let entries = [
            palette::BG, palette::SURFACE, palette::BORDER,
            palette::PRIMARY, palette::PRIMARY_DIM, palette::ACCENT, palette::HIGHLIGHT,
            palette::SUCCESS, palette::WARNING, palette::DANGER, palette::INFO,
            palette::TEXT, palette::DIM, palette::SUBTLE,
            palette::USER, palette::ASSISTANT, palette::SYSTEM, palette::TOOL, palette::PROCESS,
        ];
        for e in entries {
            assert!(parse_hex(e).is_some(), "bad hex: {}", e);
        }
    }

    // ── icons ──────────────────────────────────────────────────────────────

    #[test]
    fn icons_match_python_glyphs() {
        assert_eq!(icon::USER, "›");
        assert_eq!(icon::ASSISTANT, "✦");
        assert_eq!(icon::SUCCESS, "✓");
        assert_eq!(icon::ERROR, "✗");
        assert_eq!(icon::WARNING, "⚠");
    }

    // ── style map ──────────────────────────────────────────────────────────

    #[test]
    fn style_map_includes_all_semantic_names() {
        let m = style_map();
        for name in [
            "primary", "accent", "highlight", "success", "warning",
            "danger", "info", "dim", "subtle", "text", "user",
            "assistant", "system", "tool", "process",
        ] {
            assert!(m.contains_key(name), "missing style: {}", name);
        }
    }

    #[test]
    fn tool_and_process_styles_are_bold() {
        let tool = lookup("tool").unwrap();
        let proc_ = lookup("process").unwrap();
        assert!(tool.bold);
        assert!(proc_.bold);
    }

    #[test]
    fn other_styles_are_not_bold() {
        let info = lookup("info").unwrap();
        assert!(!info.bold);
    }

    #[test]
    fn rich_string_format() {
        assert_eq!(Style::plain("#FFFFFF").rich_string(), "#FFFFFF");
        assert_eq!(Style::bold("#FFFFFF").rich_string(), "bold #FFFFFF");
    }

    #[test]
    fn lookup_unknown_returns_none() {
        assert!(lookup("nonexistent").is_none());
    }

    // ── parse_hex ──────────────────────────────────────────────────────────

    #[test]
    fn parse_hex_full_range() {
        assert_eq!(parse_hex("#000000"), Some((0, 0, 0)));
        assert_eq!(parse_hex("#FFFFFF"), Some((255, 255, 255)));
        assert_eq!(parse_hex("#80E5FF"), Some((0x80, 0xE5, 0xFF)));
    }

    #[test]
    fn parse_hex_rejects_bad_input() {
        assert!(parse_hex("ffffff").is_none()); // missing #
        assert!(parse_hex("#fff").is_none()); // 3-char short form not supported
        assert!(parse_hex("#GGGGGG").is_none()); // non-hex
        assert!(parse_hex("").is_none());
    }

    // ── ANSI rendering ─────────────────────────────────────────────────────

    #[test]
    fn ansi_fg_emits_truecolor_sequence() {
        assert_eq!(ansi_fg("#00D9FF"), "\x1b[38;2;0;217;255m");
    }

    #[test]
    fn ansi_fg_empty_for_bad_input() {
        assert_eq!(ansi_fg("not-hex"), "");
    }

    #[test]
    fn render_styled_wraps_text() {
        let style = Style::bold(palette::PRIMARY);
        let r = render_styled(&style, "hello");
        assert!(r.contains("\x1b[1m"));
        assert!(r.contains("\x1b[38;2;0;217;255m"));
        assert!(r.contains("hello"));
        assert!(r.ends_with("\x1b[0m"));
    }

    #[test]
    fn render_styled_no_bold_skips_bold_prefix() {
        let style = Style::plain(palette::TEXT);
        let r = render_styled(&style, "x");
        assert!(!r.starts_with("\x1b[1m"));
    }
}
