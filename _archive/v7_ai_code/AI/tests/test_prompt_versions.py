"""AI/tests/test_prompt_versions.py — PV1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    fake_prompt = tmp_path / "PROMPT.md"
    fake_prompt.write_text(
        "# Self-Diagnostic v1\n\nRule 1.\nRule 2.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake_prompt))
    import importlib, sys
    if "AI.ai.prompt_versions" in sys.modules:
        importlib.reload(sys.modules["AI.ai.prompt_versions"])
    return tmp_path, fake_prompt


# ── fingerprint ─────────────────────────────────────────────────


def test_fingerprint_returns_sha_and_sizes(isolated):
    _, p = isolated
    from AI.ai.prompt_versions import fingerprint
    fp = fingerprint()
    assert len(fp.sha256) == 64
    assert fp.byte_count == p.stat().st_size
    assert fp.line_count >= 1


def test_fingerprint_changes_when_content_changes(isolated):
    _, p = isolated
    from AI.ai.prompt_versions import fingerprint
    fp1 = fingerprint()
    p.write_text(p.read_text() + "\nRule 3.\n", encoding="utf-8")
    fp2 = fingerprint()
    assert fp1.sha256 != fp2.sha256
    assert fp2.byte_count > fp1.byte_count


def test_fingerprint_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT",
                        str(tmp_path / "missing.md"))
    import importlib, sys
    if "AI.ai.prompt_versions" in sys.modules:
        importlib.reload(sys.modules["AI.ai.prompt_versions"])
    from AI.ai.prompt_versions import fingerprint
    with pytest.raises(FileNotFoundError):
        fingerprint()


# ── record_current / history ────────────────────────────────────


def test_record_current_persists(isolated):
    from AI.ai.prompt_versions import record_current, history
    fp = record_current(ts="2026-05-04T09:00:00")
    assert fp.ts == "2026-05-04T09:00:00"
    rows = history()
    assert len(rows) == 1
    assert rows[0].sha256 == fp.sha256


def test_record_current_idempotent_on_same_sha(isolated):
    from AI.ai.prompt_versions import record_current, history
    record_current(ts="2026-05-04T09:00:00")
    record_current(ts="2026-05-04T10:00:00")  # same content → ignored
    assert len(history()) == 1


def test_record_current_new_row_when_content_changes(isolated):
    _, p = isolated
    from AI.ai.prompt_versions import record_current, history
    record_current(ts="2026-05-04T09:00:00")
    p.write_text(p.read_text() + "\n# v2\n", encoding="utf-8")
    record_current(ts="2026-05-04T10:00:00")
    rows = history()
    assert len(rows) == 2
    assert rows[0].sha256 != rows[1].sha256


# ── drift_since_last ────────────────────────────────────────────


def test_drift_no_baseline(isolated):
    from AI.ai.prompt_versions import drift_since_last
    d = drift_since_last()
    assert d["have_baseline"] is False
    assert d["prompt_present"] is True


def test_drift_unchanged(isolated):
    from AI.ai.prompt_versions import record_current, drift_since_last
    record_current()
    d = drift_since_last()
    assert d["have_baseline"] is True
    assert d["changed"] is False


def test_drift_detects_change(isolated):
    _, p = isolated
    from AI.ai.prompt_versions import record_current, drift_since_last
    record_current()
    p.write_text(p.read_text() + "\nNEW\n", encoding="utf-8")
    d = drift_since_last()
    assert d["changed"] is True
    assert d["delta_bytes"] > 0
    assert d["delta_lines"] >= 1


def test_drift_handles_missing_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT",
                        str(tmp_path / "no.md"))
    import importlib, sys
    if "AI.ai.prompt_versions" in sys.modules:
        importlib.reload(sys.modules["AI.ai.prompt_versions"])
    from AI.ai.prompt_versions import drift_since_last
    d = drift_since_last()
    assert d["have_baseline"] is False
    assert d["prompt_present"] is False


# ── summary ─────────────────────────────────────────────────────


def test_summary_first_time(isolated):
    from AI.ai.prompt_versions import summary
    s = summary()
    assert "first time" in s


def test_summary_unchanged(isolated):
    from AI.ai.prompt_versions import record_current, summary
    record_current()
    s = summary()
    assert "unchanged" in s


def test_summary_detects_drift(isolated):
    _, p = isolated
    from AI.ai.prompt_versions import record_current, summary
    record_current(ts="2026-05-04T09:00:00")
    p.write_text(p.read_text() + "\nNEW LINE\n", encoding="utf-8")
    s = summary()
    assert "Δ" in s


def test_summary_missing_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT",
                        str(tmp_path / "no.md"))
    import importlib, sys
    if "AI.ai.prompt_versions" in sys.modules:
        importlib.reload(sys.modules["AI.ai.prompt_versions"])
    from AI.ai.prompt_versions import summary
    s = summary()
    assert "missing" in s


# ── concurrency ─────────────────────────────────────────────────


def test_concurrent_record_no_corruption(isolated):
    """5 threads × 10 record() — same sha → exactly 1 row."""
    import threading
    from AI.ai.prompt_versions import record_current, history

    errs: list[str] = []
    err_lock = threading.Lock()

    def worker():
        try:
            for _ in range(10):
                record_current()
        except Exception as e:
            with err_lock:
                errs.append(str(e))

    ts = [threading.Thread(target=worker) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    assert not errs
    assert len(history()) == 1
