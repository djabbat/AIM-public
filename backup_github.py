#!/usr/bin/env python3
"""
backup_github.py — AIM auto-backup to GitHub
=============================================
Запускается автоматически 3-го числа каждого месяца через cron.
Также можно запустить вручную или из GUI.

Что делает:
  1. Обновляет раздел статистики в README.md (дата, кол-во модулей и т.д.)
  2. git add (всё кроме .gitignore-исключений)
  3. git commit с автоматическим сообщением
  4. git push origin main

Использование:
  python3 backup_github.py           # обычный бэкап
  python3 backup_github.py --dry-run # показать что будет без выполнения
  python3 backup_github.py --status  # показать git status
"""

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AIM_DIR = Path(__file__).parent


# ── helpers ──────────────────────────────────────────────────

def _run(cmd: list[str], capture=True) -> tuple[int, str]:
    """Run shell command in AIM_DIR. Returns (returncode, output)."""
    result = subprocess.run(
        cmd,
        cwd=AIM_DIR,
        capture_output=capture,
        text=True,
    )
    out = (result.stdout + result.stderr).strip()
    return result.returncode, out


def _stats() -> dict:
    """Collect current AIM statistics for README injection."""
    stats = {}

    # Python modules
    py_files = list(AIM_DIR.glob("*.py"))
    stats["modules"] = len(py_files)

    # Patients count (not in git, but show for README)
    patients_dir = AIM_DIR / "Patients"
    try:
        patients = [
            d for d in patients_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".") and d.name != "INBOX"
        ]
        stats["patients"] = len(patients)
    except Exception:
        stats["patients"] = "?"

    # Lab parameters count
    try:
        sys.path.insert(0, str(AIM_DIR))
        from lab_reference import REFERENCE_DB
        stats["lab_params"] = len(set(k[0] for k in REFERENCE_DB))
    except Exception:
        stats["lab_params"] = "165+"

    # Nutrition protocol
    try:
        from space_nutrition import FORBIDDEN_FOODS, ALLOWED_FOODS
        stats["forbidden"] = len(FORBIDDEN_FOODS)
        stats["allowed"] = len(ALLOWED_FOODS)
    except Exception:
        stats["forbidden"] = "47"
        stats["allowed"] = "69"

    stats["date"] = datetime.now().strftime("%Y-%m-%d")
    return stats


def _update_readme(stats: dict, dry_run: bool = False) -> bool:
    """
    Update the auto-stats block in README.md.
    Returns True if file was changed.
    """
    readme = AIM_DIR / "README.md"
    if not readme.exists():
        return False

    content = readme.read_text(encoding="utf-8")

    # Replace or inject the auto-stats block
    block = (
        f"**Версия:** 2.0 | "
        f"**Обновлено:** {stats['date']} | "
        f"**Автор:** Dr. Jaba Tkemaladze"
    )

    # Replace the version/date line
    new_content = re.sub(
        r"\*\*Версия:\*\*.*?\*\*Автор:\*\*.*",
        block,
        content
    )

    # Update stats table if it exists
    stats_block = (
        f"| Модулей Python | {stats['modules']} |\n"
        f"| Параметров лабораторий | {stats['lab_params']} |\n"
        f"| Запрещённых продуктов | {stats['forbidden']} |\n"
        f"| Разрешённых продуктов | {stats['allowed']} |"
    )

    # Try to replace existing stats table rows
    for pattern, replacement in [
        (r"\| Модулей Python \|.*\|", f"| Модулей Python | {stats['modules']} |"),
        (r"\| Параметров лабораторий \|.*\|", f"| Параметров лабораторий | {stats['lab_params']} |"),
        (r"\| Запрещённых продуктов \|.*\|", f"| Запрещённых продуктов | {stats['forbidden']} |"),
        (r"\| Разрешённых продуктов \|.*\|", f"| Разрешённых продуктов | {stats['allowed']} |"),
    ]:
        new_content = re.sub(pattern, replacement, new_content)

    changed = new_content != content
    if changed and not dry_run:
        readme.write_text(new_content, encoding="utf-8")
    return changed


def backup(dry_run: bool = False, verbose: bool = True) -> bool:
    """
    Full backup: update README → git add → commit → push.
    Returns True on success.
    """
    def log(msg):
        if verbose:
            print(msg)

    log(f"{'[DRY RUN] ' if dry_run else ''}AIM backup → github.com/djabbat/AIM")
    log(f"  Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── 1. Collect stats & update README ──────────────────────
    stats = _stats()
    log(f"  Модулей: {stats['modules']} | Параметров лаб: {stats['lab_params']} | "
        f"Запрещено: {stats['forbidden']} | Разрешено: {stats['allowed']}")

    readme_changed = _update_readme(stats, dry_run=dry_run)
    if readme_changed:
        log("  README.md — обновлён ✓")
    else:
        log("  README.md — без изменений")

    if dry_run:
        rc, out = _run(["git", "status", "--short"])
        log(f"\nGit status:\n{out}")
        return True

    # ── 2. git add ────────────────────────────────────────────
    rc, out = _run(["git", "add", "-A"])
    if rc != 0:
        log(f"  ❌ git add failed: {out}")
        return False

    # ── 3. Check if anything to commit ───────────────────────
    rc, out = _run(["git", "diff", "--cached", "--quiet"])
    if rc == 0:
        log("  Нет изменений для коммита.")
        return True

    # ── 4. git commit ─────────────────────────────────────────
    commit_msg = (
        f"auto-backup {stats['date']}: "
        f"{stats['modules']} modules, "
        f"{stats['lab_params']} lab params, "
        f"nutrition {stats['forbidden']}F/{stats['allowed']}A"
    )
    rc, out = _run(["git", "commit", "-m", commit_msg])
    if rc != 0:
        log(f"  ❌ git commit failed: {out}")
        return False
    log(f"  Commit: {commit_msg} ✓")

    # ── 5. git push ───────────────────────────────────────────
    rc, out = _run(["git", "push", "origin", "main"])
    if rc != 0:
        log(f"  ❌ git push failed: {out}")
        return False

    log("  ✅ Бэкап успешно загружен на GitHub!")
    return True


def status() -> str:
    """Return git status string."""
    rc, out = _run(["git", "status"])
    return out


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--status" in args:
        print(status())
        sys.exit(0)

    dry_run = "--dry-run" in args
    success = backup(dry_run=dry_run)
    sys.exit(0 if success else 1)
