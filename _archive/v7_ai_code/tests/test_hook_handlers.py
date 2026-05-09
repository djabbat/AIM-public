"""Unit tests for agents/hook_handlers.py — registration glue (HW1)."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import hooks


@pytest.fixture(autouse=True)
def _clean_hooks(tmp_path, monkeypatch):
    """Reset hook registry + AIM_HOME for isolated escalation_engine."""
    hooks.clear()
    # Изолируем escalation.jsonl + notify.jsonl в tmp:
    monkeypatch.setenv("AIM_HOME", str(tmp_path))
    yield
    hooks.clear()


def _reload_handlers():
    """Re-import hook_handlers, reset registration flag, register all."""
    from agents import hook_handlers as hh
    hh.reset_for_tests()
    hh.register_all()
    return hh


# ── basic registration ──────────────────────────────────────────────


def test_register_all_idempotent():
    hh = _reload_handlers()
    listing = hooks.list_handlers()
    assert any("alert_lab_critical" in n
               for n in listing[hooks.HOOK_LAB_CRITICAL])
    assert any("archive_on_session_end" in n
               for n in listing[hooks.HOOK_SESSION_END])
    # Re-call doesn't dupe
    hh.register_all()
    n_before = len(listing[hooks.HOOK_LAB_CRITICAL])
    listing2 = hooks.list_handlers()
    assert len(listing2[hooks.HOOK_LAB_CRITICAL]) == n_before


def test_no_handler_for_kernel_decision():
    """Q6.A — plumbing only, no handler in Day 1."""
    _reload_handlers()
    listing = hooks.list_handlers(hooks.HOOK_KERNEL_DECISION)
    assert listing[hooks.HOOK_KERNEL_DECISION] == []


def test_no_handler_for_intake_pdf():
    """Q8.A — plumbing only, Phase D will add handler."""
    _reload_handlers()
    listing = hooks.list_handlers(hooks.HOOK_INTAKE_PDF)
    assert listing[hooks.HOOK_INTAKE_PDF] == []


# ── HOOK_LAB_CRITICAL ───────────────────────────────────────────────


def test_lab_critical_calls_notify():
    """Handler routes payload to notify.notify with telegram+log channels."""
    _reload_handlers()
    captured = []

    def fake_notify(message, **kwargs):
        captured.append({"message": message, "kwargs": kwargs})
        # Mimic NotifyResult shape
        from agents.notify import NotifyResult
        return NotifyResult(delivered_via="telegram", attempted=["telegram"],
                            failures={})

    with patch("agents.notify.notify", side_effect=fake_notify):
        hooks.fire(hooks.HOOK_LAB_CRITICAL, {
            "patient_id": "TEST_Patient_1970_01_01",
            "red_flags": ["K+ > 6.5 mmol/L — риск аритмии"],
            "lang": "ru",
        })

    assert len(captured) == 1
    call = captured[0]
    assert "K+ > 6.5" in call["message"]
    assert call["kwargs"]["subject"].startswith("⚠️ LAB CRITICAL")
    assert call["kwargs"]["channels"] == ("telegram", "log")
    assert call["kwargs"]["level"] == "critical"
    assert call["kwargs"]["dedup_key"].startswith("lab_critical:")


def test_lab_critical_no_red_flags_no_op():
    """Empty red_flags → no notify call."""
    _reload_handlers()
    captured = []

    def fake_notify(*args, **kwargs):
        captured.append(args)

    with patch("agents.notify.notify", side_effect=fake_notify):
        hooks.fire(hooks.HOOK_LAB_CRITICAL, {
            "patient_id": "X",
            "red_flags": [],
            "lang": "ru",
        })
    assert captured == []


def test_lab_critical_dedup_4h():
    """Same fingerprint within 4h → suppressed by escalation_engine."""
    _reload_handlers()
    n_calls = []

    def fake_notify(*args, **kwargs):
        n_calls.append(1)
        from agents.notify import NotifyResult
        return NotifyResult(delivered_via="telegram", attempted=["telegram"],
                            failures={})

    payload = {
        "patient_id": "TEST_Patient_1970_01_01",
        "red_flags": ["K+ > 6.5 mmol/L — риск аритмии"],
        "lang": "ru",
    }
    with patch("agents.notify.notify", side_effect=fake_notify):
        hooks.fire(hooks.HOOK_LAB_CRITICAL, payload)
        # Second fire with identical payload → suppressed
        hooks.fire(hooks.HOOK_LAB_CRITICAL, payload)

    assert len(n_calls) == 1, f"expected 1 dispatch, got {len(n_calls)}"


def test_lab_critical_different_flags_alert_again():
    """Different red_flags → different fingerprint → alert fires again."""
    _reload_handlers()
    n_calls = []

    def fake_notify(*args, **kwargs):
        n_calls.append(1)
        from agents.notify import NotifyResult
        return NotifyResult(delivered_via="telegram", attempted=["telegram"],
                            failures={})

    with patch("agents.notify.notify", side_effect=fake_notify):
        hooks.fire(hooks.HOOK_LAB_CRITICAL, {
            "patient_id": "X",
            "red_flags": ["K+ > 6.5"],
            "lang": "ru",
        })
        hooks.fire(hooks.HOOK_LAB_CRITICAL, {
            "patient_id": "X",
            "red_flags": ["K+ > 6.5", "Plt < 20"],  # extra flag
            "lang": "ru",
        })

    assert len(n_calls) == 2


# ── HOOK_SESSION_END ────────────────────────────────────────────────


def test_session_end_calls_archive():
    """Handler invokes db.archive_old_events on session close."""
    _reload_handlers()
    n_calls = []

    def fake_archive(*args, **kwargs):
        n_calls.append(1)
        return 0

    with patch("db.archive_old_events", side_effect=fake_archive):
        hooks.fire(hooks.HOOK_SESSION_END, {"session_id": 42, "summary": ""})

    assert len(n_calls) == 1


def test_session_end_archive_failure_does_not_raise():
    """Archive exception is logged but doesn't crash the chain."""
    _reload_handlers()

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    with patch("db.archive_old_events", side_effect=boom):
        # fire should not raise (hooks framework already swallows)
        results = hooks.fire(hooks.HOOK_SESSION_END, {"session_id": 1})
        # handler returns None (logged warning), framework returns [None]
        assert results == [None]


# ── AIM_NO_AUTO_HOOKS env override ──────────────────────────────────


def test_no_auto_hooks_blocks_registration(monkeypatch):
    """AIM_NO_AUTO_HOOKS=1 → register_all() not auto-called on import."""
    monkeypatch.setenv("AIM_NO_AUTO_HOOKS", "1")
    # Re-import without triggering register_all
    import importlib
    from agents import hook_handlers
    hooks.clear()
    hook_handlers.reset_for_tests()
    importlib.reload(hook_handlers)

    listing = hooks.list_handlers(hooks.HOOK_LAB_CRITICAL)
    assert listing[hooks.HOOK_LAB_CRITICAL] == []
