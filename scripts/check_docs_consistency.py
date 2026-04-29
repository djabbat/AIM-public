"""scripts/check_docs_consistency.py — keep architecture docs in sync with code.

Run as a CI check (or pre-commit hook). Verifies:
    1. Every CLI wrapper in ~/.local/bin/aim-* is mentioned in at least one doc
    2. Every agents/*.py module is mentioned in at least one doc
    3. Every env var documented exists in code (or vice versa)
    4. /api routes documented match those defined in web/api.py

Exit codes:
    0  — all green
    1  — drift found
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger("aim.docs_check")

ROOT       = Path(__file__).resolve().parent.parent
DOC_FILES  = [
    ROOT.parent / "AIM_FULL_ARCHITECTURE.md",
    ROOT.parent / "AIM_AI_LAYERS_AGENTS.md",
]
LOCAL_BIN  = Path.home() / ".local" / "bin"
AGENTS_DIR = ROOT / "agents"
WEB_API    = ROOT / "web" / "api.py"


# ── helpers ─────────────────────────────────────────────────────────────────


def _read_docs() -> str:
    return "\n\n".join(
        f.read_text(encoding="utf-8") for f in DOC_FILES if f.exists()
    )


# ── checks ─────────────────────────────────────────────────────────────────


def check_cli_wrappers(docs: str) -> list[str]:
    """Every aim-* binary должен быть упомянут хотя бы в одном документе."""
    issues = []
    if not LOCAL_BIN.exists():
        return ["~/.local/bin not found"]
    for f in LOCAL_BIN.glob("aim-*"):
        if not f.is_file():
            continue
        if f.name == "aim-code-auto":  # internal helper, not user-facing
            continue
        if f.name not in docs:
            issues.append(f"CLI '{f.name}' not mentioned in any doc")
    return issues


def check_agent_modules(docs: str) -> list[str]:
    """agents/<module>.py должен быть упомянут (имя модуля без расширения)."""
    issues = []
    if not AGENTS_DIR.exists():
        return []
    for f in AGENTS_DIR.glob("*.py"):
        name = f.stem
        if name in ("__init__",):
            continue
        # accept either bare name or `agents/<name>` reference
        if (name not in docs) and (f"agents/{name}" not in docs):
            issues.append(f"agent module 'agents/{name}.py' not in docs")
    return issues


def check_env_vars(docs: str) -> list[str]:
    """Every AIM_* env var read in code must be documented (and v.v.)."""
    issues = []
    code_vars: set[str] = set()
    for f in ROOT.rglob("*.py"):
        if "agents.bak" in str(f) or "/.git/" in str(f):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        code_vars.update(re.findall(r'os\.getenv\(\s*["\'](AIM_[A-Z0-9_]+)["\']', text))
        code_vars.update(re.findall(r'environ\[?["\'](AIM_[A-Z0-9_]+)["\']', text))

    doc_vars = set(re.findall(r"\bAIM_[A-Z0-9_]+\b", docs))

    only_in_code = sorted(code_vars - doc_vars)
    only_in_doc  = sorted(doc_vars - code_vars)
    for v in only_in_code:
        issues.append(f"env var {v!r} read in code but not documented")
    for v in only_in_doc:
        # Allow forward-references (e.g. `AIM_PROFILE` set externally)
        if v in {"AIM_PROFILE", "AIM_THREAD_ID"}:
            continue
        issues.append(f"env var {v!r} documented but not read in code")
    return issues


def check_web_routes(docs: str) -> list[str]:
    """Every @router/@app endpoint должен быть упомянут в docs."""
    issues = []
    if not WEB_API.exists():
        return []
    routes: set[str] = set()
    for f in [WEB_API, ROOT / "web" / "webhooks.py"]:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r'@(?:app|router)\.(?:get|post|websocket|put|delete|patch)\(\s*["\']([^"\']+)["\']', text):
            routes.add(m.group(1))
    for r in sorted(routes):
        # Allow path with placeholders
        bare = r.replace("{task_id}", "{task}")  # normalise common pattern
        if (r not in docs) and (bare not in docs):
            issues.append(f"web route {r!r} not in docs")
    return issues


# ── runner ─────────────────────────────────────────────────────────────────


CHECKS = {
    "cli":     check_cli_wrappers,
    "agents":  check_agent_modules,
    "env":     check_env_vars,
    "routes":  check_web_routes,
}


def run(checks: list[str] | None = None) -> dict:
    docs = _read_docs()
    if not docs:
        return {"error": "no documentation files found"}
    selected = checks or list(CHECKS.keys())
    out = {}
    total = 0
    for name in selected:
        if name not in CHECKS:
            continue
        issues = CHECKS[name](docs)
        out[name] = {"count": len(issues), "issues": issues}
        total += len(issues)
    out["_total_issues"] = total
    return out


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-docs-check")
    p.add_argument("--check", action="append", choices=list(CHECKS.keys()),
                   help="run only the named checks (default: all)")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 if any issue found")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="[%(name)s] %(message)s")

    results = run(args.check)
    import json
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if (args.strict and results.get("_total_issues", 0) > 0) else 0


if __name__ == "__main__":
    raise SystemExit(_main())
