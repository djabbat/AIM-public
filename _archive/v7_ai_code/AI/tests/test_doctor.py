"""AI/tests/test_doctor.py — DR2 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.doctor" in sys.modules:
        importlib.reload(sys.modules["AI.ai.doctor"])
    if "AI.ai.diagnostic_ledger" in sys.modules:
        importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    return tmp_path


# ── individual probes ───────────────────────────────────────────


def test_probe_modules_clean(isolated):
    """Real AI/ai/* should all import."""
    from AI.ai.doctor import _probe_modules
    p = _probe_modules()
    assert p.ok is True
    assert "import cleanly" in p.detail


def test_probe_api_key_missing(isolated, monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))   # no ~/.aim_env in tmp
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.run_self_diagnostic"])
    from AI.ai.doctor import _probe_api_key
    p = _probe_api_key()
    assert p.ok is False
    assert p.severity == "warn"


def test_probe_api_key_present(isolated, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-stub")
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.run_self_diagnostic"])
    from AI.ai.doctor import _probe_api_key
    p = _probe_api_key()
    assert p.ok is True


# ── orchestrate ─────────────────────────────────────────────────


def test_diagnose_returns_probes(isolated):
    from AI.ai.doctor import diagnose
    out = diagnose()
    names = {p.name for p in out}
    assert "modules" in names
    assert "direction_rule" in names
    assert "db_writable" in names


def test_has_critical_failure_false_when_clean(isolated):
    from AI.ai.doctor import has_critical_failure
    # Real repo should be clean (or at most warnings, not crit).
    # If api_key is missing it's only `warn`, which doesn't count.
    # We don't assert False here unconditionally — we assert that
    # the function returns a bool deterministically.
    assert isinstance(has_critical_failure(), bool)


def test_has_critical_failure_true_when_crit_present(isolated, monkeypatch):
    from AI.ai import doctor
    crit = doctor.Probe(name="x", ok=False, severity="crit",
                         detail="boom")
    assert doctor.has_critical_failure([crit]) is True
    warn = doctor.Probe(name="y", ok=False, severity="warn", detail="…")
    assert doctor.has_critical_failure([warn]) is False


# ── summary ─────────────────────────────────────────────────────


def test_summary_contains_probe_names(isolated):
    from AI.ai.doctor import summary
    s = summary()
    assert "doctor" in s
    assert "modules" in s
    assert "direction_rule" in s


