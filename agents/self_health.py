"""agents/self_health.py — full-stack self-diagnostic for AIM.

Probes every runtime component and returns a structured health report.
Wired into /healthz endpoint via web/api.py:

    GET /healthz                       → existing JSON snapshot
    GET /healthz/full                  → this report (verbose)

CLI:
    aim-self-health check              → prints JSON report; exits 1 if unhealthy
    aim-self-health check --quick      → skip slow probes (lancedb, web request)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("aim.self_health")


# ── path helpers (respect profile-redirect env vars) ────────────────────────


def _path(env_var: str, default: str) -> Path:
    return Path(os.getenv(env_var, default)).expanduser()


SOCK_PATH       = Path("~/.claude/embed.sock").expanduser()
WATCHER_PID     = Path("~/.claude/memory_watch.pid").expanduser()
GRAPH_DB        = _path("AIM_GRAPH_STATE_DB", "~/.claude/aim_graph_state.db")
JOBS_DB         = _path("AIM_JOBS_DB",        "~/.claude/aim_jobs.db")
LLM_CACHE_DB    = _path("AIM_LLM_CACHE_DB",   "~/.claude/llm_cache.db")
COST_DB         = Path("~/.claude/cost_monitor.db").expanduser()
INDEX_DIR       = _path("AIM_INDEX_DIR",      "~/.claude/memory_index")
ENV_FILE        = Path("~/.aim_env").expanduser()


# ── individual probes ──────────────────────────────────────────────────────


class SelfHealthChecker:
    def __init__(self, quick: bool = False) -> None:
        self.quick = quick

    def check_all(self) -> dict[str, Any]:
        results: dict[str, Any] = {
            "timestamp":      datetime.now().isoformat(timespec="seconds"),
            "overall_status": "healthy",
            "components":     {},
        }
        for name, fn in [
            ("embed_daemon",   self._embed_daemon),
            ("memory_watcher", self._memory_watcher),
            ("checkpoint_db",  self._checkpoint_db),
            ("memory_index",   self._memory_index),
            ("llm_cache",      self._llm_cache),
            ("cost_monitor",   self._cost_monitor),
            ("job_queue",      self._job_queue),
            ("web_server",     self._web_server),
            ("disk",           self._disk),
            ("api_keys",       self._api_keys),
            ("memory_dir",     self._memory_dir),
            ("graphrag",       self._graphrag),
            ("background_pi",  self._pi_agent),
        ]:
            try:
                results["components"][name] = fn()
            except Exception as e:
                results["components"][name] = {"status": "error", "error": str(e)}

        bad = [k for k, v in results["components"].items()
               if v.get("status") in ("unhealthy", "critical", "error")]
        warn = [k for k, v in results["components"].items()
                if v.get("status") in ("warning", "degraded")]
        results["unhealthy_components"] = bad
        results["degraded_components"]  = warn
        if bad:
            results["overall_status"] = "unhealthy"
        elif warn:
            results["overall_status"] = "degraded"
        return results

    # ──────────────────────────────────────────────────────────────────────

    def _embed_daemon(self) -> dict:
        if not SOCK_PATH.exists():
            return {"status": "unhealthy", "error": "socket missing"}
        try:
            from agents.embed_daemon import daemon_status
            info = daemon_status()
            running = info.get("running") and info.get("responded")
            return {
                "status": "healthy" if running else "unhealthy",
                "pid":    info.get("pid"),
                "model":  info.get("model"),
                "reason": info.get("reason"),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _memory_watcher(self) -> dict:
        if not WATCHER_PID.exists():
            return {"status": "stopped", "message": "no pid file"}
        try:
            pid = int(WATCHER_PID.read_text().strip())
            os.kill(pid, 0)
            return {"status": "healthy", "pid": pid}
        except (ValueError, ProcessLookupError, PermissionError, OSError) as e:
            return {"status": "unhealthy", "error": str(e)}

    def _checkpoint_db(self) -> dict:
        if not GRAPH_DB.exists():
            return {"status": "stopped", "message": "no checkpoints yet"}
        try:
            conn = sqlite3.connect(str(GRAPH_DB))
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            conn.close()
            return {
                "status":   "healthy",
                "tables":   [t[0] for t in tables],
                "size_mb":  round(GRAPH_DB.stat().st_size / 1_048_576, 2),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _memory_index(self) -> dict:
        if not INDEX_DIR.exists():
            return {"status": "unhealthy", "error": "index dir missing"}
        if self.quick:
            return {"status": "healthy", "size_mb": round(_du(INDEX_DIR) / 1_048_576, 2)}
        try:
            import lancedb
            db = lancedb.connect(str(INDEX_DIR))
            tables = db.table_names() if hasattr(db, "table_names") else list(db.list_tables())
            chunks = 0
            if "memory_v1" in tables:
                t = db.open_table("memory_v1")
                chunks = t.count_rows()
            return {
                "status": "healthy",
                "tables": list(tables),
                "chunks": chunks,
                "size_mb": round(_du(INDEX_DIR) / 1_048_576, 2),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _llm_cache(self) -> dict:
        if not LLM_CACHE_DB.exists():
            return {"status": "stopped", "message": "cache not initialised"}
        try:
            conn = sqlite3.connect(str(LLM_CACHE_DB))
            n = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            hits = conn.execute("SELECT COALESCE(SUM(hits),0) FROM cache").fetchone()[0]
            conn.close()
            return {"status": "healthy", "entries": n, "total_hits": hits}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    def _cost_monitor(self) -> dict:
        if not COST_DB.exists():
            return {"status": "stopped", "message": "no costs recorded yet"}
        try:
            from agents.cost_monitor import stats as _stats
            s = _stats()
            level = "healthy"
            if s["daily_cost"]   > s["daily_limit"]:   level = "critical"
            elif s["daily_cost"] > s["daily_limit"] * 0.8: level = "warning"
            return {"status": level, **{k: s[k] for k in
                    ("daily_cost","daily_limit","monthly_cost","monthly_limit",
                     "remaining_daily","remaining_monthly","total_calls")}}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    def _job_queue(self) -> dict:
        if not JOBS_DB.exists():
            return {"status": "stopped", "message": "no jobs yet"}
        try:
            conn = sqlite3.connect(str(JOBS_DB))
            running = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
            failed_24h = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='failed' AND completed_at >= datetime('now','-1 day')"
            ).fetchone()[0]
            conn.close()
            return {"status": "healthy", "running": running,
                    "failed_last_24h": failed_24h}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    def _web_server(self) -> dict:
        port = int(os.getenv("AIM_WEB_PORT", "8080"))
        if self.quick:
            return {"status": "skipped"}
        try:
            import httpx
            r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2)
            if r.status_code == 200:
                return {"status": "healthy", "port": port}
            return {"status": "degraded", "http_status": r.status_code}
        except httpx.ConnectError:
            return {"status": "stopped", "message": "web server not running"}
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    def _disk(self) -> dict:
        usage = shutil.disk_usage(str(Path.home()))
        free_gb = usage.free / 1024**3
        if free_gb < 5:
            level = "critical"
        elif free_gb < 10:
            level = "warning"
        else:
            level = "healthy"
        return {"status": level, "free_gb": round(free_gb, 1),
                "used_pct": round((usage.total - usage.free) / usage.total * 100, 1)}

    def _api_keys(self) -> dict:
        if not ENV_FILE.exists():
            return {"status": "critical", "error": ".aim_env missing"}
        text = ENV_FILE.read_text(encoding="utf-8")
        ds = "DEEPSEEK_API_KEY=" in text
        groq = "GROQ_API_KEY=" in text
        if not ds:
            return {"status": "critical", "error": "DEEPSEEK_API_KEY missing"}
        return {"status": "healthy", "deepseek": ds, "groq": groq}

    def _memory_dir(self) -> dict:
        md = _path("AIM_MEMORY_DIR", "~/.claude/projects/-home-oem/memory")
        if not md.exists():
            return {"status": "unhealthy", "error": "memory dir missing"}
        files = sum(1 for _ in md.glob("*.md"))
        size_kb = round(_du(md) / 1024, 1)
        return {"status": "healthy", "files": files, "size_kb": size_kb}

    def _graphrag(self) -> dict:
        gp = INDEX_DIR / "graphrag.gpickle"
        if not gp.exists():
            return {"status": "stopped", "message": "not built (run: python -m agents.graphrag build)"}
        try:
            import pickle
            with open(gp, "rb") as fh:
                g = pickle.load(fh)
            return {"status": "healthy",
                    "nodes": g.number_of_nodes(),
                    "edges": g.number_of_edges()}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _pi_agent(self) -> dict:
        ph = Path("~/.claude/pi_history.json").expanduser()
        enabled = os.getenv("AIM_PI_ENABLED", "").lower() in ("1", "true", "yes")
        return {
            "status":  "healthy" if enabled else "stopped",
            "enabled": enabled,
            "history_size": ph.stat().st_size if ph.exists() else 0,
        }


def _du(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-self-health")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--quick", action="store_true",
                   help="skip slow probes (lancedb / web request)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    info = SelfHealthChecker(quick=args.quick).check_all()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if info["overall_status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
