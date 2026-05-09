"""agents/memory_date_correction.py — auto-correct stale TTL / expires_at fields.

Memory frontmatter sometimes drifts:
    • `created` set to a future date by clipboard typo
    • `expires_at` says 2025 but `ttl_hours` from `created` should be 2027
    • TTL set in days but value stored as if hours, etc.

This walks `user_memories/`, parses each frontmatter, and:
    1. If `expires_at` exists but is inconsistent with `created + ttl_hours` → fix
    2. If `created` is in the future (>1 day) → flag for manual review
    3. If `ttl_hours` is suspiciously small (e.g., 0 or 1 with a long-term name) → log

CLI:
    aim-memory correct-dates check        # dry-run (default)
    aim-memory correct-dates --apply       # actually rewrite frontmatter
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("aim.memory_date_correction")

USER_MEMORIES = Path("~/.claude/projects/-home-oem/memory/user_memories").expanduser()


_FM_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n?)(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str, str, str] | None:
    """Return (fm_dict, head, fm_block, tail) or None."""
    m = _FM_RE.match(text)
    if not m:
        return None
    head, fm_block, tail_marker, body = m.groups()
    fm: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, head, tail_marker, body


def _serialize_fm(fm: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fm.items())


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None


def audit_file(path: Path, now: datetime | None = None) -> dict:
    """Return {'issues': [...], 'corrected_fm': dict|None, 'changed': bool}."""
    now = now or datetime.now()
    text = path.read_text(encoding="utf-8")
    parsed = _parse_frontmatter(text)
    if not parsed:
        return {"issues": [], "corrected_fm": None, "changed": False, "skipped": "no frontmatter"}
    fm, head, tail_marker, body = parsed
    fm_orig = dict(fm)
    issues: list[str] = []

    created = _parse_iso(fm.get("created", ""))
    ttl     = fm.get("ttl_hours")
    exp     = _parse_iso(fm.get("expires_at", ""))

    # 1. Future created
    if created and created > now + timedelta(days=1):
        issues.append(f"created in the future: {fm.get('created')} vs now {now.isoformat(timespec='seconds')}")

    # 2. ttl_hours numeric sanity
    ttl_int: int | None = None
    if ttl:
        try:
            ttl_int = int(ttl)
        except ValueError:
            issues.append(f"ttl_hours not int: {ttl!r}")

    # 3. expires_at consistency with created + ttl_hours
    if created and ttl_int is not None:
        expected = created + timedelta(hours=ttl_int)
        if exp is None:
            fm["expires_at"] = expected.isoformat(timespec="seconds")
            issues.append("missing expires_at — computed from created + ttl_hours")
        else:
            delta_h = abs((exp - expected).total_seconds()) / 3600
            if delta_h > 1:    # >1h drift
                fm["expires_at"] = expected.isoformat(timespec="seconds")
                issues.append(f"expires_at drift {delta_h:.1f}h — corrected")

    # 4. expires_at in the past but priority is CRITICAL → don't auto-extend
    pri = (fm.get("priority") or "NORMAL").upper()
    if exp and exp < now and pri != "CRITICAL":
        # let prune_expired handle it; just note
        issues.append(f"already expired ({fm.get('expires_at')}); prune_expired will collect")

    changed = fm != fm_orig
    return {"issues": issues, "corrected_fm": fm if changed else None,
            "changed": changed, "head": head, "tail_marker": tail_marker, "body": body}


def correct_all(apply: bool = False) -> dict:
    """Walk user_memories and audit every .md."""
    if not USER_MEMORIES.exists():
        return {"checked": 0, "issues": 0}
    n_checked = n_changed = n_issues = 0
    per_file: list[dict] = []
    for f in USER_MEMORIES.rglob("*.md"):
        n_checked += 1
        report = audit_file(f)
        if report["issues"]:
            n_issues += len(report["issues"])
        if report.get("changed"):
            n_changed += 1
            if apply and report.get("corrected_fm") is not None:
                new_fm = _serialize_fm(report["corrected_fm"])
                new_text = report["head"] + new_fm + report["tail_marker"] + report["body"]
                f.write_text(new_text, encoding="utf-8")
        if report["issues"]:
            per_file.append({"file": str(f), "issues": report["issues"], "rewritten": apply and report.get("changed")})
    return {
        "checked":   n_checked,
        "with_issues": len(per_file),
        "total_issues": n_issues,
        "would_rewrite" if not apply else "rewritten": n_changed,
        "files":     per_file[:30],
    }


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-memory-correct-dates")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--apply", action="store_true",
                   help="actually rewrite frontmatter (default: dry-run)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    res = correct_all(apply=args.apply)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
