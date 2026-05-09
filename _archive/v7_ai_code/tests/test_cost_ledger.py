"""tests/test_cost_ledger.py — L1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Build a tiny `calls` table the cost_ledger queries reach into."""
    db_path = tmp_path / "cost.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            cost_usd REAL NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setenv("AIM_HOME", str(tmp_path))
    monkeypatch.setenv("AIM_BUDGET_DAILY_USD", "5")
    monkeypatch.setenv("AIM_BUDGET_WEEKLY_USD", "25")
    monkeypatch.setenv("AIM_BUDGET_MONTHLY_USD", "80")
    import importlib
    import agents.cost_ledger as cl
    importlib.reload(cl)
    # Replace _db_path so it always returns our tmp file.
    monkeypatch.setattr(cl, "_db_path", lambda: db_path)
    return cl, db_path


def insert(db_path, *rows):
    conn = sqlite3.connect(db_path)
    for ts, provider, cost in rows:
        conn.execute(
            "INSERT INTO calls(ts, provider, model, input_tokens, output_tokens, cost_usd)"
            " VALUES (?, ?, 'm', 0, 0, ?)",
            (ts, provider, cost))
    conn.commit()
    conn.close()


# ── budgets ──────────────────────────────────────────────────────


def test_budget_defaults(isolated, monkeypatch):
    cl, _ = isolated
    monkeypatch.delenv("AIM_BUDGET_DAILY_USD", raising=False)
    assert cl.daily_budget() == 5.0
    monkeypatch.setenv("AIM_BUDGET_DAILY_USD", "12.5")
    assert cl.daily_budget() == 12.5


def test_invalid_budget_falls_back(isolated, monkeypatch):
    cl, _ = isolated
    monkeypatch.setenv("AIM_BUDGET_DAILY_USD", "not-a-number")
    assert cl.daily_budget() == 5.0


# ── window aggregation ──────────────────────────────────────────


def test_daily_cost(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db,
           (f"{today}T08:00:00", "openai", 0.50),
           (f"{today}T14:00:00", "anthropic", 1.20),
           ("2026-05-02T10:00:00", "openai", 9.99),  # yesterday
           )
    assert cl.daily_cost(today=today) == pytest.approx(1.70)


def test_weekly_cost(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db,
           ("2026-05-01T00:00:00", "x", 1.0),
           ("2026-04-28T00:00:00", "x", 2.0),
           ("2026-04-26T00:00:00", "x", 3.0),  # 7 days ago — included
           ("2026-04-25T00:00:00", "x", 9.0),  # 8 days ago — excluded
           )
    assert cl.weekly_cost(today=today) == pytest.approx(6.0)


def test_monthly_cost(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db,
           ("2026-04-15T00:00:00", "x", 5.0),
           ("2026-04-04T00:00:00", "x", 5.0),  # 29 days ago — included
           ("2026-04-02T00:00:00", "x", 9.0),  # 31 days ago — excluded
           )
    assert cl.monthly_cost(today=today) == pytest.approx(10.0)


def test_zero_when_no_data(isolated):
    cl, _ = isolated
    assert cl.daily_cost() == 0.0
    assert cl.weekly_cost() == 0.0


# ── breakdown ────────────────────────────────────────────────────


def test_breakdown_per_provider(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db,
           (f"{today}T08:00:00", "openai", 1.5),
           (f"{today}T09:00:00", "openai", 0.5),
           (f"{today}T10:00:00", "anthropic", 2.0),
           )
    bk = cl.breakdown("daily", today=today)
    assert bk[0] == ("anthropic", 2.0)
    assert bk[1] == ("openai", 2.0)


def test_breakdown_unknown_window(isolated):
    cl, _ = isolated
    with pytest.raises(ValueError):
        cl.breakdown("yearly")


# ── budget check ─────────────────────────────────────────────────


def test_check_budgets_ok(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db, (f"{today}T08:00:00", "x", 1.0))   # 1/5 = 20%
    checks = cl.check_budgets(today=today)
    by_window = {c.window: c.severity for c in checks}
    assert by_window["daily"] == "ok"


def test_check_budgets_warn(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db, (f"{today}T08:00:00", "x", 4.0))   # 4/5 = 80%
    checks = cl.check_budgets(today=today)
    daily = next(c for c in checks if c.window == "daily")
    assert daily.severity == "warn"


def test_check_budgets_breach(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db, (f"{today}T08:00:00", "x", 6.0))   # 6/5 = 120%
    daily = next(c for c in cl.check_budgets(today=today) if c.window == "daily")
    assert daily.severity == "breach"


# ── alert_breaches ───────────────────────────────────────────────


def test_alert_breaches_dispatches(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db, (f"{today}T08:00:00", "x", 6.0))
    sent = []
    cl.alert_breaches(today=today, dispatch=lambda c: sent.append(c))
    assert any(c.window == "daily" for c in sent)


def test_alert_breaches_quiet_when_clean(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db, (f"{today}T08:00:00", "x", 0.5))
    sent = []
    cl.alert_breaches(today=today, dispatch=lambda c: sent.append(c))
    assert sent == []


# ── summary ──────────────────────────────────────────────────────


def test_summary_includes_breakdown(isolated):
    cl, db = isolated
    today = dt.date(2026, 5, 3)
    insert(db,
           (f"{today}T08:00:00", "deepseek", 0.5),
           (f"{today}T09:00:00", "anthropic", 0.3),
           )
    s = cl.summary(today=today)
    assert "Cost ledger" in s
    assert "deepseek" in s and "anthropic" in s
