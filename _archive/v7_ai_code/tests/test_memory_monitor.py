"""tests/test_memory_monitor.py — M1 memory hygiene (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import os
import textwrap
import time

import pytest

from agents import memory_monitor as mm


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_MEMORY_DIR", str(tmp_path))
    return tmp_path


def write_memory(setup, name, body):
    p = setup / f"{name}.md"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


# ── frontmatter parsing ──────────────────────────────────────────


def test_parse_frontmatter_basic():
    fm = mm._parse_frontmatter(
        "---\nname: x\ndescription: hi\ntype: feedback\n---\n\nbody")
    assert fm == {"name": "x", "description": "hi", "type": "feedback"}


def test_parse_frontmatter_missing():
    assert mm._parse_frontmatter("just plain body") == {}


def test_parse_frontmatter_unterminated():
    assert mm._parse_frontmatter("---\nname: x\n") == {}


# ── stale detection ──────────────────────────────────────────────


def test_stale_when_mtime_old(isolated):
    p = write_memory(isolated, "old", "---\ntype: feedback\n---\nx\n")
    old = time.time() - 365 * 24 * 3600
    os.utime(p, (old, old))
    rep = mm.scan(stale_months=6, today=dt.date(2026, 5, 3))
    assert any(f.kind == "stale" and "old.md" in f.file
               for f in rep.findings)


def test_fresh_file_not_stale(isolated):
    write_memory(isolated, "fresh", "---\ntype: feedback\n---\nx\n")
    rep = mm.scan(stale_months=6, today=dt.date(2026, 5, 3))
    assert not any(f.kind == "stale" and "fresh.md" in f.file
                   for f in rep.findings)


# ── obsolete deadlines ───────────────────────────────────────────


def test_obsolete_deadline_flagged(isolated):
    write_memory(isolated, "deadline", """
        ---
        name: x
        description: x
        type: project
        ---

        Deadline: 2024-04-25 — submit
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    obs = [f for f in rep.findings if f.kind == "obsolete_deadline"]
    assert len(obs) == 1
    assert "2024-04-25" in obs[0].detail


def test_recent_deadline_not_flagged(isolated):
    write_memory(isolated, "near", """
        ---
        type: project
        ---
        Deadline: 2026-05-01 — almost now
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert not any(f.kind == "obsolete_deadline" and "near.md" in f.file
                   for f in rep.findings)


def test_future_deadline_not_flagged(isolated):
    write_memory(isolated, "future", """
        ---
        type: project
        ---
        Deadline: 2027-01-01
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert not any(f.kind == "obsolete_deadline" and "future.md" in f.file
                   for f in rep.findings)


# ── broken paths ────────────────────────────────────────────────


def test_broken_path_flagged(isolated):
    write_memory(isolated, "ref", """
        ---
        type: reference
        ---
        File at `/tmp/this-path-does-not-exist-xyz789` is gone.
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert any(f.kind == "broken_path" for f in rep.findings)


def test_existing_path_not_flagged(isolated, tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("x")
    write_memory(isolated, "ok", f"""
        ---
        type: reference
        ---
        See `{real}`.
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert not any(f.kind == "broken_path" for f in rep.findings)


# ── duplicate detection ─────────────────────────────────────────


def test_duplicate_descriptions_flagged(isolated):
    write_memory(isolated, "a", """
        ---
        name: a
        description: integration tests must hit a real database not mocks
        type: feedback
        ---
    """)
    write_memory(isolated, "b", """
        ---
        name: b
        description: integration tests must hit real database not mocks
        type: feedback
        ---
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    dups = [f for f in rep.findings if f.kind == "duplicate"]
    assert len(dups) == 1
    assert "a.md" in dups[0].file and "b.md" in dups[0].file


def test_distinct_descriptions_no_duplicates(isolated):
    write_memory(isolated, "a", """
        ---
        name: a
        description: language rule for responses
        type: feedback
        ---
    """)
    write_memory(isolated, "b", """
        ---
        name: b
        description: testing strategy for migrations
        type: feedback
        ---
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert not any(f.kind == "duplicate" for f in rep.findings)


# ── orchestrate ─────────────────────────────────────────────────


def test_scan_skips_index_md(isolated):
    write_memory(isolated, "MEMORY", "# index\n- item")
    write_memory(isolated, "real", "---\ntype: feedback\n---\n")
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert rep.scanned == 1


def test_scan_empty_dir_returns_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_MEMORY_DIR", str(tmp_path / "missing"))
    rep = mm.scan(today=dt.date(2026, 5, 3))
    assert rep.scanned == 0 and rep.findings == []


def test_summary_calm_when_clean(isolated):
    write_memory(isolated, "ok", "---\ntype: feedback\n---\n")
    s = mm.summary()
    # Real-time freshness — no findings expected.
    assert "no issues" in s or "0 findings" in s


def test_summary_lists_findings(isolated):
    write_memory(isolated, "expired", """
        ---
        type: project
        ---
        Deadline: 2023-01-01
    """)
    s = mm.summary()
    assert "obsolete_deadline" in s


# ── jsonl report ────────────────────────────────────────────────


def test_write_jsonl_report(isolated, tmp_path):
    write_memory(isolated, "expired", """
        ---
        type: project
        ---
        Deadline: 2023-01-01
    """)
    rep = mm.scan(today=dt.date(2026, 5, 3))
    out = mm.write_jsonl_report(rep, path=tmp_path / "out.jsonl")
    lines = out.read_text().splitlines()
    assert len(lines) == len(rep.findings)
    import json
    rows = [json.loads(l) for l in lines]
    assert all("kind" in r for r in rows)
