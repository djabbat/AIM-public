"""agents/memory_versioning.py — git-like snapshots of AIM memory.

Snapshots capture every *.md under ~/.claude/projects/-home-oem/memory/
(top level + user_memories/), plus a manifest of LanceDB row counts. Enough
to restore the source-of-truth side; LanceDB is rebuildable from the .md
files via `aim-memory-index reindex`.

CLI exposed via `agents/memory_cli.py`:
    snapshot "перед миграцией"
    rollback <version_id>
    diff <ver_a> <ver_b>
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("aim.memory_versioning")

VERSIONS_DIR = Path("~/.claude/memory_versions").expanduser()
MEMORY_DIR   = Path("~/.claude/projects/-home-oem/memory").expanduser()
INDEX_DIR    = Path("~/.claude/memory_index").expanduser()


class MemoryVersioning:
    def __init__(self) -> None:
        VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.current_version = self._load_current()

    # ── Snapshot ────────────────────────────────────────────────────────────

    def snapshot(self, description: str = "") -> str:
        version_id = hashlib.md5(
            f"{datetime.now().isoformat()}:{description}".encode()
        ).hexdigest()[:8]
        target = VERSIONS_DIR / version_id
        target.mkdir()
        memory_dst = target / "memory"
        memory_dst.mkdir()

        files: list[dict[str, Any]] = []
        if MEMORY_DIR.exists():
            for f in MEMORY_DIR.rglob("*.md"):
                rel = f.relative_to(MEMORY_DIR)
                dst = memory_dst / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                files.append({
                    "rel":   str(rel),
                    "size":  f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                    "sha1":  hashlib.sha1(f.read_bytes()).hexdigest(),
                })

        index_chunks = 0
        try:
            from agents.memory_index import status
            index_chunks = status().get("index_chunks", 0)
        except Exception:
            pass

        manifest = {
            "version_id":   version_id,
            "timestamp":    datetime.now().isoformat(timespec="seconds"),
            "description":  description,
            "memory_files": files,
            "total_files":  len(files),
            "index_chunks": index_chunks,
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self.current_version = version_id
        self._save_current()
        log.info(f"snapshot {version_id} ({description}) — {len(files)} files")
        return version_id

    # ── Rollback ────────────────────────────────────────────────────────────

    def rollback(self, version_id: str) -> None:
        target = VERSIONS_DIR / version_id
        if not target.exists():
            raise FileNotFoundError(f"version not found: {version_id}")
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))

        # Backup current state into a "rollback-from-<v>" snapshot for safety
        safety = self.snapshot(f"safety-pre-rollback-from-{self.current_version}")
        log.info(f"safety snapshot: {safety}")

        # Wipe top-level *.md and user_memories/, restore from snapshot
        if MEMORY_DIR.exists():
            for f in MEMORY_DIR.rglob("*.md"):
                f.unlink()
            (MEMORY_DIR / "user_memories").mkdir(exist_ok=True)
        memory_src = target / "memory"
        for f in memory_src.rglob("*.md"):
            rel = f.relative_to(memory_src)
            dst = MEMORY_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)

        self.current_version = version_id
        self._save_current()

        # Trigger full reindex
        try:
            subprocess.run(["aim-memory-index", "reindex"], capture_output=True, timeout=600)
        except Exception as e:
            log.warning(f"reindex after rollback failed (run manually): {e}")
        log.info(f"rolled back to {version_id} ({manifest.get('description','')})")

    # ── Diff ────────────────────────────────────────────────────────────────

    def diff(self, version_a: str, version_b: str) -> dict:
        ma = self._load_manifest(version_a)
        mb = self._load_manifest(version_b)
        a = {f["rel"]: f for f in ma.get("memory_files", [])}
        b = {f["rel"]: f for f in mb.get("memory_files", [])}
        added   = [b[k] for k in b.keys() - a.keys()]
        removed = [a[k] for k in a.keys() - b.keys()]
        changed = [b[k] for k in a.keys() & b.keys() if a[k]["sha1"] != b[k]["sha1"]]
        return {
            "added":          added,
            "removed":        removed,
            "changed":        changed,
            "total_added":    len(added),
            "total_removed": len(removed),
            "total_changed": len(changed),
        }

    # ── List ───────────────────────────────────────────────────────────────

    def list_versions(self) -> list[dict]:
        out = []
        for d in sorted(VERSIONS_DIR.iterdir()):
            if not d.is_dir():
                continue
            mf = d / "manifest.json"
            if mf.exists():
                m = json.loads(mf.read_text(encoding="utf-8"))
                out.append({
                    "version_id":  m["version_id"],
                    "timestamp":   m["timestamp"],
                    "description": m["description"],
                    "files":       m["total_files"],
                })
        return out

    # ── Internals ───────────────────────────────────────────────────────────

    def _load_manifest(self, version_id: str) -> dict:
        f = VERSIONS_DIR / version_id / "manifest.json"
        if not f.exists():
            raise FileNotFoundError(f"manifest missing for {version_id}")
        return json.loads(f.read_text(encoding="utf-8"))

    def _load_current(self) -> str | None:
        f = VERSIONS_DIR / "current.txt"
        return f.read_text().strip() if f.exists() else None

    def _save_current(self) -> None:
        (VERSIONS_DIR / "current.txt").write_text(self.current_version or "", encoding="utf-8")
