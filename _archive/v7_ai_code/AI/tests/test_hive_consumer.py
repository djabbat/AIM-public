"""AI/tests/test_hive_consumer.py — HV3 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HIVE_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AIM_HIVE_QUEEN_URL", raising=False)
    (tmp_path / "cases").mkdir()
    (tmp_path / "home").mkdir()
    import importlib, sys
    if "AI.ai.hive_consumer" in sys.modules:
        importlib.reload(sys.modules["AI.ai.hive_consumer"])
    return tmp_path


_DEFAULT = object()

def _update(update_id="u-1", kind="skill",
             body=_DEFAULT, eval_delta=0.07, signature="abcdef123456"):
    from AI.ai.hive_consumer import Update
    if body is _DEFAULT:
        body = {"skill_id": "test-1"}
    return Update(
        id=update_id, ts="2026-05-04T10:00:00",
        kind=kind, body=body,
        source_n=2, eval_delta=eval_delta, signature=signature,
    )


# ── opt-in / opt-out (L_CONSENT) ───────────────────────────────


def test_opt_out_blocks_apply(isolated):
    from AI.ai.hive_consumer import opt_out, apply
    opt_out("skill")
    res = apply(_update())
    assert res.installed is False
    assert "L_CONSENT" in res.skipped_reason


def test_opt_out_pattern_matches_id(isolated):
    from AI.ai.hive_consumer import opt_out, apply
    opt_out("skill", pattern="bad-*")
    # An update whose body's skill_id matches "bad-*" → blocked
    res = apply(_update(body={"skill_id": "bad-foo"}))
    assert res.installed is False


def test_opt_out_pattern_does_not_block_unrelated(isolated):
    from AI.ai.hive_consumer import opt_out, apply
    opt_out("skill", pattern="bad-*")
    res = apply(_update(body={"skill_id": "good-thing"}))
    assert res.installed is True


def test_opt_in_reverses(isolated):
    from AI.ai.hive_consumer import opt_out, opt_in, apply
    opt_out("skill")
    assert opt_in("skill") is True
    res = apply(_update())
    assert res.installed is True


# ── apply gates ────────────────────────────────────────────────


def test_apply_dry_run_does_not_persist(isolated):
    from AI.ai.hive_consumer import apply, sync_state
    res = apply(_update(), dry_run=True)
    assert res.installed is False
    assert res.skipped is False
    s = sync_state()
    assert s.n_installed == 0


def test_apply_skips_missing_signature(isolated):
    from AI.ai.hive_consumer import apply
    res = apply(_update(signature=""))
    assert res.skipped is True
    assert "signature" in res.skipped_reason


def test_apply_skips_negative_eval_delta(isolated):
    from AI.ai.hive_consumer import apply
    res = apply(_update(eval_delta=-0.05))
    assert res.skipped is True
    assert "eval_delta" in res.skipped_reason


def test_apply_skill_writes_file(isolated):
    from AI.ai.hive_consumer import apply
    res = apply(_update(kind="skill",
                          body={"skill_id": "auto-x", "theme": ["a", "b"]}))
    assert res.installed is True
    skill_path = isolated / "home" / ".aim" / "skills" / "auto-x.json"
    assert skill_path.exists()


def test_apply_eval_case_writes_yaml(isolated):
    from AI.ai.hive_consumer import apply
    res = apply(_update(kind="eval_case",
                          body={"id": "cv-test-1",
                                  "task": "do thing",
                                  "rubrics": {"min_length": 5}}))
    assert res.installed is True
    yaml_path = isolated / "cases" / "cv-test-1.yaml"
    assert yaml_path.exists()


def test_apply_unknown_kind_logs_only(isolated):
    from AI.ai.hive_consumer import apply
    res = apply(_update(kind="weird_kind",
                          body={"x": 1}))
    # framework: unknown kind doesn't crash; logs note
    assert res.installed is True
    assert any("unknown kind" in n for n in res.notes)


def test_apply_skill_missing_id_skips(isolated):
    from AI.ai.hive_consumer import apply
    res = apply(_update(kind="skill", body={}))
    assert res.skipped is True
    assert "skill_id" in res.skipped_reason or "install error" in res.skipped_reason


def test_apply_records_in_sync_log(isolated):
    from AI.ai.hive_consumer import apply, sync_state
    apply(_update(update_id="a"))
    apply(_update(update_id="b", body={"skill_id": "y"}))
    apply(_update(update_id="c", signature=""))
    s = sync_state()
    assert s.n_installed == 2
    assert s.n_skipped == 1


# ── pull (transport — stubbed) ─────────────────────────────────


def test_pull_no_url_returns_empty(isolated):
    from AI.ai.hive_consumer import pull
    assert pull() == []


def test_pull_parses_response(isolated, monkeypatch):
    import AI.ai.hive_consumer as hc

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "updates": [
                    {"id": "u1", "ts": "2026-05-04T10:00:00",
                     "kind": "skill", "body": {"skill_id": "x"},
                     "source_n": 2, "eval_delta": 0.05,
                     "signature": "sigsig123"},
                ]
            }

    captured = {}
    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr("httpx.get", fake_get)
    out = hc.pull(queen_url="https://queen.example.com")
    assert len(out) == 1
    assert out[0].id == "u1"
    assert captured["url"].endswith("/v1/hive/updates")


def test_pull_swallows_errors(isolated, monkeypatch):
    def boom(url, params, timeout):
        raise RuntimeError("network down")
    monkeypatch.setattr("httpx.get", boom)
    from AI.ai.hive_consumer import pull
    assert pull(queen_url="https://queen.example.com") == []


# ── sync_state ─────────────────────────────────────────────────


def test_sync_state_empty(isolated):
    from AI.ai.hive_consumer import sync_state
    s = sync_state()
    assert s.n_installed == 0
    assert s.n_skipped == 0
    assert s.last_pull_ts is None


def test_summary_renders(isolated):
    from AI.ai.hive_consumer import summary
    s = summary()
    assert "Hive consumer" in s
