"""AI/tests/test_diagnostic_ledger.py — DG1 (2026-05-03)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.diagnostic_ledger" in sys.modules:
        importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    return tmp_path


# ── record / query ───────────────────────────────────────────────


def test_record_persists(isolated):
    from AI.ai.diagnostic_ledger import record, all_rows
    record(model="ds-r", grade="B", n_refs=10, n_with_line=8,
           crit=1, high=2, med=3, low=4)
    rows = all_rows()
    assert len(rows) == 1
    r = rows[0]
    assert r.model == "ds-r"
    assert r.grade == "B"
    assert r.compliance == 0.8


def test_record_zero_refs(isolated):
    from AI.ai.diagnostic_ledger import record, all_rows
    record(model="m", grade=None, n_refs=0, n_with_line=0)
    assert all_rows()[0].compliance == 0.0


def test_record_rejects_negative_counts(isolated):
    from AI.ai.diagnostic_ledger import record
    with pytest.raises(ValueError):
        record(model="m", grade=None, n_refs=-1, n_with_line=0)


def test_record_rejects_with_line_exceeds_total(isolated):
    from AI.ai.diagnostic_ledger import record
    with pytest.raises(ValueError):
        record(model="m", grade=None, n_refs=2, n_with_line=5)


def test_recent_returns_last_n(isolated):
    from AI.ai.diagnostic_ledger import record, recent
    for i in range(15):
        record(model=f"m{i}", grade="B", n_refs=10, n_with_line=10,
               ts=f"2026-05-03T10:00:{i:02d}")
    out = recent(n=5)
    assert [r.model for r in out] == ["m10", "m11", "m12", "m13", "m14"]


def test_record_from_report(isolated):
    from AI.ai.diagnostic_ledger import record_from_report, all_rows
    txt = ("Grade: D\ncrit: 2\nhigh: 1\n"
           "Issue at `agents/x.py:1` and `agents/y.py`.")
    record_from_report(txt, model="ds-r")
    r = all_rows()[0]
    assert r.grade == "D"
    assert r.n_refs == 2
    assert r.n_with_line == 1
    assert r.crit == 2


def test_record_retry_flag(isolated):
    from AI.ai.diagnostic_ledger import record, all_rows
    record(model="m", grade="C", n_refs=1, n_with_line=1, retry_used=True)
    assert all_rows()[0].retry_used is True


# ── trend ───────────────────────────────────────────────────────


def test_trend_empty(isolated):
    from AI.ai.diagnostic_ledger import trend
    assert trend() == {"n_runs": 0}


def test_trend_aggregates(isolated):
    from AI.ai.diagnostic_ledger import record, trend
    record(model="m", grade="B", n_refs=10, n_with_line=10,
           crit=1, ts="2026-05-01T10:00:00")
    record(model="m", grade="C", n_refs=10, n_with_line=5,
           crit=3, ts="2026-05-02T10:00:00")
    t = trend()
    assert t["n_runs"] == 2
    assert t["avg_compliance"] == 0.75
    assert t["avg_crit"] == 2.0
    assert t["grade_dist"] == {"B": 1, "C": 1}
    assert t["first_ts"].startswith("2026-05-01")
    assert t["last_ts"].startswith("2026-05-02")


def test_trend_retry_share(isolated):
    from AI.ai.diagnostic_ledger import record, trend
    record(model="m", grade="B", n_refs=1, n_with_line=1, retry_used=True)
    record(model="m", grade="B", n_refs=1, n_with_line=1, retry_used=False)
    record(model="m", grade="B", n_refs=1, n_with_line=1, retry_used=True)
    assert trend()["retry_share"] == pytest.approx(2 / 3)


# ── summary ─────────────────────────────────────────────────────


def test_summary_calm_when_empty(isolated):
    from AI.ai.diagnostic_ledger import summary
    assert "no diagnostic runs" in summary()


def test_summary_renders(isolated):
    from AI.ai.diagnostic_ledger import record, summary
    record(model="m", grade="B", n_refs=10, n_with_line=9, crit=0)
    s = summary()
    assert "1 runs" in s
    assert "90%" in s


def test_summary_warns_when_compliance_low(isolated):
    from AI.ai.diagnostic_ledger import record, summary
    record(model="m", grade="D", n_refs=10, n_with_line=2, crit=3)
    record(model="m", grade="D", n_refs=10, n_with_line=4, crit=2)
    s = summary()
    assert "under 60%" in s


# ── concurrency ─────────────────────────────────────────────────


def test_concurrent_record(isolated):
    """20 threads × 25 record() calls — no corruption / loss."""
    import threading
    from AI.ai.diagnostic_ledger import record, all_rows

    errs: list[str] = []
    err_lock = threading.Lock()

    def worker(tid: int) -> None:
        try:
            for i in range(25):
                record(model=f"t{tid}", grade="B",
                       n_refs=10, n_with_line=10,
                       ts=f"2026-05-03T10:{tid:02d}:{i:02d}.{tid:03d}{i:03d}")
        except Exception as e:
            with err_lock:
                errs.append(f"t{tid}: {e}")

    ts = [threading.Thread(target=worker, args=(t,))
          for t in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert not errs, f"concurrent record() failed: {errs}"
    assert len(all_rows()) == 20 * 25


# ── prune_phantom ───────────────────────────────────────────────


def test_prune_phantom_dry_run(isolated, tmp_path):
    """Dry-run reports counts but doesn't delete."""
    from AI.ai.diagnostic_ledger import record, all_rows, prune_phantom
    real = tmp_path / "real.md"
    real.write_text("ok")
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(real), ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(tmp_path / "gone.md"), ts="2026-05-03T11:00:00")
    res = prune_phantom(dry_run=True)
    assert res["dry_run"] is True
    assert res["would_remove"] == 1
    assert res["kept"] == 1
    assert res["removed"] == 0
    assert len(all_rows()) == 2   # nothing actually deleted


def test_prune_phantom_live_deletes(isolated, tmp_path):
    from AI.ai.diagnostic_ledger import record, all_rows, prune_phantom
    real = tmp_path / "real.md"
    real.write_text("ok")
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(real), ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(tmp_path / "gone.md"), ts="2026-05-03T11:00:00")
    res = prune_phantom(dry_run=False)
    assert res["removed"] == 1
    assert res["kept"] == 1
    rows = all_rows()
    assert len(rows) == 1
    assert rows[0].report_path == str(real)


def test_prune_phantom_keeps_rows_without_report_path(isolated):
    """Rows where report_path is None must NOT be pruned."""
    from AI.ai.diagnostic_ledger import record, all_rows, prune_phantom
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=None, ts="2026-05-03T10:00:00")
    res = prune_phantom(dry_run=False)
    assert res["removed"] == 0
    assert res["kept"] == 1
    assert len(all_rows()) == 1


def test_prune_phantom_idempotent(isolated, tmp_path):
    from AI.ai.diagnostic_ledger import record, prune_phantom, all_rows
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(tmp_path / "gone.md"), ts="2026-05-03T10:00:00")
    prune_phantom(dry_run=False)
    # Second run on already-pruned DB → no further deletes.
    res = prune_phantom(dry_run=False)
    assert res["removed"] == 0
    assert res["kept"] == 0


def test_prune_phantom_handles_large_batches(isolated, tmp_path):
    """Many phantom rows should still delete cleanly (batches of 500)."""
    from AI.ai.diagnostic_ledger import record, prune_phantom
    for i in range(1100):
        record(model="m", grade="B", n_refs=1, n_with_line=1,
               report_path=str(tmp_path / f"gone-{i}.md"),
               ts=f"2026-05-03T10:00:{i:04d}.{i:06d}")
    res = prune_phantom(dry_run=False)
    assert res["removed"] == 1100
    assert res["kept"] == 0
