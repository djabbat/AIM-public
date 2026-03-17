#!/usr/bin/env python3
"""
tg_desktop_importer.py — Парсер экспорта Telegram Desktop
==========================================================
Использование:
  1. Telegram Desktop → Settings → Advanced → Export Telegram data
     → Personal chats, Photos, Voice, Documents → JSON → ~/AIM/tg_export/
  2. python3 tg_desktop_importer.py --export ~/AIM/tg_export/
     Найдёт пациентов (P/П/პ в имени), скопирует в Patients/, запустит intake.

Опции:
  --export PATH   путь к папке экспорта (содержит result.json или chats/)
  --list          только показать найденных пациентов, не обрабатывать
  --dry-run       показать что будет сделано, без записи
  --from DATE     фильтр по дате начала (YYYY-MM-DD)
  --to   DATE     фильтр по дате конца   (YYYY-MM-DD)
  --intake        запустить patient_intake после импорта (по умолчанию: да)
  --no-intake     не запускать patient_intake
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, date
from pathlib import Path

AIM_DIR = Path(__file__).parent
sys.path.insert(0, str(AIM_DIR))

from config import PATIENTS_DIR, get_logger

log = get_logger("tg_desktop_importer")

# ── Patient name detection ────────────────────────────────────

PATIENT_MARKER = re.compile(r'\bP\b|\bП\b|პ', re.UNICODE)


def parse_patient_name(contact_name: str) -> tuple[str, str] | None:
    """
    'Иванов П Иван'   → ('ИВАНОВ', 'ИВАН')
    'Beridze პ Nino'  → ('BERIDZE', 'NINO')
    'ანნა პ'          → ('АННЯ', 'UNKNOWN')  (marker at end — firstname missing)
    Returns None if not a patient contact.
    """
    if not contact_name:
        return None
    parts = contact_name.strip().split()
    for i, part in enumerate(parts):
        if PATIENT_MARKER.fullmatch(part):
            surname = parts[i - 1].upper() if i > 0 else "UNKNOWN"
            firstname = parts[i + 1].upper() if i + 1 < len(parts) else surname
            if surname == "UNKNOWN" and firstname != "UNKNOWN":
                surname, firstname = firstname, "UNKNOWN"
            return (surname, firstname)
    return None


# ── Export structure detection ────────────────────────────────

def find_chat_files(export_dir: Path) -> list[Path]:
    """Find all messages.json files in export directory."""
    files = list(export_dir.rglob("messages.json"))
    if not files:
        # Some exports put everything in result.json
        result = export_dir / "result.json"
        if result.exists():
            files = [result]
    return files


def load_chat(messages_json: Path) -> dict | None:
    """Load and validate a chat JSON file. Repairs truncated exports."""
    try:
        content = messages_json.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"Cannot read {messages_json}: {e}")
        return None
    # Try parsing as-is first
    for suffix in ["", "\n    ]\n   }\n  ]\n }\n}", "\n]}]}"]:
        try:
            data = json.loads(content + suffix)
            if suffix:
                log.info(f"Repaired truncated JSON in {messages_json.name}")
            if "chats" in data:
                return data
            if "messages" in data:
                return data
            return None
        except json.JSONDecodeError:
            continue
    log.warning(f"Cannot parse {messages_json} (truncated or invalid JSON)")
    return None


# ── Date parsing ──────────────────────────────────────────────

def parse_msg_date(date_str: str) -> date | None:
    """Parse Telegram export date string → date."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt).date()
        except ValueError:
            continue
    return None


# ── Message formatting ────────────────────────────────────────

def format_message(msg: dict, chat_name: str) -> str | None:
    """Format a single Telegram message as WhatsApp-compatible line."""
    if msg.get("type") != "message":
        return None

    date_str = msg.get("date", "")
    dt = parse_msg_date(date_str)
    if dt:
        date_fmt = dt.strftime("%d.%m.%Y")
        time_part = date_str[11:16] if len(date_str) >= 16 else "00:00"
    else:
        date_fmt = "01.01.2000"
        time_part = "00:00"

    sender = msg.get("from") or "Unknown"

    # Text may be a string or a list of text entities
    text = msg.get("text", "")
    if isinstance(text, list):
        text = "".join(
            p if isinstance(p, str) else p.get("text", "")
            for p in text
        )
    text = str(text).strip()

    # Attach media references
    media_parts = []
    for key in ("photo", "file", "voice_message", "video_file", "sticker"):
        val = msg.get(key)
        if val:
            media_parts.append(f"[{key}: {val}]")

    content = text
    if media_parts:
        content = (text + " " + " ".join(media_parts)).strip()
    if not content:
        return None

    return f"{date_fmt}, {time_part} - {sender}: {content}"


# ── Media copying ─────────────────────────────────────────────

def copy_media(msg: dict, export_dir: Path, dest_dir: Path, date_prefix: str) -> list[Path]:
    """Copy media files from export dir to patient folder."""
    copied = []
    for key in ("photo", "file", "voice_message", "video_file"):
        rel = msg.get(key)
        if not rel:
            continue
        src = export_dir / rel
        if not src.exists():
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{date_prefix}_{src.name}"
        dest = dest_dir / dest_name
        try:
            shutil.copy2(src, dest)
            copied.append(dest)
        except Exception as e:
            log.warning(f"Cannot copy {src}: {e}")
    return copied


# ── Patient folder creation ───────────────────────────────────

def get_or_create_patient_folder(surname: str, firstname: str) -> Path:
    """Find existing patient folder or create new one (date=unknown)."""
    base = Path(PATIENTS_DIR)
    # Look for existing folder matching surname_firstname_*
    pattern = f"{surname}_{firstname}_"
    for d in base.iterdir():
        if d.is_dir() and d.name.upper().startswith(pattern):
            return d
    # Create new folder with today's date
    today = datetime.now().strftime("%Y_%m_%d")
    folder = base / f"{surname}_{firstname}_{today}"
    folder.mkdir(parents=True, exist_ok=True)
    log.info(f"Created patient folder: {folder.name}")
    return folder


# ── Process single chat ───────────────────────────────────────

def process_chat(
    chat: dict,
    export_dir: Path,
    date_from: date | None,
    date_to: date | None,
    dry_run: bool,
) -> dict | None:
    """
    Process one chat dict. Returns result info or None if not a patient.
    """
    name = chat.get("name", "")
    patient = parse_patient_name(name)
    if not patient:
        return None

    surname, firstname = patient
    messages = chat.get("messages", [])

    # Filter by date
    filtered = []
    for msg in messages:
        if msg.get("type") != "message":
            continue
        d = parse_msg_date(msg.get("date", ""))
        if date_from and d and d < date_from:
            continue
        if date_to and d and d > date_to:
            continue
        filtered.append(msg)

    if not filtered:
        return {"name": name, "patient": f"{surname} {firstname}", "messages": 0, "skipped": "no messages in date range"}

    log.info(f"Patient: {name} → {surname} {firstname} ({len(filtered)} messages)")

    if dry_run:
        return {"name": name, "patient": f"{surname} {firstname}", "messages": len(filtered), "dry_run": True}

    # Write to patient folder
    folder = get_or_create_patient_folder(surname, firstname)
    media_dir = folder / "tg_media"

    lines = [f"# Telegram export: {name}", f"# Imported: {datetime.now().isoformat()}", ""]
    media_count = 0

    for msg in filtered:
        line = format_message(msg, name)
        if line:
            lines.append(line)
        # Copy media
        d = parse_msg_date(msg.get("date", ""))
        prefix = d.strftime("%Y%m%d") if d else "00000000"
        copied = copy_media(msg, export_dir, media_dir, prefix)
        media_count += len(copied)

    # Save as whatsapp_chat.txt (compatible with whatsapp_importer.py)
    chat_file = folder / "whatsapp_chat.txt"
    existing = ""
    if chat_file.exists():
        existing = chat_file.read_text(encoding="utf-8")

    new_content = "\n".join(lines)
    if new_content not in existing:
        with open(chat_file, "a", encoding="utf-8") as f:
            f.write("\n" + new_content)

    # Save import log
    log_file = folder / "tg_import_log.json"
    log_data = {
        "imported_at": datetime.now().isoformat(),
        "source": "telegram_desktop_export",
        "contact_name": name,
        "messages": len(filtered),
        "media_files": media_count,
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    }
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    return {
        "name": name,
        "patient": f"{surname} {firstname}",
        "folder": str(folder),
        "messages": len(filtered),
        "media": media_count,
    }


# ── Main ──────────────────────────────────────────────────────

def run(export_path: str, list_only: bool, dry_run: bool,
        date_from: date | None, date_to: date | None, run_intake: bool):

    export_dir = Path(export_path).expanduser().resolve()
    if not export_dir.exists():
        print(f"❌ Export directory not found: {export_dir}")
        sys.exit(1)

    print(f"📂 Export: {export_dir}")

    chat_files = find_chat_files(export_dir)
    if not chat_files:
        print("❌ No messages.json files found. Check export path.")
        sys.exit(1)

    print(f"🔍 Found {len(chat_files)} chat file(s). Scanning for patients...")

    all_chats = []
    for cf in chat_files:
        data = load_chat(cf)
        if not data:
            continue
        # result.json — multiple chats
        if "chats" in data:
            for chat in data["chats"].get("list", []):
                all_chats.append((chat, cf.parent))
        else:
            all_chats.append((data, cf.parent))

    print(f"   Total chats: {len(all_chats)}")

    results = []
    for chat, chat_export_dir in all_chats:
        name = chat.get("name", "")
        patient = parse_patient_name(name)
        if not patient:
            continue
        if list_only:
            print(f"  👤 {name} → {patient[0]} {patient[1]}")
            continue
        result = process_chat(chat, chat_export_dir, date_from, date_to, dry_run)
        if result:
            results.append(result)

    if list_only:
        return

    patients_found = len(results)
    if patients_found == 0:
        print("⚠️  No patients found (contacts with П/P/პ in name).")
        print("   Mark patients in Telegram contacts as: 'SURNAME П FIRSTNAME'")
        return

    print(f"\n✅ Imported {patients_found} patients:")
    for r in results:
        if r.get("dry_run"):
            print(f"  [DRY RUN] {r['patient']}: {r['messages']} messages")
        else:
            print(f"  ✓ {r['patient']}: {r['messages']} messages, {r.get('media', 0)} media → {r.get('folder', '')}")

    if not dry_run and run_intake:
        print("\n🏥 Running patient_intake --all ...")
        try:
            from patient_intake import process_all_patients
            process_all_patients()
            print("✅ Intake complete.")
        except Exception as e:
            print(f"⚠️  Intake error: {e}")
            print("   Run manually: python3 patient_intake.py --all")


def main():
    parser = argparse.ArgumentParser(description="Telegram Desktop export → AIM patients")
    parser.add_argument("--export", default="~/AIM/tg_export/", help="Path to Telegram export folder")
    parser.add_argument("--list", action="store_true", help="List patients only, don't import")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--from", dest="date_from", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--no-intake", action="store_true", help="Skip patient_intake after import")
    args = parser.parse_args()

    date_from = date.fromisoformat(args.date_from) if args.date_from else None
    date_to = date.fromisoformat(args.date_to) if args.date_to else None

    run(
        export_path=args.export,
        list_only=args.list,
        dry_run=args.dry_run,
        date_from=date_from,
        date_to=date_to,
        run_intake=not args.no_intake,
    )


if __name__ == "__main__":
    main()
