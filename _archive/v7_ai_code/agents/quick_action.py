"""agents/quick_action.py — freeform task dispatcher (Q1, 2026-05-03).

Lets the user type `aim do "draft email to Geiger about Phase B"` and
have AIM choose the right module. Strategy:

  1. Tokenise the request, run a deterministic intent classifier
     against a small rule set (regex + keyword matches). Most useful
     for offline/cheap dispatch.
  2. If no rule fires confidently, fall back to a tiny LLM hint via
     `llm.ask_fast` returning JSON {action, args}.
  3. Each action maps to a `quick_*` function in this module — they
     are thin wrappers that import the heavier module on demand.

Supported actions (initial set):

  | intent              | trigger phrases (RU/EN)            | handler      |
  |---------------------|------------------------------------|--------------|
  | brief               | "брифинг", "morning brief"         | _quick_brief |
  | recall              | "recall ...", "найди в памяти ..." | _quick_recall|
  | followups           | "follow-up", "напомни всем"        | _quick_followups |
  | escalate            | "что горит", "what's hot"          | _quick_escalate |
  | health              | "health check", "статус"           | _quick_health |
  | project_brief       | "FCLC брифинг"                     | _quick_project_brief |
  | project_transition  | "перевести FCLC в SUBMITTED"       | _quick_transition |
  | draft_email         | "draft email to <name>"            | _quick_draft_email |

Public API:
    classify(query) -> Intent
    handle(query) -> dict   # {action, output, ...}
"""
from __future__ import annotations

import dataclasses
import logging
import re
from typing import Optional

log = logging.getLogger("aim.quick_action")


# ── intent rules ─────────────────────────────────────────────────


@dataclasses.dataclass
class Intent:
    name: str
    args: dict
    confidence: float          # 0..1
    rule: str = ""             # which rule matched (debug)


_RULES: list[tuple[str, "re.Pattern[str]"]] = [
    ("brief",              re.compile(
        r"\b(?:morning\s+)?brief\b|\bбриф(?:инг)?\b|"
        r"\bдоброе\s+утро\b|\bкак\s+дела\b", re.I)),
    ("escalate",           re.compile(
        r"\bwhat'?s\s+hot\b|\bwhat'?s\s+urgent\b|"
        r"\bчто\s+горит\b|\bчто\s+(?:срочно|критично)\b", re.I)),
    ("followups",          re.compile(
        r"\bfollow[-\s]?ups?\b|\bнапомни\b|\bпинг\s+всех\b", re.I)),
    ("health",             re.compile(
        r"\bhealth\s+check\b|\b(?:обзор|статус)\s+систем\b|"
        r"\b/healthz\b", re.I)),
    ("recall",             re.compile(
        r"\b(?:recall|find|найди|вспомни)\b", re.I)),
]


_PROJECT_RE = re.compile(r"\b([A-Z][A-Za-z0-9_-]{1,30})\b")
_TRANSITION_TARGETS = {
    "DRAFT", "REVIEW", "SUBMITTED", "ACCEPTED",
    "PUBLISHED", "REJECTED", "ARCHIVED",
}


def _extract_project(query: str) -> Optional[str]:
    """Pick the first ALL-CAPS-ish token that matches a known project name."""
    try:
        from agents import project_owner as po
        known = set(po.list_projects())
    except Exception:
        known = set()
    for m in _PROJECT_RE.finditer(query):
        tok = m.group(1)
        if tok in known:
            return tok
        if tok.upper() in known:
            return tok.upper()
    # Loose match: project mentioned via lowercase reference.
    low = query.lower()
    for k in known:
        if k.lower() in low:
            return k
    return None


def _extract_recipient(query: str) -> Optional[str]:
    # "to <Name>" — accept one or two consecutive capitalised words; reject
    # trailing lowercase prepositions like "about", "regarding" by requiring
    # the second word to also be capitalised.
    m = re.search(r"\bto\s+([A-Z][\wʼ'-]{1,40}(?:\s+[A-Z][\wʼ'-]{1,40})?)",
                  query)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(?:к|для)\s+([А-ЯҐЁA-Z][\wʼ'-]{1,40})", query)
    if m:
        return m.group(1).strip()
    return None


def classify(query: str) -> Intent:
    q = (query or "").strip()
    if not q:
        return Intent(name="noop", args={}, confidence=0.0,
                       rule="empty input")

    # Project + transition? "transition FCLC to SUBMITTED" / "перевести FCLC в SUBMITTED"
    proj = _extract_project(q)
    transition_match = re.search(
        r"\b(?:transition|перевест[ия]|move)\b.*?\b("
        + "|".join(_TRANSITION_TARGETS) + r")\b",
        q, flags=re.I)
    if proj and transition_match:
        return Intent(name="project_transition",
                       args={"project": proj,
                              "dst": transition_match.group(1).upper()},
                       confidence=0.95, rule="transition")

    # Project + (brief|status)?
    if proj and re.search(r"\b(?:brief|статус|status|state|обзор)\b", q, re.I):
        return Intent(name="project_brief",
                       args={"project": proj},
                       confidence=0.85, rule="project_brief")

    # Draft email pattern.
    if re.search(r"\b(?:draft|написать|подготовь)\b.*?\bemail\b", q, re.I):
        rec = _extract_recipient(q)
        return Intent(name="draft_email",
                       args={"recipient_hint": rec or "", "free_text": q},
                       confidence=0.7, rule="draft_email")

    for name, pat in _RULES:
        if pat.search(q):
            args: dict = {}
            if name == "recall":
                # Strip the trigger words and keep the search query.
                cleaned = re.sub(
                    r"^\s*(?:recall|find|найди|вспомни)[:\s]+", "", q,
                    flags=re.I)
                args["query"] = cleaned or q
            return Intent(name=name, args=args, confidence=0.8,
                           rule=f"rule:{name}")

    return Intent(name="unknown", args={"query": q}, confidence=0.0,
                   rule="no rule matched")


# ── handlers ─────────────────────────────────────────────────────


def _quick_brief(_args: dict) -> dict:
    from agents.brief_preamble import compose
    from agents import project_owner as po
    return {"action": "brief",
            "output": compose() + "\n\n" + po.all_briefs()}


def _quick_recall(args: dict) -> dict:
    from agents.recall_cli import recall_top
    return {"action": "recall",
            "output": recall_top(args.get("query", ""))}


def _quick_followups(_args: dict) -> dict:
    from agents.follow_up_generator import generate_all
    drafts = generate_all()
    return {"action": "followups", "n_drafts": len(drafts),
            "drafts": [{"to": d.contact_email, "subject": d.subject,
                         "lang": d.lang} for d in drafts]}


def _quick_escalate(_args: dict) -> dict:
    from agents.escalation_engine import evaluate_all
    alerts = evaluate_all(cooldown_hours=0)
    return {"action": "escalate",
            "n_alerts": len(alerts),
            "output": "\n".join(a.to_text() for a in alerts) or "(nothing hot)"}


def _quick_health(_args: dict) -> dict:
    from agents.health_extended import report
    r = report()
    return {"action": "health",
            "overall": r["overall"], "warnings": r["warnings"]}


def _quick_project_brief(args: dict) -> dict:
    from agents import project_owner as po
    return {"action": "project_brief",
            "project": args["project"],
            "output": po.morning_brief(args["project"])}


def _quick_transition(args: dict) -> dict:
    from agents import project_state_machine as sm
    rec = sm.transition(args["project"], args["dst"],
                        reason="quick_action.transition")
    return {"action": "project_transition", **rec}


def _quick_draft_email(args: dict) -> dict:
    """Draft an email — best-effort: try to find a contact matching the
    recipient hint, return the generated draft (NOT saved). The user can
    save it with `aim followups --save` later or via the email_agent."""
    rec = (args.get("recipient_hint") or "").strip()
    if not rec:
        return {"action": "draft_email",
                "error": "no recipient hint found in request"}
    try:
        from agents import stakeholder_tracker as st
        rows = st.get_by_name(rec) or []
        if not rows:
            return {"action": "draft_email",
                    "error": f"no contact named {rec!r}"}
        from agents.follow_up_generator import generate
        d = generate(rows[0])
    except Exception as e:
        return {"action": "draft_email", "error": str(e)}
    if d is None:
        return {"action": "draft_email", "error": "no email on record"}
    return {"action": "draft_email", "to": d.contact_email,
            "subject": d.subject, "body": d.body, "lang": d.lang}


_HANDLERS = {
    "brief":               _quick_brief,
    "recall":              _quick_recall,
    "followups":           _quick_followups,
    "escalate":            _quick_escalate,
    "health":              _quick_health,
    "project_brief":       _quick_project_brief,
    "project_transition":  _quick_transition,
    "draft_email":         _quick_draft_email,
}


def handle(query: str) -> dict:
    intent = classify(query)
    if intent.name == "noop":
        return {"action": "noop", "error": "empty input"}
    if intent.name == "unknown":
        return {"action": "unknown", "intent": dataclasses.asdict(intent),
                "error": "no rule matched; consider rephrasing"}
    fn = _HANDLERS.get(intent.name)
    if fn is None:
        return {"action": intent.name, "error": "no handler registered"}
    try:
        result = fn(intent.args)
    except Exception as e:  # noqa: BLE001
        return {"action": intent.name, "error": f"{type(e).__name__}: {e}"}
    result.setdefault("intent_rule", intent.rule)
    result.setdefault("confidence", intent.confidence)
    return result
