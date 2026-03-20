#!/usr/bin/env python3
"""
Patient intake pipeline.
Processes patient folders in ~/AIM/Patients/:
  - OCR screenshots (JPEG/PNG)
  - Extract PDF lab results
  - Identify patient DOB from analyses
  - Rename folders to correct format if needed
  - Generate/update medical history (history.txt)

Run: python3 patient_intake.py [--folder PATIENT_FOLDER | --all | --inbox PATH]
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import date, datetime
from typing import Optional, Dict, List

from config import (PATIENTS_DIR as DOCUMENTS_DIR, INBOX_DIR,
                    MODEL, get_logger)
from llm import ask_llm as _ask_llm_ds
import db as _db
_db.init_db()
log = get_logger("patient_intake")

FOLDER_RE = re.compile(
    r'^([A-Za-zА-Яа-яЁёა-ჿ\-]+)_([A-Za-zА-Яа-яЁёა-ჿ\-]+)_(\d{4})_(\d{2})_(\d{2})$'
)


# ── Helpers ───────────────────────────────────────────────────

# ── Processed-files cache (loaded once per session) ───────────
_processed_cache: Optional[set] = None

def load_processed() -> set:
    """Compat wrapper — возвращает пустой set; реальная проверка через db.is_processed()."""
    global _processed_cache
    if _processed_cache is None:
        _processed_cache = set()
    return _processed_cache

def save_processed(processed: set):
    """Compat wrapper — больше не пишет JSON; состояние хранится в SQLite."""
    global _processed_cache
    _processed_cache = processed

def invalidate_processed_path(old_path: str, new_path: str):
    """При переименовании папки — переносим записи в БД."""
    global _processed_cache
    if _processed_cache is not None:
        old = str(old_path)
        new_str = str(new_path)
        updated = set()
        for p in _processed_cache:
            updated.add(p.replace(old, new_str) if p.startswith(old) else p)
        _processed_cache = updated
    # SQLite: снять старые записи и переписать пути
    try:
        from pathlib import Path as _Path
        for old_file in _Path(old_path).rglob("*"):
            if old_file.is_file():
                new_file = str(old_file).replace(str(old_path), str(new_path))
                _db.unmark_processed(str(old_file))
                _db.mark_processed(new_file)
    except Exception:
        pass


def ask_llm(prompt: str, system: str = "") -> str:
    return _ask_llm_ds(prompt, system=system, max_tokens=2048, temperature=0.2)


INTEGRATIVE_SYSTEM = """Ты — цифровой ассистент доктора Джаба Ткемаладзе, специалиста \
по интегративной медицине. Твоя задача: составить структурированное клиническое резюме \
пациента на основе предоставленных данных (анамнез, жалобы, лаборатория, переписка).

ИНСТРУКЦИЯ ПО АНАЛИЗУ:
1. Извлеки ключевые жалобы и симптомы
2. Выдели значимые лабораторные отклонения (↓ низко, ↑ высоко, ⚠ критично)
3. Предложи 2–3 наиболее вероятных диагноза с обоснованием (байесовский подход)
4. Дай конкретные рекомендации: питание, добавки с дозами, медикаменты если нужны
5. Укажи что нужно проконтролировать и через сколько времени

ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ОТВЕТА:
## ЖАЛОБЫ И СИМПТОМЫ
## АНАМНЕЗ
## ЛАБОРАТОРНЫЕ ПОКАЗАТЕЛИ
(таблица: показатель | значение | норма | статус)
## ДИФФЕРЕНЦИАЛЬНЫЙ ДИАГНОЗ
## РЕКОМЕНДАЦИИ
### Питание и образ жизни
### Нутрицевтики и добавки
### Медикаменты
## КОНТРОЛЬ (что проверить, через сколько недель)

Отвечай на русском языке. Будь конкретен: дозы в мг/мкг, курс в неделях, \
анализы с конкретными показателями для повторной сдачи.
"""


# ── PDF extraction ─────────────────────────────────────────────

def extract_pdf_text(pdf_path: str) -> str:
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(pdf_path) as p:
            for page in p.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        return "\n".join(texts)
    except Exception as e:
        return f"[PDF extract error: {e}]"


# ── OCR ───────────────────────────────────────────────────────

def ocr_image_file(image_path: str) -> str:
    from ocr_engine import ocr_image
    return ocr_image(image_path)


# ── Process a single patient folder ───────────────────────────

def process_patient_folder(folder_path: str, force: bool = False) -> str:
    """
    Full processing pipeline for one patient folder.
    Returns summary of what was done.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        return f"ERROR: not a directory: {folder_path}"

    # Зарегистрировать / обновить пациента в БД
    _patient_id = None
    try:
        m = FOLDER_RE.match(folder.name)
        if m:
            sur, nam, y, mo, d = m.groups()
            _patient_id = _db.upsert_patient(
                surname=sur, name=nam,
                folder_path=str(folder),
                dob=f"{y}-{mo}-{d}"
            )
    except Exception as _e:
        log.debug(f"DB upsert_patient skipped: {_e}")

    processed = load_processed()
    steps = []
    all_text_parts = []

    # 1. Collect data from existing text file (if any)
    folder_name = folder.name
    main_txt = folder / f"{folder_name}.txt"
    if main_txt.exists():
        all_text_parts.append(f"=== ИСТОРИЯ БОЛЕЗНИ ===\n{main_txt.read_text(encoding='utf-8', errors='replace')}")

    # whatsapp chat
    wa_txt = folder / "whatsapp_chat.txt"
    if wa_txt.exists():
        all_text_parts.append(f"=== ПЕРЕПИСКА WHATSAPP ===\n{wa_txt.read_text(encoding='utf-8', errors='replace')[:5000]}")

    # 2. OCR all images
    img_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    for img_file in sorted(folder.iterdir()):
        if img_file.suffix.lower() not in img_extensions:
            continue
        ocr_out = folder / f"{img_file.stem}_ocr.txt"
        file_key = str(img_file)

        if not force and _db.is_processed(file_key) and ocr_out.exists():
            # Already processed — just load
            all_text_parts.append(f"=== СКРИН: {img_file.name} ===\n{ocr_out.read_text(encoding='utf-8', errors='replace')}")
            continue

        log.info(f"  OCR: {img_file.name} ...")
        ocr_text = ocr_image_file(str(img_file))
        ocr_out.write_text(ocr_text, encoding="utf-8")
        _db.mark_processed(file_key)
        processed.add(file_key)
        all_text_parts.append(f"=== СКРИН: {img_file.name} ===\n{ocr_text}")
        steps.append(f"OCR: {img_file.name}")
        log.info("  ✓")

    # 3. Extract PDFs
    for pdf_file in sorted(folder.rglob("*.pdf")):
        if pdf_file.is_dir():
            continue
        txt_out = folder / f"{pdf_file.stem}_text.txt"
        file_key = str(pdf_file)

        if not force and _db.is_processed(file_key) and txt_out.exists():
            all_text_parts.append(f"=== АНАЛИЗ PDF: {pdf_file.name} ===\n{txt_out.read_text(encoding='utf-8', errors='replace')}")
            continue

        log.info(f"  PDF: {pdf_file.name} ...")
        pdf_text = extract_pdf_text(str(pdf_file))
        txt_out.write_text(pdf_text, encoding="utf-8")
        _db.mark_processed(file_key)
        processed.add(file_key)
        all_text_parts.append(f"=== АНАЛИЗ PDF: {pdf_file.name} ===\n{pdf_text}")
        steps.append(f"PDF: {pdf_file.name}")
        log.info("  ✓")

    save_processed(processed)

    # 4. Try to extract DOB and fix folder name if needed
    new_folder = _try_fix_folder_dob(folder, "\n".join(all_text_parts[:3]))
    if new_folder:
        folder = new_folder

    # 5. Generate AI medical analysis
    if not all_text_parts:
        return f"Нет данных в папке: {folder_path}"

    analysis_file = folder / "_ai_analysis.txt"
    should_regenerate = force or not analysis_file.exists() or steps

    if should_regenerate:
        log.info("  Генерация анализа...")
        combined = "\n\n".join(all_text_parts)[:8000]
        patient_name = _patient_name_from_folder(folder.name)
        sex, age_group = _patient_demographics(folder, combined)

        prompt = f"""Пациент: {patient_name}

Данные из папки пациента (анамнез, анализы, переписка, скрины):
{combined}

Составь структурированную историю болезни с медицинским анализом.
Выдели ключевые отклонения в анализах. Предложи интегративный подход к лечению."""

        analysis = ask_llm(prompt, system=INTEGRATIVE_SYSTEM)

        with open(analysis_file, "w", encoding="utf-8") as f:
            f.write(f"МЕДИЦИНСКИЙ АНАЛИЗ — {patient_name}\n")
            f.write(f"Дата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(analysis)
            f.write("\n\n")
            # Append structured lab analysis if possible
            _write_lab_section(f, all_text_parts, folder=folder,
                               sex=sex, age_group=age_group)

        # Сохранить диагноз в БД
        if _patient_id:
            try:
                _db.save_diagnosis(_patient_id, analysis, source="intake")
            except Exception as _e:
                log.debug(f"DB save_diagnosis skipped: {_e}")

        log.info("  ✓")
        steps.append("Анализ обновлён")

        # ── Self-learning: record findings in knowledge base ──────
        _record_to_knowledge(patient_name, analysis, all_text_parts)

    if steps:
        return f"Обработано: {', '.join(steps)}"
    return "Уже обработано (используй --force для повторного анализа)"


def _record_to_knowledge(patient_name: str, analysis: str, text_parts: list):
    """Extract diagnoses from analysis text and record in knowledge base."""
    try:
        from medical_system import knowledge
        # Extract diagnosis names from the analysis (lines after ДИАГНОЗ/ВЫВОДЫ)
        diagnoses = []
        for line in analysis.splitlines():
            line = line.strip()
            if any(kw in line for kw in ("анемия", "гипотиреоз", "диабет", "дефицит",
                                          "синдром", "гипертония", "недостаточность",
                                          "резистентность", "дисфункция")):
                diagnoses.append(line[:80])
        # Extract treatments (numbered lines = prescriptions)
        treatments = [l.strip()[:60] for l in analysis.splitlines()
                      if l.strip() and l.strip()[0].isdigit() and ". " in l][:5]
        knowledge.record_patient_analysis(patient_name, diagnoses[:5], treatments)
        log.debug(f"Knowledge recorded for {patient_name}: {len(diagnoses)} dx")
        # Параллельно — в SQLite
        for dx in diagnoses[:5]:
            try:
                _db.upsert_knowledge(dx, {"patient": patient_name, "treatments": treatments})
            except Exception:
                pass
    except Exception as e:
        log.debug(f"Knowledge record skipped: {e}")


def _patient_name_from_folder(folder_name: str) -> str:
    parts = folder_name.split("_")
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return folder_name


def _patient_demographics(folder: Path, text: str = "") -> tuple:
    """
    Extract (sex, age_group) from folder name + text.
    sex:       'M' | 'F' | '*'
    age_group: 'child' | 'adult' | 'elder' | '*'
    """
    from datetime import date
    import re as _re

    # ── Age from folder DOB ───────────────────────────────────
    age_group = "adult"
    m = FOLDER_RE.match(folder.name)
    if m:
        try:
            y, mo, d = int(m.group(3)), int(m.group(4)), int(m.group(5))
            age = (date.today() - date(y, mo, d)).days // 365
            if age < 18:
                age_group = "child"
            elif age >= 65:
                age_group = "elder"
            else:
                age_group = "adult"
        except Exception:
            pass

    # ── Sex from text keywords ────────────────────────────────
    sex = "*"
    if text:
        tl = text.lower()
        male_kw = [r'\bмужчина\b', r'\bмужской\b', r'\bпол\s*[:]\s*м\b',
                   r'\bsex\s*[:]\s*m\b', r'\bmale\b', r'\bმამრ']
        female_kw = [r'\bженщина\b', r'\bженский\b', r'\bпол\s*[:]\s*ж\b',
                     r'\bsex\s*[:]\s*f\b', r'\bfemale\b', r'\bმდედრ']
        if any(_re.search(p, tl) for p in male_kw):
            sex = "M"
        elif any(_re.search(p, tl) for p in female_kw):
            sex = "F"

    return sex, age_group


def _write_lab_section(f, text_parts: list, folder: Path = None,
                       sex: str = "*", age_group: str = "adult"):
    """Append structured lab results section and save JSON snapshot."""
    try:
        from lab_parser import extract_from_text
        from diagnosis_engine import bayesian_differential, run_diagnosis_ai
        combined = "\n".join(text_parts)
        results = extract_from_text(combined, sex=sex, age_group=age_group)
        if not results:
            return

        # Write human-readable section
        f.write("\n" + "=" * 60 + "\n")
        f.write("СТРУКТУРИРОВАННЫЕ ЛАБОРАТОРНЫЕ ПОКАЗАТЕЛИ\n")
        f.write("=" * 60 + "\n")
        abnormal = []
        for r in results:
            status_icon = {"normal": "✓", "low": "↓", "high": "↑",
                           "critical_low": "⚠↓", "critical_high": "⚠↑"}.get(r.status, "?")
            f.write(f"  {status_icon} {r.param_id}: {r.value} {r.unit}  [{r.ref_range}] — {r.interpretation}\n")
            if r.status not in ("normal", "unknown"):
                abnormal.append(r)

        # Write diagnosis section with R1
        if abnormal and folder:
            patient_name = " ".join(folder.name.split("_")[:2])
            dx_text = run_diagnosis_ai(results, patient_name=patient_name)
            f.write("\n" + dx_text + "\n")

        # Save structured JSON snapshot for lab dynamics tracking
        if folder:
            _save_lab_snapshot(folder, results)

    except Exception as e:
        log.warning("Lab section error: %s", e)


def _save_lab_snapshot(folder: Path, results: list):
    """Save lab values as JSON for historical tracking."""
    import json
    snapshot_file = folder / "_lab_history.json"
    today = datetime.now().strftime("%Y-%m-%d")

    # Load existing history
    history = {}
    if snapshot_file.exists():
        try:
            history = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except Exception:
            history = {}

    # Add today's snapshot
    history[today] = {
        r.param_id: {
            "value": r.value,
            "unit": r.unit,
            "status": r.status,
            "ref_range": r.ref_range,
        }
        for r in results
    }

    snapshot_file.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.debug("Lab snapshot saved: %s (%d params)", today, len(results))

    # Параллельно — в SQLite
    try:
        patient_row = _db.get_patient_by_folder(str(folder))
        if patient_row:
            params_dict = {
                r.param_id: {"value": r.value, "unit": r.unit,
                             "status": r.status, "ref_range": r.ref_range}
                for r in results
            }
            _db.save_labs(patient_row["id"], params_dict,
                          taken_at=today, source_file=str(folder))
    except Exception as _e:
        log.debug(f"DB save_labs skipped: {_e}")


def _try_fix_folder_dob(folder: Path, combined_text: str) -> Optional[Path]:
    """
    If folder lacks proper DOB in name, try to detect DOB from content
    and add it. Returns new Path if renamed, None otherwise.
    """
    name = folder.name
    m = FOLDER_RE.match(name)
    if m:
        return None  # Already has proper format

    # Try to find DOB in text
    from whatsapp_importer import parse_dob
    dob = parse_dob(combined_text)
    if not dob:
        return None

    # Find if folder name is just SURNAME_NAME
    parts = name.split("_")
    if len(parts) == 2:
        new_name = f"{parts[0]}_{parts[1]}_{dob.year:04d}_{dob.month:02d}_{dob.day:02d}"
        new_path = folder.parent / new_name
        if not new_path.exists():
            folder.rename(new_path)
            # Update processed cache so old paths don't become stale
            invalidate_processed_path(str(folder), str(new_path))
            log.info(f"Папка переименована: {name} → {new_name}")
            return new_path
    return None


# ── Process all patients ───────────────────────────────────────

def process_all_patients(force: bool = False) -> int:
    """Process all patient folders in ~/AIM/Patients/. Returns count processed."""
    docs = Path(DOCUMENTS_DIR)
    count = 0
    folders = [d for d in docs.iterdir() if d.is_dir() and not d.name.startswith(".")]
    # Filter: looks like patient folder
    patient_folders = []
    for d in folders:
        parts = d.name.split("_")
        if len(parts) >= 2:
            patient_folders.append(d)

    log.info(f"Найдено папок пациентов: {len(patient_folders)}")
    for folder in sorted(patient_folders):
        
        log.info(f"Пациент: {folder.name}")
        result = process_patient_folder(str(folder), force=force)
        log.info(f"  Результат: {result}")
        count += 1

    return count


# ── INBOX processing ──────────────────────────────────────────

def process_inbox(inbox_dir: str = INBOX_DIR):
    """
    Process files dropped into INBOX/:
    - WA export .txt → import as patient
    - Folders with patient name → move to Documents
    """
    inbox = Path(inbox_dir)
    if not inbox.exists():
        inbox.mkdir(parents=True)
        print(f"Создана папка для новых файлов: {inbox_dir}")
        print("Бросайте в неё:")
        print("  • Экспорт WhatsApp (.txt с медиа)")
        print("  • Папки пациентов с анализами")
        return

    from whatsapp_importer import scan_for_wa_exports, import_chat_to_documents

    # Process WhatsApp exports
    chats = scan_for_wa_exports(str(inbox))
    for chat in chats:
        print(f"WhatsApp импорт: {chat.last_name} {chat.first_name} "
              f"(сообщений: {len(chat.messages)})")
        folder = import_chat_to_documents(chat)
        print(f"  → {folder}")
        # Now process the folder
        process_patient_folder(folder)

    if not chats:
        # Maybe raw image/PDF files — try to find which patient they belong to
        imgs = list(inbox.glob("*.jpg")) + list(inbox.glob("*.jpeg")) + \
               list(inbox.glob("*.png")) + list(inbox.glob("*.pdf"))
        if imgs:
            print(f"Найдено файлов в INBOX: {len(imgs)}")
            print("Для привязки к пациенту создайте папку INBOX/ФАМИЛИЯ_ИМЯ/ и положите файлы туда")


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Patient intake pipeline — integrative medicine AI"
    )
    parser.add_argument("--all", action="store_true", help="Process all patient folders")
    parser.add_argument("--folder", type=str, help="Process specific patient folder path")
    parser.add_argument("--inbox", type=str, default=INBOX_DIR,
                        help="Process INBOX folder for new files")
    parser.add_argument("--force", action="store_true", help="Re-process everything")
    parser.add_argument("--list", action="store_true", help="List all patients")
    args = parser.parse_args()

    if args.list:
        from medical_parser import load_all_patients
        patients = load_all_patients()
        print(f"\nПациентов: {len(patients)}")
        for p in sorted(patients, key=lambda x: x.full_name):
            print(f"  {p.full_name}  (с {p.opened_date}, записей: {len(p.entries)})")
        return

    if args.folder:
        result = process_patient_folder(args.folder, force=args.force)
        print(result)
    elif args.all:
        count = process_all_patients(force=args.force)
        print(f"\n✓ Обработано пациентов: {count}")
    else:
        process_inbox(args.inbox)
        print("\nДля обработки всех пациентов: python3 patient_intake.py --all")


if __name__ == "__main__":
    main()
