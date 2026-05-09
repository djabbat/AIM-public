"""agents/serve_daemon.py — long-running orchestrator (G10, 2026-05-03).

Where systemd timers are tidy but coarse, `aim serve` is a single
long-running process that:

  * runs internal "ticks" at configured intervals (default: minute precision)
  * fires daily_brief at 09:00, weekly_digest on Sunday 09:00,
    auto_eval at 03:30, escalation evaluation every 30 min
  * exposes a tiny Unix socket (default `~/.cache/aim/serve.sock`)
    that returns the same JSON `aim do` does, so a Telegram bot can
    forward messages without spawning Python every time

Lifecycle:
    aim serve --foreground      → runs in current shell
    aim serve --once            → one tick, then exits (handy for tests)

Safety:
  * cooperative SIGINT shutdown
  * no shelling out — every action goes through existing modules
  * dedup window keys cron events so a restart doesn't double-fire
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("aim.serve")


def state_dir() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "serve"
    p.mkdir(parents=True, exist_ok=True)
    return p


def socket_path() -> Path:
    return state_dir() / "serve.sock"


def state_path() -> Path:
    return state_dir() / "last_runs.json"


# ── tick scheduling ──────────────────────────────────────────────


@dataclasses.dataclass
class Job:
    name: str
    fn: Callable[[], None]
    schedule: str            # "daily@HH:MM" | "weekly@DOW@HH:MM" | "every@Nm"
    description: str = ""


def _parse_schedule(spec: str) -> dict:
    s = spec.strip()
    if s.startswith("daily@"):
        hh, mm = s.removeprefix("daily@").split(":")
        return {"kind": "daily", "h": int(hh), "m": int(mm)}
    if s.startswith("weekly@"):
        rest = s.removeprefix("weekly@")
        dow_s, hhmm = rest.split("@")
        hh, mm = hhmm.split(":")
        return {"kind": "weekly", "dow": _dow_to_int(dow_s),
                "h": int(hh), "m": int(mm)}
    if s.startswith("every@"):
        rest = s.removeprefix("every@")
        if rest.endswith("m"):
            return {"kind": "every", "minutes": int(rest[:-1])}
    raise ValueError(f"unrecognised schedule: {spec!r}")


def _dow_to_int(name: str) -> int:
    days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
            "fri": 4, "sat": 5, "sun": 6}
    return days[name.lower()[:3]]


def _due(spec: dict, last_run: Optional[dt.datetime],
         now: dt.datetime) -> bool:
    if spec["kind"] == "every":
        if last_run is None:
            return True
        return (now - last_run).total_seconds() >= spec["minutes"] * 60
    if spec["kind"] == "daily":
        target = now.replace(hour=spec["h"], minute=spec["m"],
                              second=0, microsecond=0)
        if now < target:
            return False
        if last_run is None:
            return True
        return last_run < target
    if spec["kind"] == "weekly":
        if now.weekday() != spec["dow"]:
            return False
        target = now.replace(hour=spec["h"], minute=spec["m"],
                              second=0, microsecond=0)
        if now < target:
            return False
        if last_run is None:
            return True
        return last_run < target
    return False


# ── persistence ──────────────────────────────────────────────────


def _load_state() -> dict:
    p = state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    p = state_path()
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError as e:
        log.warning("state save failed: %s", e)


# ── jobs registry ────────────────────────────────────────────────


def _job_daily_brief() -> None:
    from scripts.daily_brief import main as run
    run()


def _job_weekly_digest() -> None:
    from scripts.weekly_digest import main as run
    run()


def _job_auto_eval() -> None:
    from scripts.auto_eval import main as run
    run()


def _job_escalate() -> None:
    from agents.escalation_engine import evaluate_all, telegram_dispatch
    evaluate_all(dispatch=telegram_dispatch)


def _job_kpi_sync() -> None:
    from agents.kpi_auto_updater import sync
    sync()


def _job_memory_scan() -> None:
    """Stash the latest memory hygiene findings count for healthz."""
    from agents.memory_monitor import scan
    rep = scan()
    state = _load_state()
    state.setdefault("metrics", {})["memory_findings"] = len(rep.findings)
    _save_state(state)


def default_jobs() -> list[Job]:
    return [
        Job("daily_brief",   _job_daily_brief,   "daily@09:00",
            "morning project + deadline brief"),
        Job("weekly_digest", _job_weekly_digest, "weekly@sun@09:00",
            "weekly self-improvement digest"),
        Job("auto_eval",     _job_auto_eval,     "daily@03:30",
            "nightly eval + regression detection"),
        Job("escalate",      _job_escalate,      "every@30m",
            "fire matching escalation_rules"),
        Job("kpi_sync",      _job_kpi_sync,      "daily@04:00",
            "push observed signals into KPI history"),
        Job("memory_scan",   _job_memory_scan,   "daily@04:30",
            "memory hygiene snapshot for healthz"),
    ]


# ── tick loop ────────────────────────────────────────────────────


def tick(jobs: list[Job], now: Optional[dt.datetime] = None) -> list[str]:
    """Run all jobs whose schedule fires at `now`. Returns names of jobs run."""
    now = now or dt.datetime.now()
    state = _load_state()
    last = state.setdefault("last_run", {})
    fired: list[str] = []

    for job in jobs:
        try:
            spec = _parse_schedule(job.schedule)
        except Exception as e:
            log.warning("bad schedule for %s: %s", job.name, e)
            continue
        last_run = None
        last_ts = last.get(job.name)
        if last_ts:
            try:
                last_run = dt.datetime.fromisoformat(last_ts)
            except ValueError:
                last_run = None
        if not _due(spec, last_run, now):
            continue
        try:
            log.info("running job %s", job.name)
            job.fn()
        except Exception as e:
            log.exception("job %s failed: %s", job.name, e)
            continue
        last[job.name] = now.replace(microsecond=0).isoformat()
        fired.append(job.name)

    if fired:
        state["last_run"] = last
        _save_state(state)
    return fired


# ── unix socket server ──────────────────────────────────────────


def _handle_socket_request(req: str) -> str:
    """Serve a one-line JSON request `{cmd: "do", args: ["..."]}`."""
    try:
        msg = json.loads(req)
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid JSON"})
    cmd = msg.get("cmd")
    args = msg.get("args") or []
    if cmd == "do":
        from agents.quick_action import handle
        out = handle(" ".join(args))
        return json.dumps(out, ensure_ascii=False)
    if cmd == "tick":
        fired = tick(default_jobs())
        return json.dumps({"fired": fired})
    if cmd == "ping":
        return json.dumps({"pong": True})
    return json.dumps({"error": f"unknown cmd {cmd!r}"})


def serve_socket(stop_event: threading.Event,
                  jobs: Optional[list[Job]] = None) -> None:
    sp = socket_path()
    with contextlib.suppress(FileNotFoundError):
        sp.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sp))
    srv.listen(8)
    srv.settimeout(0.5)
    log.info("serve socket at %s", sp)
    while not stop_event.is_set():
        try:
            conn, _addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        with conn:
            try:
                data = conn.recv(8192).decode("utf-8", errors="replace")
                resp = _handle_socket_request(data.strip())
                conn.sendall((resp + "\n").encode("utf-8"))
            except Exception as e:
                log.warning("socket request failed: %s", e)
    srv.close()
    with contextlib.suppress(FileNotFoundError):
        sp.unlink()


# ── main loop ────────────────────────────────────────────────────


def run_forever(jobs: Optional[list[Job]] = None,
                tick_seconds: int = 30) -> None:
    jobs = jobs or default_jobs()
    stop_event = threading.Event()

    def _shutdown(*_):
        log.info("shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            pass

    sock_thread = threading.Thread(target=serve_socket,
                                    args=(stop_event, jobs),
                                    daemon=True, name="aim-serve-sock")
    sock_thread.start()

    while not stop_event.is_set():
        try:
            tick(jobs)
        except Exception as e:
            log.exception("tick failed: %s", e)
        for _ in range(tick_seconds * 2):
            if stop_event.is_set():
                break
            time.sleep(0.5)
    sock_thread.join(timeout=2.0)


def run_once() -> list[str]:
    return tick(default_jobs())


# ── CLI entrypoint (for `python -m agents.serve_daemon`) ───────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AIM long-running orchestrator")
    ap.add_argument("--once", action="store_true",
                    help="run one tick and exit (for tests)")
    ap.add_argument("--tick", type=int, default=30,
                    help="tick interval in seconds (default 30)")
    args = ap.parse_args()

    logging.basicConfig(
        level=os.environ.get("AIM_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.once:
        fired = run_once()
        print(json.dumps({"fired": fired}))
        return 0
    run_forever(tick_seconds=args.tick)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
