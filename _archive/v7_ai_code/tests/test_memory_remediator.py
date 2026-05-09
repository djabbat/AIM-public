"""tests/test_memory_remediator.py — RM1 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_DESKTOP_ROOTS", str(tmp_path / "Desktop"))
    monkeypatch.setenv("AIM_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "memory").mkdir()
    import importlib, sys
    for m in ["agents.memory_monitor", "agents.memory_remediator"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_memory(setup, name, body):
    p = setup / "memory" / f"{name}.md"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


# ── helpers ──────────────────────────────────────────────────────


def test_basename(isolated):
    from agents.memory_remediator import _basename
    assert _basename("/foo/bar/baz.md") == "baz.md"


def test_path_components_skips_short(isolated):
    from agents.memory_remediator import _path_components
    out = _path_components("/foo/x/long-name/baz.md")
    assert "long-name" in out
    assert "x" not in out


def test_confidence_levels(isolated):
    from agents.memory_remediator import _confidence
    assert _confidence(1, "anything") == "high"
    assert _confidence(0, "x") == "low"
    assert _confidence(2, "longerName") == "medium"
    assert _confidence(10, "x") == "low"


# ── candidate search ────────────────────────────────────────────


def test_find_candidates_unique_basename(isolated, tmp_path):
    desktop = tmp_path / "Desktop"
    new = desktop / "PhD" / "E0"
    new.mkdir(parents=True)
    target = new / "tsomaia_critique_2026-04-27.md"
    target.write_text("body")
    from agents.memory_remediator import _find_candidates
    out = _find_candidates(
        "~/Desktop/FCLC/docs/tsomaia_critique_2026-04-27.md",
        [desktop])
    assert len(out) == 1
    assert str(target) in out[0]


def test_find_candidates_multiple_with_components(isolated, tmp_path):
    desktop = tmp_path / "Desktop"
    (desktop / "PhD").mkdir(parents=True)
    a = desktop / "PhD" / "needle.md"
    a.write_text("x")
    (desktop / "Other").mkdir()
    b = desktop / "Other" / "needle.md"
    b.write_text("y")
    from agents.memory_remediator import _find_candidates
    out = _find_candidates(
        "~/Desktop/FCLC/PhD/needle.md", [desktop])
    # Both candidates returned, but the one with PhD/ in path scores higher.
    assert len(out) == 2
    assert "PhD/needle.md" in out[0]


def test_find_candidates_no_match(isolated, tmp_path):
    from agents.memory_remediator import _find_candidates
    out = _find_candidates("/does/not/exist.md", [tmp_path / "Desktop"])
    assert out == []


# ── suggestions() ────────────────────────────────────────────────


def test_suggestions_high_confidence_when_unique(isolated, tmp_path):
    write_memory(isolated, "ref", """
        ---
        type: reference
        ---
        See `/some/old/path/unique-doc-xyz.md` for details.
    """)
    desktop = tmp_path / "Desktop"
    target = desktop / "PhD" / "unique-doc-xyz.md"
    target.parent.mkdir(parents=True)
    target.write_text("found me")
    from agents.memory_remediator import suggestions
    s = suggestions()
    assert len(s) == 1
    assert s[0].confidence == "high"
    assert "unique-doc-xyz.md" in s[0].best


def test_suggestions_low_confidence_when_no_match(isolated):
    write_memory(isolated, "ref", """
        ---
        type: reference
        ---
        See `/totally/missing/file.md`
    """)
    from agents.memory_remediator import suggestions
    s = suggestions()
    assert len(s) == 1
    assert s[0].confidence == "low"
    assert s[0].candidates == []


def test_suggestions_dedupe_within_file(isolated, tmp_path):
    write_memory(isolated, "ref", """
        ---
        type: reference
        ---
        Path1: `/a/b/cool.md`
        Same again: `/a/b/cool.md`
    """)
    from agents.memory_remediator import suggestions
    s = suggestions()
    # Even though the path appears twice in the body, the dedup keeps
    # only one Suggestion entry per (file, path).
    assert len(s) == 1


def test_suggestions_skips_non_broken_path_findings(isolated, tmp_path):
    """Stale/obsolete-deadline findings are NOT in our remit."""
    p = isolated / "memory" / "stale.md"
    p.write_text(
        "---\ntype: project\n---\n"
        "Deadline: 2024-01-01 — submit\n", encoding="utf-8")
    import os
    old = 1700_000_000
    os.utime(p, (old, old))
    from agents.memory_remediator import suggestions
    s = suggestions()
    # Only obsolete_deadline is reported — no broken_path → no remediator entries.
    assert s == []


# ── summary ──────────────────────────────────────────────────────


def test_summary_calm_when_clean(isolated):
    from agents.memory_remediator import summary
    assert "no broken-path" in summary()


def test_summary_lists_high_confidence(isolated, tmp_path):
    write_memory(isolated, "ref", """
        ---
        type: reference
        ---
        See `/old/path/HOTFILE.md`
    """)
    target = tmp_path / "Desktop" / "PhD" / "HOTFILE.md"
    target.parent.mkdir(parents=True)
    target.write_text("here")
    from agents.memory_remediator import summary
    s = summary()
    assert "Memory remediator" in s
    assert "HOTFILE.md" in s
    assert "high:" in s


def test_summary_handles_low_confidence(isolated):
    write_memory(isolated, "ref", """
        ---
        type: reference
        ---
        See `/missing.md`
    """)
    from agents.memory_remediator import summary
    s = summary()
    assert "low:" in s


# ── env override ────────────────────────────────────────────────


def test_desktop_roots_env_split(isolated, tmp_path, monkeypatch):
    a = tmp_path / "rootA"
    b = tmp_path / "rootB"
    a.mkdir(); b.mkdir()
    monkeypatch.setenv("AIM_DESKTOP_ROOTS", f"{a}:{b}")
    import importlib, agents.memory_remediator as mr
    importlib.reload(mr)
    roots = mr._desktop_roots()
    assert a in roots and b in roots
