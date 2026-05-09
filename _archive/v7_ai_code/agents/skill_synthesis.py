"""agents/skill_synthesis.py — named-macro skills (S7, 2026-05-02).

Where S2 turns 2-tool sequences into single Python tools, S7 turns
longer recurring tool *sequences* (3+ steps) into named "skills" that
the model can invoke by name. Examples that we expect to crystallise
out of session logs:

    publish_paper:    md_to_docx → write_cover_letter → email_journal
                      → update_NEEDTOWRITE → log
    sync_repo:        bash(git status) → bash(git add) → bash(git commit)
                      → bash(git push)
    daily_brief:      project_owner.morning_brief → deadline_scanner.summary
                      → telegram_send

Skills are persisted as YAML in `~/.aim/skills/<name>.yaml`. Each
skill declares an ordered list of (tool, args_template) pairs. At
invocation time, args templates are formatted with the user-supplied
parameters before each tool fires.

Public API:
    candidates(min_length=3, min_support=3) -> list[SkillCandidate]
    propose(name, steps, description="") -> Skill
    register(skill) -> Path
    list_registered() -> list[str]
    load(name) -> Skill
    remove(name) -> bool
    invoke(name, params=None, registry=None) -> dict
"""
from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aim.skill_synthesis")


def skills_dir() -> Path:
    env = os.environ.get("AIM_SKILLS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".aim" / "skills"


# ── data ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class SkillStep:
    tool: str
    args: dict          # may contain {placeholder} keys filled at invoke time


@dataclasses.dataclass
class Skill:
    name: str
    description: str
    steps: list[SkillStep]


@dataclasses.dataclass
class SkillCandidate:
    name: str
    steps: list[str]    # tool names only (args inferred at synth time)
    support: int        # how many sessions exhibit this exact run


_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ── candidate mining ──────────────────────────────────────────────


def candidates(window_days: int = 14, min_length: int = 3,
               min_support: int = 3, top_n: int = 5
               ) -> list[SkillCandidate]:
    """Cluster session tool-call sequences into recurring N-grams.

    For each session in pattern_miner's window, take the ordered list of
    `tool_call` events, sliding-window into N-grams of length
    `min_length..min_length+2`, and count distinct sequences.
    """
    try:
        from agents import pattern_miner as pm
    except ImportError:
        return []
    sessions: dict[str, list[str]] = collections.defaultdict(list)
    for ev in pm.iter_events(window_days=window_days):
        if ev.get("type") != "tool_call":
            continue
        sid = str(ev.get("session_id") or ev.get("run_id") or "")
        name = ev.get("tool") or ev.get("name") or ""
        if name:
            sessions[sid].append(name)

    counts: dict[tuple[str, ...], int] = collections.Counter()
    for sid, calls in sessions.items():
        seen_local: set[tuple[str, ...]] = set()
        for L in range(min_length, min_length + 3):
            for i in range(0, len(calls) - L + 1):
                seq = tuple(calls[i:i + L])
                # Each session contributes ONE vote per distinct sequence.
                if seq in seen_local:
                    continue
                seen_local.add(seq)
                counts[seq] += 1

    out: list[SkillCandidate] = []
    for seq, n in counts.most_common():
        if n < min_support:
            continue
        # Auto-name: join short tool names by "_then_".
        name = "_then_".join(re.sub(r"[^a-z0-9_]", "_", t.lower()).strip("_")
                             for t in seq)[:60]
        if not _VALID_NAME_RE.match(name):
            continue
        out.append(SkillCandidate(name=name, steps=list(seq), support=n))
        if len(out) >= top_n:
            break
    return out


# ── propose / register / load ────────────────────────────────────


def propose(name: str, steps: list, description: str = "") -> Skill:
    """Build a Skill object from a name + step list.

    Steps may be:
      * dicts {"tool": ..., "args": {...}}
      * tuples (tool, args)
      * bare strings (treated as tools with empty args)
    """
    if not _VALID_NAME_RE.match(name or ""):
        raise ValueError(f"invalid skill name: {name!r}")
    if not steps:
        raise ValueError("skill must have at least one step")
    out_steps: list[SkillStep] = []
    for s in steps:
        if isinstance(s, SkillStep):
            out_steps.append(s)
        elif isinstance(s, dict):
            t = s.get("tool")
            if not t:
                raise ValueError(f"step missing tool: {s!r}")
            out_steps.append(SkillStep(tool=str(t), args=dict(s.get("args") or {})))
        elif isinstance(s, tuple) and len(s) == 2:
            out_steps.append(SkillStep(tool=str(s[0]), args=dict(s[1] or {})))
        elif isinstance(s, str):
            out_steps.append(SkillStep(tool=s, args={}))
        else:
            raise ValueError(f"unrecognised step shape: {s!r}")
    return Skill(name=name, description=description, steps=out_steps)


def register(skill: Skill) -> Path:
    import yaml
    d = skills_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{skill.name}.yaml"
    path.write_text(yaml.safe_dump({
        "name": skill.name,
        "description": skill.description,
        "steps": [{"tool": s.tool, "args": s.args} for s in skill.steps],
    }, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _audit("register", skill.name, {"steps": [s.tool for s in skill.steps]})
    return path


def load(name: str) -> Skill:
    import yaml
    p = skills_dir() / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"no skill {name!r} at {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    steps = [SkillStep(tool=str(s.get("tool")), args=dict(s.get("args") or {}))
             for s in (raw.get("steps") or [])]
    return Skill(name=str(raw.get("name", name)),
                  description=str(raw.get("description", "")),
                  steps=steps)


def list_registered() -> list[str]:
    d = skills_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def remove(name: str) -> bool:
    p = skills_dir() / f"{name}.yaml"
    if p.exists():
        p.unlink()
        _audit("unregister", name, {})
        return True
    return False


# ── invocation ───────────────────────────────────────────────────


def _format_args(args: dict, params: dict) -> dict:
    out: dict = {}
    for k, v in args.items():
        if isinstance(v, str):
            try:
                out[k] = v.format(**params)
            except (KeyError, IndexError):
                out[k] = v
        else:
            out[k] = v
    return out


def invoke(name: str, params: Optional[dict] = None,
           registry=None) -> dict:
    """Execute every step in the skill, returning a list of results.

    If `registry` is given, its .call(tool, args) is used. Otherwise we
    fall back to agents.generalist.call_tool. Stops at the first
    ERROR-prefixed result and reports `{ok: false, failed_at: i}`.
    """
    skill = load(name)
    params = params or {}
    if registry is None:
        from agents.generalist import call_tool as _ct

        class _Default:
            def call(self, n, a):
                return _ct(n, a)
        registry = _Default()

    results: list[Any] = []
    for i, step in enumerate(skill.steps):
        args = _format_args(step.args, params)
        r = registry.call(step.tool, args)
        results.append(r)
        if isinstance(r, str) and r.startswith("ERROR:"):
            _audit("invoke_failed", name,
                   {"step": i, "tool": step.tool, "error": r[:200]})
            return {"ok": False, "failed_at": i, "results": results,
                    "tool": step.tool, "error": r}
    _audit("invoke_ok", name, {"steps": len(skill.steps)})
    return {"ok": True, "results": results}


# ── audit ────────────────────────────────────────────────────────


def _audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "skill_synthesis.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _audit(event: str, name: str, extra: dict) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "event": event, "name": name, **extra,
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("skill audit write failed: %s", e)


def history(limit: int = 50) -> list[dict]:
    p = _audit_path()
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
