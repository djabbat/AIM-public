"""
AIM v7.0 — IntakeAgent
OCR изображений, парсинг PDF, автоматический intake из INBOX.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from llm import ask, ask_long
from db import save_message, upsert_patient, new_session
from i18n import t
from config import INBOX_DIR, PATIENTS_DIR

log = logging.getLogger("aim.intake")

# ── Поддерживаемые форматы ────────────────────────────────────────────────────

IMAGE_EXTS  = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
PDF_EXTS    = {".pdf"}
TEXT_EXTS   = {".txt", ".csv", ".md"}


# ── OCR ───────────────────────────────────────────────────────────────────────

def _ocr_image(path: Path) -> str:
    """OCR изображения: tesseract → rapidocr fallback."""
    # Попытка 1: pytesseract
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang="rus+eng+kat")
        if text.strip():
            log.info(f"OCR (tesseract): {path.name}, {len(text)} chars")
            return text
    except Exception as e:
        log.warning(f"tesseract failed: {e}")

    # Попытка 2: rapidocr
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        result, _ = engine(str(path))
        if result:
            text = "\n".join(line[1] for line in result)
            log.info(f"OCR (rapidocr): {path.name}, {len(text)} chars")
            return text
    except Exception as e:
        log.warning(f"rapidocr failed: {e}")

    return f"[OCR недоступен: {path.name}]"


def _parse_pdf(path: Path) -> str:
    """Извлечение текста из PDF: pymupdf → pdfplumber fallback."""
    # Попытка 1: pymupdf (fitz)
    try:
        import fitz
        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        text = "\n\n".join(pages)
        if text.strip():
            log.info(f"PDF (pymupdf): {path.name}, {len(text)} chars")
            return text
    except Exception as e:
        log.warning(f"pymupdf failed: {e}")

    # Попытка 2: pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n\n".join(pages)
        if text.strip():
            log.info(f"PDF (pdfplumber): {path.name}, {len(text)} chars")
            return text
    except Exception as e:
        log.warning(f"pdfplumber failed: {e}")

    return f"[PDF парсинг недоступен: {path.name}]"


def extract_text(path: Path) -> str:
    """Извлечь текст из любого поддерживаемого файла."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        return _ocr_image(path)
    if suffix in PDF_EXTS:
        return _parse_pdf(path)
    if suffix in TEXT_EXTS:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return f"[Ошибка чтения: {e}]"
    return f"[Неподдерживаемый формат: {suffix}]"


# ── WhatsApp parser ───────────────────────────────────────────────────────────

def _parse_whatsapp_name(contact: str) -> Optional[str]:
    """
    Формат: 'SURNAME P FIRSTNAME' или 'SURNAME П FIRSTNAME' или 'SURNAME პ FIRSTNAME'
    Возвращает 'SURNAME FIRSTNAME' или None.
    """
    match = re.match(r"^(.+?)\s+[PПპ]\s+(.+)$", contact.strip(), re.IGNORECASE)
    if match:
        return f"{match.group(1).strip()} {match.group(2).strip()}"
    return None


def _parse_whatsapp_export(path: Path) -> list[dict]:
    """
    Парсинг экспорта WhatsApp.
    Возвращает список {name, messages: [str]}.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    # Паттерн строки: [дата, время] Имя: текст
    pattern = re.compile(
        r"^\[?(\d{1,2}[./]\d{1,2}[./]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+([^:]+):\s+(.+)$",
        re.MULTILINE,
    )

    patients: dict[str, list[str]] = {}
    for m in pattern.finditer(text):
        sender = m.group(3).strip()
        content = m.group(4).strip()
        name = _parse_whatsapp_name(sender)
        if name:
            patients.setdefault(name, []).append(content)

    return [{"name": name, "messages": msgs} for name, msgs in patients.items()]


# ── IntakeAgent ───────────────────────────────────────────────────────────────

class IntakeAgent:
    """
    Агент приёма данных.

    Методы:
        process_file(path, lang, session_id) → str   — обработать один файл
        scan_inbox(lang) → list[dict]                 — сканировать INBOX
        analyze_labs(text, lang, session_id) → str    — AI-анализ лабораторных данных
    """

    def __init__(self):
        self.name = "IntakeAgent"

    def process_file(
        self,
        path: Path,
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Извлечь текст из файла и запустить AI-анализ."""
        if not path.exists():
            return f"Файл не найден: {path}"

        log.info(f"IntakeAgent.process_file: {path.name}")
        raw_text = extract_text(path)

        if raw_text.startswith("["):
            return raw_text  # ошибка извлечения

        return self.analyze_labs(raw_text, lang=lang, session_id=session_id)

    def analyze_labs(
        self,
        text: str,
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """AI-анализ лабораторных / медицинских данных."""
        if not text.strip():
            return t("error", lang)

        system_map = {
            "ru": (
                "Ты — клинический специалист по лабораторной диагностике. "
                "Проанализируй медицинские данные. Выдели отклонения, укажи клиническое значение. "
                "Disclaimer в конце обязателен."
            ),
            "en": (
                "You are a clinical laboratory diagnostics specialist. "
                "Analyze the medical data. Highlight deviations, state clinical significance. "
                "Disclaimer at the end is mandatory."
            ),
        }
        system = system_map.get(lang) or system_map["en"]
        prompt = f"Медицинские данные для анализа:\n\n{text}"

        # Длинные документы → KIMI
        result = ask_long(prompt, system=system, lang=lang)

        if session_id:
            save_message(session_id, "user", f"[Файл: intake]", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def scan_inbox(self, lang: str = "ru") -> list[dict]:
        """
        Сканировать INBOX на новые файлы.
        Возвращает список {path, text, type}.
        """
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        results = []

        supported = IMAGE_EXTS | PDF_EXTS | TEXT_EXTS
        files = [f for f in INBOX_DIR.iterdir() if f.suffix.lower() in supported]

        if not files:
            log.info("IntakeAgent.scan_inbox: INBOX пуст")
            return []

        log.info(f"IntakeAgent.scan_inbox: найдено {len(files)} файлов")
        for f in files:
            text = extract_text(f)
            results.append({
                "path": f,
                "text": text,
                "type": "image" if f.suffix.lower() in IMAGE_EXTS else
                        "pdf"   if f.suffix.lower() in PDF_EXTS   else "text",
            })

        return results

    def import_whatsapp(self, path: Path, lang: str = "ru") -> list[dict]:
        """
        Импорт экспорта WhatsApp. Создаёт папки пациентов.
        Возвращает список созданных пациентов.
        """
        patients = _parse_whatsapp_export(path)
        if not patients:
            log.warning(f"import_whatsapp: пациенты не найдены в {path.name}")
            return []

        from datetime import date
        created = []
        for p in patients:
            name = p["name"]
            folder = name.upper().replace(" ", "_") + "_" + date.today().strftime("%Y_%m_%d")
            patient_dir = PATIENTS_DIR / folder
            patient_dir.mkdir(parents=True, exist_ok=True)

            # Сохраняем переписку
            chat_file = patient_dir / "whatsapp_chat.txt"
            chat_file.write_text("\n".join(p["messages"]), encoding="utf-8")

            pid = upsert_patient(folder, name, lang)
            log.info(f"import_whatsapp: создан пациент {folder}")
            created.append({"name": name, "folder": folder, "pid": pid,
                            "messages": len(p["messages"])})

        return created
