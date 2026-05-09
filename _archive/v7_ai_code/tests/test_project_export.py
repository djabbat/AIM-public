"""tests/test_project_export.py — EX1 (2026-05-03)."""
from __future__ import annotations

import json
import textwrap
import zipfile

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "projects").mkdir()
    (tmp_path / "Desktop").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.readme_generator",
              "agents.project_export"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_proj(setup, name, body):
    (setup / "projects" / f"{name}.yaml").write_text(
        textwrap.dedent(body), encoding="utf-8")


# ── happy path ───────────────────────────────────────────────────


def test_export_creates_zip(isolated):
    write_proj(isolated, "FCLC", "name: FCLC\nphase: SUBMITTED\n")
    from agents.project_export import export
    res = export("FCLC")
    assert res.archive_path.exists()
    assert res.archive_path.suffix == ".zip"
    assert res.bytes_total > 0


def test_export_zip_has_required_members(isolated):
    write_proj(isolated, "P", "name: P\nphase: DRAFT\n")
    from agents.project_export import export
    res = export("P")
    with zipfile.ZipFile(res.archive_path) as z:
        names = {n for n in z.namelist()}
    assert "P/project.yaml" in names
    assert "P/README_AUTO.md" in names
    assert "P/morning_brief.txt" in names
    assert "P/phase_actions.txt" in names
    assert "P/memory.md" in names
    assert "P/git_log.txt" in names
    assert "P/manifest.json" in names


def test_manifest_lists_all_members(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.project_export import export
    res = export("P")
    with zipfile.ZipFile(res.archive_path) as z:
        manifest = json.loads(z.read("P/manifest.json"))
    member_names = [m["name"] for m in manifest["members"]]
    for required in ("project.yaml", "README_AUTO.md",
                     "morning_brief.txt", "phase_actions.txt"):
        assert required in member_names
    assert manifest["project"] == "P"


def test_yaml_member_matches_source(isolated):
    write_proj(isolated, "P", "name: P\nphase: ACCEPTED\n")
    from agents.project_export import export
    res = export("P")
    with zipfile.ZipFile(res.archive_path) as z:
        text = z.read("P/project.yaml").decode("utf-8")
    assert "phase: ACCEPTED" in text


def test_readme_member_includes_project_name(isolated):
    write_proj(isolated, "FCLC", "name: FCLC\n")
    from agents.project_export import export
    res = export("FCLC")
    with zipfile.ZipFile(res.archive_path) as z:
        readme = z.read("FCLC/README_AUTO.md").decode("utf-8")
    assert "# FCLC" in readme


def test_morning_brief_member_present(isolated):
    write_proj(isolated, "P", """
        name: P
        phase: SUBMITTED
        milestones:
          - id: m
            deadline: 2026-05-05
            criticality: high
            status: pending
    """)
    from agents.project_export import export
    res = export("P")
    with zipfile.ZipFile(res.archive_path) as z:
        brief = z.read("P/morning_brief.txt").decode("utf-8")
    assert "P" in brief
    assert "phase: SUBMITTED" in brief or "SUBMITTED" in brief


# ── memory pull ──────────────────────────────────────────────────


def test_memory_member_picks_relevant(isolated):
    write_proj(isolated, "FCLC", "name: FCLC\n")
    mem_dir = isolated / ".claude" / "projects" / "-home-oem" / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "project_fclc_x.md").write_text("FCLC consortium notes\n")
    (mem_dir / "project_other_y.md").write_text("unrelated notes\n")
    import importlib, agents.project_export as pe
    importlib.reload(pe)
    res = pe.export("FCLC")
    with zipfile.ZipFile(res.archive_path) as z:
        memory = z.read("FCLC/memory.md").decode("utf-8")
    assert "project_fclc_x.md" in memory
    assert "project_other_y.md" not in memory


# ── git log ─────────────────────────────────────────────────────


def test_git_log_member_when_repo_exists(isolated):
    import subprocess
    write_proj(isolated, "P", "name: P\n")
    repo = isolated / "Desktop" / "P"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=repo)
    subprocess.run(["git", "config", "user.email", "t@l"], cwd=repo)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo)
    (repo / "x").write_text("y")
    subprocess.run(["git", "add", "."], cwd=repo)
    subprocess.run(["git", "commit", "-q", "-m", "initial export"], cwd=repo)
    import importlib, agents.project_export as pe
    importlib.reload(pe)
    res = pe.export("P")
    with zipfile.ZipFile(res.archive_path) as z:
        log_text = z.read("P/git_log.txt").decode("utf-8")
    assert "initial export" in log_text


def test_git_log_empty_when_no_repo(isolated):
    write_proj(isolated, "P", "name: P\n")
    (isolated / "Desktop" / "P").mkdir()
    from agents.project_export import export
    res = export("P")
    with zipfile.ZipFile(res.archive_path) as z:
        log_text = z.read("P/git_log.txt").decode("utf-8")
    assert log_text == ""


# ── error path ──────────────────────────────────────────────────


def test_export_unknown_raises(isolated):
    from agents.project_export import export
    with pytest.raises(FileNotFoundError):
        export("ghost")


# ── custom dest ─────────────────────────────────────────────────


def test_export_custom_dest(isolated, tmp_path):
    write_proj(isolated, "P", "name: P\n")
    dest = tmp_path / "custom" / "out.zip"
    from agents.project_export import export
    res = export("P", dest=dest)
    assert res.archive_path == dest
    assert dest.exists()
