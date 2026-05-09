//! aim-ast-verify — AST-based fact verification for AIM outputs.
//!
//! Port of `agents/ast_verify.py`. Three classes of claim that regex
//! auto-verify cannot catch on its own:
//!
//! 1. **SYMBOL-AT-LINE** — `score_decision @ kernel.py:294` — the line
//!    exists, but what is *actually* defined there?
//! 2. **NEGATIVE-CALL** — `evaluate_l_consent has 0 external callers` —
//!    easy to assert, easy to be wrong.
//! 3. **NUMERICAL** — `32 @register_tool` — count, compare. (Out of scope
//!    for this port — handled by aim-citation-linter / aim-deadline-scanner
//!    where applicable.)
//!
//! Implementation: regex-based scan of Python source. We intentionally do NOT
//! depend on a full Python parser — top-level statements (`def`/`class`/
//! `async def`/`X = …`) are anchored at column 0, which a precise regex set
//! handles correctly. This matches the original module's intent, which only
//! walks `tree.body` (top-level), not nested defs.
//!
//! ## Public API
//! - [`def_at`] — what symbol is defined at file:line?
//! - [`find_callers`] — every `name(...)` or `obj.name(...)` call site
//! - [`extract_claims`] — pull AST-checkable claims from free-form text
//! - [`verify_claims`] — scan claims + return [`AstReport`]

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AstError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SymbolKind {
    Def,
    AsyncDef,
    Class,
    Const,
    Import,
}

impl SymbolKind {
    pub fn as_str(self) -> &'static str {
        match self {
            SymbolKind::Def => "def",
            SymbolKind::AsyncDef => "async_def",
            SymbolKind::Class => "class",
            SymbolKind::Const => "const",
            SymbolKind::Import => "import",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SymbolInfo {
    pub name: String,
    pub kind: SymbolKind,
    pub lineno: u32,     // 1-based start
    pub end_lineno: u32, // 1-based inclusive end
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Caller {
    pub file: String,
    pub lineno: u32,
}

// ── Regex bank ───────────────────────────────────────────────────────────

static DEF_RE: OnceLock<Regex> = OnceLock::new();
static ASYNC_DEF_RE: OnceLock<Regex> = OnceLock::new();
static CLASS_RE: OnceLock<Regex> = OnceLock::new();
static CONST_RE: OnceLock<Regex> = OnceLock::new();
static IMPORT_RE: OnceLock<Regex> = OnceLock::new();
static FROM_IMPORT_RE: OnceLock<Regex> = OnceLock::new();
static CALL_RE: OnceLock<Regex> = OnceLock::new();

fn def_re() -> &'static Regex {
    DEF_RE.get_or_init(|| Regex::new(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)").unwrap())
}
fn async_def_re() -> &'static Regex {
    ASYNC_DEF_RE.get_or_init(|| Regex::new(r"^async\s+def\s+([A-Za-z_][A-Za-z0-9_]*)").unwrap())
}
fn class_re() -> &'static Regex {
    CLASS_RE.get_or_init(|| Regex::new(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)").unwrap())
}
fn const_re() -> &'static Regex {
    CONST_RE
        .get_or_init(|| Regex::new(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?\s*=\s*").unwrap())
}
fn import_re() -> &'static Regex {
    IMPORT_RE.get_or_init(|| Regex::new(r"^import\s+([A-Za-z_][A-Za-z0-9_.]*)").unwrap())
}
fn from_import_re() -> &'static Regex {
    FROM_IMPORT_RE.get_or_init(|| {
        Regex::new(r"^from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\s+(.+)$").unwrap()
    })
}
fn call_re() -> &'static Regex {
    // Match `<name>(` or `obj.<name>(` — captures the name. Allow `.` as a
    // legal preceding char so attribute calls (`obj.alpha(`) are seen.
    CALL_RE.get_or_init(|| Regex::new(r"(?:^|[^A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*\(").unwrap())
}

fn line_is_definition(line: &str, name: &str) -> bool {
    let trimmed = line.trim_start();
    let prefixes = [
        format!("def {name}("),
        format!("def {name} ("),
        format!("async def {name}("),
        format!("async def {name} ("),
        format!("class {name}("),
        format!("class {name} "),
        format!("class {name}:"),
    ];
    prefixes.iter().any(|p| trimmed.starts_with(p.as_str()))
}

// ── helpers ──────────────────────────────────────────────────────────────

/// Scan top-level Python statements, yielding `(SymbolInfo, line_index_0_based)`
/// for each `def`/`async def`/`class`/`X =`/`import`/`from ... import ...`.
fn iter_top_level<'a>(source: &'a str) -> Vec<SymbolInfo> {
    let lines: Vec<&'a str> = source.lines().collect();
    let mut out = Vec::new();
    let mut i = 0usize;
    let mut in_block: Option<u32> = None; // line indentation depth of current block being skipped
    while i < lines.len() {
        let raw = lines[i];
        // Track multi-line block bodies — skip any line that's indented (col 0 not start of code).
        if let Some(depth) = in_block {
            // Stay in block until we reach a non-blank line that is NOT indented.
            if raw.trim().is_empty() {
                i += 1;
                continue;
            }
            // First non-indented line ends the block (no need to re-process here:
            // fall through to the col-0 detection below)
            let leading = raw.chars().take_while(|c| *c == ' ' || *c == '\t').count() as u32;
            if leading <= depth.saturating_sub(1) || leading == 0 {
                in_block = None;
            } else {
                i += 1;
                continue;
            }
        }
        let line = raw;
        // Only top-level: must start at column 0 (no leading whitespace).
        if line.starts_with(' ') || line.starts_with('\t') {
            i += 1;
            continue;
        }
        let lineno = (i + 1) as u32;

        if let Some(c) = async_def_re().captures(line) {
            let name = c.get(1).unwrap().as_str().to_string();
            let end = block_end(&lines, i);
            out.push(SymbolInfo {
                name,
                kind: SymbolKind::AsyncDef,
                lineno,
                end_lineno: end,
            });
            in_block = Some(1);
            i += 1;
            continue;
        }
        if let Some(c) = def_re().captures(line) {
            let name = c.get(1).unwrap().as_str().to_string();
            let end = block_end(&lines, i);
            out.push(SymbolInfo {
                name,
                kind: SymbolKind::Def,
                lineno,
                end_lineno: end,
            });
            in_block = Some(1);
            i += 1;
            continue;
        }
        if let Some(c) = class_re().captures(line) {
            let name = c.get(1).unwrap().as_str().to_string();
            let end = block_end(&lines, i);
            out.push(SymbolInfo {
                name,
                kind: SymbolKind::Class,
                lineno,
                end_lineno: end,
            });
            in_block = Some(1);
            i += 1;
            continue;
        }
        if let Some(c) = const_re().captures(line) {
            let name = c.get(1).unwrap().as_str().to_string();
            // Constants stretch through any continuation/parenthesised RHS
            let end = const_end(&lines, i);
            out.push(SymbolInfo {
                name,
                kind: SymbolKind::Const,
                lineno,
                end_lineno: end,
            });
            i = end as usize;
            continue;
        }
        if let Some(c) = import_re().captures(line) {
            let name = c.get(1).unwrap().as_str().to_string();
            out.push(SymbolInfo {
                name,
                kind: SymbolKind::Import,
                lineno,
                end_lineno: lineno,
            });
            i += 1;
            continue;
        }
        if let Some(c) = from_import_re().captures(line) {
            let names = c.get(2).unwrap().as_str();
            let label = names
                .split(',')
                .map(|s| {
                    let s = s.trim();
                    let parts: Vec<&str> = s.split_whitespace().collect();
                    if parts.len() >= 3 && parts[1] == "as" {
                        parts[2].to_string()
                    } else {
                        parts.first().map(|x| x.trim_end_matches(',').to_string()).unwrap_or_default()
                    }
                })
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join(", ");
            out.push(SymbolInfo {
                name: if label.is_empty() {
                    "import".into()
                } else {
                    label
                },
                kind: SymbolKind::Import,
                lineno,
                end_lineno: lineno,
            });
            i += 1;
            continue;
        }
        i += 1;
    }
    out
}

fn block_end(lines: &[&str], start: usize) -> u32 {
    // Walk forward until we find a line at column 0 (or EOF)
    let mut end = start;
    let mut j = start + 1;
    while j < lines.len() {
        let l = lines[j];
        if l.trim().is_empty() {
            j += 1;
            continue;
        }
        if !(l.starts_with(' ') || l.starts_with('\t')) {
            break;
        }
        end = j;
        j += 1;
    }
    (end + 1) as u32
}

/// For `X = ...`, the assignment may span multiple lines if the RHS is a
/// parenthesised expression. We track `(`/`[`/`{` depth.
fn const_end(lines: &[&str], start: usize) -> u32 {
    let mut depth: i32 = 0;
    let mut end = start;
    for (j, l) in lines.iter().enumerate().skip(start) {
        for c in l.chars() {
            match c {
                '(' | '[' | '{' => depth += 1,
                ')' | ']' | '}' => depth -= 1,
                _ => {}
            }
        }
        end = j;
        // Continuation backslash extends to the next line
        let trimmed = l.trim_end();
        let cont = trimmed.ends_with('\\');
        if depth <= 0 && !cont {
            break;
        }
    }
    (end + 1) as u32
}

// ── public ───────────────────────────────────────────────────────────────

/// Return the top-level symbol whose body covers `line` in `file`.
/// 1-based line numbers; mirrors the Python source.
pub fn def_at<P: AsRef<Path>>(file: P, line: u32) -> Option<SymbolInfo> {
    let path = file.as_ref();
    if !path.is_file() {
        return None;
    }
    let src = std::fs::read_to_string(path).ok()?;
    for sym in iter_top_level(&src) {
        if sym.lineno <= line && line <= sym.end_lineno {
            return Some(sym);
        }
    }
    None
}

#[derive(Debug, Clone)]
pub struct CallerSearchOpts {
    pub exclude_dirs: Vec<String>,
}

impl Default for CallerSearchOpts {
    fn default() -> Self {
        Self {
            exclude_dirs: vec![
                "_archive".into(),
                ".bak".into(),
                "__pycache__".into(),
                "venv".into(),
                ".venv".into(),
                "site-packages".into(),
                "node_modules".into(),
                ".git".into(),
                "target".into(),
            ],
        }
    }
}

pub fn find_callers<P: AsRef<Path>>(
    name: &str,
    search_root: P,
    opts: &CallerSearchOpts,
) -> Vec<Caller> {
    let mut out = Vec::new();
    let root = search_root.as_ref();
    if !root.exists() {
        return out;
    }
    for entry in walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|e| {
            !e.path()
                .components()
                .any(|c| match c {
                    std::path::Component::Normal(s) => s
                        .to_str()
                        .map(|s| opts.exclude_dirs.iter().any(|d| d == s))
                        .unwrap_or(false),
                    _ => false,
                })
        })
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        let p = entry.path();
        if !p.is_file() || p.extension().and_then(|s| s.to_str()) != Some("py") {
            continue;
        }
        let src = match std::fs::read_to_string(p) {
            Ok(s) => s,
            Err(_) => continue,
        };
        for (i, line) in src.lines().enumerate() {
            // Skip pure comments & string-only lines
            let trimmed = line.trim_start();
            if trimmed.starts_with('#') {
                continue;
            }
            // The line that *defines* `name` is not a call site of it.
            if line_is_definition(line, name) {
                continue;
            }
            for cap in call_re().captures_iter(line) {
                let m = cap.get(1).unwrap().as_str();
                if m == name {
                    out.push(Caller {
                        file: p.to_string_lossy().to_string(),
                        lineno: (i + 1) as u32,
                    });
                }
            }
        }
    }
    out
}

// ── claim extraction ─────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AstClaimKind {
    SymbolAtLine,
    NegativeCall,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstClaim {
    pub kind: AstClaimKind,
    pub symbol: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>,
    pub raw: String,
}

static SYMBOL_AT_LINE: OnceLock<Regex> = OnceLock::new();
static DEF_AT_LINE: OnceLock<Regex> = OnceLock::new();
static NEGATIVE_CALL_RU: OnceLock<Regex> = OnceLock::new();
static NEGATIVE_CALL_EN: OnceLock<Regex> = OnceLock::new();

fn symbol_at_line() -> &'static Regex {
    SYMBOL_AT_LINE.get_or_init(|| {
        Regex::new(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*@\s*([\w./\-]+\.py):(\d{1,7})\b").unwrap()
    })
}
fn def_at_line_re() -> &'static Regex {
    DEF_AT_LINE.get_or_init(|| {
        Regex::new(
            r"\b([\w./\-]+\.py):(\d{1,7})\s+(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]{2,})",
        )
        .unwrap()
    })
}
fn negative_call_ru() -> &'static Regex {
    NEGATIVE_CALL_RU.get_or_init(|| {
        Regex::new(
            r"(?i)([A-Za-z_][A-Za-z0-9_]{3,}).{0,80}?(?:нет|0|без)\s+(?:внеш\w*\s+)?(?:вызов\w*|call\w*)",
        )
        .unwrap()
    })
}
fn negative_call_en() -> &'static Regex {
    NEGATIVE_CALL_EN.get_or_init(|| {
        Regex::new(
            r"(?i)([A-Za-z_][A-Za-z0-9_]{3,}).{0,80}?(?:no|zero|0)\s+(?:external\s+)?caller",
        )
        .unwrap()
    })
}

const CLAIM_FALSE_POSITIVES: &[&str] = &["нет", "no", "the", "and", "или"];

pub fn extract_claims(text: &str) -> Vec<AstClaim> {
    let mut out = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    let mut push = |claim: AstClaim, key: String| {
        if seen.insert(key) {
            out.push(claim);
        }
    };

    for m in symbol_at_line().captures_iter(text) {
        let sym = m.get(1).unwrap().as_str().to_string();
        let path = m.get(2).unwrap().as_str().to_string();
        let line: u32 = m.get(3).unwrap().as_str().parse().unwrap_or(0);
        let raw = m.get(0).unwrap().as_str().to_string();
        let key = format!("sl|{sym}|{path}|{line}");
        push(
            AstClaim {
                kind: AstClaimKind::SymbolAtLine,
                symbol: sym,
                file: Some(path),
                line: Some(line),
                raw,
            },
            key,
        );
    }
    for m in def_at_line_re().captures_iter(text) {
        let path = m.get(1).unwrap().as_str().to_string();
        let line: u32 = m.get(2).unwrap().as_str().parse().unwrap_or(0);
        let sym = m.get(3).unwrap().as_str().to_string();
        let raw = m.get(0).unwrap().as_str().to_string();
        let key = format!("sl|{sym}|{path}|{line}");
        push(
            AstClaim {
                kind: AstClaimKind::SymbolAtLine,
                symbol: sym,
                file: Some(path),
                line: Some(line),
                raw,
            },
            key,
        );
    }
    for re in [negative_call_ru(), negative_call_en()] {
        for m in re.captures_iter(text) {
            let sym = m.get(1).unwrap().as_str().to_string();
            if CLAIM_FALSE_POSITIVES.contains(&sym.to_lowercase().as_str()) {
                continue;
            }
            let raw = m.get(0).unwrap().as_str().to_string();
            let key = format!("nc|{sym}");
            push(
                AstClaim {
                    kind: AstClaimKind::NegativeCall,
                    symbol: sym,
                    file: None,
                    line: None,
                    raw,
                },
                key,
            );
        }
    }
    out
}

// ── verify driver ────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AstReport {
    pub total: u32,
    pub ok: u32,
    pub bad: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct VerifyOpts {
    pub base_dirs: Vec<PathBuf>,
    pub subdirs: Vec<String>,
}

impl VerifyOpts {
    pub fn from_root(search_root: &Path) -> Self {
        let mut base_dirs = vec![search_root.to_path_buf()];
        if let Some(p) = search_root.parent() {
            base_dirs.push(p.to_path_buf());
        }
        Self {
            base_dirs,
            subdirs: vec![
                "agents".into(),
                "tools".into(),
                "tests".into(),
                "scripts".into(),
                "web".into(),
                "cli".into(),
            ],
        }
    }
}

pub fn verify_claims(text: &str, search_root: &Path, opts: &VerifyOpts) -> AstReport {
    let mut rep = AstReport::default();
    let claims = extract_claims(text);
    if claims.is_empty() {
        return rep;
    }
    let resolve = |raw: &str| -> Option<PathBuf> {
        let p = PathBuf::from(raw);
        if p.is_absolute() {
            return if p.is_file() { Some(p) } else { None };
        }
        for b in &opts.base_dirs {
            let cand = b.join(&p);
            if cand.is_file() {
                return Some(cand);
            }
        }
        if p.parent().map(|q| q.as_os_str().is_empty()).unwrap_or(true) {
            for b in &opts.base_dirs {
                for s in &opts.subdirs {
                    let cand = b.join(s).join(&p);
                    if cand.is_file() {
                        return Some(cand);
                    }
                }
            }
        }
        None
    };

    let caller_opts = CallerSearchOpts::default();

    for c in claims {
        rep.total += 1;
        match c.kind {
            AstClaimKind::SymbolAtLine => {
                let f = match resolve(c.file.as_deref().unwrap_or("")) {
                    Some(p) => p,
                    None => {
                        rep.bad.push(format!("{}: file not found", c.raw));
                        continue;
                    }
                };
                let sym = match def_at(&f, c.line.unwrap_or(0)) {
                    Some(s) => s,
                    None => {
                        rep.bad
                            .push(format!("{}: no symbol at line {}", c.raw, c.line.unwrap_or(0)));
                        continue;
                    }
                };
                if sym.name != c.symbol {
                    rep.bad.push(format!(
                        "{}: line {} actually defines {} '{}', not '{}'",
                        c.raw,
                        c.line.unwrap_or(0),
                        sym.kind.as_str(),
                        sym.name,
                        c.symbol
                    ));
                    continue;
                }
                rep.ok += 1;
            }
            AstClaimKind::NegativeCall => {
                let callers = find_callers(&c.symbol, search_root, &caller_opts);
                if !callers.is_empty() {
                    let where_: Vec<String> = callers
                        .iter()
                        .take(5)
                        .map(|x| {
                            let name = Path::new(&x.file)
                                .file_name()
                                .and_then(|s| s.to_str())
                                .unwrap_or("?");
                            format!("{}:{}", name, x.lineno)
                        })
                        .collect();
                    rep.bad.push(format!(
                        "claimed '{}' has 0 callers but found {} ({})",
                        c.symbol,
                        callers.len(),
                        where_.join(", ")
                    ));
                    continue;
                }
                rep.ok += 1;
            }
        }
    }
    rep
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write_py(dir: &TempDir, rel: &str, body: &str) -> PathBuf {
        let p = dir.path().join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn iter_top_level_finds_def() {
        let src = "def alpha():\n    return 1\n\ndef beta():\n    return 2\n";
        let syms = iter_top_level(src);
        assert_eq!(syms.len(), 2);
        assert_eq!(syms[0].name, "alpha");
        assert_eq!(syms[0].kind, SymbolKind::Def);
        assert_eq!(syms[0].lineno, 1);
        assert_eq!(syms[1].name, "beta");
        assert_eq!(syms[1].lineno, 4);
    }

    #[test]
    fn iter_top_level_finds_async_def_and_class() {
        let src = "async def fetch():\n    pass\n\nclass Foo:\n    x = 1\n";
        let syms = iter_top_level(src);
        assert_eq!(syms.len(), 2);
        assert_eq!(syms[0].kind, SymbolKind::AsyncDef);
        assert_eq!(syms[0].name, "fetch");
        assert_eq!(syms[1].kind, SymbolKind::Class);
        assert_eq!(syms[1].name, "Foo");
    }

    #[test]
    fn iter_top_level_finds_const_and_imports() {
        let src = "import os\nfrom pathlib import Path, PurePath as PP\nROOT = '/tmp'\n";
        let syms = iter_top_level(src);
        let names: Vec<&str> = syms.iter().map(|s| s.name.as_str()).collect();
        assert!(names.contains(&"os"));
        assert!(syms.iter().any(|s| s.name.contains("Path") && matches!(s.kind, SymbolKind::Import)));
        assert!(syms.iter().any(|s| s.name == "ROOT" && matches!(s.kind, SymbolKind::Const)));
    }

    #[test]
    fn def_at_returns_top_level_symbol() {
        let dir = TempDir::new().unwrap();
        let path = write_py(
            &dir,
            "k.py",
            "def alpha():\n    return 1\n\ndef beta():\n    return 2\n",
        );
        let s = def_at(&path, 5).expect("must find beta");
        assert_eq!(s.name, "beta");
        assert_eq!(s.kind, SymbolKind::Def);
    }

    #[test]
    fn def_at_returns_none_for_blank_line() {
        let dir = TempDir::new().unwrap();
        let path = write_py(&dir, "k.py", "def alpha():\n    return 1\n");
        // Line 999 is past EOF
        assert!(def_at(&path, 999).is_none());
    }

    #[test]
    fn def_at_handles_missing_file() {
        let dir = TempDir::new().unwrap();
        assert!(def_at(dir.path().join("nope.py"), 1).is_none());
    }

    #[test]
    fn find_callers_matches_name_and_attribute() {
        let dir = TempDir::new().unwrap();
        write_py(
            &dir,
            "a.py",
            "def alpha(): return 1\n\nresult = alpha()\nobj.alpha()\n",
        );
        write_py(&dir, "_archive/skip.py", "alpha()\n");
        let callers = find_callers("alpha", dir.path(), &CallerSearchOpts::default());
        assert!(callers.iter().any(|c| c.lineno == 3));
        assert!(callers.iter().any(|c| c.lineno == 4));
        // Excluded dir must not appear
        assert!(callers.iter().all(|c| !c.file.contains("_archive")));
    }

    #[test]
    fn find_callers_skips_comments() {
        let dir = TempDir::new().unwrap();
        write_py(&dir, "a.py", "# alpha()\nresult = alpha()\n");
        let callers = find_callers("alpha", dir.path(), &CallerSearchOpts::default());
        assert_eq!(callers.len(), 1);
        assert_eq!(callers[0].lineno, 2);
    }

    #[test]
    fn extract_claims_symbol_at_line() {
        let text = "score_decision @ kernel.py:294 — fine.";
        let claims = extract_claims(text);
        assert_eq!(claims.len(), 1);
        assert_eq!(claims[0].kind, AstClaimKind::SymbolAtLine);
        assert_eq!(claims[0].symbol, "score_decision");
        assert_eq!(claims[0].file.as_deref(), Some("kernel.py"));
        assert_eq!(claims[0].line, Some(294));
    }

    #[test]
    fn extract_claims_def_at_line_alt_form() {
        let text = "see kernel.py:294 def score_decision";
        let claims = extract_claims(text);
        assert_eq!(claims.len(), 1);
        assert_eq!(claims[0].symbol, "score_decision");
    }

    #[test]
    fn extract_claims_dedups_overlapping_forms() {
        let text = "score_decision @ kernel.py:294 and kernel.py:294 def score_decision";
        let claims = extract_claims(text);
        assert_eq!(claims.len(), 1);
    }

    #[test]
    fn extract_claims_negative_call_ru() {
        let text = "evaluate_l_consent: нет внешних вызовов";
        let claims = extract_claims(text);
        assert!(claims.iter().any(|c| {
            c.kind == AstClaimKind::NegativeCall && c.symbol == "evaluate_l_consent"
        }));
    }

    #[test]
    fn extract_claims_negative_call_en() {
        let text = "evaluate_l_consent has 0 external callers";
        let claims = extract_claims(text);
        assert!(claims.iter().any(|c| {
            c.kind == AstClaimKind::NegativeCall && c.symbol == "evaluate_l_consent"
        }));
    }

    #[test]
    fn verify_claims_passes_when_symbol_correct() {
        let dir = TempDir::new().unwrap();
        write_py(&dir, "kernel.py", "def alpha():\n    return 1\n\ndef beta():\n    return 2\n");
        let opts = VerifyOpts::from_root(dir.path());
        let r = verify_claims("alpha @ kernel.py:1 is the entry point", dir.path(), &opts);
        assert_eq!(r.total, 1);
        assert_eq!(r.ok, 1);
        assert!(r.bad.is_empty());
    }

    #[test]
    fn verify_claims_catches_wrong_symbol() {
        let dir = TempDir::new().unwrap();
        write_py(&dir, "kernel.py", "def alpha():\n    return 1\n\ndef beta():\n    return 2\n");
        let opts = VerifyOpts::from_root(dir.path());
        let r = verify_claims("score_decision @ kernel.py:1", dir.path(), &opts);
        assert_eq!(r.total, 1);
        assert_eq!(r.ok, 0);
        assert_eq!(r.bad.len(), 1);
        assert!(r.bad[0].contains("alpha"));
    }

    #[test]
    fn verify_claims_negative_call_with_actual_callers_fails() {
        let dir = TempDir::new().unwrap();
        write_py(&dir, "kernel.py", "def evaluate_l_consent(): pass\n");
        write_py(&dir, "use.py", "result = evaluate_l_consent()\n");
        let opts = VerifyOpts::from_root(dir.path());
        let r = verify_claims(
            "evaluate_l_consent has 0 external callers",
            dir.path(),
            &opts,
        );
        assert_eq!(r.ok, 0);
        assert!(!r.bad.is_empty());
    }

    #[test]
    fn verify_claims_negative_call_when_truly_unused_passes() {
        let dir = TempDir::new().unwrap();
        write_py(&dir, "kernel.py", "def evaluate_l_consent(): pass\n");
        let opts = VerifyOpts::from_root(dir.path());
        let r = verify_claims(
            "evaluate_l_consent has 0 external callers",
            dir.path(),
            &opts,
        );
        assert_eq!(r.ok, 1);
        assert!(r.bad.is_empty());
    }

    #[test]
    fn verify_claims_resolves_relative_via_subdirs() {
        let dir = TempDir::new().unwrap();
        write_py(&dir, "agents/x.py", "def helper(): pass\n");
        let opts = VerifyOpts::from_root(dir.path());
        let r = verify_claims("helper @ x.py:1", dir.path(), &opts);
        assert_eq!(r.ok, 1, "report: {:?}", r);
    }
}
