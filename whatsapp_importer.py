#!/usr/bin/env python3
"""
WhatsApp chat importer for patient records.
Identifies patients by separator: პ | P | П  between surname and first name.
Example contact names:
  "Robakidze P Nino"
  "Beridze П Кети"
  "Nishnianidze პ ანი"

WhatsApp export format (.txt):
  [DD.MM.YY, HH:MM:SS] ContactName: message text
  [DD.MM.YY, HH:MM:SS] ContactName: <attached: filename.jpg>
"""

import os
import re
import shutil
import zipfile
import tempfile
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

from config import PATIENTS_DIR as DOCUMENTS_DIR, INBOX_DIR, get_logger
log = get_logger("whatsapp_importer")

# Patient separator pattern: П (Rus), P (Lat), პ (Georgian)
# Between surname and firstname in contact name
PATIENT_SEPARATOR_RE = re.compile(
    r'^([A-Za-zА-Яа-яЁёა-ჿ\-]+)\s+[PПპ]\s+([A-Za-zА-Яа-яЁёა-ჿ\-]+)$'
)

# WhatsApp message line
WA_LINE_RE = re.compile(
    r'^\[(\d{1,2}[./]\d{1,2}[./]\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s*(.*)'
)

# Attached file reference
ATTACHED_RE = re.compile(r'<attached:\s*(.+?)>')

# DOB patterns in text: formats DD.MM.YYYY or YYYY-MM-DD or DD/MM/YYYY
DOB_RE = re.compile(
    r'(?:'
    # Russian / Cyrillic keywords
    r'дата\s+рождения|д\.?\s*р\.?|дату\s+рождения|год\s+рождения|дата\s+рожд|р\.\s*\d|'
    r'родил(?:ся|ась)|рождён(?:а)?|пациент(?:ка)?\s+\d|'
    # English
    r'birthday|date\s+of\s+birth|DOB|birth\s+date|born|'
    # Georgian
    r'დაბადების\s+თარიღი|დ[./]შ|დაბ\.|დაბადება'
    r')[:\s]*'
    r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}[./\-]\d{1,2}[./\-]\d{1,2})',
    re.IGNORECASE | re.UNICODE
)
# Also bare date after "рождения"
DOB_RE2 = re.compile(
    r'\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b'
)
# Year-only DOB: "год рождения: 1985" or "р. 1985"
DOB_YEAR_RE = re.compile(
    r'(?:год\s+рождения|г\.?\s*р\.?|birth\s*year)[:\s]*(\d{4})',
    re.IGNORECASE
)


@dataclass
class WaMessage:
    dt: datetime
    sender: str
    text: str
    attached: Optional[str] = None  # filename if attachment


@dataclass
class WaPatientChat:
    contact_name: str
    last_name: str
    first_name: str
    messages: List[WaMessage] = field(default_factory=list)
    media_files: List[str] = field(default_factory=list)   # absolute paths
    detected_dob: Optional[date] = None


def parse_contact_name(name: str) -> Optional[Tuple[str, str]]:
    """
    Returns (last_name, first_name) if contact name matches patient pattern.
    Otherwise returns None.
    """
    m = PATIENT_SEPARATOR_RE.match(name.strip())
    if m:
        return m.group(1), m.group(2)
    return None


def parse_dob(text: str) -> Optional[date]:
    """
    Try to extract date of birth from text.
    Only matches dates preceded by explicit DOB keywords — avoids
    mistaking analysis dates / appointment dates for DOB.
    Returns full date if found, or Jan 1 of birth year if only year found.
    """
    m = DOB_RE.search(text)
    if m:
        d = _parse_date_str(m.group(1))
        if d:
            return d
    # Try year-only fallback
    m2 = DOB_YEAR_RE.search(text)
    if m2:
        try:
            return date(int(m2.group(1)), 1, 1)
        except ValueError:
            pass
    return None


def _parse_date_str(s: str) -> Optional[date]:
    """Parse DD.MM.YYYY or DD/MM/YYYY or DD-MM-YYYY or YYYY-MM-DD."""
    s = s.strip()
    fmts = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y",
            "%Y-%m-%d", "%Y.%m.%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_wa_export(txt_path: str) -> Optional[WaPatientChat]:
    """
    Parse a WhatsApp exported .txt file.
    Returns WaPatientChat if the contact is a patient, else None.
    """
    txt_path = Path(txt_path)
    if not txt_path.exists():
        return None

    # Contact name is typically in the filename: "WhatsApp Chat with NAME.txt"
    stem = txt_path.stem
    contact_name = stem
    for prefix in ["WhatsApp Chat with ", "Переписка WhatsApp с ", "ВотсАпп "]:
        if stem.startswith(prefix):
            contact_name = stem[len(prefix):]
            break

    result = parse_contact_name(contact_name)
    if not result:
        return None

    last_name, first_name = result
    chat = WaPatientChat(
        contact_name=contact_name,
        last_name=last_name,
        first_name=first_name,
    )

    media_dir = txt_path.parent  # media files should be alongside the txt

    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = WA_LINE_RE.match(line.rstrip())
            if not m:
                continue
            date_str, time_str, sender, text = m.groups()
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%y %H:%M:%S")
            except ValueError:
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
                except ValueError:
                    dt = datetime.now()

            attached = None
            att_m = ATTACHED_RE.search(text)
            if att_m:
                fname = att_m.group(1).strip()
                fpath = media_dir / fname
                if fpath.exists():
                    chat.media_files.append(str(fpath))
                    attached = fname

            msg = WaMessage(dt=dt, sender=sender, text=text, attached=attached)
            chat.messages.append(msg)

            # Try to find DOB in messages
            if not chat.detected_dob:
                chat.detected_dob = parse_dob(text)

    return chat


_ZIP_MAX_MEMBER_MB  = 50    # max single file inside zip (MB)
_ZIP_MAX_TOTAL_MB   = 200   # max total uncompressed size (MB)
_ZIP_MAX_FILES      = 500   # max number of files in archive

def extract_zip_to_temp(zip_path: str) -> str:
    """
    Extract WhatsApp .zip export to a temp folder, return its path.
    Guards against zip bombs: checks per-member and total uncompressed size.
    """
    tmp = tempfile.mkdtemp(prefix="wa_import_")
    os.chmod(tmp, 0o700)  # private temp dir

    with zipfile.ZipFile(zip_path, "r") as z:
        members = z.infolist()
        if len(members) > _ZIP_MAX_FILES:
            raise ValueError(
                f"ZIP contains {len(members)} files (limit {_ZIP_MAX_FILES}) — possible zip bomb"
            )
        total_bytes = 0
        for info in members:
            # Path traversal guard
            member_path = os.path.normpath(info.filename)
            if member_path.startswith("..") or os.path.isabs(member_path):
                raise ValueError(f"ZIP path traversal attempt: {info.filename!r}")
            # Single-member size guard
            if info.file_size > _ZIP_MAX_MEMBER_MB * 1024 * 1024:
                raise ValueError(
                    f"ZIP member {info.filename!r} is {info.file_size//1048576}MB "
                    f"(limit {_ZIP_MAX_MEMBER_MB}MB)"
                )
            total_bytes += info.file_size
            if total_bytes > _ZIP_MAX_TOTAL_MB * 1024 * 1024:
                raise ValueError(
                    f"ZIP total uncompressed size exceeds {_ZIP_MAX_TOTAL_MB}MB — possible zip bomb"
                )
        z.extractall(tmp)
    return tmp


def scan_for_wa_exports(folder: str) -> List[WaPatientChat]:
    """
    Scan a folder for WhatsApp export files containing patient chats.
    Handles:
      - .txt files (direct WhatsApp export text)
      - .zip files (WhatsApp "Export Chat with Media" archives)
      - subfolders (already-extracted exports)
    """
    folder = Path(folder)
    chats = []
    temp_dirs = []

    # Handle .zip files first — extract them
    for zf in folder.glob("*.zip"):
        try:
            tmp = extract_zip_to_temp(str(zf))
            temp_dirs.append(tmp)
            for f in Path(tmp).rglob("*.txt"):
                chat = parse_wa_export(str(f))
                if chat:
                    # Tag with original zip name for reporting
                    chat.contact_name = chat.contact_name or zf.stem
                    chats.append(chat)
        except Exception as e:
            print(f"  [ZIP error: {zf.name}: {e}]")

    # Handle .txt files directly in folder and subfolders
    for f in folder.rglob("*.txt"):
        chat = parse_wa_export(str(f))
        if chat:
            chats.append(chat)

    # Cleanup temp dirs
    for tmp in temp_dirs:
        shutil.rmtree(tmp, ignore_errors=True)

    return chats


def make_folder_name(last_name: str, first_name: str, dob: Optional[date]) -> str:
    """Build patient folder name: SURNAME_NAME_YYYY_MM_DD (original script preserved)"""
    base = f"{last_name}_{first_name}"
    if dob:
        return f"{base}_{dob.year:04d}_{dob.month:02d}_{dob.day:02d}"
    # If no DOB, use today as folder creation date
    today = date.today()
    return f"{base}_{today.year:04d}_{today.month:02d}_{today.day:02d}"


def import_chat_to_documents(chat: WaPatientChat,
                              documents_dir: str = DOCUMENTS_DIR) -> str:
    """
    Create/update patient folder from WhatsApp chat data.
    Returns path to the patient folder.
    """
    folder_name = make_folder_name(chat.last_name, chat.first_name, chat.detected_dob)
    folder_path = Path(documents_dir) / folder_name

    # Check if a folder for this patient already exists (different date)
    existing = _find_existing_folder(chat.last_name, chat.first_name, documents_dir)
    if existing:
        folder_path = Path(existing)
    else:
        folder_path.mkdir(parents=True, exist_ok=True)

    # Write chat transcript
    chat_file = folder_path / "whatsapp_chat.txt"
    with open(chat_file, "w", encoding="utf-8") as f:
        f.write(f"ПАЦИЕНТ: {chat.last_name} {chat.first_name}\n")
        if chat.detected_dob:
            f.write(f"ДАТА РОЖДЕНИЯ: {chat.detected_dob.strftime('%d.%m.%Y')}\n")
        f.write(f"СООБЩЕНИЙ: {len(chat.messages)}\n")
        f.write("=" * 60 + "\n\n")
        for msg in chat.messages:
            f.write(f"[{msg.dt.strftime('%d.%m.%Y %H:%M')}] {msg.sender}:\n")
            f.write(f"{msg.text}\n\n")

    # Copy media files
    for media_path in chat.media_files:
        src = Path(media_path)
        dst = folder_path / src.name
        if not dst.exists():
            shutil.copy2(src, dst)

    return str(folder_path)


def _find_existing_folder(last_name: str, first_name: str,
                           documents_dir: str) -> Optional[str]:
    """Find existing patient folder regardless of date suffix."""
    prefix = f"{last_name}_{first_name}_"
    docs = Path(documents_dir)
    if not docs.exists():
        return None
    for d in docs.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            return str(d)
    return None


def extract_dob_from_analyses(folder_path: str) -> Optional[date]:
    """
    Scan PDF and OCR text files in patient folder to find DOB.
    """
    import glob
    folder = Path(folder_path)

    # Check whatsapp_chat.txt
    chat_file = folder / "whatsapp_chat.txt"
    if chat_file.exists():
        text = chat_file.read_text(encoding="utf-8", errors="replace")
        dob = parse_dob(text)
        if dob:
            return dob

    # Check text files
    for txt in folder.glob("*.txt"):
        text = txt.read_text(encoding="utf-8", errors="replace")
        dob = parse_dob(text)
        if dob:
            return dob

    # Check OCR'd text
    for ocr_file in folder.glob("*_ocr.txt"):
        text = ocr_file.read_text(encoding="utf-8", errors="replace")
        dob = parse_dob(text)
        if dob:
            return dob

    # Try PDFs
    try:
        import pdfplumber
        for pdf in folder.glob("*.pdf"):
            try:
                with pdfplumber.open(str(pdf)) as p:
                    for page in p.pages[:3]:
                        text = page.extract_text() or ""
                        dob = parse_dob(text)
                        if dob:
                            return dob
            except Exception:
                pass
    except ImportError:
        pass

    return None
