"""agents/project_export.py — bundle a project into a zip (EX1, 2026-05-03).

Composes everything we know about a project into one shareable archive:

  * `project.yaml`          — current YAML
  * `README_AUTO.md`        — generated README (PR1)
  * `morning_brief.txt`     — current brief (P1)
  * `phase_actions.txt`     — per-phase next actions (P5)
  * `memory.md`             — concatenated relevant memory entries
  * `git_log.txt`           — last 50 commits if a desktop dir is a repo
  * `manifest.json`         — what's in here, with hashes + timestamps

Use cases:
  * email a co-PI a snapshot ("here's where FCLC stands today")
  * archive a project's decision-log before transition to PUBLISHED
  * back-up before rough refactor
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import io
import json
import logging
import os
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.project_export")


@dataclasses.dataclass
class ExportResult:
    project: str
    archive_path: Path
    members: list[str]
    bytes_total: int


# ── helpers ──────────────────────────────────────────────────────


def _yaml_text(project: str) -> str:
    from agents import project_owner as po
    p = po.projects_dir() / f"{project}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"no project YAML at {p}")
    return p.read_text(encoding="utf-8")


def _morning_brief_text(project: str) -> str:
    try:
        from agents.project_owner import morning_brief
        return morning_brief(project)
    except Exception as e:
        return f"(brief failed: {e})"


def _phase_actions_text(project: str) -> str:
    try:
        from agents.project_owner import load
        from agents.project_state_machine import next_actions
        state = load(project)
        actions = next_actions(state.phase) or []
        if not actions:
            return f"(no advisory actions for phase {state.phase})"
        lines = [f"Phase: {state.phase}", ""]
        for a in actions:
            lines.append(f"- {a}")
        return "\n".join(lines)
    except Exception as e:
        return f"(actions failed: {e})"


def _readme_text(project: str) -> str:
    try:
        from agents.readme_generator import generate
        return generate(project)
    except Exception as e:
        return f"(README failed: {e})"


def _memory_text(project: str, max_files: int = 12) -> str:
    base = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
    if not base.exists():
        return ""
    needle = project.lower()
    out: list[str] = []
    for p in sorted(base.glob("project_*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle not in text.lower() and needle not in p.name.lower():
            continue
        out.append(f"--- {p.name} ---")
        out.append(text)
        out.append("")
        if len(out) // 3 >= max_files:
            break
    return "\n".join(out)


def _git_log_text(project_root: Path, limit: int = 50) -> str:
    if not (project_root / ".git").exists():
        return ""
    try:
        proc = subprocess.run(
            ["git", "log", "-n", str(limit), "--pretty=oneline",
             "--abbrev-commit"],
            cwd=project_root, capture_output=True, text=True, check=False,
        )
        return proc.stdout
    except FileNotFoundError:
        return ""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:12]


# ── bundle ───────────────────────────────────────────────────────


def export(project: str, *, dest: Optional[Path] = None) -> ExportResult:
    """Build a zip and return its path + manifest."""
    yaml_text = _yaml_text(project)
    brief = _morning_brief_text(project)
    phase = _phase_actions_text(project)
    readme = _readme_text(project)
    memory = _memory_text(project)
    project_root = Path.home() / "Desktop" / project
    git_log = _git_log_text(project_root)

    members = [
        ("project.yaml",        yaml_text),
        ("README_AUTO.md",      readme),
        ("morning_brief.txt",   brief),
        ("phase_actions.txt",   phase),
        ("memory.md",           memory),
        ("git_log.txt",         git_log),
    ]

    manifest = {
        "project":  project,
        "exported_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "members":  [
            {"name": name, "size": len(text), "sha": _hash(text)}
            for name, text in members
        ],
    }

    if dest is None:
        out_dir = Path(os.environ.get("AIM_EXPORT_DIR")
                        or Path.home() / "Desktop" / "_exports").expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = out_dir / f"{project}-{stamp}.zip"

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members:
            z.writestr(f"{project}/{name}", text)
        z.writestr(f"{project}/manifest.json",
                   json.dumps(manifest, indent=2, ensure_ascii=False))

    return ExportResult(
        project=project, archive_path=dest,
        members=[m["name"] for m in manifest["members"]] + ["manifest.json"],
        bytes_total=dest.stat().st_size,
    )
