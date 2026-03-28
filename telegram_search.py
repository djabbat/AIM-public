#!/usr/bin/env python3
"""
telegram_search.py — Поиск по Telegram/WhatsApp чатам пациентов AIM.

Поддерживает:
  - Точный поиск:   "анализ крови"
  - Wildcard (*):   "*анализ*"  →  содержит "анализ"
                    "боль*"     →  начинается с "боль"
                    "*головн"   →  заканчивается на "головн"
  - Несколько слов: "боль голов*"  →  совпадение по ИЛИ

Результат: список SearchResult(patient, file, line_num, line, match_start, match_end)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

PATIENTS_DIR = Path.home() / "Desktop" / "AIM" / "Patients"

# Файлы чатов в каждой папке пациента (приоритет: первый найденный)
CHAT_FILENAMES = [
    "whatsapp_chat.txt",   # Telegram-импорт + WhatsApp
]


@dataclass
class SearchResult:
    patient:     str   # имя пациента (из папки)
    file:        Path  # путь к файлу
    line_num:    int
    line:        str   # оригинальная строка
    match_start: int   # позиция начала совпадения
    match_end:   int   # позиция конца совпадения


# ─────────────────────────────────────────────────────────────────────────────
# Преобразование wildcard-паттерна в regex
# ─────────────────────────────────────────────────────────────────────────────

def _wildcard_to_regex(pattern: str) -> re.Pattern:
    """
    Converts a wildcard pattern (using *) to a compiled case-insensitive regex.
    Examples:
      "*боль*"  → re.compile(r'(?i).*боль.*')
      "боль*"   → re.compile(r'(?i)боль.*')
      "*боль"   → re.compile(r'(?i).*боль')
      "анализ"  → re.compile(r'(?i)анализ')   # treated as contains
    """
    stripped = pattern.strip()
    if not stripped:
        return re.compile(r'(?i).*')

    # If no wildcard — treat as contains (*word*)
    if '*' not in stripped:
        escaped = re.escape(stripped)
        return re.compile(r'(?i)' + escaped)

    # Split on * and escape each segment
    parts = stripped.split('*')
    regex_parts = [re.escape(p) for p in parts]
    # Join with .* (each * becomes .*)
    pattern_re = r'.*'.join(regex_parts)
    return re.compile(r'(?i)' + pattern_re)


def _build_patterns(query: str) -> list[re.Pattern]:
    """
    Split query by spaces (multiple words = OR matching).
    Each token can be a wildcard pattern.
    """
    tokens = [t for t in query.strip().split() if t]
    if not tokens:
        return []
    return [_wildcard_to_regex(tok) for tok in tokens]


# ─────────────────────────────────────────────────────────────────────────────
# Основной поиск
# ─────────────────────────────────────────────────────────────────────────────

def search_chats(
    query: str,
    patients_dir: Path = PATIENTS_DIR,
    max_results: int = 500,
) -> list[SearchResult]:
    """
    Search all patient chat files for the given query.
    Returns up to max_results SearchResult objects.

    query supports:
      - plain text   : "анализ крови"      → lines containing анализ OR крови
      - wildcard     : "*боль*"            → lines containing боль
      - prefix       : "приём*"            → lines starting with приём
      - suffix       : "*усталость"        → lines ending with усталость
      - combination  : "*боль* *голова*"   → lines containing боль OR голова
    """
    patterns = _build_patterns(query)
    if not patterns:
        return []

    results: list[SearchResult] = []

    for patient_dir in sorted(patients_dir.iterdir()):
        if not patient_dir.is_dir():
            continue
        if patient_dir.name == "INBOX":
            continue

        patient_name = patient_dir.name.replace("_", " ").strip()

        for fname in CHAT_FILENAMES:
            chat_file = patient_dir / fname
            if not chat_file.exists():
                continue

            try:
                text = chat_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for line_num, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if not stripped:
                    continue

                # Check if any pattern matches
                for pat in patterns:
                    m = pat.search(stripped)
                    if m:
                        results.append(SearchResult(
                            patient=patient_name,
                            file=chat_file,
                            line_num=line_num,
                            line=stripped,
                            match_start=m.start(),
                            match_end=m.end(),
                        ))
                        break  # avoid duplicates if multiple patterns match same line

                if len(results) >= max_results:
                    return results

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Форматирование для терминала
# ─────────────────────────────────────────────────────────────────────────────

def format_results_text(results: list[SearchResult], query: str) -> str:
    """Format search results as plain text for terminal or textbox display."""
    if not results:
        return f"Результатов не найдено для: «{query}»"

    lines = [f"🔍 Поиск: «{query}» — найдено {len(results)} совпадений\n"]
    lines.append("─" * 60)

    current_patient = None
    for r in results:
        if r.patient != current_patient:
            current_patient = r.patient
            lines.append(f"\n👤 {r.patient}")
            lines.append("─" * 40)

        lines.append(f"  [{r.line_num:>4}]  {r.line}")

    lines.append(f"\n─── Итого: {len(results)} строк ───")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Терминальный интерфейс
# ─────────────────────────────────────────────────────────────────────────────

def run_terminal_search():
    """Interactive terminal search loop."""
    print("\n🔍 Поиск в Telegram/WhatsApp чатах пациентов")
    print("  Поддерживается wildcard *: '*анализ*', 'боль*', '*голов'")
    print("  Несколько слов = ИЛИ: 'боль усталость'")
    print("  Пустой запрос или 'q' — выход\n")

    while True:
        try:
            query = input("Запрос: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() == "q":
            break
        results = search_chats(query)
        print()
        print(format_results_text(results, query))
        print()
