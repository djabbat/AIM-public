"""agents/kpi_auto_updater.py — observed-signal → KPI bridge (P7, 2026-05-03).

Project YAMLs declare KPIs; manually `record()`-ing each new value is
tedious. This module subscribes a KPI to a *named source* and runs once
per scheduling tick (typically daily) to push the latest observed value
into the KPI history.

Subscriptions live in the project YAML:

    kpis:
      - id: weekly-llm-cost
        target: 25.0
        target_kind: ceiling
        source: cost.weekly         # source name (registry below)
      - id: stakeholder-count
        target: 10
        source: stakeholders.total
      - id: eval-score
        target: 0.85
        source: eval.latest
      - id: pubmed-publications
        target: 8
        source: literature.own_count

Sources are bound in `_SOURCES` (free-form callables that read from
existing modules). Any unsupported source falls through and is left
manual.

Public API:
    sync(today=None) -> dict[project, list[(kpi_id, value)]]
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, Optional

log = logging.getLogger("aim.kpi_auto_updater")


# ── source bindings ─────────────────────────────────────────────


def _src_cost_weekly(today: dt.date) -> float:
    from agents import cost_ledger as cl
    return cl.weekly_cost(today=today)


def _src_cost_daily(today: dt.date) -> float:
    from agents import cost_ledger as cl
    return cl.daily_cost(today=today)


def _src_cost_monthly(today: dt.date) -> float:
    from agents import cost_ledger as cl
    return cl.monthly_cost(today=today)


def _src_stakeholders_total(today: dt.date) -> float:
    from agents import stakeholder_tracker as st
    return float(len(st.all_contacts()))


def _src_stakeholders_overdue(today: dt.date) -> float:
    from agents import stakeholder_tracker as st
    return float(len(st.overdue_followups(today=today)))


def _src_eval_latest(today: dt.date) -> Optional[float]:
    """Average score across the most recent eval-run version."""
    try:
        import sqlite3
        from agents import evals as ev
        conn = sqlite3.connect(ev.db_path())
        cur = conn.execute(
            "SELECT AVG(score) FROM eval_runs "
            "WHERE version=("
            "  SELECT version FROM eval_runs ORDER BY run_at DESC LIMIT 1"
            ")")
        v = cur.fetchone()[0]
        conn.close()
        return float(v) if v is not None else None
    except Exception:
        return None


def _src_memory_findings(today: dt.date) -> float:
    from agents import memory_monitor as mm
    return float(len(mm.scan().findings))


def _src_literature_own_count(today: dt.date) -> Optional[float]:
    from agents import literature_watch as lw
    try:
        return float(len(lw._own_pmids()))
    except Exception:
        return None


_SOURCES: dict[str, Callable[[dt.date], Optional[float]]] = {
    "cost.daily":             _src_cost_daily,
    "cost.weekly":            _src_cost_weekly,
    "cost.monthly":           _src_cost_monthly,
    "stakeholders.total":     _src_stakeholders_total,
    "stakeholders.overdue":   _src_stakeholders_overdue,
    "eval.latest":            _src_eval_latest,
    "memory.findings":        _src_memory_findings,
    "literature.own_count":   _src_literature_own_count,
}


# ── orchestration ───────────────────────────────────────────────


def _kpi_source(project: str, kpi_id: str) -> Optional[str]:
    """Re-read the YAML to find the `source:` field for a KPI."""
    import yaml
    from agents import project_owner as po
    p = po.projects_dir() / f"{project}.yaml"
    if not p.exists():
        return None
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for k in raw.get("kpis") or []:
        if str(k.get("id")) == kpi_id:
            src = k.get("source")
            return str(src) if src else None
    return None


def sync(today: Optional[dt.date] = None) -> dict:
    """Walk every project's KPIs; for each KPI with a known source,
    record() its latest observed value.

    Returns a dict {project_name: [(kpi_id, value), ...]} of all
    successful updates. Idempotent within a day: skip if a point with
    today's date already exists for that KPI.
    """
    today = today or dt.date.today()
    from agents import project_owner as po
    from agents import kpi_tracker as kt
    out: dict[str, list] = {}
    for proj in po.list_projects():
        try:
            kpis = kt.load(proj)
        except Exception as e:
            log.debug("skip %s: %s", proj, e)
            continue
        for k in kpis:
            src = _kpi_source(proj, k.id)
            if not src or src not in _SOURCES:
                continue
            # Skip if today's value already recorded.
            already = any(p.date == today for p in k.history)
            if already:
                continue
            try:
                value = _SOURCES[src](today)
            except Exception as e:
                log.warning("source %s failed: %s", src, e)
                continue
            if value is None:
                continue
            try:
                kt.record(proj, k.id, float(value), date=today)
                out.setdefault(proj, []).append((k.id, float(value)))
            except Exception as e:
                log.warning("record %s/%s failed: %s", proj, k.id, e)
    return out
