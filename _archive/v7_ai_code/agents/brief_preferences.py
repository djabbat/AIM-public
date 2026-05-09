"""agents/brief_preferences.py — user-tunable brief delivery (B2, 2026-05-03).

Reads `USER/preferences/brief.yaml` (or env override) and returns a
single resolved Preferences object that scripts/daily_brief.py and
weekly_digest.py consult before delivery.

Schema:

    lang:       ru                # default RU; ka / en
    user_name:  Джаба             # injected into preamble
    quiet_hours: ["23:00", "07:00"]   # never deliver inside this window
    channels:
      daily:    [telegram, stdout]
      weekly:   [telegram, email, stdout]
    include:
      sections: [hot_milestones, overdue_followups, awaiting_reply,
                 deadlines, kpis, phase_actions]
      projects: ["FCLC", "MCOA"]   # whitelist; null/empty = all
    exclude:
      projects: []                 # explicit hide
    digest:
      window_days: 7

Defaults are conservative — missing fields fall back to lang=ru,
channels=["telegram","stdout"], all sections, all projects.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.brief_preferences")


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Preferences:
    lang: str = "ru"
    user_name: Optional[str] = None
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    daily_channels: list[str] = dataclasses.field(
        default_factory=lambda: ["telegram", "stdout"])
    weekly_channels: list[str] = dataclasses.field(
        default_factory=lambda: ["telegram", "email", "stdout"])
    include_sections: list[str] = dataclasses.field(
        default_factory=lambda: ["hot_milestones", "overdue_followups",
                                  "awaiting_reply", "deadlines",
                                  "kpis", "phase_actions"])
    include_projects: list[str] = dataclasses.field(default_factory=list)
    exclude_projects: list[str] = dataclasses.field(default_factory=list)
    digest_window_days: int = 7

    def project_visible(self, name: str) -> bool:
        if self.exclude_projects and name in self.exclude_projects:
            return False
        if self.include_projects:
            return name in self.include_projects
        return True

    def section_visible(self, name: str) -> bool:
        if not self.include_sections:
            return True
        return name in self.include_sections


# ── path resolution ──────────────────────────────────────────────


def prefs_path() -> Path:
    env = os.environ.get("AIM_BRIEF_PREFS")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "USER" / "preferences" / "brief.yaml"


# ── parsing ──────────────────────────────────────────────────────


def _parse_quiet(window) -> tuple[Optional[str], Optional[str]]:
    if not window:
        return None, None
    if isinstance(window, list) and len(window) == 2:
        a, b = window
        return str(a), str(b)
    return None, None


def load() -> Preferences:
    p = prefs_path()
    prefs = Preferences()
    if not p.exists():
        return prefs
    try:
        import yaml
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("brief prefs parse failed (%s): %s", p, e)
        return prefs
    if not isinstance(raw, dict):
        return prefs

    if "lang" in raw:
        prefs.lang = str(raw["lang"]).lower()
    if "user_name" in raw:
        prefs.user_name = str(raw["user_name"])
    qs, qe = _parse_quiet(raw.get("quiet_hours"))
    prefs.quiet_start, prefs.quiet_end = qs, qe

    channels = raw.get("channels") or {}
    if isinstance(channels, dict):
        if "daily" in channels and isinstance(channels["daily"], list):
            prefs.daily_channels = [str(c) for c in channels["daily"]]
        if "weekly" in channels and isinstance(channels["weekly"], list):
            prefs.weekly_channels = [str(c) for c in channels["weekly"]]

    include = raw.get("include") or {}
    if isinstance(include, dict):
        if isinstance(include.get("sections"), list):
            prefs.include_sections = [str(s) for s in include["sections"]]
        if isinstance(include.get("projects"), list):
            prefs.include_projects = [str(p) for p in include["projects"]]

    exclude = raw.get("exclude") or {}
    if isinstance(exclude, dict) and isinstance(exclude.get("projects"), list):
        prefs.exclude_projects = [str(p) for p in exclude["projects"]]

    digest = raw.get("digest") or {}
    if isinstance(digest, dict) and "window_days" in digest:
        try:
            prefs.digest_window_days = int(digest["window_days"])
        except (TypeError, ValueError):
            pass

    return prefs


# ── quiet-hours check ────────────────────────────────────────────


def in_quiet_hours(now: Optional[dt.time] = None,
                   prefs: Optional[Preferences] = None) -> bool:
    """True if `now` falls inside [quiet_start, quiet_end). Wraps midnight."""
    prefs = prefs or load()
    if not (prefs.quiet_start and prefs.quiet_end):
        return False
    now = now or dt.datetime.now().time()
    try:
        start = dt.time.fromisoformat(prefs.quiet_start)
        end = dt.time.fromisoformat(prefs.quiet_end)
    except ValueError:
        return False
    if start == end:
        return False
    if start < end:
        return start <= now < end
    # Wraps midnight (e.g. 23:00 → 07:00).
    return now >= start or now < end


def daily_channels(prefs: Optional[Preferences] = None) -> list[str]:
    prefs = prefs or load()
    return list(prefs.daily_channels)


def weekly_channels(prefs: Optional[Preferences] = None) -> list[str]:
    prefs = prefs or load()
    return list(prefs.weekly_channels)
