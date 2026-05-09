"""agents/project_archive.py — auto-archive flow (A1, 2026-05-03).

Once a project's phase is ARCHIVED (or PUBLISHED + sat there for N
months), it shouldn't crowd the daily brief. This module:

  * archive(project): move USER/projects/<name>.yaml to
    USER/projects/_archive/<year>/<name>.yaml; prepend an audit footer.
  * unarchive(project): reverse it (find the archive copy across all
    year folders and restore).
  * archived_list(): every project sitting in the _archive tree.
  * autosweep(): scan all active projects and archive any that have been
    in PHASE in {PUBLISHED, ARCHIVED, REJECTED} for >= idle_months.

Used by:
  * `weekly_digest.py` — calls `autosweep(dry_run=True)` and includes
    the suggestion list in the digest, so the user can confirm.
  * Manual CLI: `python -m agents.project_archive archive FCLC`.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.project_archive")


def _projects_dir() -> Path:
    from agents import project_owner as po
    return po.projects_dir()


def archive_root() -> Path:
    return _projects_dir() / "_archive"


def audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "project_archive.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclasses.dataclass
class ArchiveCandidate:
    project: str
    phase: str
    last_modified: dt.date
    idle_days: int
    reason: str


def _audit(record: dict) -> None:
    record = {**record,
              "ts": dt.datetime.now().replace(microsecond=0).isoformat()}
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("archive audit write failed: %s", e)


# ── archive / unarchive ──────────────────────────────────────────


def archive(project: str, *, reason: str = "") -> Path:
    """Move <project>.yaml to _archive/<year>/<project>.yaml.

    Raises FileNotFoundError if the project doesn't exist.
    Returns the new path.
    """
    src = _projects_dir() / f"{project}.yaml"
    if not src.exists():
        raise FileNotFoundError(f"no project at {src}")
    year = dt.date.today().year
    dest_dir = archive_root() / str(year)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{project}.yaml"
    if dest.exists():
        # Don't clobber a previous archive of the same name. Stamp it.
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = dest_dir / f"{project}.{stamp}.yaml"
    shutil.move(str(src), str(dest))
    _audit({"event": "archive", "project": project, "to": str(dest),
            "reason": reason})
    return dest


def unarchive(project: str) -> Path:
    """Find the most-recent archived copy of `project` and move it back."""
    if not archive_root().exists():
        raise FileNotFoundError("archive root does not exist")
    candidates: list[Path] = []
    for year_dir in archive_root().iterdir():
        if not year_dir.is_dir():
            continue
        for f in year_dir.glob(f"{project}.yaml"):
            candidates.append(f)
        for f in year_dir.glob(f"{project}.*.yaml"):
            candidates.append(f)
    if not candidates:
        raise FileNotFoundError(f"no archive of {project!r}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    src = candidates[0]
    dest = _projects_dir() / f"{project}.yaml"
    if dest.exists():
        raise FileExistsError(f"active {project!r} already exists")
    shutil.move(str(src), str(dest))
    _audit({"event": "unarchive", "project": project, "from": str(src)})
    return dest


def archived_list() -> list[dict]:
    """Every YAML under _archive/, with year + path + project name."""
    out: list[dict] = []
    root = archive_root()
    if not root.exists():
        return out
    for year_dir in sorted(root.iterdir()):
        if not year_dir.is_dir():
            continue
        for p in sorted(year_dir.glob("*.yaml")):
            stem = p.stem.split(".", 1)[0]
            out.append({"project": stem, "year": year_dir.name,
                        "path": str(p)})
    return out


# ── autosweep ────────────────────────────────────────────────────


_TERMINAL_PHASES = {"PUBLISHED", "ARCHIVED", "REJECTED"}


def candidates(idle_months: int = 6,
               today: Optional[dt.date] = None) -> list[ArchiveCandidate]:
    """Active projects whose phase is terminal AND whose YAML hasn't been
    touched for `idle_months` are surfaced as archive candidates."""
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=int(idle_months * 30))
    from agents import project_owner as po
    out: list[ArchiveCandidate] = []
    for name in po.list_projects():
        try:
            state = po.load(name)
        except (FileNotFoundError, ValueError):
            continue
        phase = state.phase.upper()
        if phase not in _TERMINAL_PHASES:
            continue
        path = po.projects_dir() / f"{name}.yaml"
        try:
            mtime = dt.date.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime > cutoff:
            continue
        out.append(ArchiveCandidate(
            project=name, phase=phase,
            last_modified=mtime,
            idle_days=(today - mtime).days,
            reason=f"phase={phase}, idle {idle_months}m+",
        ))
    return out


def autosweep(idle_months: int = 6, *, dry_run: bool = True,
              today: Optional[dt.date] = None) -> list[ArchiveCandidate]:
    cands = candidates(idle_months=idle_months, today=today)
    if dry_run:
        return cands
    for c in cands:
        try:
            archive(c.project, reason=c.reason)
        except FileNotFoundError:
            continue
    return cands


def history(limit: int = 50) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Project archive manager")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("archive")
    g.add_argument("project")
    g.add_argument("--reason", default="")
    g = sub.add_parser("unarchive")
    g.add_argument("project")
    sub.add_parser("list", help="list archived projects")
    g = sub.add_parser("sweep", help="show archive candidates")
    g.add_argument("--idle-months", type=int, default=6)
    g.add_argument("--apply", action="store_true",
                    help="actually archive (default = dry-run)")
    args = ap.parse_args()

    if args.cmd == "archive":
        path = archive(args.project, reason=args.reason)
        print(f"archived → {path}")
    elif args.cmd == "unarchive":
        path = unarchive(args.project)
        print(f"restored → {path}")
    elif args.cmd == "list":
        for row in archived_list():
            print(json.dumps(row, ensure_ascii=False))
    elif args.cmd == "sweep":
        cands = autosweep(idle_months=args.idle_months,
                           dry_run=not args.apply)
        for c in cands:
            print(f"  {c.project}  phase={c.phase}  "
                  f"idle={c.idle_days}d  ({c.reason})")
        if not cands:
            print("(no candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
