"""agents/project_owner.py — Project Owner Agent (P1, 2026-05-02).

A long-running agent that *owns* a project for weeks, not just answers
prompts. Loads a YAML state file per project, monitors goals / milestones
/ stakeholders / deadlines, and produces a morning brief listing what's
hot today.

Project YAML schema (USER/projects/<name>.yaml):

    name:        FCLC
    canonical:   /home/oem/Desktop/LongevityCommon/FCLC
    phase:       SUBMITTED            # DRAFT|REVIEW|SUBMITTED|ACCEPTED|PUBLISHED
    goals:
      - Get EIC Pathfinder Challenges 2026 funded (€3M, 36 mo)
    milestones:
      - id: eic-submit
        deadline: 2026-10-28T17:00:00+02:00
        status: pending                  # pending|done|blocked
        blockers:
          - Need ≥2 EU-MS Co-PI LoIs
        criticality: high
    stakeholders:
      - name: Hartmut Geiger
        role: Co-PI Phase B
        last_contact: 2026-04-23
        awaiting_reply: false
        expected_response_by: ~
        notes: LoS signed
      - name: Miguel A. Gonzalez Ballester
        role: Potential Co-PI (UPF)
        last_contact: 2026-04-28
        awaiting_reply: true
        expected_response_by: 2026-05-05
        notes: Promised reply in a few days
    daily_checks:
      - "EIC submission deadline countdown"
      - "Stakeholder follow-ups"
    escalation_rules:
      - when: deadline_within_days <= 7 and milestone.criticality=='high'
        action: telegram_alert

Public API:
    morning_brief(project="FCLC")  -> str   # ready-to-send Telegram brief
    list_projects()                -> list[str]
    load(project)                  -> ProjectState
    overdue_followups(project, today=None) -> list[str]
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.project_owner")


def projects_dir() -> Path:
    """Resolve <AIM>/USER/projects, honoring an optional override.

    AIM_PROJECTS_DIR=/path/to/somewhere lets tests point to a tmp dir.
    """
    env = os.environ.get("AIM_PROJECTS_DIR")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "USER" / "projects"


# ── Data classes ──────────────────────────────────────────────────────


@dataclasses.dataclass
class Stakeholder:
    name: str
    role: str = ""
    last_contact: Optional[dt.date] = None
    awaiting_reply: bool = False
    expected_response_by: Optional[dt.date] = None
    notes: str = ""

    def days_silent(self, today: dt.date) -> Optional[int]:
        if self.last_contact is None:
            return None
        return (today - self.last_contact).days

    def overdue(self, today: dt.date) -> bool:
        if not self.awaiting_reply or self.expected_response_by is None:
            return False
        return today > self.expected_response_by


@dataclasses.dataclass
class Milestone:
    id: str
    deadline: Optional[dt.datetime] = None
    status: str = "pending"
    blockers: list[str] = dataclasses.field(default_factory=list)
    criticality: str = "medium"   # low | medium | high

    def days_to_deadline(self, today: dt.date) -> Optional[int]:
        if self.deadline is None:
            return None
        return (self.deadline.date() - today).days

    def is_hot(self, today: dt.date) -> bool:
        d = self.days_to_deadline(today)
        if d is None or self.status != "pending":
            return False
        return d <= 7 or (self.criticality == "high" and d <= 14)


@dataclasses.dataclass
class ProjectState:
    name: str
    canonical: str = ""
    phase: str = "DRAFT"
    goals: list[str] = dataclasses.field(default_factory=list)
    milestones: list[Milestone] = dataclasses.field(default_factory=list)
    stakeholders: list[Stakeholder] = dataclasses.field(default_factory=list)
    daily_checks: list[str] = dataclasses.field(default_factory=list)


# ── Loaders ──────────────────────────────────────────────────────────


def _parse_date(v) -> Optional[dt.date]:
    if v is None or v == "" or v == "~":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        try:
            return dt.date.fromisoformat(v.split("T", 1)[0])
        except ValueError:
            return None
    return None


def _parse_datetime(v) -> Optional[dt.datetime]:
    if v is None or v == "" or v == "~":
        return None
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    if isinstance(v, str):
        try:
            return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            try:
                return dt.datetime.fromisoformat(v[:19])
            except ValueError:
                return None
    return None


def list_projects() -> list[str]:
    d = projects_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def load(project: str) -> ProjectState:
    """Read USER/projects/<project>.yaml and return a ProjectState.

    Tolerant to missing fields. Raises FileNotFoundError if YAML doesn't
    exist; ValueError if it's not a mapping.
    """
    import yaml
    path = projects_dir() / f"{project}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no project YAML at {path}")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level must be a mapping")

    ms: list[Milestone] = []
    for m in raw.get("milestones") or []:
        ms.append(Milestone(
            id=str(m.get("id", "")),
            deadline=_parse_datetime(m.get("deadline")),
            status=str(m.get("status", "pending")),
            blockers=list(m.get("blockers") or []),
            criticality=str(m.get("criticality", "medium")),
        ))

    sh: list[Stakeholder] = []
    for s in raw.get("stakeholders") or []:
        sh.append(Stakeholder(
            name=str(s.get("name", "")),
            role=str(s.get("role", "")),
            last_contact=_parse_date(s.get("last_contact")),
            awaiting_reply=bool(s.get("awaiting_reply", False)),
            expected_response_by=_parse_date(s.get("expected_response_by")),
            notes=str(s.get("notes", "")),
        ))

    return ProjectState(
        name=str(raw.get("name", project)),
        canonical=str(raw.get("canonical", "")),
        phase=str(raw.get("phase", "DRAFT")),
        goals=list(raw.get("goals") or []),
        milestones=ms,
        stakeholders=sh,
        daily_checks=list(raw.get("daily_checks") or []),
    )


# ── Brief generation ─────────────────────────────────────────────────


def overdue_followups(project: str, today: Optional[dt.date] = None) -> list[str]:
    today = today or dt.date.today()
    state = load(project)
    out: list[str] = []
    for s in state.stakeholders:
        if s.overdue(today):
            days = (today - (s.expected_response_by or today)).days
            out.append(f"{s.name} ({s.role}) — overdue by {days}d")
    return out


def hot_milestones(state: ProjectState, today: dt.date) -> list[Milestone]:
    return [m for m in state.milestones if m.is_hot(today)]


def morning_brief(project: str, today: Optional[dt.date] = None) -> str:
    """Render a one-screen status brief — what's hot today.

    Output is plain text suitable for Telegram or terminal. Targets ≤ 30
    lines so it actually gets read.
    """
    today = today or dt.date.today()
    state = load(project)

    lines: list[str] = []
    lines.append(f"📌 {state.name} — {today.isoformat()}")
    lines.append(f"phase: {state.phase}")
    if state.goals:
        lines.append(f"goal: {state.goals[0]}")

    hot = hot_milestones(state, today)
    if hot:
        lines.append("")
        lines.append(f"🔥 hot milestones ({len(hot)}):")
        for m in sorted(hot, key=lambda x: x.days_to_deadline(today) or 9999):
            d = m.days_to_deadline(today)
            tag = "TODAY" if d == 0 else (f"in {d}d" if d > 0 else f"OVERDUE {-d}d")
            line = f"  • {m.id} — {tag} [{m.criticality}]"
            if m.blockers:
                line += f"  blockers: {', '.join(m.blockers[:2])}"
            lines.append(line)

    overdue = [s for s in state.stakeholders if s.overdue(today)]
    if overdue:
        lines.append("")
        lines.append(f"📮 overdue follow-ups ({len(overdue)}):")
        for s in overdue:
            d = (today - (s.expected_response_by or today)).days
            lines.append(f"  • {s.name} ({s.role}) — {d}d past expected reply")

    awaiting = [s for s in state.stakeholders
                if s.awaiting_reply and not s.overdue(today)]
    if awaiting:
        lines.append("")
        lines.append(f"⏳ awaiting reply ({len(awaiting)}):")
        for s in awaiting[:5]:
            silent = s.days_silent(today)
            silent_s = f", {silent}d silent" if silent is not None else ""
            lines.append(f"  • {s.name} ({s.role}{silent_s})")

    if state.daily_checks:
        lines.append("")
        lines.append("✅ daily checks:")
        for c in state.daily_checks:
            lines.append(f"  • {c}")

    # Phase-aware next-action advisory (P5).
    try:
        from agents.project_state_machine import next_actions
        acts = next_actions(state.phase)
    except Exception:
        acts = []
    if acts:
        lines.append("")
        lines.append(f"📐 phase {state.phase} — next actions:")
        for a in acts:
            lines.append(f"  • {a}")

    # KPI dashboard (K1, 2026-05-03).
    try:
        from agents.kpi_tracker import summary as _kpi_summary
        kpi_block = _kpi_summary(state.name)
    except Exception:
        kpi_block = ""
    if kpi_block:
        lines.append("")
        lines.append(kpi_block)

    if not (hot or overdue or awaiting):
        lines.append("")
        lines.append("✨ nothing on fire today.")

    return "\n".join(lines)


def all_briefs(today: Optional[dt.date] = None) -> str:
    """Concatenate morning_brief() for every YAML in projects_dir."""
    today = today or dt.date.today()
    parts = []
    for name in list_projects():
        try:
            parts.append(morning_brief(name, today))
        except (FileNotFoundError, ValueError) as e:
            parts.append(f"❌ {name}: failed to render — {e}")
    return "\n\n———\n\n".join(parts) if parts else "(no projects configured)"


# ── CLI entrypoint ───────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Project Owner Agent — morning brief")
    ap.add_argument("project", nargs="?", default=None,
                    help="project name (omit for ALL configured projects)")
    ap.add_argument("--list", action="store_true", help="list configured projects")
    args = ap.parse_args()
    if args.list:
        for n in list_projects():
            print(n)
        return 0
    if args.project:
        try:
            print(morning_brief(args.project))
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            return 1
    else:
        print(all_briefs())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
