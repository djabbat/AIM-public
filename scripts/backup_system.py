"""scripts/backup_system.py — full-system backup/restore for AIM.

Captures:
    • LanceDB index           (~/.claude/memory_index/)
    • LangGraph checkpoints   (~/.claude/aim_graph_state.db)
    • Memory snapshots        (~/.claude/memory_versions/)
    • Source-of-truth memory  (~/.claude/projects/-home-oem/memory/)
    • AIM SQLite DB           (~/Desktop/AIM/aim.db)
    • Agents source tree      (~/Desktop/AIM/agents/)
    • Scripts / web / export  (~/Desktop/AIM/{scripts,web,export}/)
    • llm.py / config.py / i18n.py
    • API keys                (~/.aim_env)        [optional, encrypted]

Usage:
    python -m scripts.backup_system create              # local archive
    python -m scripts.backup_system create --encrypt    # GPG-symmetric
    python -m scripts.backup_system create --auto --keep 7
    python -m scripts.backup_system list
    python -m scripts.backup_system restore <archive>

Backups land under ~/Desktop/AIM_backups/aim_backup_<ts>.tar.gz[.gpg].
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.backup")

BACKUP_PATHS = [
    "~/.claude/memory_index/",
    "~/.claude/memory_versions/",
    "~/.claude/aim_graph_state.db",
    "~/.claude/memory_import_log.json",
    "~/.claude/projects/-home-oem/memory/",
    "~/Desktop/AIM/aim.db",
    "~/Desktop/AIM/agents/",
    "~/Desktop/AIM/scripts/",
    "~/Desktop/AIM/web/",
    "~/Desktop/AIM/export/",
    "~/Desktop/AIM/experiments/",
    "~/Desktop/AIM/llm.py",
    "~/Desktop/AIM/config.py",
    "~/Desktop/AIM/i18n.py",
    "~/Desktop/AIM/db.py",
    "~/Desktop/AIM/lab_reference.py",
    "~/Desktop/AIM/CLAUDE.md",
    "~/Desktop/AIM/CONCEPT.md",
    "~/Desktop/AIM/MAP.md",
]
KEYS_PATH = Path("~/.aim_env").expanduser()

OUT_DIR = Path("~/Desktop/AIM_backups").expanduser()


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class AIMBackup:
    def __init__(self, out_dir: Path = OUT_DIR) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ── create ──────────────────────────────────────────────────────────────

    def create(
        self,
        name: Optional[str] = None,
        encrypt: bool = False,
        include_keys: bool = False,
    ) -> Path:
        name = name or f"aim_backup_{_ts()}"
        with tempfile.TemporaryDirectory(prefix="aim_bk_") as tmp:
            staging = Path(tmp) / name
            staging.mkdir()
            included: list[dict] = []

            for p in BACKUP_PATHS:
                src = Path(p).expanduser()
                if not src.exists():
                    continue
                rel = src.relative_to(Path.home()) if src.is_relative_to(Path.home()) else Path(src.name)
                dst = staging / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                included.append({
                    "path":  str(src),
                    "kind":  "dir" if src.is_dir() else "file",
                    "size":  _du(src),
                })

            if include_keys and KEYS_PATH.exists():
                shutil.copy2(KEYS_PATH, staging / ".aim_env")
                included.append({"path": str(KEYS_PATH), "kind": "file", "size": KEYS_PATH.stat().st_size})

            manifest = {
                "name":      name,
                "created":   datetime.now().isoformat(timespec="seconds"),
                "version":   "7.0",
                "host":      _hostname(),
                "encrypted": encrypt,
                "include_keys": include_keys,
                "files":     included,
                "total_size": sum(f["size"] for f in included),
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            archive = self.out_dir / f"{name}.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(staging, arcname=name)
            log.info(f"archive: {archive} ({_du(archive) // 1024} KB)")

            if encrypt:
                if not shutil.which("gpg"):
                    raise RuntimeError("gpg not found; install gnupg or omit --encrypt")
                enc_path = archive.with_suffix(archive.suffix + ".gpg")
                subprocess.run(
                    ["gpg", "--batch", "--symmetric", "--cipher-algo", "AES256",
                     "-o", str(enc_path), str(archive)],
                    check=True,
                )
                archive.unlink()
                archive = enc_path
                log.info(f"encrypted → {archive}")

            print(f"✅ backup ready: {archive}")
            return archive

    # ── prune ───────────────────────────────────────────────────────────────

    def prune(self, keep: int = 7) -> list[Path]:
        archives = sorted(
            list(self.out_dir.glob("aim_backup_*.tar.gz")) +
            list(self.out_dir.glob("aim_backup_*.tar.gz.gpg")),
            key=lambda p: p.stat().st_mtime,
        )
        to_delete = archives[:-keep] if len(archives) > keep else []
        for f in to_delete:
            f.unlink()
            log.info(f"pruned {f.name}")
        return to_delete

    # ── list ────────────────────────────────────────────────────────────────

    def list_(self) -> list[dict]:
        out = []
        for f in sorted(self.out_dir.glob("aim_backup_*.tar.gz*")):
            out.append({
                "file":   f.name,
                "size":   f.stat().st_size,
                "mtime":  datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                "encrypted": f.suffix == ".gpg",
            })
        return out

    # ── restore ─────────────────────────────────────────────────────────────

    def restore(self, archive: Path, decrypt: Optional[bool] = None,
                yes: bool = False) -> dict:
        archive = Path(archive).expanduser()
        if not archive.exists():
            raise FileNotFoundError(archive)

        if decrypt is None:
            decrypt = archive.suffix == ".gpg"

        with tempfile.TemporaryDirectory(prefix="aim_rst_") as tmp:
            tmpd = Path(tmp)
            local_archive = archive
            if decrypt:
                if not shutil.which("gpg"):
                    raise RuntimeError("gpg not found")
                dec_path = tmpd / archive.with_suffix("").name
                subprocess.run(
                    ["gpg", "--batch", "--decrypt", "-o", str(dec_path), str(archive)],
                    check=True,
                )
                local_archive = dec_path

            with tarfile.open(local_archive, "r:gz") as tar:
                tar.extractall(tmpd)
                top_level = tar.getnames()[0].split("/", 1)[0]
            staging = tmpd / top_level

            manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
            print("ℹ️  restoring backup:")
            for k in ("name", "created", "host", "total_size"):
                print(f"    {k}: {manifest.get(k)}")
            if not yes:
                ans = input("⚠️  this will OVERWRITE current state. Continue? [yes/NO] ").strip().lower()
                if ans != "yes":
                    print("aborted")
                    return {"restored": False}

            # stop services
            for cmd in (["aim-embed-daemon", "stop"], ["aim-memory-watch", "stop"]):
                subprocess.run(cmd, capture_output=True)

            # restore files
            for child in staging.iterdir():
                if child.name == "manifest.json":
                    continue
                if child.name == ".aim_env":
                    target = KEYS_PATH
                else:
                    target = Path.home() / child.relative_to(staging)
                target.parent.mkdir(parents=True, exist_ok=True)
                if child.is_dir():
                    if target.exists() and target.is_dir():
                        shutil.rmtree(target)
                    shutil.copytree(child, target)
                else:
                    shutil.copy2(child, target)

            # restart
            subprocess.run(["aim-embed-daemon", "start", "--bg"], capture_output=True)
            subprocess.run(["aim-memory-watch", "--bg"], capture_output=True)

            print("✅ restore done. Run `aim-memory-index status` to verify.")
            return {"restored": True, "manifest": manifest}


# ── helpers ────────────────────────────────────────────────────────────────


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def _du(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-backup")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--name")
    c.add_argument("--encrypt", action="store_true")
    c.add_argument("--include-keys", action="store_true",
                   help="also bundle ~/.aim_env (recommend with --encrypt)")
    c.add_argument("--auto", action="store_true",
                   help="non-interactive (no prompts)")
    c.add_argument("--keep", type=int, default=0,
                   help="prune older backups, keep N latest (0=disabled)")

    sub.add_parser("list")

    r = sub.add_parser("restore")
    r.add_argument("archive")
    r.add_argument("--yes", action="store_true")

    pr = sub.add_parser("prune")
    pr.add_argument("--keep", type=int, default=7)

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    bk = AIMBackup()

    if args.cmd == "create":
        bk.create(args.name, encrypt=args.encrypt, include_keys=args.include_keys)
        if args.keep > 0:
            bk.prune(keep=args.keep)
    elif args.cmd == "list":
        print(json.dumps(bk.list_(), ensure_ascii=False, indent=2))
    elif args.cmd == "restore":
        bk.restore(Path(args.archive), yes=args.yes)
    elif args.cmd == "prune":
        bk.prune(keep=args.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
