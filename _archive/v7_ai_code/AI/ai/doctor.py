"""AI/ai/doctor.py — hybrid Rust+Python shim (Phase 9 Tier 3 #11, 2026-05-07).

Smoke-test every AI/ai/* module + verify the wiring assumptions a fresh
checkout depends on. Runs in O(seconds), no network, no model calls —
pure local introspection.

Architecture:
- Rust binary `aim-ai-doctor` owns: db_writable, workspace, artifacts_dir,
  direction_rule, latest_report (structural / fs probes).
- Python keeps: modules (every `AI/ai/*.py` must import — no Rust
  equivalent) and api_key (DEEPSEEK_API_KEY presence).

Public API (preserved):
    Probe dataclass
    diagnose() -> list[Probe]
    has_critical_failure(probes=None) -> bool
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.doctor")


@dataclasses.dataclass
class Probe:
    name: str
    ok: bool
    detail: str
    severity: str = "info"   # info | warn | crit


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _binary_path() -> Path:
    return _project_root() / "rust-core" / "target" / "release" / "aim-ai-doctor"


def _rust_probes() -> list[Probe]:
    bin_path = _binary_path()
    if not bin_path.exists():
        return [Probe(
            name="rust_doctor", ok=False, severity="warn",
            detail=f"aim-ai-doctor binary not built at {bin_path}",
        )]
    repo_root = _project_root().parent  # Rust expects parent-of-AIM
    proc = subprocess.run(
        [str(bin_path), "diagnose", "--repo-root", str(repo_root)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return [Probe(
            name="rust_doctor", ok=False, severity="warn",
            detail=f"aim-ai-doctor diagnose failed: {proc.stderr.strip()}",
        )]
    out: list[Probe] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(Probe(
            name=j.get("name", "?"),
            ok=bool(j.get("ok")),
            detail=str(j.get("detail", "")),
            severity=str(j.get("severity", "info")),
        ))
    return out


# ── Python-only probes ──────────────────────────────────────────


def _probe_modules() -> Probe:
    """Every AI/ai/*.py must import without error."""
    failed: list[str] = []
    ai_dir = _project_root() / "AI" / "ai"
    for p in sorted(ai_dir.glob("*.py")):
        if p.name.startswith("_") or p.name == "__init__.py":
            continue
        modname = f"AI.ai.{p.stem}"
        try:
            importlib.import_module(modname)
        except Exception as e:
            failed.append(f"{modname}: {type(e).__name__}: {e}")
    if failed:
        return Probe(name="modules", ok=False, severity="crit",
                     detail=f"{len(failed)} import failures:\n  "
                             + "\n  ".join(failed))
    n = sum(1 for p in ai_dir.glob("*.py")
             if not p.name.startswith("_") and p.name != "__init__.py")
    return Probe(name="modules", ok=True,
                 detail=f"{n} AI/ai modules import cleanly")


def _probe_api_key() -> Probe:
    """DEEPSEEK_API_KEY presence (warn, not crit)."""
    try:
        from AI.ai.run_self_diagnostic import _api_key
    except Exception as e:
        return Probe(name="api_key", ok=False, severity="warn",
                     detail=f"run_self_diagnostic unimportable: {e}")
    if _api_key():
        return Probe(name="api_key", ok=True,
                     detail="DEEPSEEK_API_KEY resolved")
    return Probe(name="api_key", ok=False, severity="warn",
                 detail="DEEPSEEK_API_KEY missing — "
                         "run_self_diagnostic.run() will fail")


# ── orchestrate ─────────────────────────────────────────────────


def diagnose() -> list[Probe]:
    out: list[Probe] = []
    # Python-only first (fastest, structural).
    for fn in (_probe_modules, _probe_api_key):
        try:
            out.append(fn())
        except Exception as e:
            out.append(Probe(name=fn.__name__.lstrip("_probe_"),
                              ok=False, severity="crit",
                              detail=f"probe crashed: "
                                      f"{type(e).__name__}: {e}"))
    # Then Rust binary's structural probes.
    out.extend(_rust_probes())
    return out


def has_critical_failure(probes: Optional[list[Probe]] = None) -> bool:
    probes = probes if probes is not None else diagnose()
    return any((not p.ok) and p.severity == "crit" for p in probes)


# ── render ──────────────────────────────────────────────────────


def summary() -> str:
    probes = diagnose()
    lines = [f"🩺 AI/ doctor — {len(probes)} probes"]
    crit = sum(1 for p in probes if not p.ok and p.severity == "crit")
    warn = sum(1 for p in probes if not p.ok and p.severity == "warn")
    if crit == 0 and warn == 0:
        lines.append("  ✅ all probes ok")
    else:
        lines.append(f"  {crit} crit · {warn} warn")
    for p in probes:
        mark = "✅" if p.ok else ("❌" if p.severity == "crit" else "⚠")
        lines.append(f"  {mark} {p.name}: {p.detail}")
    return "\n".join(lines)
