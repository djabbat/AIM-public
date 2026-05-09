//! aim-escalation — narrow DSL for project escalation rules (P6).
//!
//! Port of the rule-evaluation core of `agents/escalation_engine.py`. The
//! DSL is deliberately small and deterministic — no `eval()`, no LLM, no
//! arbitrary attribute access — so YAML rules in `projects/<name>.yaml`
//! become safe to execute at scheduler tick time.
//!
//! ## Grammar
//!
//! ```text
//! rule       := or_expr
//! or_expr    := and_expr ("or" and_expr)*
//! and_expr   := not_expr ("and" not_expr)*
//! not_expr   := "not" atom | atom
//! atom       := "(" or_expr ")" | comparison | value
//! comparison := value op value
//! op         := "==" | "!=" | "<" | "<=" | ">" | ">=" | "contains" | "in"
//! value      := number | string | identifier
//! identifier := name ("." name)*    (resolved against context)
//! ```
//!
//! Operators are left-associative, no precedence between `and` / `or` —
//! callers must use parentheses for unambiguous grouping (matches Python).
//!
//! ## Alert pipeline
//!
//! Each rule fires against a [`Context`] (e.g. one per milestone, one per
//! stakeholder). Matches go to a [`Dispatcher`] (Telegram, log, custom)
//! and are written to a JSONL audit log. Repeat alerts inside the
//! cooldown window are suppressed via SHA-1 fingerprint.

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum EscalationError {
    #[error("parse: {0}")]
    Parse(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

/// Loose typed value the DSL sees during evaluation.
#[derive(Debug, Clone)]
pub enum Value {
    None,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Value>),
}

impl Value {
    pub fn truthy(&self) -> bool {
        match self {
            Value::None => false,
            Value::Bool(b) => *b,
            Value::Int(n) => *n != 0,
            Value::Float(f) => *f != 0.0,
            Value::Str(s) => !s.is_empty(),
            Value::List(l) => !l.is_empty(),
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        if let Value::Str(s) = self {
            Some(s)
        } else {
            None
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(n) => Some(*n as f64),
            Value::Float(f) => Some(*f),
            _ => None,
        }
    }
}

impl PartialEq for Value {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Value::None, Value::None) => true,
            (Value::Bool(a), Value::Bool(b)) => a == b,
            (Value::Str(a), Value::Str(b)) => a == b,
            (Value::List(a), Value::List(b)) => a == b,
            (a, b) => match (a.as_f64(), b.as_f64()) {
                (Some(x), Some(y)) => x == y,
                _ => false,
            },
        }
    }
}

/// Map name → resolver. Each top-level identifier (e.g. `milestone`,
/// `stakeholder`, `project`) registers a `Resolver` that walks dotted
/// suffixes (`.criticality`, `.role`, …).
pub trait Resolver: Send + Sync {
    fn resolve(&self, path: &[&str]) -> Value;
}

/// Backed by `serde_json::Value` so callers can build contexts from any
/// JSON-shaped data.
pub struct JsonResolver(pub serde_json::Value);

impl Resolver for JsonResolver {
    fn resolve(&self, path: &[&str]) -> Value {
        let mut cur = &self.0;
        for p in path {
            match cur.get(p) {
                Some(v) => cur = v,
                None => return Value::None,
            }
        }
        json_to_value(cur)
    }
}

fn json_to_value(v: &serde_json::Value) -> Value {
    match v {
        serde_json::Value::Null => Value::None,
        serde_json::Value::Bool(b) => Value::Bool(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::Int(i)
            } else if let Some(f) = n.as_f64() {
                Value::Float(f)
            } else {
                Value::None
            }
        }
        serde_json::Value::String(s) => Value::Str(s.clone()),
        serde_json::Value::Array(arr) => Value::List(arr.iter().map(json_to_value).collect()),
        serde_json::Value::Object(_) => Value::None,
    }
}

#[derive(Default)]
pub struct Context {
    map: std::collections::HashMap<String, Box<dyn Resolver>>,
}

impl Context {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_json(mut self, name: impl Into<String>, value: serde_json::Value) -> Self {
        self.map
            .insert(name.into(), Box::new(JsonResolver(value)) as Box<dyn Resolver>);
        self
    }

    pub fn with_resolver(
        mut self,
        name: impl Into<String>,
        resolver: Box<dyn Resolver>,
    ) -> Self {
        self.map.insert(name.into(), resolver);
        self
    }

    /// Resolve a dotted identifier such as `milestone.criticality`.
    pub fn lookup(&self, dotted: &str) -> Value {
        let parts: Vec<&str> = dotted.split('.').collect();
        if parts.is_empty() {
            return Value::None;
        }
        if let Some(r) = self.map.get(parts[0]) {
            r.resolve(&parts[1..])
        } else {
            // Bare identifier inside a top-level resolver (e.g. when the
            // rule says `deadline_within_days <= 7` directly on the
            // milestone ctx).
            for r in self.map.values() {
                let v = r.resolve(&parts[..]);
                if !matches!(v, Value::None) {
                    return v;
                }
            }
            Value::None
        }
    }
}

// ── tokenizer ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
enum Tok {
    LParen,
    RParen,
    Op(String),
    Word(String), // and / or / not / contains / in / identifier / true / false
    Str(String),
    Int(i64),
    Float(f64),
}

fn tokenize(rule: &str) -> Result<Vec<Tok>, EscalationError> {
    let mut out = Vec::new();
    let bytes = rule.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        if c == '(' {
            out.push(Tok::LParen);
            i += 1;
            continue;
        }
        if c == ')' {
            out.push(Tok::RParen);
            i += 1;
            continue;
        }
        // 2-char operators
        if i + 1 < bytes.len() {
            let two = &rule[i..i + 2];
            if matches!(two, "==" | "!=" | "<=" | ">=") {
                out.push(Tok::Op(two.to_string()));
                i += 2;
                continue;
            }
        }
        if c == '<' || c == '>' {
            out.push(Tok::Op(c.to_string()));
            i += 1;
            continue;
        }
        // Strings
        if c == '\'' || c == '"' {
            let quote = c;
            i += 1;
            let start = i;
            while i < bytes.len() && bytes[i] as char != quote {
                i += 1;
            }
            if i >= bytes.len() {
                return Err(EscalationError::Parse(format!(
                    "unterminated string starting at byte {}",
                    start - 1
                )));
            }
            out.push(Tok::Str(rule[start..i].to_string()));
            i += 1; // closing quote
            continue;
        }
        // Numbers
        if c == '-' || c.is_ascii_digit() {
            // Disambiguate `-` as unary only when followed by a digit
            let mut j = i;
            if c == '-' {
                j += 1;
            }
            let mut saw_digit = false;
            let mut saw_dot = false;
            while j < bytes.len() {
                let cj = bytes[j] as char;
                if cj.is_ascii_digit() {
                    saw_digit = true;
                    j += 1;
                } else if cj == '.' && !saw_dot {
                    saw_dot = true;
                    j += 1;
                } else {
                    break;
                }
            }
            if saw_digit {
                let raw = &rule[i..j];
                if saw_dot {
                    out.push(Tok::Float(raw.parse().map_err(|e: std::num::ParseFloatError| {
                        EscalationError::Parse(e.to_string())
                    })?));
                } else {
                    out.push(Tok::Int(raw.parse().map_err(|e: std::num::ParseIntError| {
                        EscalationError::Parse(e.to_string())
                    })?));
                }
                i = j;
                continue;
            }
        }
        // Words: identifiers or keywords
        if c.is_ascii_alphabetic() || c == '_' {
            let start = i;
            while i < bytes.len() {
                let cj = bytes[i] as char;
                if cj.is_ascii_alphanumeric() || cj == '_' || cj == '.' {
                    i += 1;
                } else {
                    break;
                }
            }
            out.push(Tok::Word(rule[start..i].to_string()));
            continue;
        }
        return Err(EscalationError::Parse(format!(
            "unexpected character {:?} at byte {}",
            c, i
        )));
    }
    Ok(out)
}

// ── parser / evaluator ────────────────────────────────────────────────────

struct Parser<'a> {
    tokens: &'a [Tok],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(tokens: &'a [Tok]) -> Self {
        Self { tokens, pos: 0 }
    }

    fn peek(&self) -> Option<&Tok> {
        self.tokens.get(self.pos)
    }

    fn consume(&mut self) -> Option<Tok> {
        let t = self.tokens.get(self.pos).cloned();
        if t.is_some() {
            self.pos += 1;
        }
        t
    }

    fn parse_or(&mut self, ctx: &Context) -> Result<bool, EscalationError> {
        let mut left = self.parse_and(ctx)?;
        while matches!(self.peek(), Some(Tok::Word(w)) if w == "or") {
            self.consume();
            let right = self.parse_and(ctx)?;
            left = left || right;
        }
        Ok(left)
    }

    fn parse_and(&mut self, ctx: &Context) -> Result<bool, EscalationError> {
        let mut left = self.parse_not(ctx)?;
        while matches!(self.peek(), Some(Tok::Word(w)) if w == "and") {
            self.consume();
            let right = self.parse_not(ctx)?;
            left = left && right;
        }
        Ok(left)
    }

    fn parse_not(&mut self, ctx: &Context) -> Result<bool, EscalationError> {
        if matches!(self.peek(), Some(Tok::Word(w)) if w == "not") {
            self.consume();
            let inner = self.parse_atom(ctx)?;
            Ok(!truthy(&inner))
        } else {
            self.parse_atom(ctx).map(|v| truthy(&v))
        }
    }

    fn parse_atom(&mut self, ctx: &Context) -> Result<Value, EscalationError> {
        // Parenthesised group
        if matches!(self.peek(), Some(Tok::LParen)) {
            self.consume();
            let v = self.parse_or(ctx)?;
            if !matches!(self.peek(), Some(Tok::RParen)) {
                return Err(EscalationError::Parse("missing )".into()));
            }
            self.consume();
            return Ok(Value::Bool(v));
        }
        // value [op value]?
        let left_tok = self
            .consume()
            .ok_or_else(|| EscalationError::Parse("unexpected end".into()))?;
        let left = coerce(&left_tok, ctx);

        let op = match self.peek() {
            Some(Tok::Op(o)) => Some(o.clone()),
            Some(Tok::Word(w))
                if w == "contains" || w == "in" =>
            {
                Some(w.clone())
            }
            _ => None,
        };
        if let Some(op) = op {
            self.consume();
            let right_tok = self
                .consume()
                .ok_or_else(|| EscalationError::Parse("operand after operator".into()))?;
            let right = coerce(&right_tok, ctx);
            return Ok(Value::Bool(apply(&op, &left, &right)));
        }
        Ok(left)
    }
}

fn coerce(tok: &Tok, ctx: &Context) -> Value {
    match tok {
        Tok::Str(s) => Value::Str(s.clone()),
        Tok::Int(n) => Value::Int(*n),
        Tok::Float(f) => Value::Float(*f),
        Tok::Word(w) => match w.as_str() {
            "true" | "True" => Value::Bool(true),
            "false" | "False" => Value::Bool(false),
            _ => ctx.lookup(w),
        },
        _ => Value::None,
    }
}

fn apply(op: &str, l: &Value, r: &Value) -> bool {
    match op {
        "==" => l == r,
        "!=" => l != r,
        "<" => match (l.as_f64(), r.as_f64()) {
            (Some(a), Some(b)) => a < b,
            _ => false,
        },
        "<=" => match (l.as_f64(), r.as_f64()) {
            (Some(a), Some(b)) => a <= b,
            _ => false,
        },
        ">" => match (l.as_f64(), r.as_f64()) {
            (Some(a), Some(b)) => a > b,
            _ => false,
        },
        ">=" => match (l.as_f64(), r.as_f64()) {
            (Some(a), Some(b)) => a >= b,
            _ => false,
        },
        "contains" => {
            // Mirrors Python: `r in (l or "")`
            match (l, r) {
                (Value::Str(haystack), Value::Str(needle)) => haystack.contains(needle.as_str()),
                (Value::List(items), needle) => items.iter().any(|x| x == needle),
                _ => false,
            }
        }
        "in" => match (l, r) {
            (needle, Value::Str(haystack)) => match needle {
                Value::Str(s) => haystack.contains(s.as_str()),
                _ => false,
            },
            (needle, Value::List(items)) => items.iter().any(|x| x == needle),
            _ => false,
        },
        _ => false,
    }
}

fn truthy(v: &Value) -> bool {
    v.truthy()
}

/// Parse + evaluate a rule against a [`Context`]. Returns `Ok(false)` if
/// any side fails to resolve (mirrors Python — non-applicable contexts
/// silently produce False rather than raising).
pub fn evaluate_rule(rule: &str, ctx: &Context) -> Result<bool, EscalationError> {
    let tokens = tokenize(rule)?;
    if tokens.is_empty() {
        return Ok(false);
    }
    let mut p = Parser::new(&tokens);
    p.parse_or(ctx)
}

// ── Alert + audit ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Alert {
    pub project: String,
    pub rule: String,
    pub action: String,
    pub subject: String,
    pub detail: String,
    pub fingerprint: String,
}

impl Alert {
    pub fn to_text(&self) -> String {
        format!("⚠️ [{}] {} — {}", self.project, self.subject, self.detail)
    }
}

/// Pluggable side-effect handler. The default action is `telegram_alert`,
/// but custom dispatchers (log, webhook, queue) plug in via this trait.
pub trait Dispatcher: Send + Sync {
    fn dispatch(&self, alert: &Alert) -> Result<(), EscalationError>;
}

#[derive(Debug, Default)]
pub struct MemoryDispatcher {
    pub events: Mutex<Vec<Alert>>,
}

impl MemoryDispatcher {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn snapshot(&self) -> Vec<Alert> {
        self.events.lock().clone()
    }
}

impl Dispatcher for MemoryDispatcher {
    fn dispatch(&self, alert: &Alert) -> Result<(), EscalationError> {
        self.events.lock().push(alert.clone());
        Ok(())
    }
}

pub fn fingerprint(parts: &[&str]) -> String {
    let mut h = Sha1::new();
    h.update(parts.join(":").as_bytes());
    hex::encode(&h.finalize()[..6])
}

#[derive(Debug)]
pub struct AuditLog {
    path: PathBuf,
}

impl AuditLog {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    pub fn from_env() -> Self {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        let base = std::env::var("AIM_HOME")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".cache").join("aim"));
        Self::new(base.join("escalation.jsonl"))
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn append(&self, alert: &Alert, ts: DateTime<Utc>) -> Result<(), EscalationError> {
        if let Some(parent) = self.path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let entry = serde_json::json!({
            "ts": ts.to_rfc3339(),
            "project": alert.project,
            "rule": alert.rule,
            "action": alert.action,
            "subject": alert.subject,
            "detail": alert.detail,
            "fingerprint": alert.fingerprint,
        });
        let line = serde_json::to_string(&entry)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    pub fn was_recently_dispatched(
        &self,
        fp: &str,
        cutoff: DateTime<Utc>,
    ) -> Result<bool, EscalationError> {
        if !self.path.exists() {
            return Ok(false);
        }
        let raw = std::fs::read_to_string(&self.path)?;
        for line in raw.lines() {
            if line.is_empty() {
                continue;
            }
            let row: serde_json::Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(_) => continue,
            };
            if row.get("fingerprint").and_then(|v| v.as_str()) != Some(fp) {
                continue;
            }
            let ts_str = match row.get("ts").and_then(|v| v.as_str()) {
                Some(s) => s,
                None => continue,
            };
            let ts: DateTime<Utc> = match DateTime::parse_from_rfc3339(ts_str) {
                Ok(t) => t.with_timezone(&Utc),
                Err(_) => continue,
            };
            if ts >= cutoff {
                return Ok(true);
            }
        }
        Ok(false)
    }

    pub fn history(
        &self,
        project: Option<&str>,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, EscalationError> {
        if !self.path.exists() {
            return Ok(Vec::new());
        }
        let raw = std::fs::read_to_string(&self.path)?;
        let filtered: Vec<serde_json::Value> = raw
            .lines()
            .filter_map(|l| serde_json::from_str(l).ok())
            .filter(|row: &serde_json::Value| match project {
                Some(p) => row.get("project").and_then(|v| v.as_str()) == Some(p),
                None => true,
            })
            .collect();
        let n = filtered.len();
        Ok(filtered.into_iter().skip(n.saturating_sub(limit)).collect())
    }
}

#[derive(Debug, Clone, Copy)]
pub struct EvaluatorOpts {
    pub cooldown_hours: f64,
}

impl Default for EvaluatorOpts {
    fn default() -> Self {
        Self {
            cooldown_hours: 24.0,
        }
    }
}

/// Drive a single rule against many contexts. Returns the alerts that
/// fired (post-dedup); writes them through `dispatcher` and `audit`.
#[allow(clippy::too_many_arguments)]
pub fn run_rule_over_contexts(
    project: &str,
    rule: &str,
    action: &str,
    contexts: &[(String, Context)], // (subject_key, ctx)
    dispatcher: Option<Arc<dyn Dispatcher>>,
    audit: &AuditLog,
    now: DateTime<Utc>,
    opts: &EvaluatorOpts,
    detail_for: impl Fn(&Context) -> String,
) -> Result<Vec<Alert>, EscalationError> {
    let cutoff = now - chrono::Duration::seconds((opts.cooldown_hours * 3600.0) as i64);
    let mut out = Vec::new();
    for (subject, ctx) in contexts {
        match evaluate_rule(rule, ctx) {
            Ok(true) => {
                let detail = detail_for(ctx);
                let fp = fingerprint(&[project, subject, rule]);
                if audit.was_recently_dispatched(&fp, cutoff)? {
                    continue;
                }
                let alert = Alert {
                    project: project.to_string(),
                    rule: rule.to_string(),
                    action: action.to_string(),
                    subject: format!("{} matches rule", subject),
                    detail,
                    fingerprint: fp,
                };
                if let Some(d) = &dispatcher {
                    if let Err(e) = d.dispatch(&alert) {
                        tracing::warn!("dispatch failed: {e}");
                    }
                }
                audit.append(&alert, now)?;
                out.push(alert);
            }
            _ => continue,
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    fn ctx_milestone(crit: &str, days: i64) -> Context {
        Context::new()
            .with_json("milestone", json!({"id": "m1", "criticality": crit, "deadline_within_days": days, "status": "active"}))
            .with_json("project", json!({"name": "FCLC", "phase": "DRAFT"}))
            .with_json("deadline_within_days", json!(days))
    }

    fn ctx_stakeholder(role: &str, overdue: bool, silent: i64) -> Context {
        Context::new().with_json(
            "stakeholder",
            json!({
                "name": "Geiger",
                "role": role,
                "overdue": overdue,
                "days_silent": silent,
                "awaiting_reply": true,
            }),
        )
    }

    #[test]
    fn tokenize_basic() {
        let toks = tokenize("milestone.criticality == 'high'").unwrap();
        assert_eq!(toks.len(), 3);
        assert!(matches!(toks[0], Tok::Word(ref w) if w == "milestone.criticality"));
        assert!(matches!(toks[1], Tok::Op(ref o) if o == "=="));
        assert!(matches!(toks[2], Tok::Str(ref s) if s == "high"));
    }

    #[test]
    fn tokenize_int_and_neg() {
        let toks = tokenize("days_within <= -7").unwrap();
        assert_eq!(toks.len(), 3);
        assert!(matches!(toks[2], Tok::Int(-7)));
    }

    #[test]
    fn tokenize_paren_and_keywords() {
        let toks = tokenize("(a == 1) and not b").unwrap();
        assert!(matches!(toks[0], Tok::LParen));
        assert!(matches!(toks[4], Tok::RParen));
        assert!(matches!(toks[5], Tok::Word(ref w) if w == "and"));
    }

    #[test]
    fn evaluate_simple_eq() {
        let ctx = ctx_milestone("high", 5);
        assert!(evaluate_rule("milestone.criticality == 'high'", &ctx).unwrap());
        assert!(!evaluate_rule("milestone.criticality == 'low'", &ctx).unwrap());
    }

    #[test]
    fn evaluate_le_compound() {
        let ctx = ctx_milestone("high", 5);
        assert!(evaluate_rule(
            "deadline_within_days <= 7 and milestone.criticality == 'high'",
            &ctx
        )
        .unwrap());
        // bump days outside the threshold
        let ctx2 = ctx_milestone("high", 10);
        assert!(!evaluate_rule(
            "deadline_within_days <= 7 and milestone.criticality == 'high'",
            &ctx2
        )
        .unwrap());
    }

    #[test]
    fn evaluate_or() {
        let ctx = ctx_milestone("low", 30);
        assert!(evaluate_rule(
            "milestone.criticality == 'high' or deadline_within_days < 31",
            &ctx
        )
        .unwrap());
    }

    #[test]
    fn evaluate_not() {
        let ctx = ctx_milestone("low", 100);
        assert!(evaluate_rule("not milestone.criticality == 'high'", &ctx).unwrap());
    }

    #[test]
    fn evaluate_contains() {
        let ctx = ctx_stakeholder("Co-PI WP3", true, 14);
        assert!(evaluate_rule("stakeholder.role contains 'Co-PI'", &ctx).unwrap());
        assert!(!evaluate_rule("stakeholder.role contains 'PI Lead'", &ctx).unwrap());
    }

    #[test]
    fn evaluate_in_string() {
        let ctx = ctx_stakeholder("Co-PI", true, 5);
        assert!(evaluate_rule("'PI' in stakeholder.role", &ctx).unwrap());
    }

    #[test]
    fn evaluate_bare_boolean_atom() {
        let ctx = ctx_stakeholder("PI", true, 5);
        assert!(evaluate_rule("stakeholder.overdue", &ctx).unwrap());
        let ctx2 = ctx_stakeholder("PI", false, 1);
        assert!(!evaluate_rule("stakeholder.overdue", &ctx2).unwrap());
    }

    #[test]
    fn evaluate_returns_false_on_missing_ident() {
        let ctx = Context::new();
        assert!(!evaluate_rule("absent.thing == 'x'", &ctx).unwrap());
    }

    #[test]
    fn evaluate_parens_override_associativity() {
        let ctx = ctx_milestone("high", 100);
        // With parens: false AND (true OR true) → false because milestone.criticality 'low' doesn't match 'low' since crit='high'. Use a different case.
        // milestone.criticality == 'low' OR (deadline_within_days < 200 AND milestone.criticality == 'high')
        assert!(evaluate_rule(
            "milestone.criticality == 'low' or (deadline_within_days < 200 and milestone.criticality == 'high')",
            &ctx
        )
        .unwrap());
    }

    #[test]
    fn fingerprint_stable() {
        let a = fingerprint(&["FCLC", "milestone", "m1", "rule"]);
        let b = fingerprint(&["FCLC", "milestone", "m1", "rule"]);
        let c = fingerprint(&["FCLC", "milestone", "m2", "rule"]);
        assert_eq!(a, b);
        assert_ne!(a, c);
        assert_eq!(a.len(), 12); // 6 bytes hex = 12 chars
    }

    #[test]
    fn audit_round_trip_and_cooldown() {
        let dir = TempDir::new().unwrap();
        let log = AuditLog::new(dir.path().join("audit.jsonl"));
        let alert = Alert {
            project: "FCLC".into(),
            rule: "milestone.criticality == 'high'".into(),
            action: "telegram_alert".into(),
            subject: "milestone m1 matches rule".into(),
            detail: "deadline_in=3d".into(),
            fingerprint: "abc123".into(),
        };
        let now = Utc::now();
        log.append(&alert, now).unwrap();
        let cutoff = now - chrono::Duration::hours(1);
        assert!(log.was_recently_dispatched("abc123", cutoff).unwrap());
        // Cutoff in the future — entry is "old"
        let future = now + chrono::Duration::hours(1);
        assert!(!log.was_recently_dispatched("abc123", future).unwrap());
        // Different fingerprint never matches
        assert!(!log.was_recently_dispatched("xyz", cutoff).unwrap());
    }

    #[test]
    fn run_rule_over_contexts_dedupes() {
        let dir = TempDir::new().unwrap();
        let log = AuditLog::new(dir.path().join("a.jsonl"));
        let dispatcher = Arc::new(MemoryDispatcher::new());

        let contexts = vec![("milestone:m1".to_string(), ctx_milestone("high", 5))];
        let now = Utc::now();
        let opts = EvaluatorOpts::default();
        let alerts = run_rule_over_contexts(
            "FCLC",
            "deadline_within_days <= 7 and milestone.criticality == 'high'",
            "telegram_alert",
            &contexts,
            Some(dispatcher.clone()),
            &log,
            now,
            &opts,
            |_| "deadline_in=5d".to_string(),
        )
        .unwrap();
        assert_eq!(alerts.len(), 1);
        assert_eq!(dispatcher.snapshot().len(), 1);

        // Run again immediately — fingerprint dedup should suppress
        let alerts2 = run_rule_over_contexts(
            "FCLC",
            "deadline_within_days <= 7 and milestone.criticality == 'high'",
            "telegram_alert",
            &contexts,
            Some(dispatcher.clone()),
            &log,
            now,
            &opts,
            |_| "deadline_in=5d".to_string(),
        )
        .unwrap();
        assert_eq!(alerts2.len(), 0);
        assert_eq!(dispatcher.snapshot().len(), 1, "dispatcher not re-hit");
    }

    #[test]
    fn audit_history_filters_by_project() {
        let dir = TempDir::new().unwrap();
        let log = AuditLog::new(dir.path().join("a.jsonl"));
        let now = Utc::now();
        for project in ["FCLC", "Ze", "FCLC"] {
            let alert = Alert {
                project: project.into(),
                rule: "x == 1".into(),
                action: "telegram_alert".into(),
                subject: "subject".into(),
                detail: "detail".into(),
                fingerprint: format!("fp-{project}"),
            };
            log.append(&alert, now).unwrap();
        }
        let h = log.history(Some("FCLC"), 10).unwrap();
        assert_eq!(h.len(), 2);
        let h2 = log.history(None, 10).unwrap();
        assert_eq!(h2.len(), 3);
    }

    #[test]
    fn alert_to_text() {
        let a = Alert {
            project: "FCLC".into(),
            rule: "".into(),
            action: "telegram_alert".into(),
            subject: "milestone m1 matches rule".into(),
            detail: "deadline_in=3d".into(),
            fingerprint: "fp".into(),
        };
        assert_eq!(
            a.to_text(),
            "⚠️ [FCLC] milestone m1 matches rule — deadline_in=3d"
        );
    }
}
