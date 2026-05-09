"""AI/tests/test_hive_queen.py — HV2 queen (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HIVE_QUEEN_DB", str(tmp_path / "queen.db"))
    import importlib, sys
    if "AI.ai.hive_queen" in sys.modules:
        importlib.reload(sys.modules["AI.ai.hive_queen"])
    return tmp_path


def _payload(worker_id: str = "abc12345", **overrides) -> dict:
    base = {
        "v": 1,
        "ts": "2026-05-04T10:00:00",
        "worker_id": worker_id,
        "ledger": {"n_runs": 0},
        "prompt": {},
        "skills": {"skill_invocations": {}},
        "reflexion": {"clusters": []},
        "suppressions": {"n_active_suppressions": 0},
        "system": {"aim_version": "AI-hive-1"},
    }
    base.update(overrides)
    return base


# ── accept ─────────────────────────────────────────────────────


def test_accept_contribution_persists(isolated):
    from AI.ai.hive_queen import accept_contribution, list_contributions
    cid = accept_contribution(_payload())
    assert cid
    assert len(cid) >= 16
    rows = list_contributions()
    assert len(rows) == 1
    assert rows[0].worker_id == "abc12345"


def test_accept_rejects_wrong_version(isolated):
    from AI.ai.hive_queen import accept_contribution
    assert accept_contribution({"v": 99, "worker_id": "xxxxxxxx"}) is None


def test_accept_rejects_missing_worker(isolated):
    from AI.ai.hive_queen import accept_contribution
    assert accept_contribution({"v": 1}) is None


def test_accept_rejects_short_worker_id(isolated):
    from AI.ai.hive_queen import accept_contribution
    p = _payload(worker_id="ab")
    assert accept_contribution(p) is None


def test_accept_rejects_non_dict(isolated):
    from AI.ai.hive_queen import accept_contribution
    assert accept_contribution("not a dict") is None
    assert accept_contribution([1, 2, 3]) is None


def test_list_filters_by_worker(isolated):
    from AI.ai.hive_queen import accept_contribution, list_contributions
    accept_contribution(_payload(worker_id="aaaaaaaa"))
    accept_contribution(_payload(worker_id="bbbbbbbb"))
    accept_contribution(_payload(worker_id="aaaaaaaa"))
    a = list_contributions(worker_id="aaaaaaaa")
    assert len(a) == 2


# ── distill ────────────────────────────────────────────────────


def test_distill_empty_when_no_contribs(isolated):
    from AI.ai.hive_queen import distill_candidates
    assert distill_candidates() == []


def test_distill_compliance_drift(isolated):
    """Two workers with low compliance → prompt_patch candidate."""
    from AI.ai.hive_queen import accept_contribution, distill_candidates
    accept_contribution(_payload(
        worker_id="w1aaaaaa",
        ledger={"n_runs": 5, "avg_compliance": 0.3, "avg_crit": 1.0,
                 "retry_share": 0.2, "grade_dist": {}},
    ))
    accept_contribution(_payload(
        worker_id="w2bbbbbb",
        ledger={"n_runs": 5, "avg_compliance": 0.4, "avg_crit": 1.0,
                 "retry_share": 0.2, "grade_dist": {}},
    ))
    cands = distill_candidates()
    pp = [c for c in cands if c.kind == "prompt_patch"]
    assert len(pp) == 1
    assert pp[0].source_n == 2


def test_distill_does_not_fire_below_min_workers(isolated):
    from AI.ai.hive_queen import accept_contribution, distill_candidates
    accept_contribution(_payload(
        worker_id="loneone",
        ledger={"n_runs": 5, "avg_compliance": 0.3, "avg_crit": 1.0,
                 "retry_share": 0.2, "grade_dist": {}},
    ))
    cands = distill_candidates()
    assert all(c.kind != "prompt_patch" for c in cands)


def test_distill_skill_from_clustered_theme(isolated):
    """Two workers' reflexion clusters share theme → skill candidate."""
    from AI.ai.hive_queen import accept_contribution, distill_candidates
    accept_contribution(_payload(
        worker_id="w1aaaaaa",
        reflexion={"clusters": [{"theme": ["pubmed", "verify"], "n": 5}]},
    ))
    accept_contribution(_payload(
        worker_id="w2bbbbbb",
        reflexion={"clusters": [{"theme": ["pubmed", "verify"], "n": 3}]},
    ))
    cands = distill_candidates()
    skill = [c for c in cands if c.kind == "skill"]
    assert len(skill) == 1
    assert skill[0].source_n == 2


def test_distill_high_compliance_no_drift_alarm(isolated):
    """If everybody's compliance is high, NO prompt_patch should fire."""
    from AI.ai.hive_queen import accept_contribution, distill_candidates
    for w in ("w1aaaaaa", "w2bbbbbb", "w3cccccc"):
        accept_contribution(_payload(
            worker_id=w,
            ledger={"n_runs": 5, "avg_compliance": 0.92, "avg_crit": 0.5,
                     "retry_share": 0.05, "grade_dist": {}},
        ))
    cands = distill_candidates()
    assert all(c.kind != "prompt_patch" for c in cands)


# ── publish ────────────────────────────────────────────────────


def test_publish_eval_pass_creates_update(isolated):
    from AI.ai.hive_queen import (
        Candidate, publish_update, list_updates,
    )
    cand = Candidate(
        kind="skill", body={"skill_id": "test-1"},
        source_workers={"w1", "w2"}, rationale="test",
    )
    upd = publish_update(cand, eval_pass=True, eval_delta=0.07)
    assert upd is not None
    assert upd.eval_delta == 0.07
    assert upd.signature
    rows = list_updates()
    assert len(rows) == 1


def test_publish_eval_fail_skips(isolated):
    from AI.ai.hive_queen import Candidate, publish_update, list_updates
    cand = Candidate(kind="skill", body={"skill_id": "x"},
                      source_workers={"w1"}, rationale="r")
    assert publish_update(cand, eval_pass=False) is None
    assert list_updates() == []


def test_list_updates_since(isolated):
    from AI.ai.hive_queen import (
        Candidate, publish_update, list_updates,
    )
    cand = Candidate(kind="skill", body={"skill_id": "y"},
                      source_workers={"w1"}, rationale="r")
    upd = publish_update(cand, eval_pass=True)
    # Same-second since filter — should return nothing.
    later = list_updates(since=upd.ts)
    assert later == []
    # Earlier filter returns the row.
    earlier = list_updates(since="2020-01-01T00:00:00")
    assert len(earlier) == 1


def test_signature_deterministic(isolated):
    from AI.ai.hive_queen import _signature
    a = _signature({"a": 1, "b": 2})
    b = _signature({"b": 2, "a": 1})
    assert a == b   # sorted keys


# ── summary ────────────────────────────────────────────────────


def test_summary_renders_empty(isolated):
    from AI.ai.hive_queen import summary
    s = summary()
    assert "Hive queen" in s
    assert "0 contributions" in s


def test_summary_with_data(isolated):
    from AI.ai.hive_queen import accept_contribution, summary
    for w in ("w1aaaaaa", "w2bbbbbb"):
        accept_contribution(_payload(
            worker_id=w,
            ledger={"n_runs": 5, "avg_compliance": 0.3, "avg_crit": 1.0,
                     "retry_share": 0.1, "grade_dist": {}},
        ))
    s = summary()
    assert "2 contributions" in s
    assert "candidate updates pending" in s
