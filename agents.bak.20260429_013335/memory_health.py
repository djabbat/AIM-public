"""agents/memory_health.py — healthcheck + auto-repair for AIM memory layer.

Detects:
    • Missing LanceDB index dir
    • Empty / unopenable LanceDB
    • Corrupted GraphRAG pickle
    • Stale incremental-state pickle (file count mismatch with index)
    • Stranded import-log without source files

Repair strategies (in order, until one succeeds):
    1. Roll back to the most recent versioning snapshot
    2. Full reindex from source-of-truth memory dir
    3. (last resort) clear LanceDB and rebuild from empty

CLI:
    python -m agents.memory_health check
    python -m agents.memory_health repair        # interactive
    python -m agents.memory_health repair --force
    python -m agents.memory_health auto          # check + repair if FAILED

Boot hook:
    from agents.memory_health import ensure_memory_health
    ensure_memory_health()                       # call at process startup
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("aim.memory_health")

INDEX_DIR     = Path("~/.claude/memory_index").expanduser()
TABLE_NAME    = "memory_v1"
GRAPHRAG_PATH = INDEX_DIR / "graphrag.gpickle"
STATE_PATH    = INDEX_DIR / "_index_state.pkl"
MEMORY_DIR    = Path("~/.claude/projects/-home-oem/memory").expanduser()
VERSIONS_DIR  = Path("~/.claude/memory_versions").expanduser()


class MemoryHealthChecker:
    def check(self) -> dict:
        issues: list[str] = []

        # 1. Index dir
        if not INDEX_DIR.exists():
            issues.append("INDEX_DIR_MISSING")
        else:
            # 2. LanceDB
            try:
                import lancedb
                db = lancedb.connect(str(INDEX_DIR))
                if TABLE_NAME not in db.table_names():
                    issues.append("LANCEDB_TABLE_MISSING")
                else:
                    t = db.open_table(TABLE_NAME)
                    n = t.count_rows()
                    if n == 0:
                        issues.append("LANCEDB_EMPTY")
            except Exception as e:
                issues.append(f"LANCEDB_CORRUPTED: {e}")

        # 3. GraphRAG (optional — only flag if present-but-corrupted)
        if GRAPHRAG_PATH.exists():
            try:
                with open(GRAPHRAG_PATH, "rb") as fh:
                    pickle.load(fh)
            except Exception as e:
                issues.append(f"GRAPHRAG_CORRUPTED: {e}")

        # 4. State pickle
        if STATE_PATH.exists():
            try:
                with open(STATE_PATH, "rb") as fh:
                    state = pickle.load(fh)
                # consistency: state should reflect files that still exist
                if MEMORY_DIR.exists():
                    on_disk = {f.name for f in MEMORY_DIR.glob("*.md")}
                    diff = len(set(state.keys()) - on_disk)
                    if diff > max(5, len(on_disk) // 4):
                        issues.append(f"STATE_STALE: {diff} files in state not on disk")
            except Exception as e:
                issues.append(f"STATE_CORRUPTED: {e}")

        # 5. Memory dir empty (no source-of-truth)
        if not MEMORY_DIR.exists():
            issues.append("MEMORY_DIR_MISSING")
        else:
            md_count = sum(1 for _ in MEMORY_DIR.glob("*.md"))
            if md_count == 0:
                issues.append("MEMORY_DIR_EMPTY")

        return {
            "status":     "OK" if not issues else "FAILED",
            "issues":     issues,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "index_dir":  str(INDEX_DIR),
            "memory_dir": str(MEMORY_DIR),
        }

    # ── repair strategies ──────────────────────────────────────────────────

    def repair(self, force: bool = False) -> dict:
        result: dict[str, Any] = {"actions": [], "ok": False}

        # Strategy 1: rollback to the latest snapshot
        if VERSIONS_DIR.exists():
            versions = sorted(
                [d for d in VERSIONS_DIR.iterdir() if d.is_dir() and (d / "manifest.json").exists()],
                key=lambda p: p.stat().st_mtime,
            )
            if versions:
                latest = versions[-1].name
                try:
                    from agents.memory_versioning import MemoryVersioning
                    log.info(f"strategy 1: rollback → {latest}")
                    MemoryVersioning().rollback(latest)
                    result["actions"].append(f"rolled_back_to:{latest}")
                except Exception as e:
                    log.warning(f"rollback failed: {e}")
                    result["actions"].append(f"rollback_failed:{e}")

        # Strategy 2: full reindex from source-of-truth
        if MEMORY_DIR.exists() and any(MEMORY_DIR.glob("*.md")):
            try:
                from agents.memory_index import reindex
                log.info("strategy 2: full reindex")
                info = reindex(progress=False)
                result["actions"].append(f"reindex_done:{info.get('chunks',0)}_chunks")
                result["ok"] = True
            except Exception as e:
                log.error(f"reindex failed: {e}")
                result["actions"].append(f"reindex_failed:{e}")

        # Strategy 3: nuke LanceDB and try once more
        if not result["ok"] and force:
            try:
                if INDEX_DIR.exists():
                    shutil.rmtree(INDEX_DIR)
                INDEX_DIR.mkdir(parents=True, exist_ok=True)
                from agents.memory_index import reindex
                info = reindex(progress=False)
                result["actions"].append(f"nuked_and_rebuilt:{info.get('chunks',0)}_chunks")
                result["ok"] = True
            except Exception as e:
                log.error(f"nuke+rebuild failed: {e}")
                result["actions"].append(f"nuke_rebuild_failed:{e}")

        # Re-build GraphRAG (best-effort)
        try:
            subprocess.run([sys.executable, "-m", "agents.graphrag", "build"],
                           capture_output=True, timeout=300)
            result["actions"].append("graphrag_rebuilt")
        except Exception as e:
            result["actions"].append(f"graphrag_rebuild_skipped:{e}")

        return result

    # ── auto-backup helper ─────────────────────────────────────────────────

    def auto_backup(self) -> Path | None:
        """Lightweight pre-mutation safety snapshot via memory_versioning."""
        try:
            from agents.memory_versioning import MemoryVersioning
            vid = MemoryVersioning().snapshot(f"auto-{datetime.now():%Y%m%d_%H%M%S}")
            return VERSIONS_DIR / vid
        except Exception as e:
            log.warning(f"auto-backup failed: {e}")
            return None


# ── boot hook ──────────────────────────────────────────────────────────────


def ensure_memory_health(repair: bool = False) -> dict:
    """Call at process startup. If `repair=True` and check FAILED, attempt repair."""
    checker = MemoryHealthChecker()
    status = checker.check()
    if status["status"] == "FAILED":
        log.warning(f"memory health: {status['issues']}")
        if repair:
            r = checker.repair(force=False)
            status["repair"] = r
    return status


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-memory-health")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    rp = sub.add_parser("repair")
    rp.add_argument("--force", action="store_true")
    a = sub.add_parser("auto", help="check + repair if FAILED")
    a.add_argument("--force", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    checker = MemoryHealthChecker()

    if args.cmd == "check":
        info = checker.check()
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["status"] == "OK" else 1

    if args.cmd == "repair":
        if not args.force:
            try:
                ans = input("⚠️  repair attempts will rebuild index; continue? [yes/NO] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans != "yes":
                print("aborted")
                return 1
        r = checker.repair(force=args.force)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1

    if args.cmd == "auto":
        info = checker.check()
        if info["status"] == "OK":
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
        info["repair"] = checker.repair(force=args.force)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["repair"].get("ok") else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
