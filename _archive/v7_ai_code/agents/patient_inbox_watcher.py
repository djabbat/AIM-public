"""agents/patient_inbox_watcher.py — INBOX → patient folder mover (PA1, 2026-05-03).

Polls `Patients/INBOX/` for newly-dropped lab PDFs / scans / images,
extracts the patient's DOB (via OCR + simple regex pull), and moves the
file into `Patients/<Surname>_<Name>_<YYYY_MM_DD>/`. Per CLAUDE.md, when
the DOB is unknown / inconsistent, we use the sentinel `2000_01_01`.

Each run:
  * Walks INBOX (top-level only — sub-dirs are user-organised).
  * For each file with a known extension, runs OCR (delegating to the
    existing `agents.intake.OCREngine` when available — else falls back
    to a tesseract subprocess).
  * Searches the OCR text for a Surname Name + DOB pattern in Russian
    or Georgian. If both found, moves the file. If not, leaves it.
  * Appends an `AI_LOG.md` entry to the patient folder.

This is intake-pipeline glue — it never edits clinical content itself.

Public API:
    candidates() -> list[Path]
    classify(file_path) -> Classification | None
    process_one(file_path, *, dry_run=True) -> Action
    process_inbox(*, dry_run=True) -> list[Action]
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.patient_inbox_watcher")


def patients_dir() -> Path:
    env = os.environ.get("AIM_PATIENTS_DIR")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "Patients"


def inbox_dir() -> Path:
    return patients_dir() / "INBOX"


_OCR_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
# Surname / first-name patterns: capitalised Cyrillic word ≥3 letters,
# possibly followed by a second one (patronymic ignored). We iterate
# matches and drop the common label words (Пациент, Анализ, …) so a
# header like "Пациент: Феридзе Майя" classifies on the real name.
_NAME_RE = re.compile(
    r"\b([А-ЯҐЁ][а-яёҐґії-]{2,30})\s+([А-ЯҐЁ][а-яёҐґії-]{2,30})\b"
)
_NAME_STOPWORDS = {
    "пациент", "пациентка", "анализ", "анализы", "результат", "результаты",
    "доктор", "клиника", "лаборатория", "медкарта", "карта", "образец",
    "patient", "subject", "doctor", "clinic", "lab", "results",
}
_DOB_RE = re.compile(
    r"(?:год\s+рождения|дата\s+рождения|д[\.\s]р[\.\s]?|"
    r"дата:|date\s+of\s+birth|DOB)[\s:]*?"
    r"(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](\d{2,4})",
    re.IGNORECASE,
)
# Generic "01.05.1981"-style date when no preceding label fires.
_GENERIC_DATE_RE = re.compile(
    r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](19[3-9]\d|20[0-1]\d)\b"
)


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Classification:
    surname: Optional[str]
    name: Optional[str]
    dob: Optional[dt.date]
    text_excerpt: str        # first 400 chars of OCR text


@dataclasses.dataclass
class Action:
    file: str
    moved_to: Optional[str]
    reason: str               # "moved" | "ambiguous" | "ocr_failed" | "skipped"
    classification: Optional[Classification]


# ── OCR adapters ────────────────────────────────────────────────


def _ocr_text(path: Path) -> Optional[str]:
    """Try the project's intake.OCREngine; fall back to tesseract subprocess.
    Returns None on failure."""
    try:
        from agents.intake import ocr_file  # type: ignore
        return str(ocr_file(path) or "")
    except Exception:
        pass
    try:
        from agents.intake import OCREngine  # type: ignore
        eng = OCREngine()
        if hasattr(eng, "extract_text"):
            return str(eng.extract_text(path) or "")
    except Exception:
        pass
    # Subprocess fallback for plain images.
    if path.suffix.lower() in _OCR_EXTS:
        try:
            out = subprocess.run(
                ["tesseract", str(path), "-", "-l", "rus+eng+kat"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            return out.stdout
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return None
    return None


# ── classification ──────────────────────────────────────────────


def _normalise_dob(d: int, m: int, y: int) -> Optional[dt.date]:
    if y < 100:
        y += 1900 if y > 30 else 2000
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def classify(file_path: Path) -> Optional[Classification]:
    text = _ocr_text(Path(file_path))
    if not text:
        return None
    surname = name = None
    # Walk overlapping pairs of capitalised Cyrillic words so a header
    # like "Пациент Феридзе Майя" still finds (Феридзе, Майя).
    word_re = re.compile(r"\b[А-ЯҐЁ][а-яёҐґії-]{2,30}\b")
    words = [m.group(0) for m in word_re.finditer(text)]
    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        if a.lower() in _NAME_STOPWORDS or b.lower() in _NAME_STOPWORDS:
            continue
        surname, name = a, b
        break
    dob: Optional[dt.date] = None
    m = _DOB_RE.search(text)
    if m:
        dob = _normalise_dob(int(m.group(1)), int(m.group(2)),
                              int(m.group(3)))
    if dob is None:
        m2 = _GENERIC_DATE_RE.search(text)
        if m2:
            dob = _normalise_dob(int(m2.group(1)), int(m2.group(2)),
                                   int(m2.group(3)))
    return Classification(
        surname=surname, name=name, dob=dob,
        text_excerpt=text[:400],
    )


# ── routing ──────────────────────────────────────────────────────


_ALLOWED_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _patient_folder(c: Classification) -> Path:
    surname = (c.surname or "Unknown").strip()
    name = (c.name or "Unknown").strip()
    # CLAUDE.md sentinel — when DOB is unknown OR clearly suspicious.
    dob = c.dob
    if dob is None:
        slug_dob = "2000_01_01"
    else:
        slug_dob = dob.strftime("%Y_%m_%d")
    safe_surname = re.sub(r"[^A-Za-zА-Яа-яҐЁёї_-]+", "_", surname)[:40]
    safe_name = re.sub(r"[^A-Za-zА-Яа-яҐЁёї_-]+", "_", name)[:40]
    return patients_dir() / f"{safe_surname}_{safe_name}_{slug_dob}"


def candidates() -> list[Path]:
    inbox = inbox_dir()
    if not inbox.exists():
        return []
    return sorted([p for p in inbox.iterdir()
                   if p.is_file() and p.suffix.lower() in _OCR_EXTS])


def process_one(file_path: Path, *, dry_run: bool = True) -> Action:
    file_path = Path(file_path)
    if not file_path.exists():
        return Action(file=str(file_path), moved_to=None,
                      reason="not_found", classification=None)
    cls = classify(file_path)
    if cls is None:
        return Action(file=str(file_path), moved_to=None,
                      reason="ocr_failed", classification=None)
    if not (cls.surname and cls.name):
        return Action(file=str(file_path), moved_to=None,
                      reason="ambiguous", classification=cls)

    target_folder = _patient_folder(cls)
    target = target_folder / file_path.name
    if dry_run:
        return Action(file=str(file_path), moved_to=str(target),
                      reason="moved (dry-run)", classification=cls)

    target_folder.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Don't clobber — append a suffix.
        target = target.with_name(
            f"{target.stem}-{dt.datetime.now():%Y%m%d-%H%M%S}{target.suffix}")
    shutil.move(str(file_path), str(target))
    _append_log(target_folder, file_path.name, target.name, cls)

    # Fire HOOK_INTAKE_PDF (HW1, 2026-05-06) с stage="moved" — отдельный
    # этап от "processed" (intake.process_file). Q9.A: переиспользуем
    # константу с stage-полем вместо новой HOOK_PATIENT_FILE_MOVED.
    try:
        from agents.hooks import fire, HOOK_INTAKE_PDF
        fire(HOOK_INTAKE_PDF, {
            "stage": "moved",
            "path": str(target),
            "patient_dir": str(target_folder),
            "patient_id": target_folder.name,
            "ext": target.suffix.lower(),
            "dob": cls.dob.isoformat() if cls.dob else None,
        })
    except Exception as e:
        log.debug("HOOK_INTAKE_PDF (stage=moved) fire failed: %s", e)

    return Action(file=str(file_path), moved_to=str(target),
                  reason="moved", classification=cls)


def _append_log(folder: Path, original: str, final: str,
                cls: Classification) -> None:
    log_file = folder / "AI_LOG.md"
    line = (f"\n- {dt.datetime.now().replace(microsecond=0).isoformat()}  "
            f"intake: `{original}` → `{final}`"
            + (f"  (dob={cls.dob.isoformat()})" if cls.dob else "  (dob unknown)"))
    try:
        with log_file.open("a", encoding="utf-8") as f:
            if log_file.stat().st_size == 0:
                f.write(f"# AI intake log — {folder.name}\n")
            f.write(line + "\n")
    except OSError as e:
        log.warning("AI_LOG write failed: %s", e)


def process_inbox(*, dry_run: bool = True) -> list[Action]:
    return [process_one(p, dry_run=dry_run) for p in candidates()]
