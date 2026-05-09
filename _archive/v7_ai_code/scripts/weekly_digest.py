#!/usr/bin/env python3
"""scripts/weekly_digest.py — Self-improvement digest (T1, 2026-05-03).

A 10-line snapshot of what AIM noticed and what it changed about itself
in the last 7 days. Run from a systemd timer once a week.

Sources aggregated:
  * pattern_miner.summary(7)          — flaky tools, slow tools, dupes
  * ab_router.history()               — promote/keep verdicts
  * prompt_evolver.history()          — prompt patches landed
  * tool_synthesis.history()          — new tools registered
  * skill_synthesis.history()         — new skills registered
  * evals: latest aggregate score per known version (best-effort)

Routing identical to scripts/daily_brief.py: chunked Telegram if
TELEGRAM_BOT_TOKEN + AIM_TELEGRAM_CHAT_ID set, otherwise stdout.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

logging.basicConfig(level=os.environ.get("AIM_LOGLEVEL", "INFO"))
log = logging.getLogger("aim.weekly_digest")


def _section(title: str, body: str) -> str:
    return f"### {title}\n{body}".rstrip()


def _safe(call, default="(unavailable)"):
    try:
        return call()
    except Exception as e:  # noqa: BLE001
        log.debug("digest source failed: %s", e)
        return default


def render_digest(today: dt.date | None = None, window_days: int = 7) -> str:
    today = today or dt.date.today()
    start = today - dt.timedelta(days=window_days)
    parts: list[str] = []
    parts.append(f"📊 AIM weekly self-improvement digest")
    parts.append(f"   {start.isoformat()} → {today.isoformat()}")
    parts.append("")

    # 1. Pattern miner
    from agents import pattern_miner as pm
    parts.append(_section("🔎 Pattern findings",
                          _safe(lambda: pm.summary(window_days=window_days))))

    # 2. A/B router decisions in window.
    from agents import ab_router as ar
    def ab_lines() -> str:
        rows = _safe(lambda: ar.history(limit=50), default=[])
        if not isinstance(rows, list) or not rows:
            return "(no A/B decisions yet)"
        cutoff = start.isoformat()
        kept: list[str] = []
        for r in rows:
            t = (r.get("decided_at") or "")[:10]
            if t < cutoff:
                continue
            kept.append(
                f"  • {t}  {r.get('challenger','?')} vs "
                f"{r.get('baseline','?')} → {r.get('verdict','?')}"
                + (f"  Δ={r.get('delta'):+.3f}" if r.get('delta') is not None else "")
            )
        return "\n".join(kept) if kept else "(no decisions in window)"
    parts.append(_section("⚖️ A/B router", ab_lines()))

    # 3. Prompt evolver patches.
    from agents import prompt_evolver as pe
    def pe_lines() -> str:
        rows = _safe(lambda: pe.history(limit=50), default=[])
        if not rows:
            return "(no prompt evolution events yet)"
        cutoff = start.isoformat()
        kept = [r for r in rows if (r.get("ts") or "")[:10] >= cutoff]
        if not kept:
            return "(no prompt evolution in window)"
        out = []
        for r in kept:
            verdict = r.get("verdict", "?")
            key = r.get("key", "?")
            note = r.get("note", "")
            out.append(f"  • {r.get('ts','?')[:16]}  {key} → {verdict}  {note}")
        return "\n".join(out)
    parts.append(_section("🧬 Prompt evolution", pe_lines()))

    # 4. Tool synthesis registry events.
    from agents import tool_synthesis as ts
    def ts_lines() -> str:
        rows = _safe(lambda: ts.history(limit=50), default=[])
        if not rows:
            return "(no synthesised tools yet)"
        cutoff = start.isoformat()
        kept = [r for r in rows if (r.get("ts") or "")[:10] >= cutoff]
        if not kept:
            return "(no tool synthesis in window)"
        return "\n".join(
            f"  • {r.get('ts','?')[:16]}  {r.get('event','?'):10s} "
            f"{r.get('name','?')}"
            for r in kept
        )
    parts.append(_section("🛠 Tool synthesis", ts_lines()))

    # 5. Skill synthesis registry events.
    from agents import skill_synthesis as ss
    def ss_lines() -> str:
        rows = _safe(lambda: ss.history(limit=50), default=[])
        if not rows:
            return "(no synthesised skills yet)"
        cutoff = start.isoformat()
        kept = [r for r in rows if (r.get("ts") or "")[:10] >= cutoff]
        if not kept:
            return "(no skill synthesis in window)"
        return "\n".join(
            f"  • {r.get('ts','?')[:16]}  {r.get('event','?'):10s} "
            f"{r.get('name','?')}"
            for r in kept
        )
    parts.append(_section("🎯 Skill synthesis", ss_lines()))

    # 6. Memory hygiene (M1).
    from agents import memory_monitor as mh
    parts.append(_section("🧠 Memory hygiene",
                          _safe(lambda: mh.summary(stale_months=6))))

    # 6b. Archive candidates (A1).
    from agents import project_archive as pa
    def archive_lines() -> str:
        cands = _safe(lambda: pa.autosweep(idle_months=6, dry_run=True,
                                            today=today), default=[])
        if not cands:
            return "(no archive candidates)"
        return "\n".join(
            f"  • {c.project}  phase={c.phase}  idle={c.idle_days}d"
            for c in cands
        )
    parts.append(_section("📦 Archive candidates", archive_lines()))

    # 7. Evals: list versions seen with their latest score.
    from agents import evals as ev
    def ev_lines() -> str:
        try:
            import sqlite3
            conn = sqlite3.connect(ev.db_path())
            rows = conn.execute(
                "SELECT version, AVG(score) AS s, COUNT(*) AS n, MAX(run_at) "
                "FROM eval_runs GROUP BY version ORDER BY MAX(run_at) DESC LIMIT 5"
            ).fetchall()
            conn.close()
        except Exception:
            return "(no eval runs yet)"
        if not rows:
            return "(no eval runs yet)"
        out = []
        for v, s, n, ts in rows:
            out.append(f"  • {ts[:10]}  version={v}  score={s:.3f}  n={n}")
        return "\n".join(out)
    parts.append(_section("📈 Evals — latest score per version", ev_lines()))

    return "\n\n".join(parts).rstrip() + "\n"


def main() -> int:
    text = render_digest()
    if os.environ.get("AIM_TG_DRYRUN") == "1":
        print(text)
        return 0
    # Reuse the canonical Telegram sender (HW1, 2026-05-06: extracted
    # from scripts/daily_brief.py to agents/telegram_sender.py).
    try:
        from agents.telegram_sender import send_telegram
    except Exception:
        print(text)
        return 0
    if send_telegram(text):
        log.info("weekly digest sent (%d chars)", len(text))
        return 0
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
