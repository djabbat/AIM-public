"""tests/test_readme_generator.py — PR1 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "projects").mkdir()
    (tmp_path / "Desktop").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.kpi_tracker",
              "agents.readme_generator"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_proj(setup, name, body):
    (setup / "projects" / f"{name}.yaml").write_text(
        textwrap.dedent(body), encoding="utf-8")


# ── shape ────────────────────────────────────────────────────────


def test_generate_minimal(isolated):
    write_proj(isolated, "P", "name: P\nphase: DRAFT\n")
    from agents.readme_generator import generate
    out = generate("P")
    assert out.startswith("# P")
    assert "phase" in out.lower()
    assert "DRAFT" in out


def test_generate_includes_goals(isolated):
    write_proj(isolated, "P", """
        name: P
        goals:
          - Win the EIC grant
          - Publish 5 papers
    """)
    from agents.readme_generator import generate
    out = generate("P")
    assert "## Goals" in out
    assert "Win the EIC grant" in out


def test_generate_includes_milestones_with_status(isolated):
    write_proj(isolated, "P", """
        name: P
        phase: SUBMITTED
        milestones:
          - id: m1
            deadline: 2026-05-05
            criticality: high
            status: pending
            blockers:
              - Waiting on Geiger
    """)
    from agents.readme_generator import generate
    out = generate("P")
    assert "## Milestones" in out
    assert "m1" in out
    assert "high" in out
    assert "Waiting on Geiger" in out


def test_generate_includes_stakeholders(isolated):
    write_proj(isolated, "P", """
        name: P
        stakeholders:
          - name: Geiger
            role: Co-PI
            awaiting_reply: false
          - name: Late
            role: advisor
            awaiting_reply: true
            expected_response_by: 2026-04-25
    """)
    from agents.readme_generator import generate
    out = generate("P")
    assert "## Stakeholders" in out
    assert "Geiger" in out
    assert "Late" in out
    # Late has awaiting marker.
    assert "awaiting since 2026-04-25" in out


def test_generate_includes_phase_actions(isolated):
    write_proj(isolated, "P", "name: P\nphase: REVIEW\n")
    from agents.readme_generator import generate
    out = generate("P")
    assert "## Next actions (REVIEW)" in out


def test_generate_includes_kpi_block(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: pubs
            target: 5
            unit: count
            history:
              - {date: 2026-05-01, value: 3}
    """)
    from agents.readme_generator import generate
    out = generate("P")
    assert "## KPIs" in out
    assert "pubs" in out


def test_generate_no_kpi_block_when_empty(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.readme_generator import generate
    out = generate("P")
    assert "## KPIs" not in out


def test_generate_no_milestones_block_when_empty(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.readme_generator import generate
    out = generate("P")
    assert "## Milestones" not in out


# ── memory & git extracts ───────────────────────────────────────


def test_generate_pulls_project_memory(isolated, monkeypatch):
    write_proj(isolated, "FCLC", "name: FCLC\n")
    # Plant a project_*.md memory referencing FCLC.
    mem = isolated / ".claude" / "projects" / "-home-oem" / "memory"
    mem.mkdir(parents=True)
    (mem / "project_fclc_x.md").write_text(textwrap.dedent("""
        ---
        type: project
        ---
        description: FCLC consortium notes
        body referencing FCLC throughout.
    """).lstrip())
    import importlib, agents.readme_generator as rg
    importlib.reload(rg)
    out = rg.generate("FCLC")
    assert "## Project memory" in out
    assert "project_fclc_x.md" in out


def test_generate_includes_git_log(isolated, monkeypatch):
    """If `~/Desktop/<name>` is a git repo, recent commits show up."""
    import subprocess
    write_proj(isolated, "FCLC", "name: FCLC\n")
    repo = isolated / "Desktop" / "FCLC"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=repo)
    subprocess.run(["git", "config", "user.email", "t@l"], cwd=repo)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo)
    (repo / "x.txt").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo)
    subprocess.run(["git", "commit", "-q", "-m", "first commit"], cwd=repo)
    import importlib, agents.readme_generator as rg
    importlib.reload(rg)
    out = rg.generate("FCLC")
    assert "## Recent activity" in out
    assert "first commit" in out


# ── write() ──────────────────────────────────────────────────────


def test_write_creates_readme_auto(isolated):
    write_proj(isolated, "FCLC", "name: FCLC\n")
    (isolated / "Desktop" / "FCLC").mkdir()
    from agents.readme_generator import write
    p = write("FCLC")
    assert p.name == "README_AUTO.md"
    assert p.exists()
    assert "# FCLC" in p.read_text()


def test_write_custom_dest(isolated, tmp_path):
    write_proj(isolated, "P", "name: P\n")
    dest = tmp_path / "custom" / "OUT.md"
    from agents.readme_generator import write
    out = write("P", dest=dest)
    assert out == dest
    assert dest.exists()


# ── polish hook ─────────────────────────────────────────────────


def test_polish_replaces_text(isolated, monkeypatch):
    write_proj(isolated, "P", "name: P\n")
    import llm
    monkeypatch.setattr(llm, "ask_fast", lambda _p: "polished readme",
                         raising=False)
    from agents.readme_generator import generate
    out = generate("P", polish=True)
    assert out.strip() == "polished readme"


def test_polish_failure_falls_back(isolated, monkeypatch):
    write_proj(isolated, "P", "name: P\n")
    import llm

    def boom(_p):
        raise RuntimeError("nope")

    monkeypatch.setattr(llm, "ask_fast", boom, raising=False)
    from agents.readme_generator import generate
    out = generate("P", polish=True)
    assert out.startswith("# P")
