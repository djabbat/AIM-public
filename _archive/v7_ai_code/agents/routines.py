"""agents/routines.py — named bundle launcher (RB1, 2026-05-03).

Composes multiple existing CLI actions into a single named "routine".
Define them in `USER/preferences/routines.yaml`:

    routines:
      morning:
        - escalate
        - brief
        - { do: "follow-up everyone" }
        - memory

      pre-grant-submit:
        - { project: brief, args: ["FCLC"] }
        - { do: "what's hot" }
        - cost

Each step is either:
  * a string — name of a top-level handler ("brief", "memory", ...)
  * `{ do: "<query>" }` — runs the freeform dispatcher
  * `{ project: "<sub>", args: [...] }` — calls _cmd_project sub
  * `{ recall: "<query>", k: 3 }` — semantic memory query

Output: list of {step, action, result} captured in JSONL audit.

Public API:
    list_routines() -> list[str]
    run(name) -> RoutineResult
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aim.routines")


def prefs_path() -> Path:
    env = os.environ.get("AIM_ROUTINES_PREFS")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "USER" / "preferences" / "routines.yaml"


def audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "routines.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class StepResult:
    step: int
    action: str
    output: Any
    ok: bool
    error: Optional[str] = None


@dataclasses.dataclass
class RoutineResult:
    name: str
    started_at: str
    finished_at: str
    steps: list[StepResult]

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


# ── load ─────────────────────────────────────────────────────────


def _load() -> dict:
    p = prefs_path()
    if not p.exists():
        return {}
    try:
        import yaml
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("routines parse failed: %s", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw.get("routines") or {}


def list_routines() -> list[str]:
    return sorted(_load().keys())


# ── runners for each step type ──────────────────────────────────


def _run_brief(args: dict) -> Any:
    from agents.brief_preamble import compose
    from agents import project_owner as po
    project = (args or {}).get("project") if isinstance(args, dict) else None
    if project:
        return po.morning_brief(project)
    return compose() + "\n\n" + po.all_briefs()


def _run_recall(args: dict) -> Any:
    from agents.recall_cli import recall_top
    q = args.get("recall") or ""
    k = int(args.get("k", 5))
    return recall_top(q, k=k)


def _run_do(args: dict) -> Any:
    from agents.quick_action import handle
    q = args.get("do") or ""
    return handle(q)


def _run_project_sub(args: dict) -> Any:
    """Invoke `aim project <sub> [args]` programmatically. Limited to
    safe read sub-commands: list, sweep (dry-run only)."""
    sub = args.get("project") or ""
    sub_args = args.get("args") or []
    if sub == "list":
        from agents import project_owner as po
        return po.list_projects()
    if sub == "sweep":
        from agents import project_archive as pa
        cands = pa.autosweep(idle_months=6, dry_run=True)
        return [c.project for c in cands]
    return f"unsupported project sub-command: {sub!r}"


def _run_simple(name: str) -> Any:
    """Top-level commands by name (matches aim_cli handlers)."""
    if name == "escalate":
        from agents.escalation_engine import evaluate_all
        return [a.to_text() for a in evaluate_all(cooldown_hours=0)]
    if name == "memory":
        from agents.memory_monitor import summary
        return summary()
    if name == "cost":
        from agents.cost_ledger import summary
        return summary()
    if name == "health":
        from agents.health_extended import report
        return report()
    if name == "brief":
        return _run_brief({})
    if name == "digest":
        from scripts.weekly_digest import render_digest
        return render_digest()
    if name == "followups":
        from agents.follow_up_generator import generate_all
        return [{"to": d.contact_email, "subject": d.subject, "lang": d.lang}
                for d in generate_all()]
    raise ValueError(f"unknown routine step: {name!r}")


def _run_step(idx: int, raw: Any) -> StepResult:
    action: str
    try:
        if isinstance(raw, str):
            action = raw
            out = _run_simple(raw)
        elif isinstance(raw, dict):
            if "do" in raw:
                action = f"do:{raw['do'][:60]}"
                out = _run_do(raw)
            elif "recall" in raw:
                action = f"recall:{raw['recall'][:60]}"
                out = _run_recall(raw)
            elif "project" in raw:
                action = f"project:{raw['project']}"
                out = _run_project_sub(raw)
            elif "brief" in raw:
                action = "brief"
                out = _run_brief(raw)
            else:
                raise ValueError(f"unsupported step shape: {raw!r}")
        else:
            raise ValueError(f"unsupported step type: {type(raw).__name__}")
        return StepResult(step=idx, action=action, output=out, ok=True)
    except Exception as e:
        return StepResult(step=idx, action=raw if isinstance(raw, str) else "?",
                           output=None, ok=False,
                           error=f"{type(e).__name__}: {e}")


# ── orchestrate ──────────────────────────────────────────────────


def run(name: str) -> RoutineResult:
    routines = _load()
    if name not in routines:
        raise KeyError(f"no routine named {name!r}; "
                       f"available: {list(routines)}")
    steps_raw = routines[name] or []
    started = dt.datetime.now().replace(microsecond=0).isoformat()
    out: list[StepResult] = []
    for i, raw in enumerate(steps_raw, 1):
        out.append(_run_step(i, raw))
    finished = dt.datetime.now().replace(microsecond=0).isoformat()
    res = RoutineResult(name=name, started_at=started,
                        finished_at=finished, steps=out)
    _audit(res)
    return res


def _audit(res: RoutineResult) -> None:
    rec = {
        "name": res.name,
        "started_at": res.started_at,
        "finished_at": res.finished_at,
        "ok": res.ok,
        "steps": [
            {"step": s.step, "action": s.action,
             "ok": s.ok, "error": s.error}
            for s in res.steps
        ],
    }
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("routines audit write failed: %s", e)


def history(limit: int = 50) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]
