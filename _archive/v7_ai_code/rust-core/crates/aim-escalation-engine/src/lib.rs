//! aim-escalation-engine — execute project escalation_rules (P6).
//!
//! Port of `agents/escalation_engine.py`. Runs a tiny deterministic DSL
//! over project milestones / stakeholders, emits `Alert`s, deduplicates
//! via fingerprint+cooldown, and dispatches via a pluggable trait.
//!
//! DSL (no `eval()`): `==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `in`,
//! `and`, `or`, `not`, parentheses. Use parentheses for `and`/`or`
//! grouping — there is no precedence (left-to-right).

use std::collections::BTreeMap;

use chrono::{DateTime, Duration, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum EscError {
    #[error("rule parse error: {0}")]
    Parse(String),
}

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
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

/// Resolved value during evaluation. JSON-friendly so callers can
/// pass arbitrary nested data via `serde_json::Value`.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Value>),
}

impl Value {
    fn from_json(v: &serde_json::Value) -> Self {
        match v {
            serde_json::Value::Null => Self::Null,
            serde_json::Value::Bool(b) => Self::Bool(*b),
            serde_json::Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Self::Int(i)
                } else if let Some(f) = n.as_f64() {
                    Self::Float(f)
                } else {
                    Self::Null
                }
            }
            serde_json::Value::String(s) => Self::Str(s.clone()),
            serde_json::Value::Array(a) => Self::List(a.iter().map(Self::from_json).collect()),
            serde_json::Value::Object(_) => Self::Null,
        }
    }

    fn truthy(&self) -> bool {
        match self {
            Self::Null => false,
            Self::Bool(b) => *b,
            Self::Int(n) => *n != 0,
            Self::Float(n) => *n != 0.0,
            Self::Str(s) => !s.is_empty(),
            Self::List(v) => !v.is_empty(),
        }
    }

    fn cmp_num(&self) -> Option<f64> {
        match self {
            Self::Int(n) => Some(*n as f64),
            Self::Float(f) => Some(*f),
            _ => None,
        }
    }
}

// ── tokenizer ──────────────────────────────────────────────────────────────

fn tokenize(rule: &str) -> std::result::Result<Vec<String>, EscError> {
    use once_cell::sync::Lazy;
    static TOKEN_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(
            r#"(?x)
            \s*(
                \(|\)|
                ==|!=|<=|>=|<|>|
                \band\b|\bor\b|\bnot\b|
                \bcontains\b|\bin\b|
                '[^']*'|"[^"]*"|
                -?\d+\.?\d*|
                [a-zA-Z_][a-zA-Z0-9_.]*
            )"#,
        )
        .expect("token regex compiles")
    });
    let mut out = Vec::new();
    let mut pos = 0;
    while pos < rule.len() {
        let slice = &rule[pos..];
        if let Some(m) = TOKEN_RE.captures(slice) {
            let outer = m.get(0).expect("match has whole match");
            // Only accept matches anchored at position 0
            if outer.start() != 0 {
                let next = slice.chars().next().unwrap();
                if next.is_whitespace() {
                    pos += next.len_utf8();
                    continue;
                }
                return Err(EscError::Parse(format!(
                    "unexpected token at pos {}: {:?}",
                    pos,
                    &slice.chars().take(20).collect::<String>()
                )));
            }
            let tok = m.get(1).expect("group 1 captured").as_str().to_string();
            out.push(tok);
            pos += outer.end();
        } else {
            let next = slice.chars().next().unwrap();
            if next.is_whitespace() {
                pos += next.len_utf8();
                continue;
            }
            return Err(EscError::Parse(format!(
                "unexpected token at pos {}: {:?}",
                pos,
                &slice.chars().take(20).collect::<String>()
            )));
        }
    }
    Ok(out)
}

// ── evaluator ──────────────────────────────────────────────────────────────

pub type Context = BTreeMap<String, serde_json::Value>;

fn resolve(name: &str, ctx: &Context) -> Value {
    let parts: Vec<&str> = name.split('.').collect();
    let mut cur: serde_json::Value = match ctx.get(parts[0]) {
        Some(v) => v.clone(),
        None => return Value::Null,
    };
    for part in &parts[1..] {
        match cur {
            serde_json::Value::Object(map) => {
                cur = match map.get(*part) {
                    Some(v) => v.clone(),
                    None => return Value::Null,
                };
            }
            _ => return Value::Null,
        }
    }
    Value::from_json(&cur)
}

fn coerce(tok: &str, ctx: &Context) -> Value {
    if tok.starts_with('\'') && tok.ends_with('\'') && tok.len() >= 2 {
        return Value::Str(tok[1..tok.len() - 1].to_string());
    }
    if tok.starts_with('"') && tok.ends_with('"') && tok.len() >= 2 {
        return Value::Str(tok[1..tok.len() - 1].to_string());
    }
    if let Ok(i) = tok.parse::<i64>() {
        // No decimal point → int
        if !tok.contains('.') {
            return Value::Int(i);
        }
    }
    if let Ok(f) = tok.parse::<f64>() {
        return Value::Float(f);
    }
    if matches!(tok, "True" | "true") {
        return Value::Bool(true);
    }
    if matches!(tok, "False" | "false") {
        return Value::Bool(false);
    }
    resolve(tok, ctx)
}

struct Parser<'a> {
    tokens: &'a [String],
    pos: usize,
    ctx: &'a Context,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&str> {
        self.tokens.get(self.pos).map(|s| s.as_str())
    }
    fn consume(&mut self) -> Option<String> {
        let t = self.tokens.get(self.pos).cloned();
        if t.is_some() {
            self.pos += 1;
        }
        t
    }
    fn parse_or(&mut self) -> Value {
        let mut left = self.parse_and();
        while self.peek() == Some("or") {
            self.consume();
            let right = self.parse_and();
            left = Value::Bool(left.truthy() || right.truthy());
        }
        left
    }
    fn parse_and(&mut self) -> Value {
        let mut left = self.parse_not();
        while self.peek() == Some("and") {
            self.consume();
            let right = self.parse_not();
            left = Value::Bool(left.truthy() && right.truthy());
        }
        left
    }
    fn parse_not(&mut self) -> Value {
        if self.peek() == Some("not") {
            self.consume();
            let v = self.parse_atom();
            return Value::Bool(!v.truthy());
        }
        self.parse_atom()
    }
    fn parse_atom(&mut self) -> Value {
        if self.peek() == Some("(") {
            self.consume();
            let v = self.parse_or();
            if self.peek() == Some(")") {
                self.consume();
            }
            return v;
        }
        let left_tok = match self.consume() {
            Some(t) => t,
            None => return Value::Null,
        };
        let op = self.peek().map(String::from);
        let is_op = matches!(
            op.as_deref(),
            Some("==" | "!=" | "<" | "<=" | ">" | ">=" | "contains" | "in")
        );
        if is_op {
            let op = op.unwrap();
            self.consume();
            let right_tok = match self.consume() {
                Some(t) => t,
                None => return Value::Bool(false),
            };
            let l = coerce(&left_tok, self.ctx);
            let r = coerce(&right_tok, self.ctx);
            return apply_op(&op, &l, &r);
        }
        coerce(&left_tok, self.ctx)
    }
}

fn apply_op(op: &str, l: &Value, r: &Value) -> Value {
    let bool_result = match op {
        "==" => l == r,
        "!=" => l != r,
        "<" | "<=" | ">" | ">=" => {
            match (l.cmp_num(), r.cmp_num()) {
                (Some(a), Some(b)) => match op {
                    "<" => a < b,
                    "<=" => a <= b,
                    ">" => a > b,
                    _ => a >= b,
                },
                _ => false,
            }
        }
        "contains" => match (l, r) {
            (Value::Str(s), Value::Str(needle)) => s.contains(needle.as_str()),
            (Value::List(xs), v) => xs.iter().any(|x| x == v),
            (Value::Null, _) => false,
            _ => false,
        },
        "in" => match (l, r) {
            (Value::Str(needle), Value::Str(haystack)) => haystack.contains(needle.as_str()),
            (v, Value::List(xs)) => xs.iter().any(|x| x == v),
            _ => false,
        },
        _ => false,
    };
    Value::Bool(bool_result)
}

/// Evaluate a rule against a context. Returns `false` on parse / lookup
/// failure (matches Python's "fail safe").
pub fn evaluate_rule(rule: &str, ctx: &Context) -> bool {
    let tokens = match tokenize(rule) {
        Ok(t) => t,
        Err(e) => {
            tracing::warn!("rule tokenize failed ({:?}): {}", rule, e);
            return false;
        }
    };
    let mut p = Parser {
        tokens: &tokens,
        pos: 0,
        ctx,
    };
    p.parse_or().truthy()
}

// ── fingerprint / cooldown ──────────────────────────────────────────────────

pub fn fingerprint(parts: &[&str]) -> String {
    let mut hasher = Sha1::new();
    hasher.update(parts.join(":").as_bytes());
    let digest = hasher.finalize();
    let hex: String = digest.iter().map(|b| format!("{:02x}", b)).collect();
    hex.chars().take(12).collect()
}

pub trait CooldownStore: Send + Sync {
    /// Was the same fingerprint dispatched within `cooldown`?
    fn was_recent(&self, fingerprint: &str, cooldown: Duration, now: DateTime<Utc>) -> bool;
    /// Persist a freshly-emitted alert.
    fn record(&self, alert: &Alert, now: DateTime<Utc>);
}

#[derive(Default)]
pub struct InMemCooldown {
    inner: parking_lot::Mutex<Vec<(String, DateTime<Utc>)>>,
}

impl CooldownStore for InMemCooldown {
    fn was_recent(&self, fp: &str, cooldown: Duration, now: DateTime<Utc>) -> bool {
        let cutoff = now - cooldown;
        self.inner
            .lock()
            .iter()
            .any(|(f, ts)| f == fp && *ts >= cutoff)
    }
    fn record(&self, alert: &Alert, now: DateTime<Utc>) {
        self.inner
            .lock()
            .push((alert.fingerprint.clone(), now));
    }
}

// ── dispatch trait ─────────────────────────────────────────────────────────

pub trait Dispatch: Send + Sync {
    fn dispatch(&self, alert: &Alert);
}

pub struct NoopDispatch;
impl Dispatch for NoopDispatch {
    fn dispatch(&self, _: &Alert) {}
}

// ── orchestrator ───────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct Rule {
    pub when: String,
    pub action: String,
}

#[derive(Clone, Debug)]
pub struct Milestone {
    pub id: String,
    pub criticality: String,
    pub status: String,
    pub deadline_within_days: Option<i64>,
}

impl Milestone {
    fn ctx_for(&self, project_name: &str, project_phase: &str) -> Context {
        let mut ctx = Context::new();
        ctx.insert(
            "milestone".into(),
            serde_json::json!({
                "id": self.id,
                "criticality": self.criticality,
                "status": self.status,
                "deadline_within_days": self.deadline_within_days.unwrap_or(9999),
            }),
        );
        ctx.insert(
            "deadline_within_days".into(),
            serde_json::json!(self.deadline_within_days.unwrap_or(9999)),
        );
        ctx.insert(
            "project".into(),
            serde_json::json!({"name": project_name, "phase": project_phase}),
        );
        ctx
    }
}

#[derive(Clone, Debug)]
pub struct Stakeholder {
    pub name: String,
    pub role: String,
    pub awaiting_reply: bool,
    pub overdue: bool,
    pub days_silent: i64,
}

impl Stakeholder {
    fn ctx_for(&self, project_name: &str, project_phase: &str) -> Context {
        let mut ctx = Context::new();
        ctx.insert(
            "stakeholder".into(),
            serde_json::json!({
                "name": self.name,
                "role": self.role,
                "awaiting_reply": self.awaiting_reply,
                "overdue": self.overdue,
                "days_silent": self.days_silent,
            }),
        );
        ctx.insert(
            "project".into(),
            serde_json::json!({"name": project_name, "phase": project_phase}),
        );
        ctx
    }
}

#[derive(Clone, Debug)]
pub struct ProjectState {
    pub name: String,
    pub phase: String,
    pub milestones: Vec<Milestone>,
    pub stakeholders: Vec<Stakeholder>,
    pub rules: Vec<Rule>,
}

pub struct Engine<'a> {
    pub cooldown: &'a dyn CooldownStore,
    pub dispatch: &'a dyn Dispatch,
    pub cooldown_window: Duration,
}

impl<'a> Engine<'a> {
    pub fn new(cooldown: &'a dyn CooldownStore, dispatch: &'a dyn Dispatch) -> Self {
        Self {
            cooldown,
            dispatch,
            cooldown_window: Duration::hours(24),
        }
    }

    /// Run all rules against milestones + stakeholders. Already-recently-
    /// dispatched alerts (per fingerprint + cooldown) are skipped.
    pub fn evaluate(&self, project: &ProjectState, now: DateTime<Utc>) -> Vec<Alert> {
        let mut alerts: Vec<Alert> = Vec::new();
        for rule in &project.rules {
            for m in &project.milestones {
                let ctx = m.ctx_for(&project.name, &project.phase);
                if !evaluate_rule(&rule.when, &ctx) {
                    continue;
                }
                let detail = format!(
                    "milestone={} crit={} deadline_in={}d",
                    m.id,
                    m.criticality,
                    m.deadline_within_days.unwrap_or(9999)
                );
                let fp = fingerprint(&[&project.name, "milestone", &m.id, &rule.when]);
                if self.cooldown.was_recent(&fp, self.cooldown_window, now) {
                    continue;
                }
                let alert = Alert {
                    project: project.name.clone(),
                    rule: rule.when.clone(),
                    action: rule.action.clone(),
                    subject: format!("milestone {} matches rule", m.id),
                    detail,
                    fingerprint: fp,
                };
                self.dispatch.dispatch(&alert);
                self.cooldown.record(&alert, now);
                alerts.push(alert);
            }
            for s in &project.stakeholders {
                let ctx = s.ctx_for(&project.name, &project.phase);
                if !evaluate_rule(&rule.when, &ctx) {
                    continue;
                }
                let detail = format!(
                    "stakeholder={} role={} overdue={} silent={}d",
                    s.name, s.role, s.overdue, s.days_silent
                );
                let fp = fingerprint(&[&project.name, "stakeholder", &s.name, &rule.when]);
                if self.cooldown.was_recent(&fp, self.cooldown_window, now) {
                    continue;
                }
                let alert = Alert {
                    project: project.name.clone(),
                    rule: rule.when.clone(),
                    action: rule.action.clone(),
                    subject: format!("stakeholder {} matches rule", s.name),
                    detail,
                    fingerprint: fp,
                };
                self.dispatch.dispatch(&alert);
                self.cooldown.record(&alert, now);
                alerts.push(alert);
            }
        }
        alerts
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    fn ts(secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(secs, 0).unwrap()
    }

    fn ctx(pairs: &[(&str, serde_json::Value)]) -> Context {
        let mut c = Context::new();
        for (k, v) in pairs {
            c.insert((*k).to_string(), v.clone());
        }
        c
    }

    // ── tokenize ───────────────────────────────────────────────────────────

    #[test]
    fn tokenize_handles_full_rule() {
        let toks = tokenize("milestone.criticality == 'high' and deadline_within_days <= 7")
            .unwrap();
        assert_eq!(
            toks,
            vec![
                "milestone.criticality",
                "==",
                "'high'",
                "and",
                "deadline_within_days",
                "<=",
                "7",
            ]
        );
    }

    #[test]
    fn tokenize_supports_parens_and_logic() {
        let toks = tokenize("(a == 1 or b == 2) and not c").unwrap();
        assert!(toks.contains(&"(".to_string()));
        assert!(toks.contains(&"or".to_string()));
        assert!(toks.contains(&"not".to_string()));
        assert!(toks.contains(&")".to_string()));
    }

    // ── coerce / resolve ───────────────────────────────────────────────────

    #[test]
    fn coerce_int_float_string_bool() {
        let c = Context::new();
        assert_eq!(coerce("42", &c), Value::Int(42));
        assert_eq!(coerce("3.14", &c), Value::Float(3.14));
        assert_eq!(coerce("'hi'", &c), Value::Str("hi".into()));
        assert_eq!(coerce("\"hi\"", &c), Value::Str("hi".into()));
        assert_eq!(coerce("true", &c), Value::Bool(true));
        assert_eq!(coerce("False", &c), Value::Bool(false));
    }

    #[test]
    fn resolve_dotted_path() {
        let c = ctx(&[("a", serde_json::json!({"b": {"c": 7}}))]);
        assert_eq!(coerce("a.b.c", &c), Value::Int(7));
        assert_eq!(coerce("a.missing", &c), Value::Null);
    }

    // ── evaluate_rule ──────────────────────────────────────────────────────

    #[test]
    fn rule_simple_eq() {
        let c = ctx(&[("status", serde_json::json!("DRAFT"))]);
        assert!(evaluate_rule("status == 'DRAFT'", &c));
        assert!(!evaluate_rule("status == 'SUBMITTED'", &c));
    }

    #[test]
    fn rule_lt_le_gt_ge_on_int() {
        let c = ctx(&[("days", serde_json::json!(5))]);
        assert!(evaluate_rule("days <= 7", &c));
        assert!(!evaluate_rule("days > 10", &c));
        assert!(evaluate_rule("days >= 5", &c));
        assert!(evaluate_rule("days < 6", &c));
    }

    #[test]
    fn rule_contains_string() {
        let c = ctx(&[("role", serde_json::json!("Co-PI Geiger"))]);
        assert!(evaluate_rule("role contains 'Co-PI'", &c));
        assert!(!evaluate_rule("role contains 'PI-Lead'", &c));
    }

    #[test]
    fn rule_in_string_list() {
        let c = ctx(&[("color", serde_json::json!("red"))]);
        // `color in 'red,green,blue'` → string-in-string
        assert!(evaluate_rule("color in 'red,green,blue'", &c));
    }

    #[test]
    fn rule_and_or_combination() {
        let c = ctx(&[
            ("a", serde_json::json!(1)),
            ("b", serde_json::json!(2)),
            ("c", serde_json::json!(3)),
        ]);
        assert!(evaluate_rule("a == 1 and b == 2", &c));
        assert!(!evaluate_rule("a == 1 and b == 99", &c));
        assert!(evaluate_rule("a == 99 or b == 2", &c));
        assert!(!evaluate_rule("a == 99 or b == 99", &c));
    }

    #[test]
    fn rule_not_and_parens() {
        let c = ctx(&[("ok", serde_json::json!(false))]);
        assert!(evaluate_rule("not ok", &c));
        let c2 = ctx(&[("a", serde_json::json!(1)), ("b", serde_json::json!(2))]);
        assert!(evaluate_rule("(a == 1 or a == 99) and b == 2", &c2));
    }

    #[test]
    fn rule_resolves_dotted_property() {
        let c = ctx(&[("milestone", serde_json::json!({"criticality": "high"}))]);
        assert!(evaluate_rule("milestone.criticality == 'high'", &c));
    }

    #[test]
    fn rule_bare_truthy_atom() {
        let c = ctx(&[("flag", serde_json::json!(true))]);
        assert!(evaluate_rule("flag", &c));
        let c2 = ctx(&[("flag", serde_json::json!(false))]);
        assert!(!evaluate_rule("flag", &c2));
    }

    #[test]
    fn rule_missing_var_returns_false() {
        let c = Context::new();
        assert!(!evaluate_rule("missing == 1", &c));
        assert!(!evaluate_rule("missing < 5", &c));
    }

    #[test]
    fn rule_garbage_returns_false() {
        let c = Context::new();
        assert!(!evaluate_rule("@@@$$$", &c));
    }

    // ── fingerprint ────────────────────────────────────────────────────────

    #[test]
    fn fingerprint_stable_and_short() {
        let f1 = fingerprint(&["A", "B", "C"]);
        let f2 = fingerprint(&["A", "B", "C"]);
        assert_eq!(f1, f2);
        assert_eq!(f1.len(), 12);
        let f3 = fingerprint(&["A", "B", "D"]);
        assert_ne!(f1, f3);
    }

    // ── InMemCooldown ──────────────────────────────────────────────────────

    #[test]
    fn cooldown_recent_within_window_only() {
        let cd = InMemCooldown::default();
        let alert = Alert {
            fingerprint: "fp1".into(),
            ..Default::default()
        };
        cd.record(&alert, ts(1_700_000_000));
        // 1 hour later → still recent (24h window)
        assert!(cd.was_recent("fp1", Duration::hours(24), ts(1_700_003_600)));
        // 25 hours later → outside window
        assert!(!cd.was_recent("fp1", Duration::hours(24), ts(1_700_000_000) + Duration::hours(25)));
    }

    // ── Engine.evaluate ────────────────────────────────────────────────────

    #[derive(Default)]
    struct CapturingDispatch(Mutex<Vec<Alert>>);
    impl Dispatch for CapturingDispatch {
        fn dispatch(&self, a: &Alert) {
            self.0.lock().push(a.clone());
        }
    }

    fn fclc_state() -> ProjectState {
        ProjectState {
            name: "FCLC".into(),
            phase: "SUBMITTED".into(),
            milestones: vec![
                Milestone {
                    id: "m1-deadline".into(),
                    criticality: "high".into(),
                    status: "open".into(),
                    deadline_within_days: Some(5),
                },
                Milestone {
                    id: "m2-far".into(),
                    criticality: "low".into(),
                    status: "open".into(),
                    deadline_within_days: Some(60),
                },
            ],
            stakeholders: vec![
                Stakeholder {
                    name: "Geiger".into(),
                    role: "Co-PI".into(),
                    awaiting_reply: true,
                    overdue: true,
                    days_silent: 14,
                },
                Stakeholder {
                    name: "Anonymous".into(),
                    role: "Reader".into(),
                    awaiting_reply: false,
                    overdue: false,
                    days_silent: 0,
                },
            ],
            rules: vec![
                Rule {
                    when: "deadline_within_days <= 7 and milestone.criticality == 'high'".into(),
                    action: "telegram_alert".into(),
                },
                Rule {
                    when: "stakeholder.overdue and stakeholder.role contains 'Co-PI'".into(),
                    action: "telegram_alert".into(),
                },
            ],
        }
    }

    #[test]
    fn engine_emits_alerts_for_matching_rules_only() {
        let cd = InMemCooldown::default();
        let dp = CapturingDispatch::default();
        let eng = Engine::new(&cd, &dp);
        let alerts = eng.evaluate(&fclc_state(), ts(1_700_000_000));
        // 1 milestone match (m1-deadline) + 1 stakeholder match (Geiger) = 2
        assert_eq!(alerts.len(), 2);
        assert!(alerts.iter().any(|a| a.subject.contains("m1-deadline")));
        assert!(alerts.iter().any(|a| a.subject.contains("Geiger")));
        // m2-far / Anonymous don't match
        assert!(!alerts.iter().any(|a| a.subject.contains("m2-far")));
        assert!(!alerts.iter().any(|a| a.subject.contains("Anonymous")));
        assert_eq!(dp.0.lock().len(), 2);
    }

    #[test]
    fn engine_skips_alert_in_cooldown() {
        let cd = InMemCooldown::default();
        let dp = CapturingDispatch::default();
        let eng = Engine::new(&cd, &dp);
        // first run records both alerts
        eng.evaluate(&fclc_state(), ts(1_700_000_000));
        // second run within 24h → no new alerts
        let again = eng.evaluate(&fclc_state(), ts(1_700_000_000) + Duration::hours(1));
        assert!(again.is_empty());
    }

    #[test]
    fn engine_re_emits_after_cooldown_expires() {
        let cd = InMemCooldown::default();
        let dp = CapturingDispatch::default();
        let eng = Engine::new(&cd, &dp);
        eng.evaluate(&fclc_state(), ts(1_700_000_000));
        // 25h later → past 24h cooldown
        let again = eng.evaluate(&fclc_state(), ts(1_700_000_000) + Duration::hours(25));
        assert_eq!(again.len(), 2);
    }

    #[test]
    fn alert_to_text_format() {
        let a = Alert {
            project: "FCLC".into(),
            rule: "x".into(),
            action: "telegram_alert".into(),
            subject: "milestone m1 matches".into(),
            detail: "details here".into(),
            fingerprint: "abc".into(),
        };
        assert_eq!(
            a.to_text(),
            "⚠️ [FCLC] milestone m1 matches — details here"
        );
    }
}
