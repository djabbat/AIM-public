"""agents/readme_generator.py — auto README from project state (PR1, 2026-05-03).

For each project we own (USER/projects/<name>.yaml + ~/Desktop/<name>/),
synthesise a fresh README.md by combining:

  * Project YAML: name, phase, goals, milestones, stakeholders, KPIs
  * Memory entries tagged for this project (project_*.md)
  * Recent activity (git log if available)
  * Phase-aware next-actions (project_state_machine)

Output is a deterministic markdown skeleton; an optional LLM polish pass
keeps the structure but tightens prose. We never overwrite a README the
user is actively editing — by default we write to README_AUTO.md and
ask the user to merge.

Public API:
    generate(project, polish=False) -> str
    write(project, *, dest=None, polish=False) -> Path
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.readme_generator")


# ── deterministic template ──────────────────────────────────────


def _yaml_load(project: str):
    from agents import project_owner as po
    return po.load(project)


def _kpi_block(project: str) -> str:
    try:
        from agents.kpi_tracker import summary
        return summary(project)
    except Exception:
        return ""


def _phase_actions(phase: str) -> list[str]:
    try:
        from agents.project_state_machine import next_actions
        return next_actions(phase) or []
    except Exception:
        return []


def _git_log(project_root: Path, limit: int = 8) -> list[str]:
    if not (project_root / ".git").exists():
        return []
    try:
        out = subprocess.run(
            ["git", "log", "-n", str(limit), "--oneline", "--no-decorate"],
            cwd=project_root, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return []
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def _memory_titles(project: str, max_n: int = 8) -> list[str]:
    """Find project_*.md memories whose name/description references `project`."""
    base = (Path.home() / ".claude" / "projects" / "-home-oem" / "memory")
    if not base.exists():
        return []
    out: list[str] = []
    needle = project.lower()
    for p in sorted(base.glob("project_*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            continue
        if needle not in text.lower() and needle not in p.name.lower():
            continue
        # Pull the description: line if present.
        for line in text.splitlines()[:10]:
            if line.lower().startswith("description:"):
                out.append(f"`{p.name}` — {line.split(':', 1)[1].strip()}")
                break
        else:
            out.append(f"`{p.name}` — (no description)")
        if len(out) >= max_n:
            break
    return out


def _project_root(project: str) -> Path:
    return Path.home() / "Desktop" / project


# ── generate ─────────────────────────────────────────────────────


def generate(project: str, *, polish: bool = False) -> str:
    state = _yaml_load(project)
    today = dt.date.today()
    root = _project_root(state.name)

    md: list[str] = []
    md.append(f"# {state.name}")
    md.append("")
    md.append(f"_Last regenerated: {today.isoformat()} via "
              "`agents.readme_generator` — review before committing._")
    md.append("")

    md.append(f"**Phase:** `{state.phase}`")
    if state.canonical:
        md.append(f"**Canonical path:** `{state.canonical}`")
    md.append("")

    if state.goals:
        md.append("## Goals")
        for g in state.goals:
            md.append(f"- {g}")
        md.append("")

    if state.milestones:
        md.append("## Milestones")
        for m in state.milestones:
            d = m.days_to_deadline(today)
            tag = (f"in {d}d" if d is not None and d > 0
                    else "TODAY" if d == 0
                    else f"OVERDUE {-d}d" if d is not None
                    else "")
            line = f"- **{m.id}** — {m.status}, {m.criticality}"
            if tag:
                line += f"  ({tag})"
            md.append(line)
            for b in m.blockers[:3]:
                md.append(f"  - blocker: {b}")
        md.append("")

    if state.stakeholders:
        md.append("## Stakeholders")
        for s in state.stakeholders:
            mark = "🟡" if s.awaiting_reply else "🟢"
            md.append(f"- {mark} **{s.name}** — {s.role or '?'}"
                      + (f"  (awaiting since {s.expected_response_by})"
                         if s.awaiting_reply and s.expected_response_by else ""))
        md.append("")

    actions = _phase_actions(state.phase)
    if actions:
        md.append(f"## Next actions ({state.phase})")
        for a in actions:
            md.append(f"- {a}")
        md.append("")

    kpi_block = _kpi_block(state.name)
    if kpi_block:
        md.append("## KPIs")
        md.append("```")
        md.append(kpi_block)
        md.append("```")
        md.append("")

    log_lines = _git_log(root)
    if log_lines:
        md.append("## Recent activity")
        for l in log_lines:
            md.append(f"- {l}")
        md.append("")

    titles = _memory_titles(state.name)
    if titles:
        md.append("## Project memory")
        for t in titles:
            md.append(f"- {t}")
        md.append("")

    md.append("---")
    md.append(f"_Generated by AIM 2026-05-03 — see `agents/readme_generator.py`._")

    text = "\n".join(md).rstrip() + "\n"

    if polish:
        try:
            from llm import ask_fast
            polished = ask_fast(
                "Polish this README. Preserve every section heading, list, "
                "and link target. Tighten prose. Keep length similar.\n\n"
                + text)
            if polished and polished.strip():
                text = polished.strip() + "\n"
        except Exception as e:
            log.debug("polish failed: %s", e)
    return text


def write(project: str, *, dest: Optional[Path] = None,
          polish: bool = False) -> Path:
    text = generate(project, polish=polish)
    if dest is None:
        dest = _project_root(project) / "README_AUTO.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest
