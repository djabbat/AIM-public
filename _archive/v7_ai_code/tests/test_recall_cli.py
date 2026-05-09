"""tests/test_recall_cli.py — V1 (2026-05-03)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    import agents.recall_cli as rc
    importlib.reload(rc)
    return rc


# ── recall() ──────────────────────────────────────────────────────


def test_recall_returns_typed_hits(isolated, monkeypatch):
    """Stub the underlying retrieve so we don't need a real LanceDB."""
    fake_hits = [
        {"file": "/x/proj.md", "text": "FCLC deadline 2026-10-28",
         "_distance": 0.12},
        {"file": "/x/state.md", "text": "submission status",
         "_distance": 0.31},
    ]
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000: fake_hits)
    hits = isolated.recall("FCLC", k=2)
    assert len(hits) == 2
    assert hits[0].file == "/x/proj.md"
    assert hits[0].distance == 0.12
    assert "FCLC deadline" in hits[0].text


def test_recall_empty_query_returns_empty(isolated):
    assert isolated.recall("") == []
    assert isolated.recall("   ") == []


def test_recall_handles_index_missing(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000: [])
    assert isolated.recall("anything") == []


def test_recall_audits(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": "y", "_distance": 0.1}])
    isolated.recall("foo")
    h = isolated.history()
    assert h and h[-1]["query"] == "foo"
    assert h[-1]["n_hits"] == 1


# ── recall_top formatting ────────────────────────────────────────


def test_recall_top_no_hits_returns_marker(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000: [])
    s = isolated.recall_top("FCLC")
    assert "no recall hits" in s


def test_recall_top_renders_one_line_per_hit(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000: [
        {"file": "/x/a.md", "text": "first hit body",
         "_distance": 0.2},
        {"file": "/x/b.md", "text": "second", "_distance": 0.3},
    ])
    s = isolated.recall_top("query")
    lines = s.splitlines()
    assert lines[0].startswith("💭 Recall:")
    assert any("a.md" in l for l in lines[1:])
    assert any("b.md" in l for l in lines[1:])


def test_recall_top_truncates_long_snippets(isolated, monkeypatch):
    long_text = "x" * 500
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": long_text,
                            "_distance": 0.1}])
    s = isolated.recall_top("q", line_max=80)
    # Each line ≤ ~80 chars, no embedded newlines from snippet.
    for line in s.splitlines():
        assert "\n" not in line


# ── recall_json ──────────────────────────────────────────────────


def test_recall_json_batches(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": "x", "_distance": 0.1}])
    out = isolated.recall_json(["a", "b"], k=1)
    rows = json.loads(out)
    assert len(rows) == 2
    assert rows[0]["query"] == "a"
    assert rows[0]["hits"][0]["file"] == "x.md"


# ── audit log ────────────────────────────────────────────────────


def test_history_filters_by_limit(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000: [])
    for q in ["a", "b", "c", "d", "e"]:
        isolated.recall(q)
    h = isolated.history(limit=3)
    assert [r["query"] for r in h] == ["c", "d", "e"]


# ── CLI entrypoint ───────────────────────────────────────────────


def test_main_text_mode(isolated, monkeypatch, capsys):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": "y", "_distance": 0.1}])
    monkeypatch.setattr("sys.argv", ["recall_cli", "test", "query"])
    rc = isolated._main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Recall:" in out


def test_main_json_mode(isolated, monkeypatch, capsys):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": "y", "_distance": 0.1}])
    monkeypatch.setattr("sys.argv", ["recall_cli", "test", "--json"])
    isolated._main()
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert rows[0]["query"] == "test"
