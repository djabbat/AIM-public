"""AI/tests/test_compliance_promoter.py — CP1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.delenv("AI_DIAG_MIN_COMPLIANCE", raising=False)
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.compliance_promoter"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def _seed(n: int, comp_value: float):
    """Plant n rows with the same compliance."""
    from AI.ai.diagnostic_ledger import record
    n_with = max(0, min(10, int(round(comp_value * 10))))
    for i in range(n):
        record(model="ds-r", grade="B", n_refs=10, n_with_line=n_with,
               crit=0, ts=f"2026-05-03T10:00:{i:02d}.{i:06d}")


# ── _current_threshold ──────────────────────────────────────────


def test_default_threshold(isolated):
    from AI.ai.compliance_promoter import _current_threshold
    assert _current_threshold() == 0.5


def test_threshold_env_override(isolated, monkeypatch):
    monkeypatch.setenv("AI_DIAG_MIN_COMPLIANCE", "0.7")
    from AI.ai.compliance_promoter import _current_threshold
    assert _current_threshold() == 0.7


def test_threshold_env_invalid_falls_back(isolated, monkeypatch):
    monkeypatch.setenv("AI_DIAG_MIN_COMPLIANCE", "not-a-number")
    from AI.ai.compliance_promoter import _current_threshold
    assert _current_threshold() == 0.5


# ── recommendation() ────────────────────────────────────────────


def test_no_data_holds(isolated):
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.direction == "hold"
    assert r.proposed_threshold is None
    assert r.n_recent == 0


def test_high_streak_recommends_tighten(isolated):
    _seed(5, 0.95)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.direction == "tighten"
    assert r.streak_high >= 3
    assert r.proposed_threshold > r.current_threshold


def test_low_streak_recommends_loosen(isolated):
    _seed(5, 0.20)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.direction == "loosen"
    assert r.streak_low >= 3
    assert r.proposed_threshold < r.current_threshold


def test_mixed_streak_holds(isolated):
    _seed(2, 0.95)
    _seed(2, 0.55)
    _seed(2, 0.95)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    # streak depends on most-recent direction; either way, < MIN_STREAK
    assert r.direction == "hold"


def test_short_streak_holds(isolated):
    _seed(2, 0.95)   # only 2 — below MIN_STREAK
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.direction == "hold"


def test_proposed_capped_at_high(isolated, monkeypatch):
    monkeypatch.setenv("AI_DIAG_MIN_COMPLIANCE", "0.78")
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.compliance_promoter"])
    _seed(5, 0.95)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    if r.direction == "tighten":
        assert r.proposed_threshold <= 0.8


def test_already_at_max_holds(isolated, monkeypatch):
    monkeypatch.setenv("AI_DIAG_MIN_COMPLIANCE", "0.85")
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.compliance_promoter"])
    _seed(5, 0.95)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.direction == "hold"


def test_already_at_min_holds_on_low_streak(isolated, monkeypatch):
    monkeypatch.setenv("AI_DIAG_MIN_COMPLIANCE", "0.25")
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.compliance_promoter"])
    _seed(5, 0.10)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.direction == "hold"


def test_avg_recent_computed(isolated):
    _seed(4, 0.50)
    from AI.ai.compliance_promoter import recommendation
    r = recommendation()
    assert r.avg_recent == pytest.approx(0.5, abs=0.05)
    assert r.n_recent == 4


# ── summary ─────────────────────────────────────────────────────


def test_summary_no_data(isolated):
    from AI.ai.compliance_promoter import summary
    s = summary()
    assert "hold" in s


def test_summary_tighten(isolated):
    _seed(5, 0.95)
    from AI.ai.compliance_promoter import summary
    s = summary()
    assert "tighten" in s
    assert "↑" in s


def test_summary_loosen(isolated):
    _seed(5, 0.20)
    from AI.ai.compliance_promoter import summary
    s = summary()
    assert "loosen" in s
    assert "↓" in s
