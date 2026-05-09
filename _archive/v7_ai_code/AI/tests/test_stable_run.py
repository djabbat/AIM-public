"""AI/tests/test_stable_run.py — S13 (2026-05-03)."""
from __future__ import annotations

import sys

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    if "AI.ai.stable_run" in sys.modules:
        importlib.reload(sys.modules["AI.ai.stable_run"])
    return tmp_path


# ── stable_run() with stub ──────────────────────────────────────


def test_stable_run_requires_n_at_least_2(isolated):
    from AI.ai.stable_run import stable_run
    with pytest.raises(ValueError):
        stable_run(n=1)


def test_stable_run_collects_reports(isolated):
    from AI.ai.stable_run import stable_run
    calls: list[int] = []
    def stub(model: str = "x") -> str:
        calls.append(1)
        return f"Grade: B\n`agents/x.py:10` `agents/y.py:20`"
    out = stable_run(n=3, run_fn=stub)
    assert sum(calls) == 3
    assert out.n_runs == 3


def test_stable_run_stable_verdict(isolated):
    """3 identical reports → stable verdict, full overlap."""
    from AI.ai.stable_run import stable_run
    body = "Grade: B\ncrit: 0\nhigh: 1\n`agents/x.py:10`"
    out = stable_run(n=3, run_fn=lambda model="x": body)
    assert out.verdict == "stable"
    assert out.shared_findings == ["agents/x.py:10"]
    assert out.unique_findings == []


def test_stable_run_unstable_verdict(isolated):
    """Different grades + different findings → unstable."""
    from AI.ai.stable_run import stable_run
    pool = [
        "Grade: A\n`agents/a.py:1`",
        "Grade: F\n`agents/z.py:99`",
    ]
    idx = {"i": 0}
    def stub(model="x"):
        r = pool[idx["i"] % 2]
        idx["i"] += 1
        return r
    out = stable_run(n=2, run_fn=stub)
    assert out.verdict == "unstable"
    assert len(out.unique_findings) == 2


def test_stable_run_save_individual(isolated, tmp_path, monkeypatch):
    """save_individual=True writes one pass-N file per run."""
    import AI.ai.stable_run as sr
    monkeypatch.setattr(sr, "ai_root", lambda: tmp_path)
    sr.stable_run(n=3,
                   run_fn=lambda model="x": "Grade: B\n`agents/x.py:1`",
                   save_individual=True)
    files = sorted((tmp_path / "artifacts").glob("stable_run_*_pass*.md"))
    assert len(files) == 3


def test_stable_run_does_not_save_by_default(isolated, tmp_path, monkeypatch):
    import AI.ai.stable_run as sr
    monkeypatch.setattr(sr, "ai_root", lambda: tmp_path)
    sr.stable_run(n=2,
                   run_fn=lambda model="x": "Grade: B\n`agents/x.py:1`")
    assert not (tmp_path / "artifacts").exists() or \
           not list((tmp_path / "artifacts").glob("stable_run_*_pass*.md"))


# ── render_consolidated ─────────────────────────────────────────


def test_render_consolidated_stable(isolated):
    from AI.ai.stable_run import StableResult, render_consolidated
    r = StableResult(
        n_runs=3, raw_reports=[],
        grades=["B", "B", "B"], verdict="stable",
        shared_findings=["agents/x.py:10", "AI/ai/y.py:20"],
        unique_findings=[],
        crit_counts=[0, 0, 0], jaccard=1.0,
    )
    text = render_consolidated(r)
    assert "Verdict" in text
    assert "STABLE" in text
    assert "agents/x.py:10" in text
    assert "Adversarial mode converged" in text


def test_render_consolidated_noisy_recommendation(isolated):
    from AI.ai.stable_run import StableResult, render_consolidated
    r = StableResult(
        n_runs=2, raw_reports=[],
        grades=["B", "B"], verdict="noisy",
        shared_findings=["agents/x.py:1"],
        unique_findings=["agents/a.py:2", "agents/b.py:3"],
        crit_counts=[1, 1], jaccard=0.3,
    )
    text = render_consolidated(r)
    assert "NOISY" in text
    assert "SHARED findings only" in text
    assert "agents/x.py:1" in text


def test_render_consolidated_unstable(isolated):
    from AI.ai.stable_run import StableResult, render_consolidated
    r = StableResult(
        n_runs=2, raw_reports=[],
        grades=["A", "F"], verdict="unstable",
        shared_findings=[], unique_findings=["a.py:1", "z.py:99"],
        crit_counts=[0, 3], jaccard=0.0,
    )
    text = render_consolidated(r)
    assert "UNSTABLE" in text
    assert "paranoia mode" in text or "open-ended" in text


# ── line compliance aggregate ───────────────────────────────────


def test_stable_run_collects_line_compliance(isolated):
    from AI.ai.stable_run import stable_run
    pool = [
        "Grade: B\n`agents/x.py:10`",       # 100%
        "Grade: B\n`agents/y.py`",          # 0%
    ]
    idx = {"i": 0}
    def stub(model="x"):
        r = pool[idx["i"] % 2]
        idx["i"] += 1
        return r
    out = stable_run(n=2, run_fn=stub)
    assert out.line_compliance == [1.0, 0.0]
    assert out.avg_compliance == 0.5
    assert out.compliance_ok is False


def test_stable_run_compliance_ok_when_all_runs_good(isolated):
    from AI.ai.stable_run import stable_run
    body = "Grade: B\n`agents/x.py:1` and `agents/y.py:2`"
    out = stable_run(n=3, run_fn=lambda model="x": body)
    assert all(c == 1.0 for c in out.line_compliance)
    assert out.compliance_ok is True


def test_render_consolidated_warns_low_compliance(isolated):
    from AI.ai.stable_run import StableResult, render_consolidated
    r = StableResult(
        n_runs=2, raw_reports=[],
        grades=["B", "B"], verdict="stable",
        shared_findings=[], unique_findings=[],
        crit_counts=[0, 0], jaccard=1.0,
        line_compliance=[0.0, 0.0],
    )
    text = render_consolidated(r)
    assert "Line compliance below 80%" in text


def test_render_consolidated_silent_when_compliance_ok(isolated):
    from AI.ai.stable_run import StableResult, render_consolidated
    r = StableResult(
        n_runs=2, raw_reports=[],
        grades=["B", "B"], verdict="stable",
        shared_findings=[], unique_findings=[],
        crit_counts=[0, 0], jaccard=1.0,
        line_compliance=[1.0, 1.0],
    )
    text = render_consolidated(r)
    assert "Line compliance below 80%" not in text


def test_render_consolidated_truncates_noise_list(isolated):
    """Many unique findings → list truncated to 20 + '+N more' marker."""
    from AI.ai.stable_run import StableResult, render_consolidated
    r = StableResult(
        n_runs=2, raw_reports=[],
        grades=["B", "B"], verdict="noisy",
        shared_findings=[],
        unique_findings=[f"agents/x{i}.py:1" for i in range(50)],
        crit_counts=[0, 0], jaccard=0.0,
    )
    text = render_consolidated(r)
    assert "+30 more" in text


# ── write_consolidated ──────────────────────────────────────────


def test_write_consolidated_default(isolated, tmp_path, monkeypatch):
    import AI.ai.stable_run as sr
    monkeypatch.setattr(sr, "ai_root", lambda: tmp_path)
    r = sr.StableResult(
        n_runs=2, raw_reports=[],
        grades=["B", "B"], verdict="stable",
        shared_findings=["agents/x.py:1"],
        unique_findings=[], crit_counts=[0, 0], jaccard=1.0,
    )
    out = sr.write_consolidated(r)
    assert out.exists()
    assert "stable_run_" in out.name


def test_write_consolidated_custom_dest(isolated, tmp_path):
    import AI.ai.stable_run as sr
    r = sr.StableResult(n_runs=2, raw_reports=[], grades=["B", "B"],
                         verdict="stable", shared_findings=[],
                         unique_findings=[], crit_counts=[0, 0],
                         jaccard=1.0)
    dest = tmp_path / "custom.md"
    out = sr.write_consolidated(r, dest=dest)
    assert out == dest
    assert dest.exists()


# ── CLI ──────────────────────────────────────────────────────────


def test_main_success(isolated, monkeypatch, capsys, tmp_path):
    import AI.ai.stable_run as sr
    monkeypatch.setattr(sr, "ai_root", lambda: tmp_path)
    monkeypatch.setattr(sr, "stable_run",
                        lambda n=3, model="x", save_individual=False, run_fn=None:
                        sr.StableResult(n_runs=n, raw_reports=[],
                                         grades=["B"]*n, verdict="stable",
                                         shared_findings=["agents/x.py:1"],
                                         unique_findings=[],
                                         crit_counts=[0]*n, jaccard=1.0))
    monkeypatch.setattr(sys, "argv", ["stable_run", "--n", "3"])
    rc = sr._main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "verdict: stable" in out
    assert "shared findings: 1" in out


def test_main_failure(isolated, monkeypatch, capsys):
    import AI.ai.stable_run as sr

    def boom(*args, **kwargs):
        raise RuntimeError("API down")

    monkeypatch.setattr(sr, "stable_run", boom)
    monkeypatch.setattr(sys, "argv", ["stable_run", "--n", "2"])
    rc = sr._main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERROR" in err
