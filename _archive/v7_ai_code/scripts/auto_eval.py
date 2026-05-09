#!/usr/bin/env python3
"""scripts/auto_eval.py — daily eval run + regression alert (G7, 2026-05-03).

Run from cron / systemd timer once a day. Steps:

  1. Pick the runner (default: `llm.ask`).
  2. Run every eval case via `agents.evals.run_all`, version=YYYY-MM-DD.
  3. Compare to the previous date's run.
  4. If aggregate score regressed by ≥ `AIM_EVAL_REGRESSION_THRESHOLD`
     (default 0.05) AND p-value below 0.10, alert via notify.

Persisted into `eval_runs.db`; weekly_digest already shows the 5 most
recent versions.

Env knobs:
    AIM_EVAL_REGRESSION_THRESHOLD   (default 0.05)
    AIM_EVAL_TAG_FILTER             (run only cases with this tag)
    AIM_TG_DRYRUN                   (skip notification)
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
log = logging.getLogger("aim.auto_eval")


def _previous_version(today: dt.date) -> str | None:
    """Find the most recent eval-run version != today."""
    from agents import evals as ev
    try:
        import sqlite3
        conn = sqlite3.connect(ev.db_path())
        cur = conn.execute(
            "SELECT version FROM eval_runs WHERE version != ? "
            "ORDER BY run_at DESC LIMIT 1",
            (today.isoformat(),))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log.debug("previous_version lookup failed: %s", e)
        return None


def main() -> int:
    today = dt.date.today()
    version = today.isoformat()
    threshold = float(os.environ.get("AIM_EVAL_REGRESSION_THRESHOLD", "0.05"))
    tag = os.environ.get("AIM_EVAL_TAG_FILTER") or None

    from agents import evals as ev
    from llm import ask
    log.info("running eval cases (version=%s, tag=%s)", version, tag)
    run = ev.run_all(ask, version=version, tag_filter=tag)
    log.info("done: aggregate=%.3f over %d cases",
             run.aggregate_score, len(run.cases))

    prev = _previous_version(today)
    if not prev:
        log.info("no previous version; baseline established")
        return 0

    cmp = ev.compare(prev, version)
    log.info("vs %s: Δ=%+.3f verdict=%s", prev, cmp["delta"], cmp["verdict"])

    if cmp["delta"] <= -threshold and cmp["verdict"] != "improved":
        msg = (f"⚠️ Eval regression: {prev} → {version}\n"
               f"  prev_score = {cmp['a']:.3f}\n"
               f"  curr_score = {cmp['b']:.3f}\n"
               f"  Δ          = {cmp['delta']:+.3f}\n"
               f"  threshold  = -{threshold}\n"
               f"  cases      = {len(run.cases)}")
        if os.environ.get("AIM_TG_DRYRUN") == "1":
            print(msg)
        else:
            try:
                from agents.notify import notify
                notify(msg, channels=("telegram", "stdout"),
                       subject="🩺 AIM eval regression",
                       level="high", source="auto_eval",
                       dedup_key=f"regression:{version}",
                       dedup_window_minutes=24 * 60)
            except Exception as e:
                log.warning("alert failed: %s", e)
                print(msg)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
