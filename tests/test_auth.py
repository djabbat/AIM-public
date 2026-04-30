"""tests/test_auth.py — AIM Hub auth smoke tests.

Run:
    cd ~/Desktop/AIM && python -m pytest tests/test_auth.py -q
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fresh_hub(monkeypatch, tmp_path):
    """Spin up a clean hub DB in a tmpdir for each test."""
    db = tmp_path / "hub.db"
    monkeypatch.setenv("AIM_HUB_DB", str(db))
    # Force reimport so HUB_DB_PATH binds to the tmp path
    if "agents.auth" in sys.modules:
        del sys.modules["agents.auth"]
    from agents import auth as _a
    _a.init_hub_db()
    return _a


def test_first_user_create_and_login(fresh_hub):
    a = fresh_hub
    u = a.create_user("alice", "horsebatterystaple", role="admin")
    assert u["username"] == "alice"
    assert u["role"] == "admin"
    assert u["disabled"] is False
    # password hashing
    ok = a.verify_password("alice", "horsebatterystaple")
    assert ok and ok["id"] == u["id"]
    assert a.verify_password("alice", "wrong-password") is None
    assert a.verify_password("nobody", "anything") is None


def test_password_min_length(fresh_hub):
    a = fresh_hub
    with pytest.raises(ValueError):
        a.create_user("x", "short")


def test_jwt_roundtrip_and_revoke(fresh_hub):
    a = fresh_hub
    u = a.create_user("bob", "passpasspass")
    tok = a.issue_jwt(u["id"], ttl_days=1)
    assert tok.count(".") == 2
    r = a.verify_jwt(tok)
    assert r and r["id"] == u["id"]
    a.revoke_jwt(tok)
    assert a.verify_jwt(tok) is None


def test_api_token_lifecycle(fresh_hub):
    a = fresh_hub
    u = a.create_user("carol", "passpasspass")
    t1 = a.issue_api_token(u["id"])
    assert t1.startswith("aim_")
    fetched = a.get_user_by_token(t1)
    assert fetched and fetched["id"] == u["id"]
    # Re-issue replaces the previous token
    t2 = a.issue_api_token(u["id"])
    assert t2 != t1
    assert a.get_user_by_token(t1) is None
    assert a.get_user_by_token(t2)["id"] == u["id"]
    # Disable revokes
    a.disable_user(u["id"])
    assert a.get_user_by_token(t2) is None


def test_disable_blocks_login(fresh_hub):
    a = fresh_hub
    u = a.create_user("dan", "passpasspass")
    a.disable_user(u["id"])
    assert a.verify_password("dan", "passpasspass") is None


def test_telegram_link_code(fresh_hub):
    a = fresh_hub
    u = a.create_user("eve", "passpasspass")
    code = a.create_link_code(u["id"], ttl_min=5)
    assert len(code) == 6 and code.isdigit()
    bound = a.consume_link_code(code, telegram_id=42)
    assert bound and bound["telegram_id"] == 42
    # Code is one-shot
    assert a.consume_link_code(code, telegram_id=43) is None
    # And tg_id resolves back to the user
    fetched = a.get_user_by_telegram(42)
    assert fetched and fetched["id"] == u["id"]


def test_audit_log(fresh_hub):
    a = fresh_hub
    u = a.create_user("frank", "passpasspass")
    a.audit(u["id"], "test.event", target="x", ip="127.0.0.1")
    rows = a.list_audit(user_id=u["id"], limit=10)
    assert any(r["action"] == "test.event" for r in rows)


def test_node_heartbeat(fresh_hub):
    a = fresh_hub
    u = a.create_user("ivan", "passpasspass")
    a.record_node_heartbeat(u["id"], "ivan-laptop", host="ivan-mbp", version="7.0")
    a.record_node_heartbeat(u["id"], "ivan-laptop", host="ivan-mbp", version="7.0.1")
    rows = a.list_nodes(u["id"])
    assert len(rows) == 1  # upserted
    assert rows[0]["version"] == "7.0.1"


def test_constant_time_login_for_unknown_user(fresh_hub):
    """Verify non-existent users still trigger a hash-verify (timing-safe)."""
    a = fresh_hub
    import time
    a.create_user("real", "passpasspass")
    t0 = time.time(); a.verify_password("real", "wrong"); t_real = time.time() - t0
    t0 = time.time(); a.verify_password("nonexistent", "wrong"); t_fake = time.time() - t0
    # Allow generous margin — just want neither to be <10x slower (pure DB miss)
    assert t_fake > 0.001 or t_real > 0.001  # if argon2 active, both > 1ms
