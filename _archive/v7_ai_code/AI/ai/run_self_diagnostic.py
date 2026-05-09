"""AI/ai/run_self_diagnostic.py — thin Python shim over the
`aim-ai-diag` Rust binary (Phase 9 Tier 3 #13, 2026-05-07).

The Rust crate `aim-ai-runner` owns the full pipeline: safety gate,
prompt build, DeepSeek POST (with deepseek-chat fallback), compliance
retry, save, ledger record, prompt fingerprint. Python keeps the
public `run()` API plus `project_root()`, `ai_root()`, `_api_key()`
helpers (consumed by `AI.ai.doctor` and `AI.ai.finding_validator`).

Public API (preserved):
    project_root() -> Path
    ai_root() -> Path
    _api_key() -> str | None
    run(model="deepseek-reasoner", *, save=True, verbose=True,
        compliance_retry=True, min_compliance=0.5,
        skip_safety_gate=False) -> Path

Env: DEEPSEEK_API_KEY (or ~/.aim_env), AI_DIAGNOSTIC_DB.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.run_self_diagnostic")


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def ai_root() -> Path:
    return project_root() / "AI"


def _api_key() -> Optional[str]:
    """Resolve DEEPSEEK_API_KEY from env, or by reading ~/.aim_env."""
    val = os.environ.get("DEEPSEEK_API_KEY")
    if val:
        return val
    aim_env = Path.home() / ".aim_env"
    if not aim_env.exists():
        return None
    for line in aim_env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY=") or line.startswith("export DEEPSEEK_API_KEY="):
            v = line.split("=", 1)[1].strip().strip("'\"")
            if v:
                return v
    return None


def _binary_path() -> Path:
    return project_root() / "rust-core" / "target" / "release" / "aim-ai-diag"


def _output_path(today: Optional[dt.date] = None) -> Path:
    today = today or dt.date.today()
    return ai_root() / "artifacts" / f"self_diag_{today.isoformat()}.md"


def run(model: str = "deepseek-reasoner",
        *,
        save: bool = True,
        verbose: bool = True,
        compliance_retry: bool = True,
        min_compliance: float = 0.5,
        skip_safety_gate: bool = False) -> Path:
    """Build prompt, send to DeepSeek, save the report. Delegates to
    the Rust `aim-ai-diag` binary."""
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-diag binary not built at {bin_path}"
        )
    args = [str(bin_path), "--model", model]
    if not save:
        args.append("--no-save")
    if skip_safety_gate:
        args.append("--force")
    if not compliance_retry:
        args.append("--no-retry")
    if not verbose:
        args.append("--quiet")
    # The binary uses its own min_compliance default (0.5). If the
    # caller wants a different threshold, propagate via env (the Rust
    # runner reads RunOpts.min_compliance from defaults; for now we
    # only support the default — matches existing call sites).
    if abs(min_compliance - 0.5) > 1e-6:
        log.debug("min_compliance override (%s) ignored — Rust runner uses default 0.5",
                  min_compliance)

    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        if "safety gate blocked" in msg.lower() or "SafetyBlocked" in msg:
            raise RuntimeError(f"safety gate blocked diagnostic run: {msg}")
        raise RuntimeError(f"aim-ai-diag failed: {msg}")
    if verbose:
        # Mirror the binary's stderr to the parent for cron / interactive logs.
        sys.stderr.write(proc.stderr)
    if not save:
        return Path("/dev/null")
    return _output_path()


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run AIM/AI self-diagnostic")
    ap.add_argument("--model", default="deepseek-reasoner")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--force", action="store_true",
                     help="bypass safety gate (cooldown + budget)")
    args = ap.parse_args()
    try:
        out = run(model=args.model, verbose=not args.quiet,
                  skip_safety_gate=args.force)
        if not args.quiet:
            print(f"\nreport: {out}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
