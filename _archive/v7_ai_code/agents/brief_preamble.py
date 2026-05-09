"""agents/brief_preamble.py — smart morning preamble (B1, 2026-05-03).

The daily brief used to lead with a static "AIM daily brief — <date>"
header. With every project + 424 deadlines + N stakeholders in flight,
the user wants the first three lines to TELL them what's hot — not
make them scroll through the brief to find it.

This module composes a 1-3 line preamble from:

  * the most-overdue stakeholder (P3 stakeholder_tracker)
  * the closest milestone deadline today (P1 hot_milestones)
  * the biggest deadline_scanner red flag (P2 by_horizon)
  * a friendly Russian-locale greeting timed to wall clock

Scope is deliberately narrow: 3 punchy lines, ≤ 280 chars total.
Plug it into scripts/daily_brief.py via AIM_BRIEF_HEAD or call
`compose(today)` directly.

Public API:
    compose(today=None) -> str
    install_into_brief()  -> str   # convenience: sets AIM_BRIEF_HEAD env
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Optional

log = logging.getLogger("aim.brief_preamble")


_GREETINGS = {
    "ru": ("Спокойной ночи", "Доброе утро", "Добрый день", "Добрый вечер"),
    "en": ("Late evening",   "Good morning", "Good afternoon", "Good evening"),
    "ka": ("ღამე მშვიდობისა", "დილა მშვიდობისა", "შუადღე მშვიდობისა", "საღამო მშვიდობისა"),
}

_LABELS = {
    "ru": {"today": "СЕГОДНЯ", "overdue": "просрочено", "in_d": "через {n}д",
            "no_reply": "нет ответа уже {n}д",
            "deadlines": "🗓 дедлайны", "today_short": "сегодня",
            "this_week": "в эту неделю",
            "overdue_short": "просрочено"},
    "en": {"today": "TODAY", "overdue": "overdue", "in_d": "in {n}d",
            "no_reply": "no reply for {n}d",
            "deadlines": "🗓 deadlines", "today_short": "today",
            "this_week": "this week",
            "overdue_short": "overdue"},
    "ka": {"today": "დღეს", "overdue": "ვადაგასული", "in_d": "{n}დღეში",
            "no_reply": "{n}დღე უპასუხოდ",
            "deadlines": "🗓 ვადები", "today_short": "დღეს",
            "this_week": "ამ კვირაში",
            "overdue_short": "ვადაგასული"},
}


def _greeting(now: dt.datetime, name: str = "Джаба",
               lang: str = "ru") -> str:
    h = now.hour
    g_set = _GREETINGS.get(lang, _GREETINGS["ru"])
    if h < 5:
        g = g_set[0]
    elif h < 12:
        g = g_set[1]
    elif h < 18:
        g = g_set[2]
    else:
        g = g_set[3]
    return f"{g}, {name}."


def _fmt_milestone(label: str, days: int, lang: str = "ru") -> str:
    L = _LABELS.get(lang, _LABELS["ru"])
    if days == 0:
        return f"🔥 {L['today']}: {label}"
    if days < 0:
        return f"⛔ {L['overdue']} {-days}d: {label}"
    return f"📅 {L['in_d'].format(n=days)}: {label}"


def _hot_milestone_line(today: dt.date, lang: str = "ru") -> Optional[str]:
    """Pick the highest-priority milestone across all configured projects."""
    try:
        from agents import project_owner as po
    except ImportError:
        return None
    best: Optional[tuple[int, int, str]] = None  # (priority, days, label)
    rank = {"high": 0, "medium": 1, "low": 2}
    for name in po.list_projects():
        try:
            state = po.load(name)
        except (FileNotFoundError, ValueError):
            continue
        for m in state.milestones:
            if m.deadline is None or m.status != "pending":
                continue
            d = (m.deadline.date() - today).days
            if d < -14 or d > 14:
                continue   # outside the urgent window
            pr = rank.get(m.criticality, 1)
            label = f"{state.name}/{m.id}"
            cand = (pr, d, label)
            if best is None or cand < best:
                best = cand
    if best is None:
        return None
    _, days, label = best
    return _fmt_milestone(label, days, lang=lang)


def _stakeholder_line(today: dt.date, lang: str = "ru") -> Optional[str]:
    """Most-overdue stakeholder follow-up, if any."""
    try:
        from agents import stakeholder_tracker as st
    except ImportError:
        return None
    try:
        rows = st.overdue_followups(today=today)
    except Exception as e:
        log.debug("stakeholder lookup failed: %s", e)
        return None
    if not rows:
        return None
    # Sort by oldest expected_response_by → most overdue.
    rows = sorted(rows, key=lambda c: c.expected_response_by or "9999-01-01")
    c = rows[0]
    days = (today - dt.date.fromisoformat(
        (c.expected_response_by or today.isoformat())[:10])).days
    L = _LABELS.get(lang, _LABELS["ru"])
    return f"📮 {c.name} ({c.role or 'contact'}) — {L['no_reply'].format(n=days)}"


def _deadline_horizon_line(today: dt.date, lang: str = "ru") -> Optional[str]:
    """Cross-project deadline summary: today + this week counts."""
    try:
        from agents import deadline_scanner as ds
    except ImportError:
        return None
    try:
        deads = ds.scan_all(today=today)
    except Exception as e:
        log.debug("deadline scan failed: %s", e)
        return None
    bk = ds.by_horizon(deads, today)
    today_n = len(bk["today"])
    week_n = len(bk["this_week"])
    overdue_n = len(bk["overdue"])
    if today_n == 0 and week_n == 0 and overdue_n == 0:
        return None
    L = _LABELS.get(lang, _LABELS["ru"])
    parts = []
    if today_n:
        parts.append(f"{today_n} {L['today_short']}")
    if week_n:
        parts.append(f"{week_n} {L['this_week']}")
    if overdue_n:
        parts.append(f"{overdue_n} {L['overdue_short']}")
    return f"{L['deadlines']}: " + ", ".join(parts)


# ── compose ──────────────────────────────────────────────────────


def compose(today: Optional[dt.date] = None,
            now: Optional[dt.datetime] = None,
            name: Optional[str] = None,
            max_chars: int = 280,
            lang: Optional[str] = None) -> str:
    today = today or dt.date.today()
    now = now or dt.datetime.now()
    lang = (lang or os.environ.get("AIM_BRIEF_LANG", "ru")).lower()
    if lang not in _GREETINGS:
        lang = "ru"
    if name is None:
        name = "Джаба" if lang == "ru" else ("Jaba" if lang == "en" else "ჯაბა")

    lines: list[str] = [_greeting(now, name=name, lang=lang)]
    for fn in (_hot_milestone_line, _stakeholder_line,
               _deadline_horizon_line):
        try:
            line = fn(today, lang=lang)
        except Exception as e:  # noqa: BLE001
            log.debug("preamble source failed (%s): %s", fn.__name__, e)
            continue
        if line:
            lines.append(line)
        if sum(len(l) for l in lines) > max_chars:
            break

    return "\n".join(lines)


def install_into_brief() -> str:
    """Compute the preamble and stash it into AIM_BRIEF_HEAD for the
    daily-brief script to pick up."""
    text = compose()
    os.environ["AIM_BRIEF_HEAD"] = text
    return text


def _main() -> int:
    print(compose())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
