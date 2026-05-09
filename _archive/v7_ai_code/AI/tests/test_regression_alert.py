"""AI/tests/test_regression_alert.py — RA1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in (
        "AI.ai.diagnostic_ledger",
        "AI.ai.regression_detector",
        "AI.ai.regression_alert",
    ):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def _seed_regression(tmp_path):
    """Plant a 2-row ledger that constitutes a regression."""
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    p2 = tmp_path / "r2.md"
    p2.write_text("`agents/x.py:1` and `agents/new.py:42`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="C", n_refs=2, n_with_line=2, crit=1,
           report_path=str(p2), ts="2026-05-04T10:00:00")


# ── no-baseline / no-regression cases ───────────────────────────


def test_no_baseline_returns_none(isolated):
    from AI.ai.regression_alert import check_and_alert
    assert check_and_alert() is None


def test_no_regression_returns_none(isolated, tmp_path):
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(p1), ts="2026-05-04T10:00:00")
    from AI.ai.regression_alert import check_and_alert
    assert check_and_alert() is None


# ── dry-run path ────────────────────────────────────────────────


def test_dry_run_builds_alert_without_side_effects(isolated, tmp_path):
    _seed_regression(tmp_path)
    from AI.ai.regression_alert import check_and_alert
    a = check_and_alert(dry_run=True)
    assert a is not None
    assert a.fired is False
    assert "regression" in a.title.lower()
    assert "agents/new.py:42" in a.body
    assert a.channels == []


def test_dry_run_includes_grade_delta(isolated, tmp_path):
    _seed_regression(tmp_path)
    from AI.ai.regression_alert import check_and_alert
    a = check_and_alert(dry_run=True)
    assert "B" in a.body and "C" in a.body
    assert "crit:" in a.body


# ── real notify path (stub) ─────────────────────────────────────


def test_check_and_alert_calls_notify(isolated, tmp_path, monkeypatch):
    _seed_regression(tmp_path)
    captured: dict = {}

    class FakeResult:
        delivered_via = "telegram"

    def fake_notify(message, **kwargs):
        captured["message"] = message
        captured["kwargs"] = kwargs
        return FakeResult()

    import sys, agents as _agents_pkg
    fake_mod = type(sys)("agents.notify")
    fake_mod.notify = fake_notify
    monkeypatch.setitem(sys.modules, "agents.notify", fake_mod)
    monkeypatch.setattr(_agents_pkg, "notify", fake_mod, raising=False)

    from AI.ai.regression_alert import check_and_alert
    a = check_and_alert()
    assert a is not None
    assert a.fired is True
    assert a.channels == ["telegram"]
    assert "regression" in captured["message"].lower()
    assert captured["kwargs"]["level"] == "high"
    assert captured["kwargs"]["source"] == "ai.regression_alert"
    # Dedup key locks to the curr-run date so we don't double-fire today.
    assert captured["kwargs"]["dedup_key"].startswith("regression:")


def test_alert_swallows_notify_exception(isolated, tmp_path, monkeypatch):
    """Notify import/call failure → fired=False, but still returns
    Alert with title+body so caller can fall back."""
    _seed_regression(tmp_path)

    def boom(message, **kwargs):
        raise RuntimeError("telegram down")

    import sys, agents as _agents_pkg
    fake_mod = type(sys)("agents.notify")
    fake_mod.notify = boom
    monkeypatch.setitem(sys.modules, "agents.notify", fake_mod)
    monkeypatch.setattr(_agents_pkg, "notify", fake_mod, raising=False)

    from AI.ai.regression_alert import check_and_alert
    a = check_and_alert()
    assert a is not None
    assert a.fired is False
    assert a.channels == []
    assert a.body  # still composed
