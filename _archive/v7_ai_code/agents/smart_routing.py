"""agents/smart_routing.py — thin Python shim over the
`aim-smart-routing` Rust binary (Phase 8 Week 1, 2026-05-07).

All classification, pricing, routing, and SQLite persistence live in
Rust (`rust-core/crates/aim-smart-routing`). This module exists only to
give Python callers (llm.py, cost_monitor.py) a Pythonic API and to
preserve the public surface (`classify`, `route`, `estimate_cost`,
`stats`) so existing imports keep working.

If you find yourself adding pricing tables or regex tuning here — STOP
and put it in the Rust crate, then expose a new subcommand. See
`PHASE_8_ROADMAP.md` for the migration pattern.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("aim.smart_routing")

ENABLED = os.getenv("AIM_SMART_ROUTING", "").lower() in ("1", "true", "yes")
DB_PATH = Path("~/.claude/smart_routing.db").expanduser()


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-smart-routing"
    )


def _run(args: list[str], pass_env_routing: bool = True) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-smart-routing binary not built at {bin_path}; "
            "run `cargo build -p aim-smart-routing --release` in rust-core/"
        )
    env = dict(os.environ)
    if pass_env_routing and ENABLED:
        env["AIM_SMART_ROUTING"] = "1"
    proc = subprocess.run(
        [str(bin_path), *args],
        capture_output=True, text=True, check=False, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aim-smart-routing {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def classify(prompt: str, force_model: str | None = None) -> dict:
    """Pure classifier — no DB write. Returns
    {model, tier, reason, est_in_tokens, est_cost (always 0.0)}."""
    args = ["classify"]
    if force_model:
        args += ["--force-model", force_model]
    args.append(prompt)
    return json.loads(_run(args))


def estimate_cost(model: str, in_tok: int, out_tok: int = 0) -> float:
    """Cost in USD for the given token counts on the given model."""
    out = _run(["estimate-cost", model, str(in_tok), str(out_tok)])
    return float(json.loads(out)["cost_usd"])


def route(prompt: str, force_model: str | None = None,
          assume_output: int = 500) -> dict:
    """Public API: returns {model, tier, est_cost, ...}. Logs to the
    Rust-side SQLite ledger iff AIM_SMART_ROUTING=1."""
    args = ["route", "--db", str(DB_PATH), "--assume-output", str(assume_output)]
    if force_model:
        args += ["--force-model", force_model]
    args.append(prompt)
    return json.loads(_run(args))


def stats() -> dict:
    """Lifetime routing stats from the SQLite ledger."""
    return json.loads(_run(["stats", "--db", str(DB_PATH)]))


# ── CLI parity (preserved for any caller that did
#                `python -m agents.smart_routing classify ...`) ────────────


def _main() -> int:
    p = argparse.ArgumentParser(description="Smart LLM routing (shim → Rust)")
    sub = p.add_subparsers(dest="cmd", required=True)
    cl = sub.add_parser("classify")
    cl.add_argument("prompt")
    cl.add_argument("--force-model")
    rt = sub.add_parser("route")
    rt.add_argument("prompt")
    rt.add_argument("--force-model")
    rt.add_argument("--assume-output", type=int, default=500)
    sub.add_parser("stats")
    ec = sub.add_parser("estimate-cost")
    ec.add_argument("model")
    ec.add_argument("in_tokens", type=int)
    ec.add_argument("out_tokens", type=int, nargs="?", default=0)
    a = p.parse_args()
    if a.cmd == "classify":
        print(json.dumps(classify(a.prompt, a.force_model), ensure_ascii=False))
    elif a.cmd == "route":
        print(json.dumps(route(a.prompt, a.force_model, a.assume_output),
                         ensure_ascii=False))
    elif a.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif a.cmd == "estimate-cost":
        print(estimate_cost(a.model, a.in_tokens, a.out_tokens))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
