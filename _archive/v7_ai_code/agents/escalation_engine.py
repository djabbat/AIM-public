"""agents/escalation_engine.py — execute project escalation_rules (P6, 2026-05-03).

The FCLC.yaml pilot already declares:

    escalation_rules:
      - when: "deadline_within_days <= 7 and milestone.criticality == 'high'"
        action: telegram_alert
      - when: "stakeholder.overdue and stakeholder.role contains 'Co-PI'"
        action: telegram_alert

Until now those rules were dead text. This module evaluates them on
every project, emits matching alerts (Telegram + JSONL audit), and
de-duplicates so the same alert doesn't fire daily.

DSL — narrow, deterministic, no eval():

    Object scope:
      milestone.<field>             — id, deadline_within_days, criticality, status
      stakeholder.<field>            — name, role, days_silent, overdue, awaiting_reply
      project.<field>                — name, phase

    Operators (binary):
      ==  !=  <  <=  >  >=  contains  in

    Logic:
      and  or  not        (left-to-right, no precedence — use parentheses)
      ( ... )

Examples:
    deadline_within_days <= 7 and milestone.criticality == 'high'
    stakeholder.role contains 'Co-PI' and stakeholder.overdue
    project.phase == 'SUBMITTED' and milestone.criticality == 'high'

Public API:
    evaluate(project_name, today=None, dispatch=None) -> list[Alert]
    evaluate_all(today=None, dispatch=None) -> list[Alert]
    rule_history(project=None, limit=20) -> list[dict]
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("aim.escalation")


def audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "escalation.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Alert:
    project: str
    rule: str            # original rule text
    action: str          # telegram_alert / log / etc.
    subject: str         # short title
    detail: str          # one-line context
    fingerprint: str = "" # dedup key

    def to_text(self) -> str:
        return f"⚠️ [{self.project}] {self.subject} — {self.detail}"


# ── DSL evaluator ────────────────────────────────────────────────


_TOKEN_RE = re.compile(
    r"\s*("
    r"\(|\)|"
    r"==|!=|<=|>=|<|>|"
    r"\band\b|\bor\b|\bnot\b|"
    r"\bcontains\b|\bin\b|"
    r"'[^']*'|\"[^\"]*\"|"
    r"-?\d+\.?\d*|"
    r"[a-zA-Z_][a-zA-Z0-9_.]*"
    r")"
)


def _tokenize(rule: str) -> list[str]:
    out: list[str] = []
    pos = 0
    while pos < len(rule):
        m = _TOKEN_RE.match(rule, pos)
        if not m:
            if rule[pos].isspace():
                pos += 1
                continue
            raise ValueError(f"unexpected token in rule at pos {pos}: {rule[pos:pos+20]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _resolve(name: str, ctx: dict) -> Any:
    """Resolve a dotted name like `milestone.criticality` against ctx."""
    cur: Any = ctx
    for part in name.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif hasattr(cur, part):
            cur = getattr(cur, part)
        else:
            return None
    return cur


def _coerce(tok: str, ctx: dict) -> Any:
    if tok.startswith("'") and tok.endswith("'"):
        return tok[1:-1]
    if tok.startswith('"') and tok.endswith('"'):
        return tok[1:-1]
    if re.match(r"^-?\d+\.\d+$", tok):
        return float(tok)
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    if tok in ("True", "true"):
        return True
    if tok in ("False", "false"):
        return False
    return _resolve(tok, ctx)


def _eval_rpn(tokens: list[str], ctx: dict) -> bool:
    """Tiny recursive-descent over the token stream. No precedence between
    `and`/`or` — caller must use parentheses for unambiguous grouping."""
    pos = [0]

    def peek() -> Optional[str]:
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def consume() -> str:
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_or() -> bool:
        left = parse_and()
        while peek() == "or":
            consume()
            right = parse_and()
            left = bool(left) or bool(right)
        return left

    def parse_and() -> bool:
        left = parse_not()
        while peek() == "and":
            consume()
            right = parse_not()
            left = bool(left) and bool(right)
        return left

    def parse_not() -> bool:
        if peek() == "not":
            consume()
            return not parse_atom()
        return parse_atom()

    def parse_atom() -> Any:
        if peek() == "(":
            consume()
            v = parse_or()
            if peek() == ")":
                consume()
            return v
        # comparison / value
        left_tok = consume()
        op = peek()
        if op in ("==", "!=", "<", "<=", ">", ">=", "contains", "in"):
            consume()
            right_tok = consume()
            l = _coerce(left_tok, ctx)
            r = _coerce(right_tok, ctx)
            try:
                if op == "==":  return l == r
                if op == "!=":  return l != r
                if op == "<":   return l is not None and r is not None and l < r
                if op == "<=":  return l is not None and r is not None and l <= r
                if op == ">":   return l is not None and r is not None and l > r
                if op == ">=":  return l is not None and r is not None and l >= r
                if op == "contains":
                    return r in (l or "")
                if op == "in":
                    if isinstance(r, str):
                        return l in r
                    if isinstance(r, (list, tuple, set)):
                        return l in r
                    return False
            except TypeError:
                return False
        # bare boolean atom (e.g. `stakeholder.overdue`)
        return _coerce(left_tok, ctx)

    return bool(parse_or())


def evaluate_rule(rule: str, ctx: dict) -> bool:
    try:
        tokens = _tokenize(rule)
        return _eval_rpn(tokens, ctx)
    except Exception as e:
        log.warning("rule eval failed (%r): %s", rule, e)
        return False


# ── context builders ─────────────────────────────────────────────


def _milestone_ctx(state, m, today: dt.date) -> dict:
    d = m.days_to_deadline(today) if m.deadline else None
    return {
        "milestone": {
            "id": m.id,
            "criticality": m.criticality,
            "status": m.status,
            "deadline_within_days": d if d is not None else 9999,
        },
        "deadline_within_days": d if d is not None else 9999,
        "project": {"name": state.name, "phase": state.phase},
    }


def _stakeholder_ctx(state, s, today: dt.date) -> dict:
    return {
        "stakeholder": {
            "name": s.name,
            "role": s.role,
            "awaiting_reply": s.awaiting_reply,
            "overdue": s.overdue(today),
            "days_silent": s.days_silent(today) or 0,
        },
        "project": {"name": state.name, "phase": state.phase},
    }


# ── orchestrate ──────────────────────────────────────────────────


def _fingerprint(*parts: str) -> str:
    h = hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()[:12]
    return h


def _was_recently_dispatched(fp: str,
                              cooldown_hours: float = 24.0) -> bool:
    p = audit_path()
    if not p.exists():
        return False
    cutoff = dt.datetime.now() - dt.timedelta(hours=cooldown_hours)
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("fingerprint") != fp:
                    continue
                ts_str = row.get("ts") or ""
                try:
                    ts = dt.datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                if ts >= cutoff:
                    return True
    except OSError:
        return False
    return False


def _audit(alert: Alert) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "project": alert.project,
        "rule": alert.rule,
        "action": alert.action,
        "subject": alert.subject,
        "detail": alert.detail,
        "fingerprint": alert.fingerprint,
    }
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("escalation audit write failed: %s", e)


def _load_yaml_rules(project: str) -> list[dict]:
    """Read raw escalation_rules from the YAML — project_owner.load doesn't
    surface them, so we re-parse the file directly."""
    import yaml
    from agents import project_owner as po
    path = po.projects_dir() / f"{project}.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = raw.get("escalation_rules") or []
    return [r for r in rules if isinstance(r, dict)
            and r.get("when") and r.get("action")]


def evaluate(project: str, today: Optional[dt.date] = None,
             dispatch: Optional[Callable[[Alert], None]] = None,
             cooldown_hours: float = 24.0) -> list[Alert]:
    today = today or dt.date.today()
    rules = _load_yaml_rules(project)
    if not rules:
        return []
    from agents import project_owner as po
    state = po.load(project)
    alerts: list[Alert] = []

    for rule in rules:
        when = str(rule.get("when") or "")
        action = str(rule.get("action") or "")

        # Try every milestone / stakeholder against the rule. The eval
        # returns True only when both the variable and the comparison
        # resolve, so non-applicable contexts (e.g. a stakeholder rule
        # against a milestone ctx) silently produce False.
        for m in state.milestones:
            ctx = _milestone_ctx(state, m, today)
            if evaluate_rule(when, ctx):
                d = m.days_to_deadline(today)
                detail = (f"milestone={m.id} crit={m.criticality} "
                          f"deadline_in={d}d")
                fp = _fingerprint(state.name, "milestone", m.id, when)
                if _was_recently_dispatched(fp, cooldown_hours):
                    continue
                alert = Alert(project=state.name, rule=when, action=action,
                              subject=f"milestone {m.id} matches rule",
                              detail=detail, fingerprint=fp)
                alerts.append(alert)
                if dispatch:
                    try: dispatch(alert)
                    except Exception as e: log.warning("dispatch failed: %s", e)
                _audit(alert)

        for s in state.stakeholders:
            ctx = _stakeholder_ctx(state, s, today)
            if evaluate_rule(when, ctx):
                detail = (f"stakeholder={s.name} role={s.role} "
                          f"overdue={s.overdue(today)} silent={s.days_silent(today)}d")
                fp = _fingerprint(state.name, "stakeholder", s.name, when)
                if _was_recently_dispatched(fp, cooldown_hours):
                    continue
                alert = Alert(project=state.name, rule=when, action=action,
                              subject=f"stakeholder {s.name} matches rule",
                              detail=detail, fingerprint=fp)
                alerts.append(alert)
                if dispatch:
                    try: dispatch(alert)
                    except Exception as e: log.warning("dispatch failed: %s", e)
                _audit(alert)

    return alerts


def evaluate_all(today: Optional[dt.date] = None,
                 dispatch: Optional[Callable[[Alert], None]] = None,
                 cooldown_hours: float = 24.0) -> list[Alert]:
    from agents import project_owner as po
    out: list[Alert] = []
    for name in po.list_projects():
        try:
            out.extend(evaluate(name, today=today, dispatch=dispatch,
                                cooldown_hours=cooldown_hours))
        except (FileNotFoundError, ValueError) as e:
            log.debug("skip %s: %s", name, e)
    return out


def rule_history(project: Optional[str] = None,
                 limit: int = 20) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project and row.get("project") != project:
                continue
            out.append(row)
    return out[-limit:]


# ── default Telegram dispatch ────────────────────────────────────


def telegram_dispatch(alert: Alert) -> None:
    """Default action handler — sends `telegram_alert` actions to TG."""
    if alert.action != "telegram_alert":
        return
    try:
        from scripts.daily_brief import send_telegram
    except Exception:
        return
    send_telegram(alert.to_text())
