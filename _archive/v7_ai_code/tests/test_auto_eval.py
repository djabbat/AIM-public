"""tests/test_auto_eval.py — G7 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import sys

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    monkeypatch.setenv("AIM_EVAL_DB", str(tmp_path / "eval.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_TG_DRYRUN", "1")
    import importlib
    for m in ["agents.evals", "scripts.auto_eval"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_case(setup, name, body):
    (setup / "cases" / f"{name}.yaml").write_text(body, encoding="utf-8")


# ── previous_version lookup ──────────────────────────────────────


def test_previous_version_none_when_empty(isolated):
    from scripts.auto_eval import _previous_version
    assert _previous_version(dt.date(2026, 5, 3)) is None


def test_previous_version_skips_today(isolated):
    write_case(isolated, "c", "id: c\ntask: t\nrubrics: {min_length: 0}\n")
    from agents import evals as ev
    ev.run_all(lambda t: "x", version="v-old", persist_results=True)
    ev.run_all(lambda t: "x", version="2026-05-03", persist_results=True)
    from scripts.auto_eval import _previous_version
    prev = _previous_version(dt.date(2026, 5, 3))
    assert prev == "v-old"


# ── main() flow ──────────────────────────────────────────────────


def test_main_success_no_regression(isolated, monkeypatch, capsys):
    write_case(isolated, "c", "id: c\ntask: hi\nrubrics: {min_length: 0}\n")
    # Stub llm.ask so we don't hit the network.
    import llm
    monkeypatch.setattr(llm, "ask", lambda t: "ok response")
    # Pre-seed a previous version with similar score.
    from agents import evals as ev
    ev.run_all(lambda t: "ok", version="v-prev", persist_results=True)
    # Force today's version path through scripts.auto_eval.
    from scripts import auto_eval
    monkeypatch.setattr(auto_eval, "_previous_version",
                        lambda today: "v-prev")
    rc = auto_eval.main()
    assert rc == 0


def test_main_detects_regression(isolated, monkeypatch, capsys):
    write_case(isolated, "c", """\
id: c
task: hi
rubrics:
  contains_any: ["expected"]
""")
    import llm
    monkeypatch.setattr(llm, "ask", lambda t: "wrong answer")
    from agents import evals as ev
    # Pre-seed a "good" previous version.
    ev.run_all(lambda t: "expected", version="v-prev", persist_results=True)
    from scripts import auto_eval
    monkeypatch.setattr(auto_eval, "_previous_version",
                        lambda today: "v-prev")
    rc = auto_eval.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "regression" in out.lower()


def test_main_first_run_no_previous(isolated, monkeypatch):
    write_case(isolated, "c", "id: c\ntask: t\nrubrics: {min_length: 0}\n")
    import llm
    monkeypatch.setattr(llm, "ask", lambda t: "x")
    rc = __import__("scripts.auto_eval", fromlist=["main"]).main()
    assert rc == 0


def test_main_respects_tag_filter(isolated, monkeypatch):
    write_case(isolated, "match", """\
id: match
task: x
tags: [keep]
rubrics: {min_length: 0}
""")
    write_case(isolated, "skip", """\
id: skip
task: x
rubrics: {min_length: 0}
""")
    monkeypatch.setenv("AIM_EVAL_TAG_FILTER", "keep")
    import llm
    monkeypatch.setattr(llm, "ask", lambda t: "ok")
    import importlib, scripts.auto_eval as ae
    importlib.reload(ae)
    rc = ae.main()
    assert rc == 0
    # Confirm only the tagged case was scored.
    from agents import evals as ev
    import sqlite3
    conn = sqlite3.connect(ev.db_path())
    rows = conn.execute("SELECT case_id FROM eval_runs").fetchall()
    conn.close()
    assert {r[0] for r in rows} == {"match"}
