"""AI/tests/test_finding_suppressions.py — FS1 (2026-05-04)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.finding_suppressions" in sys.modules:
        importlib.reload(sys.modules["AI.ai.finding_suppressions"])
    return tmp_path


# ── suppress / unsuppress / is_suppressed ───────────────────────


def test_suppress_persists(isolated):
    from AI.ai.finding_suppressions import suppress, is_suppressed
    s = suppress("agents/x.py:42", reason="known TODO")
    assert s.ref == "agents/x.py:42"
    assert s.reason == "known TODO"
    assert s.until_ts is None
    assert is_suppressed("agents/x.py:42")


def test_suppress_strips_whitespace(isolated):
    from AI.ai.finding_suppressions import suppress, is_suppressed
    suppress("  agents/x.py:1  ")
    assert is_suppressed("agents/x.py:1")


def test_suppress_rejects_empty(isolated):
    from AI.ai.finding_suppressions import suppress
    with pytest.raises(ValueError):
        suppress("")
    with pytest.raises(ValueError):
        suppress("   ")


def test_unsuppress_removes(isolated):
    from AI.ai.finding_suppressions import (
        suppress, unsuppress, is_suppressed,
    )
    suppress("agents/x.py:1")
    assert unsuppress("agents/x.py:1") is True
    assert not is_suppressed("agents/x.py:1")


def test_unsuppress_unknown_returns_false(isolated):
    from AI.ai.finding_suppressions import unsuppress
    assert unsuppress("never-existed") is False


# ── expiry / active() ───────────────────────────────────────────


def test_expired_suppression_is_inactive(isolated):
    from AI.ai.finding_suppressions import (
        suppress, is_suppressed, active,
    )
    past = dt.datetime.now() - dt.timedelta(hours=1)
    suppress("agents/x.py:1", until=past)
    assert not is_suppressed("agents/x.py:1")
    assert active() == []


def test_active_excludes_expired(isolated):
    from AI.ai.finding_suppressions import suppress, active
    past = dt.datetime.now() - dt.timedelta(days=1)
    future = dt.datetime.now() + dt.timedelta(days=1)
    suppress("expired/x.py:1", until=past)
    suppress("future/y.py:2", until=future)
    suppress("forever/z.py:3")
    refs = {s.ref for s in active()}
    assert refs == {"future/y.py:2", "forever/z.py:3"}


# ── filter_findings ─────────────────────────────────────────────


def test_filter_findings_drops_suppressed(isolated):
    from AI.ai.finding_suppressions import suppress, filter_findings
    suppress("agents/x.py:1")
    out = filter_findings(["agents/x.py:1", "agents/y.py:2",
                            "agents/x.py:1"])  # dup
    assert "agents/x.py:1" not in out
    assert out.count("agents/y.py:2") == 1


def test_filter_findings_passes_through_when_empty_db(isolated):
    from AI.ai.finding_suppressions import filter_findings
    refs = ["agents/x.py:1", "agents/y.py:2"]
    assert filter_findings(refs) == refs


def test_filter_findings_keeps_expired_suppression_refs(isolated):
    """Expired suppression doesn't filter — finding becomes alertable."""
    from AI.ai.finding_suppressions import suppress, filter_findings
    past = dt.datetime.now() - dt.timedelta(hours=1)
    suppress("agents/x.py:1", until=past)
    assert filter_findings(["agents/x.py:1"]) == ["agents/x.py:1"]


# ── summary ─────────────────────────────────────────────────────


def test_summary_empty(isolated):
    from AI.ai.finding_suppressions import summary
    assert "no finding suppressions" in summary()


def test_summary_lists_active(isolated):
    from AI.ai.finding_suppressions import suppress, summary
    suppress("agents/x.py:1", reason="known TODO")
    s = summary()
    assert "active" in s
    assert "agents/x.py:1" in s
    assert "known TODO" in s


# ── regression_detector integration ─────────────────────────────


# ── prune_expired ───────────────────────────────────────────────


def test_prune_expired_no_op_when_none_expired(isolated):
    from AI.ai.finding_suppressions import suppress, prune_expired
    suppress("agents/x.py:1")
    suppress("agents/y.py:2",
              until=dt.datetime.now() + dt.timedelta(days=7))
    assert prune_expired() == 0


def test_prune_expired_handles_empty(isolated):
    from AI.ai.finding_suppressions import prune_expired
    assert prune_expired() == 0


# ── regression_detector integration ─────────────────────────────


def test_regression_detect_filters_suppressed_new_findings(
    isolated, tmp_path,
):
    """A finding suppressed at time of detect() must NOT show up as
    a new regression even if it's truly new in the latest report."""
    from AI.ai.finding_suppressions import suppress
    from AI.ai.diagnostic_ledger import record
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    p2 = tmp_path / "r2.md"
    p2.write_text("`agents/x.py:1` and `agents/known.py:99`")
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=2, n_with_line=2, crit=0,
           report_path=str(p2), ts="2026-05-04T10:00:00")
    suppress("agents/known.py:99", reason="documented limitation")
    from AI.ai.regression_detector import detect
    r = detect()
    assert "agents/known.py:99" not in r.new_findings
    assert r.regressed is False  # was the only new finding
