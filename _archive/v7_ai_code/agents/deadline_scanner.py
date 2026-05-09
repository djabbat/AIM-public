"""agents/deadline_scanner.py — calendar-aware deadline scanner (P2, 2026-05-02).

Aggregates deadlines from three sources into one unified view:

  1. Project YAML milestones (USER/projects/<name>.yaml — parsed by
     project_owner.load).
  2. Memory files (~/.claude/projects/-home-oem/memory/project_*.md and
     ~/Desktop/<project>/{CONCEPT,TODO,STATE,REMINDER,NEEDTOWRITE}.md) —
     scanned for YYYY-MM-DD dates and `**Deadline:**` markers.
  3. Google Calendar events (optional: when running inside the AIM CLI
     with a live Calendar MCP connection, pulled via callable hook).

Output is sorted by absolute date with a horizon partitioner:
  - today
  - this week (1-7d ahead)
  - this month (8-30d ahead)
  - overdue (negative)

Public API:
    scan_all(today=None, calendar_pull=None) -> list[Deadline]
    by_horizon(deadlines, today=None) -> dict[str, list[Deadline]]
    summary(today=None, calendar_pull=None) -> str  # ready to print

`calendar_pull` is an optional callable that returns a list of dicts
shaped like {"summary": ..., "start": "2026-05-10", "source": "gcal"}.
The MCP wiring lives outside this module so we can unit-test the parser
without standing up Google auth.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import re
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger("aim.deadline_scanner")

# ── date extraction ──────────────────────────────────────────────────

# YYYY-MM-DD anywhere; we restrict 19xx-21xx to dodge phone numbers.
_DATE_RE = re.compile(
    r"\b(?P<y>(?:19|20|21)\d{2})-(?P<m>0[1-9]|1[0-2])-(?P<d>0[1-9]|[12]\d|3[01])\b"
)
# Lines like "**Deadline:** 2026-10-28 17:00 CET" or
# "deadline 2026-09-30" — give them more weight when classifying.
_DEADLINE_LINE_RE = re.compile(
    r"(?i)(?:deadline|due|by|до|дедлайн)[\s:*\-]*"
    r"(?P<y>(?:19|20|21)\d{2})-(?P<m>0[1-9]|1[0-2])-(?P<d>0[1-9]|[12]\d|3[01])"
)


@dataclasses.dataclass(frozen=True)
class Deadline:
    when: dt.date
    label: str          # one-line excerpt
    source: str         # path or "gcal" / "yaml:<name>"
    kind: str           # "milestone" | "memory" | "calendar"
    criticality: str = "medium"

    def days_from(self, today: dt.date) -> int:
        return (self.when - today).days


# ── memory & desktop scanners ────────────────────────────────────────


def _memory_files() -> list[Path]:
    """Files we'll scan for ad-hoc deadlines.

    Limited to per-project memory and project core docs to keep the scan
    fast (≤200 files). Caches: skip __pycache__ etc.
    """
    out: list[Path] = []
    mem = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
    if mem.exists():
        out.extend(p for p in mem.glob("project_*.md"))
        # MEMORY.md itself is index — skip; but include other top-level
        # signal files like fact_*.md if user wrote a deadline there.
        out.extend(p for p in mem.glob("fact_*.md"))
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        for proj_dir in desktop.iterdir():
            if not proj_dir.is_dir() or proj_dir.name.startswith("."):
                continue
            for fname in ("TODO.md", "REMINDER.md", "NEEDTOWRITE.md",
                          "CONCEPT.md", "STATE.md"):
                p = proj_dir / fname
                if p.exists():
                    out.append(p)
    return out


# Past-tense / historical-event markers — if any of these appear on
# a line WITH a date, the date is a recorded event, not a deadline.
_HISTORICAL_RE = re.compile(
    r"\b(consented|sent|submitted|fired|received|replied|"
    r"approved|signed|published|merged|closed|deployed|"
    r"completed|done|notified|delivered|invited|confirmed|"
    r"reversed|reconciled|deferred|established|supersedes|"
    r"effective|audit failures|wave|"
    r"подал|отправлен|подписан|подтверждено|опубликован|"
    r"завершено|выполнено|отменено|установлено|подтвердил|"
    r"закрыта|закрыт|закрыто|волна|"
    r"received)\b",
    re.IGNORECASE,
)
# Lines marked done with status emoji (✅ or ✔) at start are historical.
_DONE_PREFIX_RE = re.compile(r"^\s*[-*]?\s*[✅✔]\s")
# Markdown table row marker (`| ... |`).
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
# Heading lines (markdown `# / ## / ###`) are section markers, not
# deadlines.
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
# YAML/markdown metadata fields: `description: ...`, `name: ...`,
# `note: ...` — context, not actionable deadlines.
_METADATA_LINE_RE = re.compile(
    r"^\s*(description|name|note|status|origin\w*|type|quote|source):",
    re.IGNORECASE,
)
# Blockquote lines `> ...` — historical quotes.
_QUOTE_LINE_RE = re.compile(r"^\s*>\s")


def _is_historical(line: str) -> bool:
    """A line that records an event in the past, not a future deadline."""
    if _HEADING_RE.match(line):
        return True
    if _METADATA_LINE_RE.match(line):
        return True
    if _QUOTE_LINE_RE.match(line):
        return True
    if _DONE_PREFIX_RE.match(line):
        return True   # ✅ / ✔ prefix = completed event
    if _TABLE_LINE_RE.match(line):
        return True   # table cells are records, not deadlines
    if _HISTORICAL_RE.search(line):
        return True
    return False


def _extract_deadlines_from_text(
    text: str, source: str,
) -> Iterable[Deadline]:
    seen: set[tuple[dt.date, str]] = set()
    for line in text.splitlines():
        line_label = line.strip()[:160]
        # Strong "deadline: <date>" markers — every match gets high criticality.
        deadline_dates: set[dt.date] = set()
        for m in _DEADLINE_LINE_RE.finditer(line):
            try:
                d = dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                continue
            key = (d, line_label[:60])
            if key in seen:
                continue
            seen.add(key)
            deadline_dates.add(d)
            yield Deadline(when=d, label=line_label, source=source,
                           kind="memory", criticality="high")
        # Plain ISO dates — fire once per distinct date in the line.
        # Skip historical-event / markdown-table rows (high false-positive
        # rate per 2026-05-04 audit: 80% of "overdue" were ledger noise).
        if _is_historical(line):
            continue
        for m in _DATE_RE.finditer(line):
            try:
                d = dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                continue
            if d in deadline_dates:
                continue   # already emitted with high criticality
            key = (d, line_label[:60])
            if key in seen:
                continue
            seen.add(key)
            yield Deadline(when=d, label=line_label, source=source,
                           kind="memory")


def scan_memory(today: dt.date,
                horizon_back: int = 30,
                horizon_fwd: int = 365) -> list[Deadline]:
    """Walk memory & core .md files and pull plausible deadlines.

    `horizon_back/_fwd` filter out dates obviously irrelevant (e.g. past
    publication years 2017, far-future planning 2050).

    Deadlines that are already past get demoted from `high` → `medium`:
    a missed deadline is no longer actionable in the same way as a
    pending one.
    """
    out: list[Deadline] = []
    for p in _memory_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for d in _extract_deadlines_from_text(text, str(p)):
            delta = (d.when - today).days
            if delta < -horizon_back or delta > horizon_fwd:
                continue
            if delta < 0 and d.criticality == "high":
                d = dataclasses.replace(d, criticality="medium")
            out.append(d)
    return out


def scan_yaml(today: dt.date) -> list[Deadline]:
    """Translate every project_owner.Milestone with a deadline into a Deadline."""
    from agents import project_owner as po
    out: list[Deadline] = []
    for name in po.list_projects():
        try:
            state = po.load(name)
        except (FileNotFoundError, ValueError):
            continue
        for m in state.milestones:
            if m.deadline is None:
                continue
            out.append(Deadline(
                when=m.deadline.date(),
                label=f"{state.name}: {m.id}"
                      + (f" — {', '.join(m.blockers[:2])}" if m.blockers else ""),
                source=f"yaml:{state.name}",
                kind="milestone",
                criticality=m.criticality,
            ))
    return out


# ── calendar adapter ─────────────────────────────────────────────────


def scan_calendar(today: dt.date,
                  pull: Optional[Callable[[], list[dict]]],
                  horizon_fwd: int = 60) -> list[Deadline]:
    if pull is None:
        return []
    try:
        events = pull() or []
    except Exception as e:
        log.warning("calendar pull failed: %s", e)
        return []
    out: list[Deadline] = []
    for ev in events:
        start = ev.get("start") or ev.get("date")
        if not start:
            continue
        try:
            d = dt.date.fromisoformat(str(start)[:10])
        except ValueError:
            continue
        if d < today or (d - today).days > horizon_fwd:
            continue
        out.append(Deadline(
            when=d,
            label=str(ev.get("summary") or "(calendar event)")[:160],
            source="gcal",
            kind="calendar",
        ))
    return out


# ── aggregation & summary ────────────────────────────────────────────


def scan_all(today: Optional[dt.date] = None,
             calendar_pull: Optional[Callable[[], list[dict]]] = None,
             ) -> list[Deadline]:
    today = today or dt.date.today()
    out: list[Deadline] = []
    out.extend(scan_yaml(today))
    out.extend(scan_memory(today))
    out.extend(scan_calendar(today, calendar_pull))
    # de-dupe: same date + same label substring → collapse, prefer
    # milestone source (most authoritative).
    seen: dict[tuple[dt.date, str], Deadline] = {}
    weight = {"milestone": 0, "calendar": 1, "memory": 2}
    for d in sorted(out, key=lambda x: (x.when, weight.get(x.kind, 9))):
        key = (d.when, d.label[:80].lower())
        seen.setdefault(key, d)
    return sorted(seen.values(), key=lambda x: x.when)


def conflicts(deadlines: list[Deadline],
               *,
               window_days: int = 7,
               min_critical_per_day: int = 2,
               ) -> list[tuple[dt.date, list[Deadline]]]:
    """Return [(date, [deadline, …])] for any day with multiple deadlines.

    `window_days` filters to dates between today and today+window_days.
    Days with `< min_critical_per_day` deadlines are skipped. Only
    counts non-overdue (delta >= 0) — the user can already see overdue
    items in the brief; we want them to spot day-of crowding.
    """
    today = dt.date.today()
    by_date: dict[dt.date, list[Deadline]] = {}
    for d in deadlines:
        delta = d.days_from(today)
        if delta < 0 or delta > window_days:
            continue
        by_date.setdefault(d.when, []).append(d)
    return [(date, items) for date, items in sorted(by_date.items())
            if len(items) >= min_critical_per_day]


def by_horizon(deadlines: list[Deadline],
               today: Optional[dt.date] = None) -> dict[str, list[Deadline]]:
    today = today or dt.date.today()
    buckets: dict[str, list[Deadline]] = {
        "overdue": [],
        "today": [],
        "this_week": [],   # 1-7 days
        "this_month": [],  # 8-30 days
        "later": [],
    }
    for d in deadlines:
        delta = d.days_from(today)
        if delta < 0:
            buckets["overdue"].append(d)
        elif delta == 0:
            buckets["today"].append(d)
        elif delta <= 7:
            buckets["this_week"].append(d)
        elif delta <= 30:
            buckets["this_month"].append(d)
        else:
            buckets["later"].append(d)
    return buckets


def summary(today: Optional[dt.date] = None,
            calendar_pull: Optional[Callable[[], list[dict]]] = None,
            ) -> str:
    today = today or dt.date.today()
    deads = scan_all(today, calendar_pull)
    bk = by_horizon(deads, today)

    sections = [
        ("⛔ overdue",     bk["overdue"],    True),
        ("📍 today",       bk["today"],      True),
        ("📅 this week",   bk["this_week"],  True),
        ("🗓  this month", bk["this_month"], False),
    ]
    out = [f"Deadlines as of {today.isoformat()} (total {len(deads)}):"]
    for header, items, always in sections:
        if not items and not always:
            continue
        out.append("")
        out.append(f"{header} ({len(items)})")
        for d in items[:8]:
            delta = d.days_from(today)
            tag = (f"{abs(delta)}d ago" if delta < 0
                   else "today" if delta == 0
                   else f"+{delta}d")
            out.append(f"  • {d.when} ({tag})  {d.label[:120]}  [{d.kind}]")
    if not deads:
        out.append("(no deadlines on the radar)")
    return "\n".join(out)


def _main() -> int:
    print(summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
