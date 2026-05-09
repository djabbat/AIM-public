"""AI/tests/test_dashboard.py — DB1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DISTILL_DB", str(tmp_path / "distill.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "sessions"))
    import importlib, sys
    for m in (
        "AI.ai.diagnostic_ledger",
        "AI.ai.regression_detector",
        "AI.ai.distillation_tracker",
        "AI.ai.gap_detector",
        "AI.ai.reflexion_cluster",
        "AI.ai.dashboard",
    ):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── sections() ──────────────────────────────────────────────────


def test_sections_lists_known_modules(isolated):
    from AI.ai.dashboard import sections
    out = sections()
    names = [s.name for s in out]
    assert "score" in names
    assert "safety" in names
    assert "ledger" in names
    assert "regression" in names
    assert "suppressions" in names
    assert "prompt" in names
    assert "prompt_impact" in names
    assert "compliance" in names
    assert "distillation" in names
    assert "gaps" in names
    assert "reflexion" in names


def test_sections_have_titles_and_bodies(isolated):
    from AI.ai.dashboard import sections
    for s in sections():
        assert s.title  # non-empty
        assert s.body   # non-empty


def test_sections_handle_failure_gracefully(isolated, monkeypatch):
    """If one summary raises, other sections still render."""
    from AI.ai import dashboard
    def bad_one():
        raise RuntimeError("boom")
    monkeypatch.setitem({}, "x", "y")  # noop to keep monkeypatch fresh
    monkeypatch.setattr(dashboard, "_REGISTRY", [
        ("ok", "Working", lambda: "ok body"),
        ("bad", "Broken", bad_one),
    ])
    out = dashboard.sections()
    assert out[0].ok is True
    assert out[0].body == "ok body"
    assert out[1].ok is False
    assert "boom" in out[1].error


def test_sections_coerces_non_string_output(isolated, monkeypatch):
    from AI.ai import dashboard
    monkeypatch.setattr(dashboard, "_REGISTRY", [
        ("nums", "Numbers", lambda: 42),
    ])
    out = dashboard.sections()
    assert out[0].ok is True
    assert out[0].body == "42"


# ── render() ────────────────────────────────────────────────────


def test_render_includes_section_titles(isolated):
    from AI.ai.dashboard import render
    text = render()
    assert "AIM/AI Dashboard" in text
    assert "Diagnostic ledger trend" in text
    assert "Regression check" in text


def test_render_calm_when_all_modules_empty(isolated):
    """Fresh tmp env → every summary returns 'no X yet' phrasing."""
    from AI.ai.dashboard import render
    text = render()
    # Cheap signal: at least one calm phrase from at least one module
    calm_signals = ("no diagnostic runs", "no baseline",
                     "no distillation", "no capability", "no reflexion")
    assert any(s in text for s in calm_signals)


def test_render_emits_error_inline(isolated, monkeypatch):
    from AI.ai import dashboard
    def boom():
        raise ValueError("nope")
    monkeypatch.setattr(dashboard, "_REGISTRY", [
        ("x", "Section X", boom),
    ])
    text = dashboard.render()
    assert "Section X" in text
    assert "section error" in text
    assert "nope" in text


def test_render_with_real_data_shows_metrics(isolated):
    """Plant minimal fixture data into the ledger; dashboard should
    surface counts, not the empty-state message."""
    from AI.ai.diagnostic_ledger import record
    record(model="ds-r", grade="B", n_refs=10, n_with_line=10, crit=1)
    from AI.ai.dashboard import render
    text = render()
    assert "1 runs" in text     # ledger
    assert "no diagnostic runs" not in text


# ── render_json ─────────────────────────────────────────────────


def test_render_json_returns_valid_json(isolated):
    import json
    from AI.ai.dashboard import render_json
    payload = json.loads(render_json())
    assert "sections" in payload
    assert isinstance(payload["sections"], list)
    assert payload["sections"]   # non-empty


def test_render_json_section_shape(isolated):
    import json
    from AI.ai.dashboard import render_json
    payload = json.loads(render_json())
    s = payload["sections"][0]
    for k in ("name", "title", "body", "ok", "error"):
        assert k in s


def test_render_json_records_section_failure(isolated, monkeypatch):
    import json
    from AI.ai import dashboard
    def boom():
        raise ValueError("nope")
    monkeypatch.setattr(dashboard, "_REGISTRY", [
        ("x", "X title", boom),
    ])
    payload = json.loads(dashboard.render_json())
    assert payload["sections"][0]["ok"] is False
    assert "nope" in payload["sections"][0]["error"]


# ── render_compact ──────────────────────────────────────────────


def test_render_compact_one_line_per_section(isolated):
    """Each section reduces to a single ✓/✗ + headline line."""
    from AI.ai.dashboard import render_compact, sections
    text = render_compact()
    body_lines = [l for l in text.splitlines() if l.startswith(("✓ ", "✗ "))]
    assert len(body_lines) == len(sections())


def test_render_compact_strips_emojis(isolated):
    from AI.ai import dashboard
    monkeypatch_section = ("x", "Score",
                            lambda: "💯 AIM/AI health: 80/100 (grade B)\n"
                                    "  • wiring        :  30")
    import contextlib
    with contextlib.ExitStack() as stack:
        from unittest.mock import patch
        stack.enter_context(patch.object(dashboard, "_REGISTRY",
                                            [monkeypatch_section]))
        text = dashboard.render_compact()
    # The 💯 prefix should be stripped (re.sub drops non-word leading chars).
    assert "AIM/AI health: 80/100" in text
    # And we shouldn't see the heart emoji at the start of the body
    body_lines = [l for l in text.splitlines() if l.startswith(("✓ ", "✗ "))]
    assert len(body_lines) == 1
    assert "💯" not in body_lines[0]


def test_render_compact_marks_failures(isolated, monkeypatch):
    from AI.ai import dashboard
    def boom():
        raise RuntimeError("section died")
    monkeypatch.setattr(dashboard, "_REGISTRY", [
        ("ok", "Working", lambda: "all good"),
        ("bad", "Broken", boom),
    ])
    text = dashboard.render_compact()
    assert "✓ Working:" in text
    assert "✗ Broken:" in text


def test_render_compact_short_for_telegram(isolated):
    """Total render fits comfortably under Telegram's ~4096-char limit."""
    from AI.ai.dashboard import render_compact
    text = render_compact()
    assert len(text) < 2000   # we have ~10 sections × ~120 chars max


def test_render_compact_handles_empty_body(isolated, monkeypatch):
    from AI.ai import dashboard
    monkeypatch.setattr(dashboard, "_REGISTRY", [
        ("e", "Empty", lambda: ""),
    ])
    text = dashboard.render_compact()
    assert "(empty)" in text
