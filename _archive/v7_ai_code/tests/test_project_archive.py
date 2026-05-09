"""tests/test_project_archive.py — A1 archive flow (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import os
import textwrap
import time

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    (tmp_path / "projects").mkdir()
    import importlib
    for m in ["agents.project_owner", "agents.project_archive"]:
        if m in __import__("sys").modules:
            importlib.reload(__import__("sys").modules[m])
    return tmp_path


def write_proj(setup, name, body="name: P\nphase: DRAFT\n"):
    p = setup / "projects" / f"{name}.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# ── archive / unarchive roundtrip ───────────────────────────────


def test_archive_moves_yaml(isolated):
    write_proj(isolated, "FCLC")
    from agents import project_archive as pa
    dest = pa.archive("FCLC", reason="closed")
    assert dest.exists()
    assert not (isolated / "projects" / "FCLC.yaml").exists()
    assert "FCLC.yaml" in dest.name


def test_archive_does_not_clobber(isolated):
    write_proj(isolated, "X")
    from agents import project_archive as pa
    pa.archive("X")
    write_proj(isolated, "X")
    second = pa.archive("X")
    # Second copy gets a stamp suffix.
    assert "." in second.stem.split("X")[1]


def test_archive_unknown_raises(isolated):
    from agents import project_archive as pa
    with pytest.raises(FileNotFoundError):
        pa.archive("ghost")


def test_unarchive_restores(isolated):
    write_proj(isolated, "FCLC")
    from agents import project_archive as pa
    pa.archive("FCLC")
    pa.unarchive("FCLC")
    assert (isolated / "projects" / "FCLC.yaml").exists()


def test_unarchive_refuses_overwrite(isolated):
    write_proj(isolated, "Y")
    from agents import project_archive as pa
    pa.archive("Y")
    write_proj(isolated, "Y")    # someone created a new active Y
    with pytest.raises(FileExistsError):
        pa.unarchive("Y")


def test_unarchive_unknown_raises(isolated):
    from agents import project_archive as pa
    with pytest.raises(FileNotFoundError):
        pa.unarchive("never-existed")


# ── archived_list ──────────────────────────────────────────────


def test_archived_list_iterates(isolated):
    write_proj(isolated, "A")
    write_proj(isolated, "B")
    from agents import project_archive as pa
    pa.archive("A")
    pa.archive("B")
    items = pa.archived_list()
    assert len(items) == 2
    names = {i["project"] for i in items}
    assert names == {"A", "B"}


# ── autosweep candidates ────────────────────────────────────────


def test_candidates_picks_terminal_phases(isolated):
    write_proj(isolated, "Done", "name: Done\nphase: PUBLISHED\n")
    write_proj(isolated, "Live", "name: Live\nphase: SUBMITTED\n")
    # Backdate Done's mtime well past the cutoff.
    p = isolated / "projects" / "Done.yaml"
    old = time.time() - 365 * 24 * 3600
    os.utime(p, (old, old))
    from agents import project_archive as pa
    cands = pa.candidates(idle_months=6, today=dt.date(2026, 5, 3))
    names = [c.project for c in cands]
    assert names == ["Done"]


def test_candidates_skips_recently_touched(isolated):
    write_proj(isolated, "Recent", "name: Recent\nphase: PUBLISHED\n")
    from agents import project_archive as pa
    cands = pa.candidates(idle_months=6, today=dt.date(2026, 5, 3))
    assert cands == []


def test_candidates_ignores_active_phases(isolated):
    write_proj(isolated, "Active", "name: Active\nphase: REVIEW\n")
    p = isolated / "projects" / "Active.yaml"
    old = time.time() - 365 * 24 * 3600
    os.utime(p, (old, old))
    from agents import project_archive as pa
    assert pa.candidates(idle_months=6, today=dt.date(2026, 5, 3)) == []


# ── autosweep apply ────────────────────────────────────────────


def test_autosweep_dry_run_does_not_move(isolated):
    write_proj(isolated, "Old", "name: Old\nphase: PUBLISHED\n")
    p = isolated / "projects" / "Old.yaml"
    old = time.time() - 365 * 24 * 3600
    os.utime(p, (old, old))
    from agents import project_archive as pa
    cands = pa.autosweep(idle_months=6, dry_run=True,
                          today=dt.date(2026, 5, 3))
    assert len(cands) == 1
    # File still in active dir.
    assert p.exists()


def test_autosweep_apply_moves(isolated):
    write_proj(isolated, "Old", "name: Old\nphase: REJECTED\n")
    p = isolated / "projects" / "Old.yaml"
    old = time.time() - 365 * 24 * 3600
    os.utime(p, (old, old))
    from agents import project_archive as pa
    pa.autosweep(idle_months=6, dry_run=False,
                  today=dt.date(2026, 5, 3))
    assert not p.exists()
    items = pa.archived_list()
    assert any(i["project"] == "Old" for i in items)


# ── audit ─────────────────────────────────────────────────────────


def test_audit_records_archive_and_unarchive(isolated):
    write_proj(isolated, "P")
    from agents import project_archive as pa
    pa.archive("P")
    pa.unarchive("P")
    h = pa.history()
    events = [r["event"] for r in h]
    assert events == ["archive", "unarchive"]
