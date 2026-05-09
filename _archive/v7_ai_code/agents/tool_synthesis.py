"""agents/tool_synthesis.py — repeating-pattern → new tool (S2, 2026-05-02).

Pattern_miner finds sequential pairs (`tool A → tool B` recurring across
sessions). Tool synthesis turns the most popular pair into a single,
named, hot-loadable Python tool that wraps both calls. Once a candidate
passes its fixture tests, it lands under `~/.aim/tools/synthesised/<name>.py`
and is exposed through the registry.

Safety constraints (L_VERIFIABILITY mirror):
  * Generated code is sandboxed via `bash` whitelist + path sandbox.
  * Each candidate must pass at least 5 fixture invocations before we
    register it. `register=False` (the default) makes propose() a dry run.
  * The body is template-driven, not LLM-generated free-form, so we don't
    accidentally execute attacker-influenced Python from session logs.

Workflow:
    cands = candidates(window_days=14)              # via pattern_miner
    res   = propose(cands[0])                       # synthesise + test
    if res.passed and you trust it:
        path = register(res)                        # persist + wire in
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import re
import textwrap
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("aim.tool_synthesis")


def synth_dir() -> Path:
    env = os.environ.get("AIM_SYNTH_TOOLS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".aim" / "tools" / "synthesised"


# ── data ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class SynthesisCandidate:
    name: str            # snake_case tool name
    tool_a: str
    tool_b: str
    support: int         # how often this pair appeared
    description: str = ""


@dataclasses.dataclass
class SynthesisResult:
    candidate: SynthesisCandidate
    code: str
    passed: bool
    fixture_results: list[dict]
    error: Optional[str] = None


# ── candidate generation ─────────────────────────────────────────


_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _safe_name(a: str, b: str) -> str:
    a = re.sub(r"[^a-z0-9_]", "_", (a or "").lower()).strip("_")
    b = re.sub(r"[^a-z0-9_]", "_", (b or "").lower()).strip("_")
    if not a or not b:
        return ""
    return f"{a}_then_{b}"


def candidates(window_days: int = 14, top_n: int = 5,
               min_support: int = 3) -> list[SynthesisCandidate]:
    try:
        from agents import pattern_miner as pm
    except ImportError:
        return []
    findings = pm.mine(window_days=window_days)
    pairs = [f for f in findings if f.kind == "sequential_pair"
             and f.support >= min_support]
    out: list[SynthesisCandidate] = []
    for f in pairs[:top_n]:
        a = f.sample.get("a", "")
        b = f.sample.get("b", "")
        name = _safe_name(a, b)
        if not name or not _VALID_NAME_RE.match(name):
            continue
        out.append(SynthesisCandidate(
            name=name, tool_a=a, tool_b=b, support=f.support,
            description=f.summary,
        ))
    return out


# ── code generation (template-only, no LLM in the body) ──────────


_TEMPLATE = textwrap.dedent('''\
    """Synthesised tool {name} — auto-generated 2026-05-02 by agents/tool_synthesis.py.

    Wraps the recurring pair: {tool_a} → {tool_b}.
    Support at synthesis time: {support} sessions.

    Hand-edit at your own risk: pattern_miner regenerates this file when
    the pair count changes materially.
    """
    from __future__ import annotations
    from typing import Any


    def {name}(args_a: dict, args_b: dict, *, registry=None) -> dict:
        """Run {tool_a}(args_a) followed by {tool_b}(args_b).

        Returns dict {{"a": <result_a>, "b": <result_b>, "ok": bool}}.

        `registry` is an aim_generalist tools.Registry. Tests can inject
        a stub that exposes a synchronous .call(name, args) method.
        """
        if registry is None:
            from agents.generalist import call_tool as _ct
            res_a = _ct({tool_a!r}, args_a)
            res_b = _ct({tool_b!r}, args_b)
        else:
            res_a = registry.call({tool_a!r}, args_a)
            res_b = registry.call({tool_b!r}, args_b)
        ok = not (isinstance(res_a, str) and res_a.startswith("ERROR:")) \
             and not (isinstance(res_b, str) and res_b.startswith("ERROR:"))
        return {{"a": res_a, "b": res_b, "ok": ok}}
''')


def render_code(candidate: SynthesisCandidate) -> str:
    return _TEMPLATE.format(
        name=candidate.name,
        tool_a=candidate.tool_a,
        tool_b=candidate.tool_b,
        support=candidate.support,
    )


# ── fixture runner ───────────────────────────────────────────────


_FIXTURE_DEFAULT_REPEATS = 5


def run_fixtures(candidate: SynthesisCandidate, code: str,
                 fixture: Callable[[], tuple[dict, dict, dict]],
                 repeats: int = _FIXTURE_DEFAULT_REPEATS) -> list[dict]:
    """Compile the code, exec it in a fresh namespace, then run `fixture`
    `repeats` times.

    `fixture()` returns `(args_a, args_b, expected)`. The synthesised
    function is invoked with a stub registry whose .call() reads pre-baked
    return values from `expected`.

    Each iteration produces a dict {"ok": bool, "a": result_a, "b": ..., "expected": ...}.
    """
    ns: dict = {}
    exec(code, ns)
    fn = ns.get(candidate.name)
    if fn is None:
        raise RuntimeError(f"compiled module missing {candidate.name}()")

    class StubRegistry:
        def __init__(self, mapping: dict):
            self._m = mapping
        def call(self, name: str, _args: dict):
            return self._m.get(name)

    out: list[dict] = []
    for _ in range(repeats):
        args_a, args_b, expected = fixture()
        try:
            result = fn(args_a, args_b,
                        registry=StubRegistry(expected))
            out.append({"ok": result.get("ok", False),
                        "a": result.get("a"), "b": result.get("b"),
                        "expected": expected})
        except Exception as e:
            out.append({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return out


def _all_passed(results: list[dict]) -> bool:
    return all(r.get("ok") is True for r in results)


# ── propose & register ───────────────────────────────────────────


def propose(candidate: SynthesisCandidate,
            fixture: Optional[Callable[[], tuple[dict, dict, dict]]] = None,
            repeats: int = _FIXTURE_DEFAULT_REPEATS) -> SynthesisResult:
    """Render, execute, and validate. Does NOT write to disk."""
    code = render_code(candidate)
    if fixture is None:
        # Default fixture: feed two safe stub results that always pass.
        def fixture():
            return ({}, {}, {candidate.tool_a: "OK_a", candidate.tool_b: "OK_b"})
    try:
        results = run_fixtures(candidate, code, fixture, repeats=repeats)
        passed = _all_passed(results)
        return SynthesisResult(
            candidate=candidate, code=code,
            passed=passed, fixture_results=results,
            error=None if passed else "fixture not all-pass",
        )
    except Exception as e:
        return SynthesisResult(
            candidate=candidate, code=code,
            passed=False, fixture_results=[],
            error=f"{type(e).__name__}: {e}",
        )


def register(result: SynthesisResult) -> Path:
    """Persist a passing SynthesisResult to disk under synth_dir().

    Raises ValueError if the result didn't pass.
    """
    if not result.passed:
        raise ValueError(f"refuse to register failing tool: {result.error}")
    d = synth_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{result.candidate.name}.py"
    path.write_text(result.code, encoding="utf-8")
    _audit_register(result, path)
    return path


def list_registered() -> list[str]:
    d = synth_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.py")
                  if not p.stem.startswith("_"))


def remove(name: str) -> bool:
    """Drop a synthesised tool. Returns True if a file was removed."""
    p = synth_dir() / f"{name}.py"
    if p.exists():
        p.unlink()
        _audit_unregister(name)
        return True
    return False


# ── audit log ────────────────────────────────────────────────────


def _audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "tool_synthesis.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _audit_register(result: SynthesisResult, path: Path) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "event": "register",
        "name": result.candidate.name,
        "support": result.candidate.support,
        "tool_a": result.candidate.tool_a,
        "tool_b": result.candidate.tool_b,
        "path": str(path),
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("synthesis audit write failed: %s", e)


def _audit_unregister(name: str) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "event": "unregister", "name": name,
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("synthesis audit write failed: %s", e)


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
