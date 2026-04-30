"""tests/test_pairing.py — 6-digit device pairing flow."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fresh_hub(tmp_path, monkeypatch):
    db = tmp_path / "hub.db"
    monkeypatch.setenv("AIM_HUB_DB", str(db))
    import importlib
    import agents
    if hasattr(agents, "auth"):
        importlib.reload(agents.auth)
    else:
        from agents import auth        # noqa: F401
    if hasattr(agents, "pairing"):
        importlib.reload(agents.pairing)
    else:
        from agents import pairing     # noqa: F401
    _a = agents.auth
    _p = sys.modules["agents.pairing"]
    _a.init_hub_db()
    return _a, _p


def test_pair_full_flow(fresh_hub):
    auth, pairing = fresh_hub
    u = auth.create_user("alice", "horsebatterystaple")
    code, exp = pairing.issue_pair_code(u["id"], ttl_min=10)
    assert len(code) == 6 and code.isdigit()

    result = pairing.consume_pair_code(code, node_id="alice-laptop",
                                        host="laptop", version="7.1")
    assert result is not None
    assert result["token"].startswith("aim_")
    assert result["user"]["id"] == u["id"]

    # one-shot
    assert pairing.consume_pair_code(code) is None

    # token authenticates
    fetched = auth.get_user_by_token(result["token"])
    assert fetched and fetched["id"] == u["id"]


def test_pair_invalidates_previous_codes(fresh_hub):
    """Issuing a new code for the same user should invalidate the prior one."""
    auth, pairing = fresh_hub
    u = auth.create_user("bob", "passpasspass")
    c1, _ = pairing.issue_pair_code(u["id"])
    c2, _ = pairing.issue_pair_code(u["id"])
    assert c1 != c2
    assert pairing.consume_pair_code(c1) is None    # invalidated
    assert pairing.consume_pair_code(c2) is not None


def test_pair_rejects_bad_codes(fresh_hub):
    _, pairing = fresh_hub
    assert pairing.consume_pair_code("") is None
    assert pairing.consume_pair_code("12345") is None    # 5 digits
    assert pairing.consume_pair_code("1234567") is None  # 7 digits
    assert pairing.consume_pair_code("abcdef") is None
    assert pairing.consume_pair_code("999999") is None   # never issued


def test_pair_disabled_user_cannot_pair(fresh_hub):
    auth, pairing = fresh_hub
    u = auth.create_user("carol", "passpasspass")
    code, _ = pairing.issue_pair_code(u["id"])
    auth.disable_user(u["id"])
    assert pairing.consume_pair_code(code) is None


def test_pair_cleanup_expired(fresh_hub):
    _, pairing = fresh_hub
    # Just smoke — function shouldn't crash on empty DB
    n = pairing.cleanup_expired(older_than_min=60)
    assert n >= 0
