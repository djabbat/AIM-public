"""agents/pattern_miner.py — JSONL session log analyser (S4, 2026-05-02).

The generalist writes one JSONL line per event (`tool_call`, `tool_result`,
`final`, `self_critique_*`, `interrupted`) into
`~/.cache/aim/sessions/<run_id>.jsonl`. Once we have ~100 sessions worth
of logs, recurring patterns surface — flaky tools, repeated memory
queries that should be cached, slow models for specific task classes,
arg shapes the LLM keeps getting wrong.

This module turns those logs into actionable findings:

    findings = mine(window_days=7)
    # → list[Finding(kind, summary, support, sample)]

Where `kind` ∈ {tool_failure_rate, slow_tool, redundant_memory_query,
sequential_pair, model_class_latency, error_type_frequency}.

The output drives:
  * Telegram weekly digest (P4 brief extension).
  * S5 A/B routing decisions ("model X consistently slower for class Y").
  * S3 prompt patches ("tool-call arg shape errors → tighten the schema
    in the system prompt").
  * S2 tool synthesis ("the same shell+parse sequence appears 12× → make
    it a named tool").

Public API:
    iter_events(paths=None) -> Iterable[dict]
    mine(window_days=7) -> list[Finding]
    summary(window_days=7) -> str
"""
from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.pattern_miner")


def sessions_dir() -> Path:
    env = os.environ.get("AIM_SESSIONS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "aim" / "sessions"


@dataclasses.dataclass
class Finding:
    kind: str           # tool_failure_rate | slow_tool | redundant_memory_query | ...
    summary: str
    support: int        # count of supporting events
    sample: dict        # one example record


# ── log iteration ─────────────────────────────────────────────────


def iter_events(paths: Optional[Iterable[Path]] = None,
                window_days: Optional[int] = None) -> Iterable[dict]:
    """Yield event dicts from session JSONL files. Skips malformed lines."""
    if paths is None:
        d = sessions_dir()
        if not d.exists():
            return
        paths = sorted(d.glob("*.jsonl"))
    cutoff = None
    if window_days is not None:
        cutoff = dt.datetime.now() - dt.timedelta(days=window_days)
    for p in paths:
        try:
            with p.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if cutoff is not None:
                        ts = ev.get("ts") or ev.get("timestamp")
                        if isinstance(ts, str):
                            try:
                                evt = dt.datetime.fromisoformat(ts)
                            except ValueError:
                                continue
                            if evt < cutoff:
                                continue
                        elif isinstance(ts, (int, float)):
                            if dt.datetime.fromtimestamp(ts) < cutoff:
                                continue
                    yield ev
        except OSError as e:
            log.debug("skip %s: %s", p, e)


# ── miners ────────────────────────────────────────────────────────


def _norm_args(args) -> str:
    """Stable string fingerprint for tool args: sorted keys, values truncated."""
    if not isinstance(args, dict):
        return str(args)[:80]
    parts = []
    for k in sorted(args):
        v = args[k]
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)[:60] \
            if isinstance(v, (dict, list)) else str(v)[:60]
        parts.append(f"{k}={s}")
    return "|".join(parts)


def _mine_tool_failure_rate(events: list[dict],
                            min_calls: int = 5,
                            failure_threshold: float = 0.30
                            ) -> list[Finding]:
    """Tools whose error rate ≥ threshold over `min_calls`."""
    calls: dict[str, int] = collections.Counter()
    fails: dict[str, int] = collections.Counter()
    samples: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "tool_result":
            continue
        name = ev.get("tool") or ev.get("name") or "?"
        calls[name] += 1
        result = str(ev.get("result", "")).strip()
        if result.startswith("ERROR:") or ev.get("error"):
            fails[name] += 1
            samples.setdefault(name, ev)
    out: list[Finding] = []
    for name, n in calls.items():
        if n < min_calls:
            continue
        rate = fails[name] / n
        if rate >= failure_threshold:
            out.append(Finding(
                kind="tool_failure_rate",
                summary=f"tool {name!r} fails {fails[name]}/{n} = {rate:.0%}",
                support=fails[name],
                sample=samples.get(name, {}),
            ))
    return out


def _mine_slow_tool(events: list[dict],
                    min_calls: int = 5,
                    slow_ms: int = 2000) -> list[Finding]:
    durations: dict[str, list[int]] = collections.defaultdict(list)
    for ev in events:
        if ev.get("type") != "tool_result":
            continue
        name = ev.get("tool") or ev.get("name") or "?"
        d = ev.get("duration_ms") or ev.get("latency_ms")
        if isinstance(d, (int, float)):
            durations[name].append(int(d))
    out: list[Finding] = []
    for name, ds in durations.items():
        if len(ds) < min_calls:
            continue
        ds_sorted = sorted(ds)
        n = len(ds_sorted)
        p50 = ds_sorted[n // 2]
        p95 = ds_sorted[min(n - 1, int(n * 0.95))]
        if p95 >= slow_ms:
            out.append(Finding(
                kind="slow_tool",
                summary=(f"tool {name!r} p95={p95}ms p50={p50}ms "
                         f"over {len(ds)} calls"),
                support=len(ds),
                sample={"name": name, "p50": p50, "p95": p95},
            ))
    return out


def _mine_redundant_memory_queries(events: list[dict],
                                   min_repeats: int = 3) -> list[Finding]:
    """Same memory_recall query appearing N+ times across sessions."""
    by_arg: dict[str, list[dict]] = collections.defaultdict(list)
    for ev in events:
        if ev.get("type") != "tool_call":
            continue
        if (ev.get("tool") or ev.get("name")) not in ("memory_recall",
                                                       "memory_save"):
            continue
        sig = _norm_args(ev.get("args"))
        by_arg[sig].append(ev)
    out: list[Finding] = []
    for sig, evs in by_arg.items():
        if len(evs) >= min_repeats:
            out.append(Finding(
                kind="redundant_memory_query",
                summary=f"memory query repeated {len(evs)}× — cache it",
                support=len(evs),
                sample={"args_fingerprint": sig},
            ))
    return out


def _mine_sequential_pairs(events: list[dict],
                           min_pairs: int = 3) -> list[Finding]:
    """Tool A consistently followed by tool B → candidate for synthesis."""
    pairs: dict[tuple[str, str], int] = collections.Counter()
    last: dict[str, str] = {}   # session_id → last tool name
    for ev in events:
        if ev.get("type") != "tool_call":
            continue
        sid = str(ev.get("session_id") or ev.get("run_id") or "")
        name = ev.get("tool") or ev.get("name") or "?"
        prev = last.get(sid)
        if prev is not None and prev != name:
            pairs[(prev, name)] += 1
        last[sid] = name
    out: list[Finding] = []
    for (a, b), n in pairs.items():
        if n >= min_pairs:
            out.append(Finding(
                kind="sequential_pair",
                summary=f"{a} → {b} appears in {n} sessions; consider a macro",
                support=n,
                sample={"a": a, "b": b},
            ))
    return out


def _mine_error_type_frequency(events: list[dict],
                               min_repeats: int = 3) -> list[Finding]:
    by_prefix: dict[str, int] = collections.Counter()
    for ev in events:
        if ev.get("type") != "tool_result":
            continue
        result = str(ev.get("result", ""))
        if not result.startswith("ERROR:"):
            continue
        prefix = ":".join(result.split(":", 3)[:3])  # ERROR:X:Y
        by_prefix[prefix] += 1
    out: list[Finding] = []
    for prefix, n in by_prefix.items():
        if n >= min_repeats:
            out.append(Finding(
                kind="error_type_frequency",
                summary=f"error class {prefix!r} fired {n}× — root-cause it",
                support=n,
                sample={"prefix": prefix},
            ))
    return out


# ── orchestration ─────────────────────────────────────────────────


def _mine_stakeholder_silence(min_days: int = 14,
                                threshold: int = 3) -> list[Finding]:
    """Phase E (HW1, 2026-05-06) — project-side signal, not session-derived.

    Reads the existing stakeholder_tracker SQLite (Co-PI + external
    contacts) and emits a finding when ≥`threshold` stakeholders are
    silent for ≥`min_days`. Bridge to project-level signals — the
    miner is reused, not re-implemented.
    """
    try:
        from agents import stakeholder_tracker as st
    except Exception:
        return []
    try:
        silent = st.silent_for(days=min_days)
    except Exception as e:
        log.debug("stakeholder_silence miner failed: %s", e)
        return []
    if len(silent) < threshold:
        return []
    sample = {
        "first_silent": silent[0].name,
        "n_silent": len(silent),
        "min_days": min_days,
    }
    return [Finding(
        kind="stakeholder_silence_pattern",
        summary=(f"{len(silent)} stakeholders silent ≥{min_days}d "
                 f"(top: {', '.join(s.name for s in silent[:3])})"),
        support=len(silent),
        sample=sample,
    )]


def _mine_patient_followup_drift(today=None,
                                   threshold: int = 2) -> list[Finding]:
    """Phase E (HW1, 2026-05-06) — patient-side signal via aim-patient-comms.

    Calls the Rust binary `aim-patient-comms overdue` (if present) to
    count overdue follow-ups; emits a finding when ≥`threshold` are
    overdue. Bridge — Python doesn't re-parse SQLite.
    """
    import datetime as _dt
    import subprocess
    today = today or _dt.date.today()
    here = Path(__file__).resolve().parent.parent
    candidates = [
        here / "rust-core" / "target" / "release" / "aim-patient-comms",
        here / "rust-core" / "target" / "debug" / "aim-patient-comms",
    ]
    bin_path = next((p for p in candidates if p.exists()), None)
    if bin_path is None:
        return []
    try:
        out = subprocess.run(
            [str(bin_path), "overdue", today.isoformat()],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    body = (out.stdout or "").strip()
    if not body:
        return []
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if len(lines) < threshold:
        return []
    return [Finding(
        kind="patient_followup_drift",
        summary=(f"{len(lines)} overdue patient follow-ups "
                 f"(top: {lines[0][:80]})"),
        support=len(lines),
        sample={"lines": lines[:5]},
    )]


def mine(window_days: int = 7,
         events: Optional[list[dict]] = None) -> list[Finding]:
    """Run every miner and return findings sorted by support desc."""
    if events is None:
        events = list(iter_events(window_days=window_days))
    findings: list[Finding] = []
    findings += _mine_tool_failure_rate(events)
    findings += _mine_slow_tool(events)
    findings += _mine_redundant_memory_queries(events)
    findings += _mine_sequential_pairs(events)
    findings += _mine_error_type_frequency(events)
    # Phase E (HW1, 2026-05-06) — project-side signals, not session-derived.
    findings += _mine_stakeholder_silence()
    findings += _mine_patient_followup_drift()
    findings.sort(key=lambda f: f.support, reverse=True)
    return findings


def summary(window_days: int = 7) -> str:
    findings = mine(window_days=window_days)
    if not findings:
        return f"(no actionable patterns over last {window_days}d)"
    out = [f"🔎 Pattern miner — last {window_days}d, {len(findings)} findings"]
    for f in findings:
        out.append(f"  • [{f.kind}] {f.summary}")
    return "\n".join(out)


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Session-log pattern miner")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    findings = mine(window_days=args.days)
    if args.json:
        print(json.dumps([dataclasses.asdict(f) for f in findings],
                         indent=2, ensure_ascii=False))
    else:
        print(summary(window_days=args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
