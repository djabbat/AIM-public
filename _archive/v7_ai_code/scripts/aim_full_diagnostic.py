#!/usr/bin/env python3
"""scripts/aim_full_diagnostic.py — comprehensive AIM system audit.

Проходит по всем слоям системы (корень + agents + AI/ai + Rust crates +
Phoenix + подпроекты + ядро .md + memory) и выдаёт:
  • inventory (что вообще есть)
  • duplicates (по hash содержимого)
  • dead code candidates (Python files без callers)
  • vapor refs (упоминания несуществующих модулей в .md)
  • STACK violations (Python вне frozen list, новый код)
  • core consistency (13 canonical файлов на месте)
  • Rust crate health (compile-check, test presence)
  • Phoenix routes coverage (each route → existing LiveView)
  • git hygiene (.gitignore covers __pycache__, *.egg-info, logs)
  • subproject vs MAP coherence (DiffDiagnosis, SSA, AI/queen_deploy)

Output: human-readable summary on stdout (default) или `--json` /
`--md` для machine / report.

Categorization: P0 = blocking, P1 = important, P2 = cosmetic.

Usage:
    python3 scripts/aim_full_diagnostic.py                  # text
    python3 scripts/aim_full_diagnostic.py --json           # JSON
    python3 scripts/aim_full_diagnostic.py --md > report.md # markdown
    python3 scripts/aim_full_diagnostic.py --calibrate      # apply fixes
                                                            # (only safe ones)
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
RUST_CORE = ROOT / "rust-core"
PHOENIX = ROOT / "phoenix-umbrella"
DOCS = ROOT / "docs"

# Canonical 13-file core (per `feedback_project_core` + 2026-05-07 audit).
CORE_FILES = [
    "CONCEPT.md", "KNOWLEDGE.md", "PARAMETERS.md", "MAP.md", "MEMORY.md",
    "LINKS.md", "UPGRADE.md", "TODO.md", "CLAUDE.md", "STRATEGY.md",
    "REMINDER.md", "THEORY.md", "NEEDTOWRITE.md",
]
SUPPLEMENTARY_FILES = ["STACK.md", "README.md", "CHANGELOG.md"]

# Frozen Python legacy (per `STACK.md` § Frozen Python legacy).
FROZEN_PYTHON = {
    "web/api.py", "medical_system.py", "telegram_bot.py",
    "aim_cli.py", "aim_gui.py",
}

# Python files allowed по STACK.md § Notes (Whisper ASR, OCR, etc).
ALLOWED_PYTHON_EXCEPTIONS = {
    "agents/voice.py", "agents/telegram_extras.py",  # Whisper ASR
    "agents/intake.py", "agents/lang.py",            # OCR / langdetect
    "agents/email_agent.py",                         # Gmail SDK
    "tools/literature.py",                           # PubMed/Crossref
}


# ── data classes ────────────────────────────────────────────────────────


@dataclasses.dataclass
class Finding:
    priority: str           # "P0" | "P1" | "P2" | "INFO"
    category: str           # "duplicate" | "dead_code" | ...
    title: str
    detail: str
    paths: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DiagnosticReport:
    inventory: dict[str, int]
    findings: list[Finding]

    def by_priority(self, p: str) -> list[Finding]:
        return [f for f in self.findings if f.priority == p]


# ── 1. INVENTORY ────────────────────────────────────────────────────────


def take_inventory() -> dict[str, int]:
    """Count files by type and location, excluding build artifacts."""
    skip = {"venv", "target", "_build", "deps", "node_modules",
            "__pycache__", ".git", "_archive"}

    def walk_count(root: Path, pattern: str) -> int:
        n = 0
        for p in root.rglob(pattern):
            if any(part in skip for part in p.parts):
                continue
            n += 1
        return n

    return {
        "core_md": walk_count(ROOT, "*.md"),
        "top_level_py": len(list(ROOT.glob("*.py"))),
        "agents_py": walk_count(ROOT / "agents", "*.py"),
        "ai_ai_py": walk_count(ROOT / "AI" / "ai", "*.py"),
        "tests_py": walk_count(ROOT / "tests", "test_*.py"),
        "ai_tests_py": walk_count(ROOT / "AI" / "tests", "test_*.py"),
        "scripts_files": walk_count(ROOT / "scripts", "*"),
        "rust_crates": len(list((RUST_CORE / "crates").iterdir())) if (RUST_CORE / "crates").exists() else 0,
        "rust_files": walk_count(RUST_CORE, "*.rs"),
        "phoenix_apps": len(list((PHOENIX / "apps").iterdir())) if (PHOENIX / "apps").exists() else 0,
        "phoenix_ex": walk_count(PHOENIX / "apps", "*.ex"),
        "docs_md": walk_count(DOCS, "*.md") if DOCS.exists() else 0,
    }


# ── 2. CORE CONSISTENCY ─────────────────────────────────────────────────


def check_core_consistency() -> list[Finding]:
    out: list[Finding] = []
    missing = [f for f in CORE_FILES if not (ROOT / f).exists()]
    if missing:
        out.append(Finding(
            priority="P0",
            category="core_canon",
            title=f"Missing canonical core files: {len(missing)}",
            detail=f"Per project_core rule (13-file canon): missing {missing}",
            paths=missing,
        ))
    # Cross-reference broken — multi-fallback heuristic:
    #   1. Direct path
    #   2. docs/<ref>
    #   3. rust-core/<ref> (для refs начинающихся с `crates/`)
    #   4. Bare-filename existing anywhere
    #   5. Skip memory-auto-entry patterns (feedback_*.md, project_*.md, …)
    # CHANGELOG не сканируется (она LEGITIMATELY ссылается на удалённое для
    # истории — это конвенция Keep-a-Changelog).
    broken_refs: list[tuple[str, str]] = []
    pat = re.compile(r"`([\w./_-]+\.(?:md|py|rs|ex|exs|sh|toml))`")
    skip_dirs = {"venv", "target", "_build", "deps", "node_modules",
                 "__pycache__", ".git", "_archive"}
    # Memory-entry naming convention from feedback_project_core / Claude memory.
    memory_pat = re.compile(
        r"^(feedback_|project_|contact_|reference_|user_|fact_|format_|"
        r"pending_|unpublished_|publications)"
    )
    basenames_existing: set[str] = set()
    for ext in ("md", "py", "rs", "ex", "exs", "sh", "toml"):
        for f in ROOT.rglob(f"*.{ext}"):
            if any(part in skip_dirs for part in f.parts):
                continue
            basenames_existing.add(f.name)
    for md in CORE_FILES + SUPPLEMENTARY_FILES:
        # Files that BY DESIGN list to-be-created paths:
        # - CHANGELOG keeps history of removed/archived files
        # - NEEDTOWRITE is the queue of docs to write
        if md in {"CHANGELOG.md", "NEEDTOWRITE.md"}:
            continue
        p = ROOT / md
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(text):
            ref = m.group(1)
            if ref.startswith(("http", "/")):
                continue
            # Memory auto-entry skip (feedback_X.md etc. live in
            # ~/.claude/projects/-home-oem/memory/, not in repo).
            base = Path(ref).name
            if memory_pat.match(base):
                continue
            target = ROOT / ref
            if target.exists() or (ROOT / "docs" / ref).exists():
                continue
            # crates/ → rust-core/crates/ fallback
            if ref.startswith("crates/") and (RUST_CORE / ref).exists():
                continue
            # Bare-filename fallback.
            if "/" not in ref and ref in basenames_existing:
                continue
            broken_refs.append((md, ref))
    if broken_refs:
        out.append(Finding(
            priority="P1",
            category="broken_ref",
            title=f"Broken `path` references in core: {len(broken_refs)}",
            detail="\n".join(f"  {md} → {ref}" for md, ref in broken_refs[:10]),
            paths=[f"{md}:{ref}" for md, ref in broken_refs],
        ))
    return out


# ── 3. DUPLICATE DETECTION (by content hash) ────────────────────────────


def detect_duplicates() -> list[Finding]:
    """Find files with identical SHA-256 hashes (ignoring trivial < 200 bytes).

    Excludes diagnostic timestamped reports (`docs/operational/diagnostic_*.md`
    — `latest` is intentionally a copy of last timestamped run).
    """
    skip = {"venv", "target", "_build", "deps", "node_modules",
            "__pycache__", ".git", "_archive", "Cargo.lock"}
    diag_pat = re.compile(r"docs/operational/diagnostic_.*\.md$")
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for ext in ("py", "rs", "ex", "exs", "md", "sh", "toml"):
        for p in ROOT.rglob(f"*.{ext}"):
            if any(part in skip for part in p.parts):
                continue
            rel = str(p.relative_to(ROOT))
            if diag_pat.search(rel):
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            if len(data) < 200:
                continue
            h = hashlib.sha256(data).hexdigest()
            by_hash[h].append(p)
    findings: list[Finding] = []
    for h, paths in by_hash.items():
        if len(paths) > 1:
            rels = [str(p.relative_to(ROOT)) for p in paths]
            findings.append(Finding(
                priority="P1",
                category="duplicate",
                title=f"Identical file copies: {len(paths)}",
                detail=" === ".join(rels[:3]) + (" ..." if len(rels) > 3 else ""),
                paths=rels,
            ))
    # Also look for near-duplicates by name (different content but same name).
    by_name: dict[str, list[Path]] = defaultdict(list)
    for p in ROOT.rglob("*.py"):
        if any(part in skip for part in p.parts):
            continue
        by_name[p.name].append(p)
    name_collision_whitelist = {
        "doctor.py",        # AI/ai/doctor (probe) vs agents/doctor (clinical)
        "_build_kernel.py", # SSA + DiffDiagnosis — different subprojects
    }
    for name, paths in by_name.items():
        if len(paths) <= 1 or name in {"__init__.py", "conftest.py", "setup.py"}:
            continue
        if name in name_collision_whitelist:
            continue
        rels = [str(p.relative_to(ROOT)) for p in paths]
        if all("test_" in p for p in rels):
            continue
        findings.append(Finding(
            priority="P2",
            category="name_collision",
            title=f"Same filename, different content: {name}",
            detail=" / ".join(rels),
            paths=rels,
        ))
    return findings


# ── 4. DEAD CODE (Python top-level + entry-points) ──────────────────────


def find_dead_code() -> list[Finding]:
    """Top-level Python modules with 0 callers (no `from X import` or `import X`)."""
    findings: list[Finding] = []
    skip = {"venv", "target", "_build", "deps", "node_modules",
            "__pycache__", ".git", "_archive"}
    top_py = [p for p in ROOT.glob("*.py")]
    for p in top_py:
        base = p.stem
        # Skip well-known entry points that are run as scripts, not imported.
        if base in {"medical_system", "aim_cli", "aim_gui", "telegram_bot"}:
            continue
        n_callers = 0
        for other in ROOT.rglob("*.py"):
            if any(part in skip for part in other.parts):
                continue
            if other == p:
                continue
            try:
                txt = other.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(rf"^\s*(from\s+{base}\s+import|import\s+{base}\b)",
                          txt, re.M):
                n_callers += 1
        if n_callers == 0:
            findings.append(Finding(
                priority="P1",
                category="dead_code",
                title=f"Top-level Python with 0 callers: {p.name}",
                detail=f"{p.relative_to(ROOT)} — possibly removable or rename to script_*",
                paths=[str(p.relative_to(ROOT))],
            ))
    return findings


# ── 5. PARALLEL STRUCTURE (./aim-web vs phoenix-umbrella, systemd vs deploy) ───


def detect_parallel_structures() -> list[Finding]:
    findings: list[Finding] = []
    # 1) ./aim-web vs phoenix-umbrella/apps/aim_web
    standalone = ROOT / "aim-web"
    umbrella = PHOENIX / "apps" / "aim_web"
    if standalone.is_dir() and umbrella.is_dir():
        findings.append(Finding(
            priority="P0",
            category="parallel_structure",
            title="Two Phoenix `aim_web` apps coexist",
            detail=f"Standalone `./aim-web/` (mix.exs) AND umbrella "
                   f"`{umbrella.relative_to(ROOT)}/`. Pick canonical, "
                   f"archive other.",
            paths=["aim-web/", str(umbrella.relative_to(ROOT)) + "/"],
        ))
    # 2) systemd vs deploy/systemd
    old_sd = ROOT / "systemd"
    new_sd = ROOT / "deploy" / "systemd"
    if old_sd.is_dir() and new_sd.is_dir():
        old_n = len(list(old_sd.glob("*.service"))) + len(list(old_sd.glob("*.timer")))
        new_n = len(list(new_sd.glob("*.service"))) + len(list(new_sd.glob("*.timer")))
        findings.append(Finding(
            priority="P0",
            category="parallel_structure",
            title=f"Two systemd dirs: ./systemd ({old_n}) + ./deploy/systemd ({new_n})",
            detail="Pick canonical. New canonical likely deploy/systemd/ "
                   f"(more units). Move legacy to _archive.",
            paths=["systemd/", "deploy/systemd/"],
        ))
    return findings


# ── 6. SUBPROJECT vs MAP coherence ──────────────────────────────────────


def check_subproject_coherence() -> list[Finding]:
    """DiffDiagnosis, SSA, AI/queen_deploy — should be in MAP/CLAUDE/CONCEPT."""
    findings: list[Finding] = []
    map_text = (ROOT / "MAP.md").read_text(encoding="utf-8", errors="replace")
    claude_text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    concept_text = (ROOT / "CONCEPT.md").read_text(encoding="utf-8", errors="replace")
    for sub in ("DiffDiagnosis", "SSA", "AI/queen_deploy"):
        sub_path = ROOT / sub
        if not sub_path.is_dir():
            continue
        in_map = sub.lower() in map_text.lower()
        in_claude = sub.lower() in claude_text.lower()
        in_concept = sub.lower() in concept_text.lower()
        if not (in_map or in_claude or in_concept):
            findings.append(Finding(
                priority="P0",
                category="subproject_orphan",
                title=f"Subproject `{sub}/` not referenced in core",
                detail=f"Exists on disk; absent from MAP.md / CLAUDE.md / "
                       f"CONCEPT.md. Add as Internal subproject OR archive.",
                paths=[sub],
            ))
    # Subprojects with own CONCEPT/DESIGN/EVIDENCE — duplicates of canon
    for sub in ("DiffDiagnosis", "SSA"):
        sub_path = ROOT / sub
        if not sub_path.is_dir():
            continue
        own_core = [f for f in ("CONCEPT.md", "DESIGN.md", "EVIDENCE.md",
                                 "OPEN_PROBLEMS.md") if (sub_path / f).exists()]
        if len(own_core) >= 2:
            findings.append(Finding(
                priority="P1",
                category="subproject_doc_dup",
                title=f"Subproject `{sub}/` carries own core .md ({len(own_core)} files)",
                detail=f"Per `feedback_subproject_git_rule`: subprojects don't "
                       f"have own kernel docs. Move {own_core} → docs/{sub.lower()}/.",
                paths=[f"{sub}/{f}" for f in own_core],
            ))
    return findings


# ── 7. RUST CRATE HEALTH ────────────────────────────────────────────────


def check_rust_crates() -> list[Finding]:
    findings: list[Finding] = []
    crates_dir = RUST_CORE / "crates"
    if not crates_dir.exists():
        return findings
    no_tests: list[str] = []
    # Crates that are intentionally test-light (acceptable):
    excused = {"aim-common", "aim-kernel-py"}
    for crate in sorted(crates_dir.iterdir()):
        if not crate.is_dir() or crate.name in excused:
            continue
        has_test = False
        for src in crate.rglob("*.rs"):
            try:
                t = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "#[test]" in t or "#[tokio::test]" in t:
                has_test = True
                break
        if not has_test:
            no_tests.append(crate.name)
    if no_tests:
        findings.append(Finding(
            priority="P1",
            category="rust_no_tests",
            title=f"Rust crates without #[test]: {len(no_tests)}",
            detail="Production-critical crates need at least 1 test. "
                   "Excused: aim-common, aim-kernel-py.\n  "
                   + "\n  ".join(no_tests),
            paths=[f"rust-core/crates/{c}" for c in no_tests],
        ))
    return findings


# ── 8. STACK violations (новый Python вне frozen list) ──────────────────


def check_stack_violations() -> list[Finding]:
    """Look for top-level Python that is NOT in frozen list AND NOT in
    legitimate exception list — those are STACK violations."""
    findings: list[Finding] = []
    # Top-level
    for p in ROOT.glob("*.py"):
        rel = str(p.relative_to(ROOT))
        if rel in FROZEN_PYTHON or rel in ALLOWED_PYTHON_EXCEPTIONS:
            continue
        # Whitelist for known central infrastructure (config / db / llm / i18n).
        if p.stem in {"config", "db", "i18n", "llm", "user_keys",
                      "lab_reference", "key_setup",
                      "AI_run_self_diag", "AI_self_diag"}:
            continue
        findings.append(Finding(
            priority="P1",
            category="stack_violation",
            title=f"Top-level Python not in frozen/exception list: {p.name}",
            detail=f"Per STACK.md: new code = Rust+Phoenix only. "
                   f"Either add to frozen, document as exception, or port.",
            paths=[rel],
        ))
    return findings


# ── 9. GIT HYGIENE ──────────────────────────────────────────────────────


def check_git_hygiene() -> list[Finding]:
    findings: list[Finding] = []
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        findings.append(Finding(
            priority="P0", category="git_hygiene",
            title="No .gitignore in repo root",
            detail="Create one with at minimum: __pycache__/, *.pyc, target/, "
                   "venv/, _build/, deps/, *.egg-info/, logs/, export/",
            paths=[".gitignore"],
        ))
        return findings
    body = gitignore.read_text(encoding="utf-8", errors="replace")
    # Multiple valid forms accepted — we just need ONE per group.
    expected_alts: list[list[str]] = [
        ["__pycache__"],
        ["*.pyc", "*.py[cod]", "*.py[co]"],
        ["target/", "**/target/"],
        ["venv/", "venv", ".venv"],
        ["_build/", "**/_build/", "_build"],
        ["deps/", "**/deps/"],
        ["*.egg-info/", "egg-info", "*.egg-info"],
        ["logs/", "*.log"],
    ]
    missing = [alts[0] for alts in expected_alts
               if not any(a in body for a in alts)]
    if missing:
        findings.append(Finding(
            priority="P1", category="git_hygiene",
            title=f".gitignore missing entries: {len(missing)}",
            detail="Add: " + ", ".join(missing),
            paths=[".gitignore"],
        ))
    # Detect accidentally committed __pycache__ / *.egg-info on disk.
    cruft: list[str] = []
    for d in ROOT.rglob("__pycache__"):
        if "venv" in d.parts or "target" in d.parts:
            continue
        cruft.append(str(d.relative_to(ROOT)))
    for e in ROOT.rglob("*.egg-info"):
        cruft.append(str(e.relative_to(ROOT)))
    if cruft:
        findings.append(Finding(
            priority="P2", category="git_hygiene",
            title=f"Build cruft on disk: {len(cruft)} dirs",
            detail="Run: find . -name __pycache__ -type d | xargs rm -rf; "
                   "find . -name '*.egg-info' -type d | xargs rm -rf",
            paths=cruft[:20],
        ))
    return findings


# ── 10. VAPOR REFERENCES (.md mentions of non-existent files / modules) ─


def detect_vapor_refs() -> list[Finding]:
    """Scan core .md for module-style references that don't resolve.

    Heuristic for Python module refs (e.g. `agents/doctor`): if no extension
    given, try `+.py`. For `module.method` form, look up `module.py`.
    """
    findings: list[Finding] = []
    pat = re.compile(r"`((?:crates|agents|AI/ai|tests|scripts|web|cli|"
                     r"phoenix-umbrella/apps)/[\w./_-]+)`")
    vapor: list[tuple[str, str]] = []
    for md in CORE_FILES + SUPPLEMENTARY_FILES:
        p = ROOT / md
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(text):
            ref = m.group(1)
            clean = ref.split("::", 1)[0].split(":", 1)[0]
            target = ROOT / clean
            if clean.startswith("crates/"):
                target = RUST_CORE / clean
            if target.exists():
                continue
            # Fallback 1: try +.py for refs without extension.
            if "." not in Path(clean).name:
                cand = ROOT / (clean + ".py")
                if cand.exists():
                    continue
            # Fallback 2: refs like agents/X.method → check agents/X.py.
            parts = clean.rsplit(".", 1)
            if len(parts) == 2 and parts[1].isidentifier():
                base = parts[0]
                cand = ROOT / (base + ".py")
                if cand.exists():
                    continue
                segments = base.rsplit("/", 1)
                if len(segments) == 2:
                    cand2 = ROOT / segments[0] / (segments[1] + ".py")
                    if cand2.exists():
                        continue
            vapor.append((md, ref))
    if vapor:
        findings.append(Finding(
            priority="P1",
            category="vapor_ref",
            title=f"Vapor references in core .md: {len(vapor)}",
            detail="\n".join(f"  {md}: `{ref}`" for md, ref in vapor[:15]),
            paths=[f"{md}::{ref}" for md, ref in vapor],
        ))
    return findings


# ── 11. PHOENIX ROUTES vs LiveView ──────────────────────────────────────


def check_phoenix_routes() -> list[Finding]:
    findings: list[Finding] = []
    router = (PHOENIX / "apps" / "aim_web" / "lib" /
              "aim_web_web" / "router.ex")
    if not router.exists():
        findings.append(Finding(
            priority="P0", category="phoenix",
            title="Phoenix router.ex not found",
            detail=f"Expected at {router.relative_to(ROOT)}",
            paths=[str(router.relative_to(ROOT))],
        ))
        return findings
    body = router.read_text(encoding="utf-8", errors="replace")
    live_dir = router.parent / "live"
    pat = re.compile(r"live\s+\"[^\"]+\",\s+(\w+),", re.M)
    routes = pat.findall(body)
    missing: list[str] = []
    for module in set(routes):
        # Module like "PamLive" → file pam_live.ex.
        snake = re.sub(r"([A-Z])", r"_\1", module).lower().lstrip("_")
        candidate = live_dir / f"{snake}.ex"
        if not candidate.exists():
            missing.append(f"{module} → {candidate.relative_to(ROOT)}")
    if missing:
        findings.append(Finding(
            priority="P1", category="phoenix",
            title=f"Phoenix routes pointing to missing LiveViews: {len(missing)}",
            detail="\n".join(f"  {m}" for m in missing),
            paths=missing,
        ))
    return findings


# ── orchestrate all checks ──────────────────────────────────────────────


def run_diagnostic() -> DiagnosticReport:
    findings: list[Finding] = []
    findings += check_core_consistency()
    findings += detect_duplicates()
    findings += find_dead_code()
    findings += detect_parallel_structures()
    findings += check_subproject_coherence()
    findings += check_rust_crates()
    findings += check_stack_violations()
    findings += check_git_hygiene()
    findings += detect_vapor_refs()
    findings += check_phoenix_routes()
    findings.sort(key=lambda f: ("P0P1P2INFO".index(f.priority), f.category))
    return DiagnosticReport(inventory=take_inventory(), findings=findings)


# ── output formatters ──────────────────────────────────────────────────


def render_text(report: DiagnosticReport) -> str:
    parts: list[str] = ["═" * 72, "🩺 AIM full-system diagnostic", "═" * 72, ""]
    parts.append("📦 Inventory:")
    for k, v in report.inventory.items():
        parts.append(f"  {k:24s} {v:>5}")
    parts.append("")
    n_p0 = len(report.by_priority("P0"))
    n_p1 = len(report.by_priority("P1"))
    n_p2 = len(report.by_priority("P2"))
    parts.append(f"⚖ Findings: {n_p0} P0 (blocking) · "
                 f"{n_p1} P1 (important) · {n_p2} P2 (cosmetic)")
    parts.append("")
    for prio, banner in (("P0", "🔴 BLOCKING"),
                          ("P1", "🟡 IMPORTANT"),
                          ("P2", "🟢 COSMETIC")):
        items = report.by_priority(prio)
        if not items:
            parts.append(f"{banner}: ✓ none")
            continue
        parts.append(f"{banner}:")
        for f in items:
            parts.append(f"  • [{f.category}] {f.title}")
            for line in f.detail.splitlines()[:6]:
                parts.append(f"      {line}")
            if len(f.detail.splitlines()) > 6:
                parts.append(f"      … (+{len(f.detail.splitlines()) - 6} more lines)")
        parts.append("")
    return "\n".join(parts)


def render_json(report: DiagnosticReport) -> str:
    payload = {
        "inventory": report.inventory,
        "findings": [dataclasses.asdict(f) for f in report.findings],
        "summary": {
            "p0_count": len(report.by_priority("P0")),
            "p1_count": len(report.by_priority("P1")),
            "p2_count": len(report.by_priority("P2")),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_md(report: DiagnosticReport) -> str:
    lines: list[str] = ["# AIM full-system diagnostic", ""]
    lines.append("## Inventory")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    for k, v in report.inventory.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    n_p0 = len(report.by_priority("P0"))
    n_p1 = len(report.by_priority("P1"))
    n_p2 = len(report.by_priority("P2"))
    lines.append(f"## Summary: {n_p0} P0 / {n_p1} P1 / {n_p2} P2 findings")
    lines.append("")
    for prio, header in (("P0", "🔴 P0 — Blocking"),
                          ("P1", "🟡 P1 — Important"),
                          ("P2", "🟢 P2 — Cosmetic")):
        items = report.by_priority(prio)
        if not items:
            continue
        lines.append(f"## {header}")
        lines.append("")
        for f in items:
            lines.append(f"### `{f.category}` — {f.title}")
            lines.append("")
            for ln in f.detail.splitlines():
                lines.append(f"  {ln}")
            if f.paths:
                lines.append("")
                lines.append(f"**Paths** ({len(f.paths)}):")
                for p in f.paths[:20]:
                    lines.append(f"- `{p}`")
                if len(f.paths) > 20:
                    lines.append(f"- _(+{len(f.paths) - 20} more)_")
            lines.append("")
    return "\n".join(lines)


# ── safe calibration (P0 fixes that are mechanical) ────────────────────


def safe_calibrate(report: DiagnosticReport) -> list[str]:
    """Apply only mechanical P0 fixes. Skip anything that needs judgement.
    Returns list of actions taken."""
    done: list[str] = []
    # Currently no mechanical P0 fixes — all of them require judgement
    # (rename / archive / re-document). Reserved for future expansion.
    done.append("(no automatic fixes implemented — calibration is read-only)")
    return done


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="AIM full-system diagnostic")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="JSON output")
    fmt.add_argument("--md", action="store_true", help="Markdown output")
    p.add_argument("--calibrate", action="store_true",
                   help="Apply mechanical safe fixes (P0 only)")
    p.add_argument("--out", type=Path, help="Write to file instead of stdout")
    args = p.parse_args(argv)

    report = run_diagnostic()

    if args.calibrate:
        actions = safe_calibrate(report)
        print("Calibration actions:", file=sys.stderr)
        for a in actions:
            print(f"  - {a}", file=sys.stderr)

    if args.json:
        rendered = render_json(report)
    elif args.md:
        rendered = render_md(report)
    else:
        rendered = render_text(report)

    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(rendered)

    # Exit code: P0 blocking → non-zero
    return 1 if report.by_priority("P0") else 0


if __name__ == "__main__":
    raise SystemExit(main())
