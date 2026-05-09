"""agents/session_visualiser.py — JSONL session log → human timeline (SE1, 2026-05-03).

The generalist writes one event per line into
~/.cache/aim/sessions/<run_id>.jsonl. When debugging a long run,
scrolling raw JSON is painful. This module turns that file into:

  * a markdown timeline (one bullet per event, durations highlighted)
  * a per-tool stats summary (n calls, p50 latency, error rate)
  * an "interesting events" list (errors, self-critique, interrupts)

Public API:
    timeline(run_id_or_path) -> str
    stats(run_id_or_path) -> dict
"""
from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aim.session_visualiser")


def sessions_dir() -> Path:
    env = os.environ.get("AIM_SESSIONS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "aim" / "sessions"


# ── load events ──────────────────────────────────────────────────


def _resolve(run_id_or_path: str) -> Path:
    p = Path(run_id_or_path)
    if p.exists():
        return p
    candidate = sessions_dir() / f"{run_id_or_path}.jsonl"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"no session at {p} or {candidate}")


def _events(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError as e:
        log.debug("read session failed: %s", e)
    return out


# ── helpers ──────────────────────────────────────────────────────


_INTERESTING = {"final", "error", "tool_error",
                 "self_critique_issue_found", "interrupted"}


def _ts(ev: dict) -> Optional[float]:
    t = ev.get("ts") or ev.get("timestamp")
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, str):
        try:
            return dt.datetime.fromisoformat(t).timestamp()
        except ValueError:
            return None
    return None


# ── timeline ─────────────────────────────────────────────────────


def timeline(run_id_or_path: str) -> str:
    path = _resolve(run_id_or_path)
    events = _events(path)
    if not events:
        return f"(empty session at {path})"

    start_ts = _ts(events[0])
    lines: list[str] = [f"# Session timeline — {path.name}", ""]
    last_ts = start_ts
    for ev in events:
        kind = ev.get("type") or "?"
        t = _ts(ev)
        offset = ""
        if t and start_ts:
            offset = f"+{t - start_ts:7.2f}s"
        delta = ""
        if t and last_ts:
            delta = f"  Δ{t - last_ts:+5.2f}s"
        last_ts = t or last_ts
        marker = "🛑" if kind in {"error", "tool_error"} else (
            "✅" if kind == "final" else "·")
        suffix = ""
        if kind in {"tool_call", "tool_result", "tool_error"}:
            tool = ev.get("tool") or ev.get("name") or "?"
            suffix = f" tool={tool}"
        elif kind == "final":
            ans = (ev.get("answer") or "")[:60]
            suffix = f" → {ans!r}"
        elif kind == "error":
            err = (ev.get("error") or "")[:60]
            suffix = f" {err}"
        lines.append(f"  {marker} {offset:9s}{delta}  {kind}{suffix}")
    return "\n".join(lines)


# ── stats ────────────────────────────────────────────────────────


def stats(run_id_or_path: str) -> dict:
    path = _resolve(run_id_or_path)
    events = _events(path)
    if not events:
        return {"n_events": 0, "tools": {}, "interesting": []}

    by_tool_calls: dict[str, int] = collections.Counter()
    by_tool_errors: dict[str, int] = collections.Counter()
    durations: dict[str, list[int]] = collections.defaultdict(list)
    interesting: list[dict] = []

    # Pair tool_call → tool_result by index so durations make sense.
    pending: dict[int, tuple[str, float]] = {}

    for i, ev in enumerate(events):
        kind = ev.get("type")
        tool = ev.get("tool") or ev.get("name") or ""
        if kind == "tool_call" and tool:
            t = _ts(ev)
            if t is not None:
                pending[i] = (tool, t)
            by_tool_calls[tool] += 1
        elif kind == "tool_result":
            t = _ts(ev)
            # Match to the most recent pending call of the same tool.
            for j in sorted(pending, reverse=True):
                pname, pt = pending[j]
                if pname == tool:
                    if t is not None and pt is not None:
                        durations[tool].append(int((t - pt) * 1000))
                    pending.pop(j)
                    break
        elif kind == "tool_error":
            by_tool_errors[tool] += 1
        if kind in _INTERESTING:
            interesting.append({k: ev[k] for k in ev if k != "raw"})

    tools_summary: dict[str, dict] = {}
    for tool, n in by_tool_calls.items():
        ds = durations.get(tool) or [0]
        ds_sorted = sorted(ds)
        tools_summary[tool] = {
            "calls": n,
            "errors": by_tool_errors.get(tool, 0),
            "p50_ms": ds_sorted[len(ds_sorted) // 2] if ds_sorted else 0,
            "max_ms": max(ds_sorted) if ds_sorted else 0,
        }

    return {
        "n_events": len(events),
        "tools": tools_summary,
        "interesting": interesting,
    }


def summary_string(run_id_or_path: str) -> str:
    s = stats(run_id_or_path)
    lines = [f"Session {run_id_or_path}: {s['n_events']} events"]
    for tool, info in sorted(s["tools"].items(), key=lambda kv: -kv[1]["calls"]):
        lines.append(f"  • {tool}: {info['calls']} calls, "
                     f"{info['errors']} errors, "
                     f"p50={info['p50_ms']}ms")
    if s["interesting"]:
        lines.append(f"  ⚠  {len(s['interesting'])} interesting events")
    return "\n".join(lines)
