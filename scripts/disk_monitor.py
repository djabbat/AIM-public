"""scripts/disk_monitor.py — disk-usage watchdog for AIM data dirs.

Two modes:
    check     — return JSON status (status: ok/warning/critical)
    auto      — perform graduated cleanup based on free space:
                  warning  → suggest cleanup commands
                  critical → emergency: prune memory_versions, rotate big logs

Cron every 6 hours:
    0 */6 * * * /home/oem/.local/bin/aim-disk-monitor auto
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger("aim.disk_monitor")

WATCH_DIRS = [
    Path("~/.claude/memory_index").expanduser(),
    Path("~/.claude/memory_versions").expanduser(),
    Path("~/Desktop/AIM_backups").expanduser(),
    Path("~/.claude").expanduser(),
    Path("~/Desktop/AIM").expanduser(),
]


def _du_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class DiskMonitor:
    THRESHOLD_GB = 10
    CRITICAL_GB = 5

    def check(self) -> dict:
        usage = shutil.disk_usage(str(Path.home()))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = round((usage.total - usage.free) / usage.total * 100, 1)

        status = "ok"
        if free_gb < self.CRITICAL_GB:
            status = "critical"
        elif free_gb < self.THRESHOLD_GB:
            status = "warning"

        per_dir = []
        for d in WATCH_DIRS:
            per_dir.append({
                "path":  str(d),
                "size":  _du_bytes(d),
                "human": _human(_du_bytes(d)),
            })
        per_dir.sort(key=lambda x: -x["size"])

        return {
            "status":    status,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "free_gb":   round(free_gb, 1),
            "total_gb":  round(total_gb, 1),
            "used_pct":  used_pct,
            "watched":   per_dir,
        }

    # ── cleanup actions ─────────────────────────────────────────────────────

    def emergency_cleanup(self, keep_versions: int = 3) -> list[str]:
        actions: list[str] = []

        # 1. Prune memory_versions
        versions_dir = Path("~/.claude/memory_versions").expanduser()
        if versions_dir.exists():
            versions = sorted(
                [d for d in versions_dir.iterdir() if d.is_dir()],
                key=lambda p: p.stat().st_mtime,
            )
            for old in versions[:-keep_versions] if len(versions) > keep_versions else []:
                size = _du_bytes(old)
                shutil.rmtree(old)
                actions.append(f"removed memory_versions/{old.name} ({_human(size)})")

        # 2. Truncate large embed.log
        log_path = Path("~/.claude/embed.log").expanduser()
        if log_path.exists() and log_path.stat().st_size > 100 * 1024 * 1024:
            size = log_path.stat().st_size
            log_path.write_text("")
            actions.append(f"truncated embed.log ({_human(size)})")

        # 3. Rotate old AIM_backups (keep 5)
        backups_dir = Path("~/Desktop/AIM_backups").expanduser()
        if backups_dir.exists():
            archives = sorted(
                list(backups_dir.glob("aim_backup_*.tar.gz*")),
                key=lambda p: p.stat().st_mtime,
            )
            for old in archives[:-5] if len(archives) > 5 else []:
                size = old.stat().st_size
                old.unlink()
                actions.append(f"removed {old.name} ({_human(size)})")

        # 4. SQLite GC
        try:
            subprocess.run(["aim-graph-gc", "3"], capture_output=True, timeout=120)
            actions.append("ran aim-graph-gc 3")
        except Exception as e:
            actions.append(f"aim-graph-gc failed: {e}")

        return actions

    def suggest_cleanup(self) -> list[str]:
        return [
            "aim-memory dedup --apply         # merge near-duplicate memories",
            "aim-graph-gc 3                    # prune old LangGraph checkpoints",
            "aim-backup prune --keep 3         # keep only 3 latest backups",
            "find ~/.claude -name '*.log' -size +50M -delete",
        ]


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-disk-monitor")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    a = sub.add_parser("auto",
                       help="check + run cleanup actions when warning/critical")
    a.add_argument("--keep-versions", type=int, default=3)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    mon = DiskMonitor()
    info = mon.check()

    if args.cmd == "check":
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    # auto
    if info["status"] == "ok":
        print(json.dumps({**info, "actions": []}, ensure_ascii=False, indent=2))
        return 0
    if info["status"] == "warning":
        info["suggestions"] = mon.suggest_cleanup()
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    # critical
    info["actions_taken"] = mon.emergency_cleanup(keep_versions=args.keep_versions)
    info["after"] = mon.check()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
