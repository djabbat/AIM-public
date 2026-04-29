"""Unit tests for agents/hooks.py — event registry."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents import hooks
from agents.hooks import (
    register, fire, unregister, clear, list_handlers,
    HOOK_LAB_CRITICAL, HOOK_KERNEL_DECISION, HOOK_SESSION_END,
    HOOK_INTAKE_PDF, HOOK_PRE_COMMIT, KNOWN_HOOKS,
)


@pytest.fixture(autouse=True)
def _clean():
    clear()
    yield
    clear()


def test_register_and_fire_basic():
    bag = []

    @register(HOOK_LAB_CRITICAL)
    def h(payload):
        bag.append(payload["analyte"])

    fire(HOOK_LAB_CRITICAL, {"analyte": "K+", "value": 7.2})
    assert bag == ["K+"]


def test_register_idempotent():
    def h(payload): return 1
    register(HOOK_SESSION_END)(h)
    register(HOOK_SESSION_END)(h)
    register(HOOK_SESSION_END)(h)
    assert len(list_handlers(HOOK_SESSION_END)[HOOK_SESSION_END]) == 1


def test_unknown_event_raises():
    with pytest.raises(ValueError):
        register("on_nonsense")(lambda p: None)


def test_fire_unknown_event_silent():
    # Не должен падать, просто warning + []
    assert fire("on_nonsense", {}) == []


def test_handler_exception_does_not_break_chain():
    bag = []

    @register(HOOK_INTAKE_PDF)
    def boom(payload):
        raise RuntimeError("intentional")

    @register(HOOK_INTAKE_PDF)
    def ok(payload):
        bag.append("ok")
        return "ok"

    results = fire(HOOK_INTAKE_PDF, {"path": "x.pdf"})
    assert bag == ["ok"]
    assert results == [None, "ok"]  # boom вернул None из-за исключения


def test_unregister():
    def h(payload): return "x"
    register(HOOK_PRE_COMMIT)(h)
    assert unregister(HOOK_PRE_COMMIT, h) is True
    assert unregister(HOOK_PRE_COMMIT, h) is False
    assert fire(HOOK_PRE_COMMIT, {}) == []


def test_fire_returns_results_in_order():
    @register(HOOK_KERNEL_DECISION)
    def h1(p): return 1
    @register(HOOK_KERNEL_DECISION)
    def h2(p): return 2
    @register(HOOK_KERNEL_DECISION)
    def h3(p): return 3
    assert fire(HOOK_KERNEL_DECISION, {}) == [1, 2, 3]


def test_known_hooks_complete():
    assert KNOWN_HOOKS == {
        HOOK_LAB_CRITICAL, HOOK_KERNEL_DECISION, HOOK_SESSION_END,
        HOOK_INTAKE_PDF, HOOK_PRE_COMMIT,
    }


def test_list_handlers_diagnostic():
    @register(HOOK_LAB_CRITICAL)
    def my_handler(p): return None
    listing = list_handlers()
    assert "my_handler" in listing[HOOK_LAB_CRITICAL]
    assert listing[HOOK_PRE_COMMIT] == []


def test_clear_specific_event():
    @register(HOOK_LAB_CRITICAL)
    def h1(p): return None
    @register(HOOK_SESSION_END)
    def h2(p): return None
    clear(HOOK_LAB_CRITICAL)
    assert list_handlers(HOOK_LAB_CRITICAL)[HOOK_LAB_CRITICAL] == []
    assert "h2" in list_handlers(HOOK_SESSION_END)[HOOK_SESSION_END]
