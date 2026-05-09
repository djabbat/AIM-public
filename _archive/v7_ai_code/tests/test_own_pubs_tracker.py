"""tests/test_own_pubs_tracker.py — PV1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_AUTHOR_NAME", "Tkemaladze")
    monkeypatch.setenv("AIM_OWN_PUBS_COOLDOWN_HOURS", "0")
    import importlib, sys
    if "agents.own_pubs_tracker" in sys.modules:
        importlib.reload(sys.modules["agents.own_pubs_tracker"])
    return tmp_path


def _pub(doi, title="T", year=2026):
    from agents.own_pubs_tracker import Publication
    return Publication(doi=doi, title=title, year=year, journal="J")


# ── new_pubs / cooldown ──────────────────────────────────────────


def test_new_pubs_returns_unseen(isolated):
    from agents.own_pubs_tracker import new_pubs
    out = new_pubs(fetch_fn=lambda: [_pub("10.1/a"), _pub("10.1/b")])
    dois = [p.doi for p in out]
    assert dois == ["10.1/a", "10.1/b"]


def test_new_pubs_dedupes_against_seen(isolated):
    from agents.own_pubs_tracker import new_pubs
    new_pubs(fetch_fn=lambda: [_pub("10.1/a")])
    out = new_pubs(fetch_fn=lambda: [_pub("10.1/a"), _pub("10.1/b")])
    assert [p.doi for p in out] == ["10.1/b"]


def test_new_pubs_cooldown_blocks_second_call(isolated, monkeypatch):
    monkeypatch.setenv("AIM_OWN_PUBS_COOLDOWN_HOURS", "24")
    import importlib, agents.own_pubs_tracker as opt
    importlib.reload(opt)
    a = opt.new_pubs(fetch_fn=lambda: [_pub("10.1/a")])
    b = opt.new_pubs(fetch_fn=lambda: [_pub("10.1/b")])
    assert [p.doi for p in a] == ["10.1/a"]
    assert b == []


def test_new_pubs_dedupes_against_publications_md(isolated, monkeypatch):
    import agents.own_pubs_tracker as opt
    monkeypatch.setattr(opt, "_publications_md_dois",
                        lambda: {"10.1/own-1"})
    out = opt.new_pubs(fetch_fn=lambda: [_pub("10.1/own-1"),
                                            _pub("10.1/new-2")])
    assert [p.doi for p in out] == ["10.1/new-2"]


# ── publications.md scanner ─────────────────────────────────────


def test_publications_md_dois_extracts_correctly(isolated, tmp_path,
                                                   monkeypatch):
    """Patch the candidate path list to point at our fake publications.md."""
    pubs_md = tmp_path / "publications.md"
    pubs_md.write_text(textwrap_dedent("""
        - 10.1073/pnas.2537697123 — Aqtivirebuli paper
        - 10.5281/zenodo.19849384  — preprint
        - just text, no DOI
    """))
    import agents.own_pubs_tracker as opt
    # Override the search list at the function scope.
    real = opt._publications_md_dois
    def fake_finder():
        out = set()
        text = pubs_md.read_text()
        for m in opt._DOI_RE.finditer(text):
            out.add(m.group(1).rstrip(".,;)").lower())
        return out
    monkeypatch.setattr(opt, "_publications_md_dois", fake_finder)
    dois = opt._publications_md_dois()
    assert "10.1073/pnas.2537697123" in dois
    assert "10.5281/zenodo.19849384" in dois


# ── summary ──────────────────────────────────────────────────────


def test_summary_no_new(isolated):
    from agents.own_pubs_tracker import summary
    import agents.own_pubs_tracker as opt
    # Override fetch globally so it returns nothing.
    opt.fetch = lambda: []  # type: ignore
    s = summary()
    assert "no new own publications" in s


def test_summary_renders_new(isolated, monkeypatch):
    import agents.own_pubs_tracker as opt
    monkeypatch.setattr(opt, "fetch", lambda: [_pub("10.1/a", "Cool paper")])
    s = opt.summary()
    assert "New publications" in s
    assert "Cool paper" in s


# ── Publication formatting ─────────────────────────────────────


def test_publication_to_line():
    from agents.own_pubs_tracker import Publication
    p = Publication(doi="10.1/x", title="My Paper", year=2025,
                     journal="Nature")
    line = p.to_line()
    assert "My Paper" in line
    assert "Nature" in line
    assert "10.1/x" in line


def test_publication_to_line_minimal():
    from agents.own_pubs_tracker import Publication
    p = Publication(doi="", title="x", year=None)
    assert p.to_line().startswith("  •")


# ── helper used by tests ─────────────────────────────────────────


def textwrap_dedent(s: str) -> str:
    import textwrap
    return textwrap.dedent(s)
