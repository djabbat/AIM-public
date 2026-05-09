"""agents/health_extended.py — full system health snapshot (G9, 2026-05-03).

The existing `agents/self_health.py` covers individual subsystems. This
module aggregates project/eval/memory/cost signals into ONE structured
report (`/healthz/full` style) suitable for monitoring dashboards.

Output schema:
    {
      "ts": "...",
      "overall": "ok" | "warn" | "degraded",
      "subsystems": {
        "self_health":      <self_health.report() output if available>,
        "projects":         {count, archived, hot_milestones, overdue},
        "eval":             {latest_version, latest_score, trend_7d},
        "memory_hygiene":   {scanned, findings_total, broken_paths, obsolete_deadlines},
        "cost":             {daily, weekly, monthly, daily_pct},
        "stakeholder":      {overdue_count},
        "deadlines":        {today, this_week, overdue},
        "cron":             {last_brief, last_digest, last_eval},
      },
      "warnings": [...]
    }

Used by:
  * `aim health` CLI command (G8).
  * Telegram health probe.
  * GitHub Actions / external monitor → /healthz/full HTTP route.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("aim.health_extended")


def _safe(call, default=None):
    try:
        return call()
    except Exception as e:  # noqa: BLE001
        log.debug("health probe failed: %s", e)
        return default


# ── subsystem probes ─────────────────────────────────────────────


def _probe_self_health() -> dict:
    try:
        import agents.self_health as sh
    except ImportError:
        return {"status": "unavailable"}
    fn = getattr(sh, "report", None) or getattr(sh, "check", None)
    if fn is None:
        return {"status": "unavailable"}
    try:
        return fn() or {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": str(e)}


def _probe_projects(today: dt.date) -> dict:
    out = {"count": 0, "archived": 0, "hot_milestones": 0,
           "overdue_milestones": 0}
    try:
        from agents import project_owner as po
        names = po.list_projects()
        out["count"] = len(names)
        for n in names:
            try:
                state = po.load(n)
            except Exception:
                continue
            for m in state.milestones:
                if m.is_hot(today):
                    out["hot_milestones"] += 1
                d = m.days_to_deadline(today)
                if d is not None and d < 0 and m.status == "pending":
                    out["overdue_milestones"] += 1
    except Exception as e:
        out["error"] = str(e)
    try:
        from agents import project_archive as pa
        out["archived"] = len(pa.archived_list())
    except Exception:
        pass
    return out


def _probe_eval(today: dt.date) -> dict:
    out = {"latest_version": None, "latest_score": None, "trend_7d": None}
    try:
        import sqlite3
        from agents import evals as ev
        conn = sqlite3.connect(ev.db_path())
        row = conn.execute(
            "SELECT version, AVG(score) FROM eval_runs "
            "GROUP BY version ORDER BY MAX(run_at) DESC LIMIT 1").fetchone()
        if row:
            out["latest_version"] = row[0]
            out["latest_score"] = row[1]
        # Trend = average over last 7 days vs preceding 7.
        cutoff_a = (today - dt.timedelta(days=7)).isoformat()
        cutoff_b = (today - dt.timedelta(days=14)).isoformat()
        a = conn.execute(
            "SELECT AVG(score) FROM eval_runs WHERE date(run_at) >= ?",
            (cutoff_a,)).fetchone()[0]
        b = conn.execute(
            "SELECT AVG(score) FROM eval_runs "
            "WHERE date(run_at) >= ? AND date(run_at) < ?",
            (cutoff_b, cutoff_a)).fetchone()[0]
        conn.close()
        if a is not None and b is not None:
            out["trend_7d"] = a - b
    except Exception as e:
        out["error"] = str(e)
    return out


def _probe_memory() -> dict:
    out = {"scanned": 0, "findings_total": 0,
           "broken_paths": 0, "obsolete_deadlines": 0,
           "duplicates": 0}
    try:
        from agents import memory_monitor as mm
        rep = mm.scan(stale_months=6)
        out["scanned"] = rep.scanned
        out["findings_total"] = len(rep.findings)
        for f in rep.findings:
            if f.kind == "broken_path":
                out["broken_paths"] += 1
            elif f.kind == "obsolete_deadline":
                out["obsolete_deadlines"] += 1
            elif f.kind == "duplicate":
                out["duplicates"] += 1
    except Exception as e:
        out["error"] = str(e)
    return out


def _probe_cost(today: dt.date) -> dict:
    out: dict[str, Any] = {}
    try:
        from agents import cost_ledger as cl
        out["daily"] = cl.daily_cost(today=today)
        out["weekly"] = cl.weekly_cost(today=today)
        out["monthly"] = cl.monthly_cost(today=today)
        if cl.daily_budget() > 0:
            out["daily_pct"] = out["daily"] / cl.daily_budget()
    except Exception as e:
        out["error"] = str(e)
    return out


def _probe_stakeholders(today: dt.date) -> dict:
    out = {"overdue_count": 0, "awaiting_count": 0}
    try:
        from agents import stakeholder_tracker as st
        out["overdue_count"] = len(st.overdue_followups(today=today))
        out["awaiting_count"] = len(st.awaiting_reply())
    except Exception as e:
        out["error"] = str(e)
    return out


def _probe_deadlines(today: dt.date) -> dict:
    out = {"today": 0, "this_week": 0, "overdue": 0}
    try:
        from agents import deadline_scanner as ds
        deads = ds.scan_all(today=today)
        bk = ds.by_horizon(deads, today)
        out["today"] = len(bk["today"])
        out["this_week"] = len(bk["this_week"])
        out["overdue"] = len(bk["overdue"])
    except Exception as e:
        out["error"] = str(e)
    return out


def _probe_cron(today: dt.date) -> dict:
    """Best-effort: read the audit log timestamps for our scheduled scripts."""
    base = Path(os.environ.get("AIM_HOME") or
                Path.home() / ".cache" / "aim").expanduser()
    out = {}
    for filename, key in (
        ("notify.jsonl", "last_notification"),
        ("phase_history.jsonl", "last_phase_transition"),
        ("escalation.jsonl", "last_escalation"),
        ("permission_log.jsonl", "last_permission"),
        ("ab_router.db", "last_ab_decision"),
    ):
        p = base / filename
        if p.exists():
            ts = dt.datetime.fromtimestamp(p.stat().st_mtime)
            out[key] = ts.isoformat()
    return out


# ── overall verdict ──────────────────────────────────────────────


def _classify_overall(report: dict) -> tuple[str, list[str]]:
    warnings: list[str] = []

    cost = report.get("subsystems", {}).get("cost", {})
    pct = cost.get("daily_pct", 0)
    if pct and pct >= 1.0:
        warnings.append(f"daily cost over budget ({pct:.0%})")
    elif pct and pct >= 0.85:
        warnings.append(f"daily cost near budget ({pct:.0%})")

    mem = report.get("subsystems", {}).get("memory_hygiene", {})
    if mem.get("broken_paths", 0) > 50:
        warnings.append(f"{mem['broken_paths']} broken memory paths")

    proj = report.get("subsystems", {}).get("projects", {})
    if proj.get("overdue_milestones", 0) > 0:
        warnings.append(
            f"{proj['overdue_milestones']} overdue milestones")

    sh_status = report.get("subsystems", {}).get("self_health", {}).get("status")
    if sh_status not in (None, "ok", "unavailable"):
        warnings.append(f"self_health: {sh_status}")

    deadlines = report.get("subsystems", {}).get("deadlines", {})
    if deadlines.get("today", 0) >= 5:
        warnings.append(f"{deadlines['today']} deadlines today")

    overall = "ok"
    if any("over budget" in w or "self_health" in w for w in warnings):
        overall = "degraded"
    elif warnings:
        overall = "warn"
    return overall, warnings


# ── public API ───────────────────────────────────────────────────


def report(today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    rep = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "subsystems": {
            "self_health":    _safe(_probe_self_health, default={}),
            "projects":       _safe(lambda: _probe_projects(today), default={}),
            "eval":           _safe(lambda: _probe_eval(today), default={}),
            "memory_hygiene": _safe(_probe_memory, default={}),
            "cost":           _safe(lambda: _probe_cost(today), default={}),
            "stakeholders":   _safe(lambda: _probe_stakeholders(today), default={}),
            "deadlines":      _safe(lambda: _probe_deadlines(today), default={}),
            "cron":           _safe(lambda: _probe_cron(today), default={}),
        },
    }
    overall, warnings = _classify_overall(rep)
    rep["overall"] = overall
    rep["warnings"] = warnings
    return rep


def report_json(today: dt.date | None = None) -> str:
    return json.dumps(report(today=today), ensure_ascii=False, indent=2)
