"""AI/tests/test_gap_detector.py — S11 (2026-05-03)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path))
    return tmp_path


def write_session(setup, name, events):
    p = setup / f"{name}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


# ── _is_surrender ────────────────────────────────────────────────


# ── surrenders() ─────────────────────────────────────────────────


def test_surrenders_picks_up_giveup_finals(sessions):
    write_session(sessions, "s1", [
        {"type": "start", "task": "send email to Geiger via SMTP",
         "ts": "2026-05-03T10:00:00"},
        {"type": "final",
         "answer": "I don't have access to email tools.",
         "ts": "2026-05-03T10:00:01"},
    ])
    from AI.ai.gap_detector import surrenders
    out = surrenders(window_days=999)
    assert len(out) == 1
    assert "Geiger" in out[0].task


def test_surrenders_skips_successful(sessions):
    write_session(sessions, "ok", [
        {"type": "start", "task": "say hi"},
        {"type": "final", "answer": "Hi!"},
    ])
    from AI.ai.gap_detector import surrenders
    assert surrenders(window_days=999) == []


def test_surrenders_window_filter(sessions):
    import datetime as dt
    old = (dt.datetime.now() - dt.timedelta(days=60)).isoformat()
    write_session(sessions, "old", [
        {"type": "start", "task": "task X", "ts": old},
        {"type": "final", "answer": "I cannot help.", "ts": old},
    ])
    from AI.ai.gap_detector import surrenders
    assert surrenders(window_days=7) == []


def test_surrenders_no_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "missing"))
    import importlib, AI.ai.gap_detector as gd
    importlib.reload(gd)
    assert gd.surrenders() == []


def test_surrenders_handles_malformed(sessions):
    p = sessions / "bad.jsonl"
    p.write_text('{"type":"start","task":"X"}\nnot-json\n'
                  '{"type":"final","answer":"I cannot help"}\n')
    from AI.ai.gap_detector import surrenders
    out = surrenders(window_days=999)
    assert len(out) == 1


# ── gaps() clustering ────────────────────────────────────────────


def test_gaps_clusters_similar_surrenders(sessions):
    for i in range(4):
        write_session(sessions, f"s{i}", [
            {"type": "start", "task": "verify PMID against PubMed API",
             "ts": "2026-05-03T10:00:00"},
            {"type": "final",
             "answer": "I cannot access PubMed external API",
             "ts": "2026-05-03T10:00:01"},
        ])
    from AI.ai.gap_detector import gaps
    out = gaps(window_days=999, threshold=0.20)
    assert len(out) == 1
    assert out[0].n == 4
    assert any(t in ("pubmed", "verify", "pmid") for t in out[0].theme)


def test_gaps_separates_distinct_themes(sessions):
    write_session(sessions, "a", [
        {"type": "start", "task": "verify PubMed citations",
         "ts": "2026-05-03T10:00:00"},
        {"type": "final", "answer": "I cannot access PubMed",
         "ts": "2026-05-03T10:00:01"},
    ])
    write_session(sessions, "b", [
        {"type": "start", "task": "translate Georgian medical paper",
         "ts": "2026-05-03T10:01:00"},
        {"type": "final", "answer": "I cannot translate Georgian",
         "ts": "2026-05-03T10:01:01"},
    ])
    from AI.ai.gap_detector import gaps
    out = gaps(window_days=999, threshold=0.4)
    assert len(out) == 2


def test_gaps_empty_when_no_surrenders(sessions):
    write_session(sessions, "ok", [
        {"type": "start", "task": "x"},
        {"type": "final", "answer": "Done!"},
    ])
    from AI.ai.gap_detector import gaps
    assert gaps() == []


# ── suggestion heuristics ────────────────────────────────────────


# ── summary ──────────────────────────────────────────────────────


def test_summary_calm_when_clean(sessions):
    from AI.ai.gap_detector import summary
    assert "no capability gaps" in summary()


def test_summary_renders(sessions):
    write_session(sessions, "s", [
        {"type": "start", "task": "verify PubMed citation",
         "ts": "2026-05-03T10:00:00"},
        {"type": "final", "answer": "I cannot access PubMed",
         "ts": "2026-05-03T10:00:01"},
    ])
    from AI.ai.gap_detector import summary
    s = summary(window_days=999)
    assert "Capability gaps" in s
    assert "1 surrenders" in s or "PubMed" in s.lower() or "pubmed" in s.lower()


# ── CRIT-3 fix: generator-safe input ────────────────────────────


def _surr(task, answer):
    from AI.ai.gap_detector import Surrender
    return Surrender(session="s1", task=task, answer=answer, ts=None)


def test_gaps_accepts_pre_computed_list(sessions):
    """`surrender_list=` parameter lets caller skip the JSONL walk."""
    from AI.ai.gap_detector import gaps
    items = [
        _surr("verify PubMed citation", "I cannot access PubMed"),
        _surr("verify another PubMed source", "I cannot reach PubMed API"),
    ]
    out = gaps(surrender_list=items, threshold=0.2)
    assert len(out) == 1
    assert out[0].n == 2


def test_gaps_consumes_generator_safely(sessions):
    """Generator input must be materialised — no StopIteration after
    the first iteration. CRIT-3 regression guard."""
    from AI.ai.gap_detector import gaps
    def gen():
        yield _surr("verify PubMed", "I cannot access PubMed")
        yield _surr("verify PubMed paper", "I cannot reach PubMed")
    out = gaps(surrender_list=gen(), threshold=0.2)
    assert len(out) == 1
    assert out[0].n == 2


def test_gaps_empty_pre_computed_list(sessions):
    from AI.ai.gap_detector import gaps
    assert gaps(surrender_list=[]) == []
