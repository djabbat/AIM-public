#!/usr/bin/env python3
"""scripts/migrate_patient_memory.py — safe migration of real patient MEMORY.md (HW1, 2026-05-06).

Adds the Phase A schema sections (`## Phase`, `## Milestones`, `## Awaiting`)
to existing patient `MEMORY.md` files that lack them. Touches REAL
medical records — therefore:

  * dry-run by default (only prints what WOULD change)
  * `--apply` flag required for actual writes
  * `--patient <id>` to limit scope
  * makes a `.bak` copy before any write
  * idempotent — skips files that already have the sections

Use `aim-patient-owner brief <id>` after migration to verify the
extended schema parses correctly and is reflected in the brief.

Usage:
    # See what would change for all patients
    python -m scripts.migrate_patient_memory

    # See what would change for one patient
    python -m scripts.migrate_patient_memory --patient Feradze_Maia_1981_12_20

    # Apply for one patient (writes .bak first)
    python -m scripts.migrate_patient_memory --patient Feradze_Maia_1981_12_20 --apply

    # Apply for ALL patients (use with care)
    python -m scripts.migrate_patient_memory --apply --all
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

logging.basicConfig(level=os.environ.get("AIM_LOGLEVEL", "INFO"),
                    format="%(message)s")
log = logging.getLogger("aim.migrate_memory")


def patients_root() -> Path:
    env = os.environ.get("AIM_PATIENTS_DIR")
    if env:
        return Path(env).expanduser()
    return HERE / "Patients"


SECTIONS_TEMPLATE = """\

## Phase
INTAKE

## Milestones
_(none)_

## Awaiting
_(none)_
"""


def needs_migration(text: str) -> dict:
    """Return which sections are missing. Empty dict = no migration needed."""
    missing = {}
    for section in ("Phase", "Milestones", "Awaiting"):
        if f"## {section}" not in text:
            missing[section] = True
    return missing


def insert_sections(text: str) -> str:
    """Insert the new sections BEFORE the `## Derived` section if present,
    else BEFORE the trailing `---` line, else append at end.

    Idempotent — does nothing if Phase/Milestones/Awaiting already exist.
    """
    if not needs_migration(text):
        return text

    # Find anchor: `## Derived`
    if "## Derived" in text:
        idx = text.index("## Derived")
        return text[:idx] + SECTIONS_TEMPLATE.lstrip("\n") + "\n" + text[idx:]

    # Find anchor: trailing `---`
    if "\n---\n" in text:
        idx = text.rindex("\n---\n")
        return text[:idx] + "\n" + SECTIONS_TEMPLATE.lstrip("\n") + text[idx:]

    # Fallback: append
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + SECTIONS_TEMPLATE


def list_patients(root: Path) -> list[Path]:
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if p.name == "INBOX":
            continue
        mem = p / "MEMORY.md"
        if mem.exists():
            out.append(mem)
    return out


def process(file: Path, *, apply: bool) -> dict:
    text = file.read_text(encoding="utf-8")
    missing = needs_migration(text)
    result = {
        "patient_id": file.parent.name,
        "missing_sections": list(missing.keys()),
        "would_apply": False,
        "applied": False,
        "backup_path": None,
    }
    if not missing:
        return result

    new_text = insert_sections(text)
    result["would_apply"] = True

    if apply:
        # Make backup with timestamp
        ts = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = file.with_suffix(f".md.bak-{ts}")
        backup.write_text(text, encoding="utf-8")
        file.write_text(new_text, encoding="utf-8")
        result["applied"] = True
        result["backup_path"] = str(backup)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Add Phase A schema sections to real patient MEMORY.md files (safe by default)"
    )
    ap.add_argument("--patient", help="patient_id (folder name); omit + --all to scan everyone")
    ap.add_argument("--all", action="store_true",
                    help="when --patient is not set, process all patients")
    ap.add_argument("--apply", action="store_true",
                    help="actually write changes (default: dry-run)")
    args = ap.parse_args()

    if not args.patient and not args.all:
        log.info("Pass --patient <id> or --all. Add --apply to commit. (Default = dry-run)")
        log.info("")

    root = patients_root()
    files: list[Path]
    if args.patient:
        f = root / args.patient / "MEMORY.md"
        if not f.exists():
            log.error("not found: %s", f)
            return 2
        files = [f]
    elif args.all:
        files = list_patients(root)
    else:
        # Default: dry-run on all
        files = list_patients(root)

    if not files:
        log.info("(no patient MEMORY.md files found at %s)", root)
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    log.info("=== %s — %d patient files ===", mode, len(files))
    log.info("")

    n_changed = 0
    for f in files:
        r = process(f, apply=args.apply)
        if r["missing_sections"]:
            n_changed += 1
            mark = "✏️ " if args.apply else "👀 "
            log.info("%s%s — would add %s",
                     mark, r["patient_id"], r["missing_sections"])
            if r["applied"]:
                log.info("    backup: %s", r["backup_path"])
        else:
            log.info("✅ %s — already has all sections (skipped)",
                     r["patient_id"])

    log.info("")
    if args.apply:
        log.info("=== Applied to %d files; %d already current ===",
                 n_changed, len(files) - n_changed)
    else:
        log.info("=== Dry-run: %d files would change; %d already current ===",
                 n_changed, len(files) - n_changed)
        log.info("Re-run with --apply to commit. Each file gets a .bak-<timestamp> backup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
