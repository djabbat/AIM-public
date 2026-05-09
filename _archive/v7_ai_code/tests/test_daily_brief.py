"""tests/test_daily_brief.py — P4 daily stand-up (2026-05-02)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest


@pytest.fixture
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    (tmp_path / "FCLC.yaml").write_text(textwrap.dedent("""
        name: FCLC
        phase: SUBMITTED
        goals:
          - Win EIC
        milestones:
          - id: hot-thing
            deadline: 2026-05-05
            criticality: high
            blockers: [LoIs]
        stakeholders:
          - name: Alice
            role: Co-PI
            awaiting_reply: true
            expected_response_by: 2026-05-04
            last_contact: 2026-04-25
    """), encoding="utf-8")
    return tmp_path


def test_render_brief_includes_project_and_deadlines(isolated_projects, monkeypatch):
    # Disable real-memory scan so brief depends only on isolated YAML.
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    from scripts import daily_brief
    text = daily_brief.render_brief(today=dt.date(2026, 5, 2))
    assert "AIM daily brief" in text
    assert "FCLC" in text
    assert "hot-thing" in text       # from morning_brief
    assert "📅 this week" in text     # from deadline summary
    assert "Alice" in text           # awaiting reply


def test_render_brief_includes_head_when_set(isolated_projects, monkeypatch):
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    monkeypatch.setenv("AIM_BRIEF_HEAD", "🤖 Доброе утро!")
    from scripts import daily_brief
    text = daily_brief.render_brief(today=dt.date(2026, 5, 2))
    assert text.startswith("🤖 Доброе утро!")


# ── send_telegram ────────────────────────────────────────────────────


def test_send_telegram_skips_without_token(monkeypatch, isolated_projects):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AIM_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AIM_TELEGRAM_CHAT_ID", raising=False)
    from scripts import daily_brief
    assert daily_brief.send_telegram("hi") is False


def test_send_telegram_chunks_long_messages(monkeypatch):
    """A 8KB message must be split into 2-3 sendMessage calls."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("AIM_TELEGRAM_CHAT_ID", "12345")

    calls = []

    class FakeResp:
        status_code = 200
        text = "{}"

    class FakeClient:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, url, json):
            calls.append({"url": url, "len": len(json["text"])})
            return FakeResp()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", FakeClient)
    from scripts import daily_brief
    big = "x" * 8000
    assert daily_brief.send_telegram(big) is True
    assert len(calls) >= 2
    assert all(c["len"] <= 3800 for c in calls)


def test_send_telegram_propagates_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("AIM_TELEGRAM_CHAT_ID", "1")

    class FakeBadResp:
        status_code = 401
        text = "unauthorized"

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json):
            return FakeBadResp()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", FakeClient)
    from scripts import daily_brief
    assert daily_brief.send_telegram("hello") is False


# ── main() entrypoint ────────────────────────────────────────────────


def test_main_dryrun_prints_to_stdout(isolated_projects, monkeypatch, capsys):
    monkeypatch.setenv("AIM_TG_DRYRUN", "1")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    from scripts import daily_brief
    rc = daily_brief.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "AIM daily brief" in out
