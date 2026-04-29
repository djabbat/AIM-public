"""agents/profile.py — multi-tenant profile isolation.

A profile is a named bundle of:
    • memory dir         (~/.claude/profiles/<name>/memory/)
    • LangGraph state DB (~/.claude/profiles/<name>/aim_graph_state.db)
    • LanceDB index      (~/.claude/profiles/<name>/memory_index/)
    • Per-profile env    (~/.claude/profiles/<name>/profile.env)

Activation:
    export AIM_PROFILE=research        # process-wide
    aim-graph --profile research ...   # one-shot

When AIM_PROFILE is set, the canonical paths used by other modules redirect
to the profile dir via `Profile.activate()`. Modules that read paths from
config / hard-coded constants are patched at import time via this hook.

CLI:
    aim-profile list
    aim-profile create research [--copy-from default]
    aim-profile use research
    aim-profile current
    aim-profile delete research
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.profile")

PROFILES_DIR    = Path("~/.claude/profiles").expanduser()
DEFAULT_PROFILE = "default"
ACTIVE_FILE     = PROFILES_DIR / "current.txt"

# Canonical paths overridden when a profile is active. Other modules look
# at AIM_*_DIR env vars after activate(); we set them so memory_index,
# memory_versioning etc. all re-point.
ENV_OVERRIDES = {
    "AIM_MEMORY_DIR":      "memory",
    "AIM_INDEX_DIR":       "memory_index",
    "AIM_VERSIONS_DIR":    "memory_versions",
    "AIM_GRAPH_STATE_DB":  "aim_graph_state.db",
    "AIM_JOBS_DB":         "aim_jobs.db",
    "AIM_LLM_CACHE_DB":    "llm_cache.db",
}


class Profile:
    def __init__(self, name: str = DEFAULT_PROFILE) -> None:
        self.name = name
        self.dir = PROFILES_DIR / name

    # ── paths ──────────────────────────────────────────────────────────────

    @property
    def memory_dir(self) -> Path:    return self.dir / "memory"
    @property
    def index_dir(self) -> Path:     return self.dir / "memory_index"
    @property
    def versions_dir(self) -> Path:  return self.dir / "memory_versions"
    @property
    def state_db(self) -> Path:      return self.dir / "aim_graph_state.db"
    @property
    def jobs_db(self) -> Path:       return self.dir / "aim_jobs.db"
    @property
    def llm_cache_db(self) -> Path:  return self.dir / "llm_cache.db"
    @property
    def env_file(self) -> Path:      return self.dir / "profile.env"
    @property
    def metadata_file(self) -> Path: return self.dir / "metadata.json"

    # ── lifecycle ──────────────────────────────────────────────────────────

    def exists(self) -> bool:
        return self.dir.is_dir()

    def create(self, copy_from: Optional[str] = None) -> "Profile":
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ("memory", "memory_index", "memory_versions"):
            (self.dir / sub).mkdir(exist_ok=True)
        # touch user_memories
        (self.dir / "memory" / "user_memories").mkdir(exist_ok=True)

        if copy_from:
            src = Profile(copy_from)
            if not src.exists():
                raise FileNotFoundError(f"source profile not found: {copy_from}")
            # Copy memory + env + index (rebuild index for new profile is also fine)
            if src.memory_dir.exists():
                shutil.copytree(src.memory_dir, self.memory_dir, dirs_exist_ok=True)
            if src.env_file.exists():
                shutil.copy2(src.env_file, self.env_file)
            log.info(f"profile '{self.name}' cloned from '{copy_from}'")

        self.metadata_file.write_text(json.dumps({
            "name":       self.name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "copy_from":  copy_from,
        }, indent=2), encoding="utf-8")
        return self

    def delete(self) -> None:
        if self.name == DEFAULT_PROFILE:
            raise ValueError("cannot delete the default profile")
        if not self.exists():
            return
        shutil.rmtree(self.dir)
        # Reset active if it was us
        if get_active() == self.name:
            set_active(DEFAULT_PROFILE)

    # ── activation ─────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Set env vars so other modules read profile paths.

        Note: most modules cache paths at import time. Activation is most
        effective when set BEFORE import — i.e. via `AIM_PROFILE=...` in
        `~/.aim_env` or `aim-graph --profile name ...`.
        """
        if not self.exists():
            self.create()
        os.environ["AIM_PROFILE"] = self.name
        for env_var, sub in ENV_OVERRIDES.items():
            os.environ[env_var] = str(self.dir / sub)
        # Source profile env file
        if self.env_file.exists():
            for line in self.env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
        log.info(f"profile '{self.name}' activated")


# ── module-level helpers ───────────────────────────────────────────────────


def list_profiles() -> list[dict]:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for d in sorted(PROFILES_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta = {}
        mf = d / "metadata.json"
        if mf.exists():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                pass
        out.append({
            "name":      d.name,
            "active":    d.name == get_active(),
            "created":   meta.get("created_at", ""),
            "memory_md_count": sum(1 for _ in (d / "memory").glob("*.md")) if (d / "memory").exists() else 0,
        })
    return out


def get_active() -> str:
    if ACTIVE_FILE.exists():
        return ACTIVE_FILE.read_text(encoding="utf-8").strip() or DEFAULT_PROFILE
    return os.getenv("AIM_PROFILE", DEFAULT_PROFILE)


def set_active(name: str) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(name, encoding="utf-8")


def use(name: str) -> Profile:
    p = Profile(name)
    if not p.exists():
        p.create()
    set_active(name)
    p.activate()
    return p


def auto_activate_from_env() -> Optional[Profile]:
    """Call early at process start. Activates AIM_PROFILE if set."""
    name = os.getenv("AIM_PROFILE", "").strip()
    if not name or name == DEFAULT_PROFILE:
        return None
    p = Profile(name)
    if not p.exists():
        log.info(f"AIM_PROFILE='{name}' not found; creating")
        p.create()
    p.activate()
    return p


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-profile")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")
    sub.add_parser("current")

    cr = sub.add_parser("create")
    cr.add_argument("name")
    cr.add_argument("--copy-from", default=None)

    us = sub.add_parser("use")
    us.add_argument("name")

    dl = sub.add_parser("delete")
    dl.add_argument("name")
    dl.add_argument("--force", action="store_true")

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "list":
        for entry in list_profiles():
            mark = "*" if entry["active"] else " "
            print(f"  {mark} {entry['name']:<20}  files={entry['memory_md_count']}  created={entry['created']}")
    elif args.cmd == "current":
        print(get_active())
    elif args.cmd == "create":
        Profile(args.name).create(copy_from=args.copy_from)
        print(f"created: {args.name}")
    elif args.cmd == "use":
        p = use(args.name)
        print(f"active: {p.name}")
        print(f"  add to ~/.aim_env to persist:  AIM_PROFILE={p.name}")
    elif args.cmd == "delete":
        if not args.force:
            try:
                ans = input(f"delete profile '{args.name}'? [yes/NO] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans != "yes":
                print("aborted")
                return 1
        Profile(args.name).delete()
        print(f"deleted: {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
