"""tests/test_literature_watch.py — L2 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import json
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_LITERATURE_PREFS", str(tmp_path / "lit.yaml"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib, sys
    if "agents.literature_watch" in sys.modules:
        importlib.reload(sys.modules["agents.literature_watch"])
    return tmp_path


def write_prefs(setup, body):
    (setup / "lit.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# ── prefs ────────────────────────────────────────────────────────


def test_queries_when_no_file(isolated):
    from agents.literature_watch import queries
    assert queries() == []


def test_queries_parses_yaml(isolated):
    write_prefs(isolated, """
        queries:
          - name: q1
            term: 'centriole'
            max_results: 5
          - name: q2
            term: 'longevity'
    """)
    from agents.literature_watch import queries
    qs = queries()
    assert [q.name for q in qs] == ["q1", "q2"]
    assert qs[0].max_results == 5
    assert qs[1].max_results == 10   # default


def test_queries_skips_blank_term(isolated):
    write_prefs(isolated, """
        queries:
          - name: bad
            term: ''
          - name: good
            term: 'aging'
    """)
    from agents.literature_watch import queries
    assert [q.name for q in queries()] == ["good"]


def test_queries_invalid_yaml(isolated):
    write_prefs(isolated, "not: valid [[")
    from agents.literature_watch import queries
    assert queries() == []


# ── new_for / dedup ──────────────────────────────────────────────


def _papers(*pmids):
    from agents.literature_watch import Paper
    return [Paper(pmid=str(p), title=f"Paper {p}", year=2026,
                  journal="J", first_author="A")
            for p in pmids]


def test_new_for_returns_unseen(isolated):
    from agents.literature_watch import Query, new_for
    q = Query(name="t", term="x")
    out = new_for(q, fetch_fn=lambda _q: _papers("111", "222"))
    pmids = [p.pmid for p in out]
    assert pmids == ["111", "222"]


def test_new_for_dedupes_against_seen(isolated):
    from agents.literature_watch import Query, new_for
    q = Query(name="t", term="x")
    new_for(q, fetch_fn=lambda _q: _papers("111", "222"))
    # 2nd call: pretend cooldown already passed by zeroing last_fetched.
    from agents.literature_watch import _load_seen, _save_seen
    state = _load_seen()
    state["t"]["last_fetched"] = 0
    _save_seen(state)
    out = new_for(q, fetch_fn=lambda _q: _papers("111", "222", "333"))
    assert [p.pmid for p in out] == ["333"]


def test_new_for_respects_cooldown(isolated):
    write_prefs(isolated, "cooldown_hours: 24\n")
    from agents.literature_watch import Query, new_for
    import importlib, agents.literature_watch as lw
    importlib.reload(lw)
    q = Query(name="t", term="x")
    a = lw.new_for(q, fetch_fn=lambda _q: _papers("111"))
    b = lw.new_for(q, fetch_fn=lambda _q: _papers("999"))
    assert [p.pmid for p in a] == ["111"]
    assert b == []   # cooldown blocked


def test_new_for_skips_own_pmids(isolated, monkeypatch):
    """If the user authored a paper, don't surface it as 'new'."""
    import agents.literature_watch as lw
    monkeypatch.setattr(lw, "_own_pmids", lambda: {"222"})
    q = lw.Query(name="t", term="x")
    out = lw.new_for(q, fetch_fn=lambda _q: _papers("111", "222"))
    assert [p.pmid for p in out] == ["111"]


def test_new_for_empty_when_fetch_returns_nothing(isolated):
    from agents.literature_watch import Query, new_for
    out = new_for(Query(name="t", term="x"), fetch_fn=lambda _q: [])
    assert out == []


# ── summary ──────────────────────────────────────────────────────


def test_summary_no_queries(isolated):
    from agents.literature_watch import summary
    assert "no literature queries" in summary()


def test_summary_renders_new_papers(isolated, monkeypatch):
    write_prefs(isolated, """
        queries:
          - name: centriole
            term: centriole
    """)
    import importlib, agents.literature_watch as lw
    importlib.reload(lw)
    monkeypatch.setattr(lw, "fetch", lambda q: _papers("111"))
    s = lw.summary()
    assert "centriole" in s
    assert "Paper 111" in s


def test_summary_calm_when_no_new(isolated, monkeypatch):
    write_prefs(isolated, """
        queries:
          - name: t
            term: x
    """)
    import importlib, agents.literature_watch as lw
    importlib.reload(lw)
    monkeypatch.setattr(lw, "fetch", lambda q: [])
    s = lw.summary()
    assert "no new papers" in s


# ── Paper formatting ─────────────────────────────────────────────


def test_paper_to_line_format():
    from agents.literature_watch import Paper
    p = Paper(pmid="123", title="Important paper", year=2025,
              journal="Nature", first_author="Smith")
    line = p.to_line()
    assert "Important paper" in line
    assert "123" in line
    assert "Smith et al." in line
    assert "Nature" in line


def test_paper_to_line_minimal():
    from agents.literature_watch import Paper
    p = Paper(pmid="9", title="x", year=None)
    assert p.to_line().startswith("  •")
    assert "9" in p.to_line()
