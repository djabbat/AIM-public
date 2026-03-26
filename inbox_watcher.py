#!/usr/bin/env python3
"""
AIM — INBOX Watcher
===================
Следит за ~/Desktop/AIM/Patients/INBOX/. При появлении новых файлов автоматически
запускает полный пайплайн: OCR → PDF → Байес + R1 диагностика → самообучение.

Запуск из aim_gui.py как фоновый поток, или отдельно:
  cd ~/AIM && source venv/bin/activate && python3 inbox_watcher.py
"""

import time
import threading
from pathlib import Path

from config import INBOX_DIR, PATIENTS_DIR, get_logger

log = get_logger("inbox_watcher")

# Минимальная задержка между обработками (сек) — не запускать если файл ещё копируется
_SETTLE_DELAY = 3.0
# Расширения, которые триггерят обработку
_TRIGGER_EXT = {".jpg", ".jpeg", ".png", ".pdf", ".txt", ".zip"}


class InboxWatcher:
    """
    Файловый watcher на основе polling (без watchdog — работает всегда).
    При появлении новых файлов в INBOX запускает patient_intake в фоне.
    """

    def __init__(self, on_new_files=None):
        """
        on_new_files(paths: list[Path]) — опциональный callback для GUI (обновить UI).
        """
        self._on_new_files = on_new_files
        self._known: set[str] = set()
        self._running = False
        self._thread: threading.Thread | None = None
        self._processing = False

    def start(self):
        """Запустить watcher в фоновом daemon-треде."""
        inbox = Path(INBOX_DIR)
        inbox.mkdir(parents=True, exist_ok=True)
        # Snapshot существующих файлов — не обрабатывать старые
        self._known = {str(p) for p in inbox.rglob("*") if p.is_file()}
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info("InboxWatcher started, watching: %s", INBOX_DIR)

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            try:
                self._check()
            except Exception as e:
                log.error("InboxWatcher error: %s", e)
            time.sleep(2.0)

    def _check(self):
        inbox = Path(INBOX_DIR)
        if not inbox.exists():
            return

        current = {str(p) for p in inbox.rglob("*") if p.is_file()}
        new_paths = [Path(p) for p in (current - self._known)]
        self._known = current

        # Фильтр по расширению
        relevant = [p for p in new_paths if p.suffix.lower() in _TRIGGER_EXT]
        if not relevant:
            return

        log.info("INBOX: %d new file(s): %s", len(relevant),
                 [p.name for p in relevant])

        # Ждём settle — файл может ещё копироваться
        time.sleep(_SETTLE_DELAY)

        if self._on_new_files:
            try:
                self._on_new_files(relevant)
            except Exception as e:
                log.error("on_new_files callback error: %s", e)

        if not self._processing:
            self._processing = True
            threading.Thread(target=self._run_intake, daemon=True).start()

    def _run_intake(self):
        """Запускает patient_intake.py --all в подпроцессе."""
        import subprocess
        import sys
        import os

        python = str(Path(__file__).parent / "venv" / "bin" / "python3")
        if not Path(python).exists():
            python = sys.executable
        script = str(Path(__file__).parent / "patient_intake.py")

        log.info("Running patient_intake --all ...")
        try:
            result = subprocess.run(
                [python, script, "--all"],
                capture_output=True, text=True,
                cwd=str(Path(__file__).parent),
                timeout=600,
            )
            if result.returncode == 0:
                log.info("patient_intake --all completed OK")
            else:
                log.error("patient_intake stderr: %s", result.stderr[:500])
        except subprocess.TimeoutExpired:
            log.error("patient_intake timed out after 10 min")
        except Exception as e:
            log.error("patient_intake launch error: %s", e)
        finally:
            self._processing = False


# ── Singleton для GUI ──────────────────────────────────────────

_watcher: InboxWatcher | None = None


def get_watcher(on_new_files=None) -> InboxWatcher:
    """Возвращает (и при необходимости создаёт) глобальный InboxWatcher."""
    global _watcher
    if _watcher is None:
        _watcher = InboxWatcher(on_new_files=on_new_files)
        _watcher.start()
    elif on_new_files and _watcher._on_new_files is None:
        _watcher._on_new_files = on_new_files
    return _watcher


if __name__ == "__main__":
    print(f"Watching: {INBOX_DIR}")
    print("Ctrl+C to stop")
    w = InboxWatcher()
    w.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        w.stop()
        print("Stopped.")
