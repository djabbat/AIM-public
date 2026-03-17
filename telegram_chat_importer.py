#!/usr/bin/env python3
"""
telegram_chat_importer.py — Импорт чатов Telegram в папки пациентов AIM.

Читает переписку с пациентом по дате начала и конца,
скачивает медиафайлы (фото, документы, голосовые),
сохраняет в ~/AIM/Patients/ФАМИЛИЯ_ИМЯ_YYYY_MM_DD/

Требует:
  pip install telethon

Первый запуск: авторизуется через код из Telegram (одноразово).
Сессия сохраняется в ~/AIM/tg_session.session — больше вводить не нужно.

Настройка:
  Получить api_id и api_hash: https://my.telegram.org/apps
  Записать в ~/.aim_env:
    TG_API_ID=1234567
    TG_API_HASH=abcdef1234567890abcdef1234567890
"""

from __future__ import annotations

import os
import sys
import re
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ─────────────────────────────────────────────────────────────────────────────

AIM_DIR     = Path(__file__).parent
SESSION_FILE = AIM_DIR / "tg_session"
ENV_FILE    = Path.home() / ".aim_env"


def _load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def get_credentials() -> tuple[int, str]:
    env = _load_env()
    api_id   = int(os.environ.get("TG_API_ID",   env.get("TG_API_ID",   0)))
    api_hash = os.environ.get("TG_API_HASH", env.get("TG_API_HASH", ""))
    if not api_id or not api_hash:
        print("\n⚠️  Нужны TG_API_ID и TG_API_HASH")
        print("1. Открой: https://my.telegram.org/apps")
        print("2. Создай приложение (любое название)")
        print(f"3. Добавь в файл {ENV_FILE}:")
        print("   TG_API_ID=1234567")
        print("   TG_API_HASH=abcdef...")
        sys.exit(1)
    return api_id, api_hash


# ─────────────────────────────────────────────────────────────────────────────
# Утилиты — имя пациента из контакта
# ─────────────────────────────────────────────────────────────────────────────

# Пациент распознаётся по разделителю P/П/პ в имени контакта
# Пример: "Robakidze P Nino" → surname=Robakidze, name=Nino
PATIENT_SEPARATOR = re.compile(r'\bP\b|\bП\b|პ', re.UNICODE)


def parse_patient_name(contact_name: str) -> tuple[str, str] | None:
    """
    Разбирает имя контакта на Фамилию и Имя.
    Форматы:
      "Robakidze P Nino"    → (Robakidze, Nino)
      "Ivanova П Anna"      → (Ivanova, Anna)
      "სახელი პ გვარი"     → (სახელი, გვარი)
      "Ivanova Anna"        → (Ivanova, Anna)  — без разделителя
    """
    parts = PATIENT_SEPARATOR.split(contact_name)
    if len(parts) == 2:
        surname = parts[0].strip()
        name    = parts[1].strip()
        if surname and name:
            return surname, name

    # Без разделителя: первое слово = фамилия, второе = имя
    words = contact_name.strip().split()
    if len(words) >= 2:
        return words[0], words[1]
    return None


def patient_folder_path(surname: str, name: str, dob: str | None = None) -> Path:
    """
    Возвращает путь к папке пациента.
    dob: 'YYYY-MM-DD' или None
    """
    from config import PATIENTS_DIR
    if dob:
        parts = dob.replace("/", "-").split("-")
        if len(parts) == 3:
            folder_name = f"{surname}_{name}_{parts[0]}_{parts[1]:>02}_{parts[2]:>02}"
        else:
            folder_name = f"{surname}_{name}_0000_00_00"
    else:
        folder_name = f"{surname}_{name}_0000_00_00"
    return Path(PATIENTS_DIR) / folder_name


# ─────────────────────────────────────────────────────────────────────────────
# Форматирование сообщений
# ─────────────────────────────────────────────────────────────────────────────

def format_message(msg, sender_name: str) -> str:
    """Форматирует одно сообщение Telegram в текст."""
    dt = msg.date.strftime("%Y-%m-%d %H:%M")
    text = ""
    if hasattr(msg, "text") and msg.text:
        text = msg.text
    elif hasattr(msg, "message") and msg.message:
        text = msg.message
    if hasattr(msg, "media") and msg.media:
        media_type = type(msg.media).__name__.replace("MessageMedia", "").lower()
        text += f" [медиа: {media_type}]"
    return f"[{dt}] {sender_name}: {text}"


# ─────────────────────────────────────────────────────────────────────────────
# Основной импортёр
# ─────────────────────────────────────────────────────────────────────────────

async def import_chat(
    contact_name: str,
    date_from: str,           # "YYYY-MM-DD"
    date_to:   str,           # "YYYY-MM-DD"
    download_media: bool = True,
    patient_dob:    str  = None,  # "YYYY-MM-DD" если известна
    run_intake:     bool = True,  # запустить AIM intake после импорта
) -> str:
    """
    Импортирует чат Telegram с пациентом за указанный период.

    contact_name : имя контакта в Telegram (как оно сохранено)
    date_from    : начало периода "2026-01-01"
    date_to      : конец периода  "2026-03-17"
    download_media: скачивать фото/документы/голосовые
    patient_dob  : дата рождения пациента (для правильного имени папки)
    run_intake   : автоматически запустить AIM анализ после импорта

    Возвращает путь к папке пациента.
    """
    try:
        from telethon import TelegramClient
        from telethon.tl.types import User, MessageMediaPhoto, MessageMediaDocument
    except ImportError:
        return "❌ Установи Telethon: pip install telethon"

    api_id, api_hash = get_credentials()

    # Разбор пациента
    patient = parse_patient_name(contact_name)
    if not patient:
        return f"❌ Не удалось определить пациента из имени: {contact_name}"
    surname, name = patient

    # Папка пациента
    folder = patient_folder_path(surname, name, patient_dob)
    folder.mkdir(parents=True, exist_ok=True)

    # Диапазон дат (UTC)
    dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dt_to   = datetime.strptime(date_to,   "%Y-%m-%d").replace(tzinfo=timezone.utc)
    # Включаем весь последний день
    dt_to   = dt_to.replace(hour=23, minute=59, second=59)

    print(f"Импорт чата: {contact_name} → {surname}_{name}")
    print(f"Период: {date_from} — {date_to}")
    print(f"Папка: {folder}")

    async with TelegramClient(str(SESSION_FILE), api_id, api_hash) as client:

        # Найти диалог по имени контакта
        target = None
        async for dialog in client.iter_dialogs():
            if contact_name.lower() in dialog.name.lower():
                target = dialog.entity
                print(f"Найден контакт: {dialog.name}")
                break

        if target is None:
            # Попробовать точное совпадение по частям имени
            async for dialog in client.iter_dialogs():
                words = contact_name.lower().split()
                if all(w in dialog.name.lower() for w in words if len(w) > 2):
                    target = dialog.entity
                    print(f"Найден контакт (частичное): {dialog.name}")
                    break

        if target is None:
            return f"❌ Контакт не найден: {contact_name}\nПроверь точное имя в Telegram."

        # Скачать сообщения за период
        messages = []
        media_dir = folder / "tg_media"
        if download_media:
            media_dir.mkdir(exist_ok=True)

        media_count = 0
        async for msg in client.iter_messages(target, offset_date=dt_to, reverse=False):
            if msg.date < dt_from:
                break
            if msg.date > dt_to:
                continue

            # Определить имя отправителя
            if msg.out:
                sender = "Доктор"
            else:
                sender = contact_name

            messages.append(format_message(msg, sender))

            # Скачать медиафайлы
            if download_media and msg.media:
                try:
                    if isinstance(msg.media, (MessageMediaPhoto, MessageMediaDocument)):
                        fname = await client.download_media(
                            msg.media,
                            file=str(media_dir) + "/"
                        )
                        if fname:
                            media_count += 1
                            # Переименовать с датой
                            old_path = Path(fname)
                            new_name = f"{msg.date.strftime('%Y%m%d_%H%M%S')}_{old_path.name}"
                            old_path.rename(media_dir / new_name)
                except Exception as e:
                    print(f"  Медиа не скачано: {e}")

        if not messages:
            return f"Сообщений за период {date_from}—{date_to} не найдено."

        # Сортировать по времени (oldest first)
        messages.reverse()

        # Сохранить чат в папку пациента
        chat_file = folder / "whatsapp_chat.txt"  # совместимый формат для whatsapp_importer
        existing = chat_file.read_text(encoding="utf-8") if chat_file.exists() else ""

        header = (f"\n\n=== Telegram чат: {contact_name} "
                  f"({date_from} — {date_to}) ===\n")
        new_content = header + "\n".join(messages)

        # Дедупликация: не дублировать если уже импортировали этот период
        if new_content[:50] not in existing:
            with open(chat_file, "a", encoding="utf-8") as f:
                f.write(new_content)

        # Сохранить метаданные импорта
        meta_file = folder / "tg_import_log.json"
        meta = []
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except Exception:
                pass
        meta.append({
            "contact": contact_name,
            "date_from": date_from,
            "date_to":   date_to,
            "messages":  len(messages),
            "media":     media_count,
            "imported_at": datetime.now().isoformat(),
        })
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

        print(f"\n✓ Импортировано: {len(messages)} сообщений, {media_count} медиафайлов")
        print(f"  → {chat_file}")

        # Запустить AIM intake (OCR + PDF + AI анализ)
        if run_intake:
            print("\nЗапуск AIM анализа...")
            try:
                from patient_intake import process_patient_folder
                result = process_patient_folder(str(folder))
                print(f"  AIM: {result}")
            except Exception as e:
                print(f"  AIM intake пропущен: {e}")

        return str(folder)


# ─────────────────────────────────────────────────────────────────────────────
# Список всех пациентских диалогов
# ─────────────────────────────────────────────────────────────────────────────

async def list_patient_dialogs() -> list[dict]:
    """Возвращает список диалогов в Telegram, похожих на пациентов (есть разделитель P/П/პ)."""
    try:
        from telethon import TelegramClient
    except ImportError:
        print("pip install telethon")
        return []

    api_id, api_hash = get_credentials()
    patients = []
    async with TelegramClient(str(SESSION_FILE), api_id, api_hash) as client:
        async for dialog in client.iter_dialogs():
            parsed = parse_patient_name(dialog.name)
            if parsed:
                patients.append({
                    "name": dialog.name,
                    "surname": parsed[0],
                    "first_name": parsed[1],
                    "last_message": dialog.date.strftime("%Y-%m-%d") if dialog.date else "",
                    "unread": dialog.unread_count,
                })
    return patients


# ─────────────────────────────────────────────────────────────────────────────
# Пакетный импорт — все пациенты за период
# ─────────────────────────────────────────────────────────────────────────────

async def import_all_patients(date_from: str, date_to: str,
                               download_media: bool = True) -> dict:
    """
    Импортирует чаты ВСЕХ пациентов (контакты с P/П/პ) за указанный период.
    Возвращает статистику.
    """
    patients = await list_patient_dialogs()
    print(f"Найдено пациентов в Telegram: {len(patients)}")

    stats = {"imported": 0, "skipped": 0, "errors": 0}
    for p in patients:
        print(f"\n→ {p['name']}")
        try:
            await import_chat(
                contact_name=p["name"],
                date_from=date_from,
                date_to=date_to,
                download_media=download_media,
                run_intake=False,  # запустим одним batch после
            )
            stats["imported"] += 1
        except Exception as e:
            print(f"  Ошибка: {e}")
            stats["errors"] += 1

    # Обработать всех пациентов одним проходом
    if stats["imported"] > 0:
        print("\nЗапуск AIM анализа для всех импортированных пациентов...")
        try:
            from patient_intake import process_all_patients
            process_all_patients()
        except Exception as e:
            print(f"Intake error: {e}")

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Импорт Telegram чатов пациентов в AIM"
    )
    parser.add_argument("--list",     action="store_true",
                        help="Показать все пациентские диалоги")
    parser.add_argument("--contact",  type=str,
                        help="Имя контакта в Telegram")
    parser.add_argument("--from",     dest="date_from", type=str,
                        help="Начало периода YYYY-MM-DD")
    parser.add_argument("--to",       dest="date_to", type=str,
                        help="Конец периода YYYY-MM-DD (по умолчанию — сегодня)")
    parser.add_argument("--all",      action="store_true",
                        help="Импортировать все пациентские чаты")
    parser.add_argument("--no-media", action="store_true",
                        help="Не скачивать медиафайлы")
    parser.add_argument("--dob",      type=str, default=None,
                        help="Дата рождения пациента YYYY-MM-DD")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    date_to = args.date_to or today

    if args.list:
        dialogs = asyncio.run(list_patient_dialogs())
        print(f"\nПациентов в Telegram: {len(dialogs)}")
        for d in dialogs:
            print(f"  {d['name']:<30} последнее: {d['last_message']}  непрочитано: {d['unread']}")
        return

    if args.all:
        if not args.date_from:
            print("Укажи --from YYYY-MM-DD")
            return
        stats = asyncio.run(import_all_patients(
            args.date_from, date_to,
            download_media=not args.no_media,
        ))
        print(f"\nГотово: {stats}")
        return

    if args.contact:
        if not args.date_from:
            print("Укажи --from YYYY-MM-DD")
            return
        folder = asyncio.run(import_chat(
            contact_name=args.contact,
            date_from=args.date_from,
            date_to=date_to,
            download_media=not args.no_media,
            patient_dob=args.dob,
        ))
        print(f"\nПапка пациента: {folder}")
        return

    # Интерактивный режим
    print("\nTelegram Chat Importer — AIM")
    print("─" * 40)
    print("1. Список пациентов в Telegram")
    print("2. Импорт одного пациента")
    print("3. Импорт всех пациентов за период")
    choice = input("\nВыбор: ").strip()

    if choice == "1":
        dialogs = asyncio.run(list_patient_dialogs())
        for d in dialogs:
            print(f"  {d['name']:<30} {d['last_message']}  непрочит: {d['unread']}")

    elif choice == "2":
        contact = input("Имя контакта: ").strip()
        date_from = input("С даты (YYYY-MM-DD): ").strip()
        date_to_in = input(f"По дату (Enter = {today}): ").strip() or today
        dob = input("Дата рождения пациента (Enter = пропустить): ").strip() or None
        no_media = input("Скачать медиафайлы? (Y/n): ").strip().lower() != "n"
        folder = asyncio.run(import_chat(contact, date_from, date_to_in,
                                          download_media=no_media, patient_dob=dob))
        print(f"\n→ {folder}")

    elif choice == "3":
        date_from = input("С даты (YYYY-MM-DD): ").strip()
        date_to_in = input(f"По дату (Enter = {today}): ").strip() or today
        no_media = input("Скачать медиафайлы? (Y/n): ").strip().lower() != "n"
        stats = asyncio.run(import_all_patients(date_from, date_to_in,
                                                 download_media=no_media))
        print(f"\nГотово: {stats}")


if __name__ == "__main__":
    main()
