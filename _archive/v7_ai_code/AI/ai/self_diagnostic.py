"""AI/ai/self_diagnostic.py — runner for SELF_DIAGNOSTIC_PROMPT.md (SD1, 2026-05-03).

Loads the markdown prompt from `AI/docs/SELF_DIAGNOSTIC_PROMPT.md`,
attaches a freshly-snapshotted inventory + invariants of the AI/
subproject, and returns ONE giant prompt string that you paste into
Claude / DeepSeek-V4-pro / Gemini.

Why a Python wrapper at all? Because the prompt's Phase 0 wants
ground-truth (LoC, test counts, imports, direction-rule status). We
compute that *here* — deterministically — and fold it into the prompt,
so the model can't fabricate the surface it's auditing.

Public API:
    inventory() -> dict
    build_prompt() -> str
    write_prompt(path=None) -> Path
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ai.self_diagnostic")


def project_root() -> Path:
    """`~/Desktop/LongevityCommon/AIM/` — the parent of AI/."""
    return Path(__file__).resolve().parent.parent.parent


def ai_root() -> Path:
    return project_root() / "AI"


def prompt_path() -> Path:
    return ai_root() / "docs" / "SELF_DIAGNOSTIC_PROMPT.md"


# ── inventory builders ──────────────────────────────────────────


def _module_inventory(py_file: Path) -> dict:
    """LoC + public API + imports for one .py file."""
    info: dict = {"path": str(py_file),
                  "loc": 0,
                  "public_functions": [],
                  "public_classes": [],
                  "imports": [],
                  "tests": []}
    try:
        text = py_file.read_text(encoding="utf-8")
        info["loc"] = sum(1 for _ in text.splitlines())
    except OSError as e:
        info["error"] = str(e)
        return info
    try:
        import ast
        tree = ast.parse(text, filename=str(py_file))
    except SyntaxError as e:
        info["error"] = f"SyntaxError: {e}"
        return info

    # Top-level definitions (public API).
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            info["public_functions"].append(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            info["public_classes"].append(node.name)

    # Walk EVERY import in the file — including lazy ones inside
    # functions / try blocks. This is critical for AI/ modules that
    # use `try: from agents.X import Y; except ImportError: ...`
    # patterns; the AI subproject's whole dependency surface lives
    # inside such guards.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info["imports"].extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                info["imports"].append(node.module)
    info["imports"] = sorted(set(info["imports"]))
    return info


def _ai_modules() -> list[dict]:
    out: list[dict] = []
    d = ai_root() / "ai"
    if not d.exists():
        return out
    for p in sorted(d.glob("*.py")):
        if p.name == "__init__.py":
            continue
        info = _module_inventory(p)
        # Wire test file presence + count.
        test_p = ai_root() / "tests" / f"test_{p.stem}.py"
        if test_p.exists():
            try:
                tt = test_p.read_text(encoding="utf-8")
                info["tests"].append({
                    "path": str(test_p),
                    "loc": sum(1 for _ in tt.splitlines()),
                    "test_count": tt.count("\ndef test_"),
                })
            except OSError:
                pass
        out.append(info)
    return out


def _direction_rule_status() -> dict:
    """`agents/` MUST NOT import from `AI/`. We grep, not just AST,
    to also catch dynamic / string-based smuggling."""
    violations: list[str] = []
    agents_dir = project_root() / "agents"
    if not agents_dir.exists():
        return {"clean": True, "violations": []}
    for p in agents_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for needle in ("from AI", "import AI", "from AI.ai",
                       "import AI.ai"):
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if needle in line:
                    rel = p.relative_to(project_root())
                    violations.append(f"{rel}:{i}  {line.strip()}")
    return {"clean": not violations, "violations": violations}


def _agent_imports(modules: list[dict]) -> list[str]:
    seen: set[str] = set()
    for m in modules:
        for imp in m.get("imports", []):
            if imp.startswith("agents") or imp.startswith("agents."):
                seen.add(imp)
    return sorted(seen)


# ── public ─────────────────────────────────────────────────────


def inventory() -> dict:
    """Snapshot the AI/ surface that the prompt should audit."""
    modules = _ai_modules()
    direction = _direction_rule_status()
    return {
        "captured_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "ai_root": str(ai_root()),
        "n_modules": len(modules),
        "modules": modules,
        "agents_imports": _agent_imports(modules),
        "direction_rule": direction,
    }


def build_prompt() -> str:
    p = prompt_path()
    if not p.exists():
        raise FileNotFoundError(f"prompt template not at {p}")
    body = p.read_text(encoding="utf-8")
    inv = inventory()
    head = (
        "# AIM/AI Self-Diagnostic — Run-time Snapshot\n\n"
        f"_captured_at:_ {inv['captured_at']}\n"
        f"_ai_root:_ {inv['ai_root']}\n"
        f"_n_modules:_ {inv['n_modules']}\n"
        f"_direction_rule_clean:_ {inv['direction_rule']['clean']}\n"
        f"_agents_imports:_ {len(inv['agents_imports'])}\n\n"
        "## Inventory (ground truth — do NOT recompute, USE this)\n\n"
        + "```json\n"
        + json.dumps(inv, ensure_ascii=False, indent=2)
        + "\n```\n\n---\n\n"
    )
    instr = (
        "## Instructions to the auditing model\n\n"
        "1. Read the inventory JSON above first. Treat it as ground "
        "truth — do not rescan the filesystem yourself.\n"
        "2. Then read every numbered phase below and produce a single "
        "markdown report covering ALL 9 phases.\n"
        "3. Return your report in the exact section order. Each finding "
        "must reference `path:line` from the inventory. Inventions "
        "(non-existent files, fictional functions) auto-fail the "
        "report at L_VERIFIABILITY.\n"
        "4. Run in adversarial mode: your goal is to FIND defects, not "
        "to confirm health. If a phase produces zero findings, lower "
        "your threshold and try again before declaring it clean.\n"
        "5. End with the aggregate summary block (totals + grade) per "
        "the rubric in the prompt body.\n\n---\n\n"
    )
    return head + instr + body


def write_prompt(path: Optional[Path] = None) -> Path:
    if path is None:
        artifacts = ai_root() / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        path = artifacts / f"self_diag_request_{dt.date.today():%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_prompt(), encoding="utf-8")
    return path


def _main() -> int:
    p = write_prompt()
    print(f"prompt → {p}  ({p.stat().st_size} bytes)")
    print("paste it into Claude / DeepSeek-V4-pro / Gemini 2.5 Pro and "
          "save the response to:")
    print(f"  {ai_root() / 'artifacts' / f'self_diag_{dt.date.today():%Y-%m-%d}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
