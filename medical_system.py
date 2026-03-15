#!/usr/bin/env python3
"""
Integrative Medicine AI System
================================
Self-developing digital specialist for Dr. Jaba Tkemaladze.

Features:
  • Patient record management (~/AIM/Patients/)
  • Lab analysis with deviations + diagnosis suggestions
  • WhatsApp chat import (patients marked with P/П/პ)
  • OCR of medical screenshots
  • Treatment recommendations (integrative medicine)
  • Self-learning: builds knowledge base from each patient

Run: python3 medical_system.py
"""

import os
import sys
import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict

# ── Path setup ─────────────────────────────────────────────────
AI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AI_DIR)

VENV_SITE = os.path.expanduser("~/AIM/venv/lib/python3.*/site-packages")
import glob as _glob
_sp = _glob.glob(VENV_SITE)
if _sp:
    sys.path.insert(0, _sp[0])

from config import (PATIENTS_DIR as DOCUMENTS_DIR, INBOX_DIR,
                    KNOWLEDGE_FILE, MODEL, get_logger)
log = get_logger("medical_system")

# ── LLM ───────────────────────────────────────────────────────
try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

SYSTEM_PROMPT = """Ты — цифровой специалист по интегративной медицине.
Пациенты доктора Джаба Ткемаладзе (Dr. Jaba Tkemaladze).

Принципы интегративной медицины которыми ты руководствуешься:
- Болезнь как адаптивный ответ организма — не только патология, но и сигнал
- Комплексный подход: доказательная медицина + нутрициология + психосоматика + образ жизни
- Работа с причиной, а не только симптомом
- Персонализация лечения под конкретного пациента

Языки пациентов: русский, грузинский, казахский, английский.
Отвечай на русском языке, структурированно, с заголовками.
"""


def ask_llm(prompt: str, system: str = SYSTEM_PROMPT,
            max_tokens: int = 2048) -> str:
    if not HAS_OLLAMA:
        return "[Ollama не установлен]"
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        r = ollama.chat(model=MODEL, messages=messages,
                        options={"temperature": 0.3, "num_predict": max_tokens})
        return r["message"]["content"].strip()
    except Exception as e:
        return f"[LLM error: {e}]"


# ── Knowledge base (self-learning) ────────────────────────────

class MedicalKnowledge:
    """
    Accumulates findings across patients.
    Stores: patterns (symptom→diagnosis), outcome notes, treatment efficacy.
    """

    def __init__(self):
        self.data: Dict = self._load()

    def _load(self) -> Dict:
        if os.path.exists(KNOWLEDGE_FILE):
            try:
                with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"patterns": {}, "treatments": {}, "notes": [], "patient_count": 0}

    def save(self):
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def record_patient_analysis(self, patient_name: str,
                                 diagnoses: List[str],
                                 treatments: List[str],
                                 outcome_notes: str = ""):
        """Called after each patient analysis to build up knowledge."""
        self.data["patient_count"] += 1

        for dx in diagnoses:
            if dx not in self.data["patterns"]:
                self.data["patterns"][dx] = {"count": 0, "treatments": []}
            self.data["patterns"][dx]["count"] += 1

        for tx in treatments:
            if tx not in self.data["treatments"]:
                self.data["treatments"][tx] = {"count": 0, "diagnoses": []}
            self.data["treatments"][tx]["count"] += 1

        if outcome_notes:
            self.data["notes"].append({
                "patient": patient_name,
                "date": date.today().isoformat(),
                "note": outcome_notes[:500],
            })
            # Keep last 200 notes
            self.data["notes"] = self.data["notes"][-200:]

        self.save()

    def get_context(self) -> str:
        """Build a context summary from accumulated knowledge."""
        n = self.data.get("patient_count", 0)
        if n == 0:
            return ""
        top_dx = sorted(self.data.get("patterns", {}).items(),
                         key=lambda x: x[1]["count"], reverse=True)[:5]
        lines = [f"База знаний: {n} пациентов проанализировано."]
        if top_dx:
            lines.append("Частые диагнозы: " + ", ".join(f"{d}({c['count']})" for d, c in top_dx))
        return " ".join(lines)


knowledge = MedicalKnowledge()


# ── Patient management ─────────────────────────────────────────

def list_patients() -> List[Dict]:
    """Return list of patient folders with basic info."""
    docs = Path(DOCUMENTS_DIR)
    patients = []
    for d in sorted(docs.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        parts = d.name.split("_")
        if len(parts) >= 2:
            info = {
                "folder": str(d),
                "name": f"{parts[0]} {parts[1]}",
                "folder_name": d.name,
            }
            if len(parts) >= 5:
                try:
                    info["dob"] = f"{parts[4]}.{parts[3]}.{parts[2]}"
                except Exception:
                    pass
            patients.append(info)
    return patients


def analyze_patient(folder_path: str, force: bool = False) -> str:
    """Run full intake pipeline on patient folder."""
    from patient_intake import process_patient_folder
    return process_patient_folder(folder_path, force=force)


def show_patient_analysis(folder_path: str) -> str:
    """Return the AI analysis for a patient."""
    folder = Path(folder_path)
    analysis_file = folder / "_ai_analysis.txt"
    if analysis_file.exists():
        return analysis_file.read_text(encoding="utf-8", errors="replace")
    return "Анализ не найден. Запустите: analyze_patient()"


def analyze_labs_only(folder_path: str) -> str:
    """Quick lab analysis using lab_parser + diagnosis_engine."""
    folder = Path(folder_path)
    all_text = ""

    # Collect text from PDFs and OCR files
    for f in folder.glob("*_text.txt"):
        all_text += f.read_text(encoding="utf-8", errors="replace") + "\n"
    for f in folder.glob("*_ocr.txt"):
        all_text += f.read_text(encoding="utf-8", errors="replace") + "\n"

    if not all_text.strip():
        return "Нет обработанных данных. Сначала запустите intake pipeline."

    try:
        from lab_parser import extract_from_text
        from diagnosis_engine import run_diagnosis
        from treatment_recommender import get_treatments

        results = extract_from_text(all_text)
        if not results:
            return "Лабораторные показатели не найдены в данных."

        lines = ["ЛАБОРАТОРНЫЕ ПОКАЗАТЕЛИ:\n"]
        abnormal = []
        for r in results:
            icon = {"normal": "✓", "low": "↓", "high": "↑",
                    "critical_low": "⚠↓", "critical_high": "⚠↑"}.get(r.status, "?")
            line = f"  {icon} {r.param_id}: {r.value} {r.unit}  [{r.ref_range}]"
            if r.interpretation:
                line += f"  — {r.interpretation}"
            lines.append(line)
            if r.status not in ("normal", "unknown"):
                abnormal.append(r)

        if abnormal:
            lines.append(f"\nОТКЛОНЕНИЙ: {len(abnormal)}")

        # Diagnosis
        try:
            dx_list = run_diagnosis(results, symptoms=[])
            if dx_list:
                lines.append("\nДИФФЕРЕНЦИАЛЬНЫЙ ДИАГНОЗ (Байес):")
                for dx in dx_list[:3]:
                    lines.append(f"  • {dx.disease_name} [{dx.icd10}] "
                                  f"вероятность: {dx.probability:.0%}")
                    # Get treatment for top diagnosis
                    txs = get_treatments(dx.icd10)
                    if txs:
                        lines.append(f"    Лечение ({txs[0].line}): "
                                      + ", ".join(d.name for d in txs[0].drugs[:3]))
        except Exception:
            pass

        return "\n".join(lines)

    except Exception as e:
        return f"Ошибка анализа: {e}"


# ── Interactive CLI ────────────────────────────────────────────

def print_banner():
    print("\n" + "═" * 60)
    print("   ИНТЕГРАТИВНАЯ МЕДИЦИНА — AI СИСТЕМА")
    print("   Dr. Jaba Tkemaladze")
    print("═" * 60)
    kb = knowledge.get_context()
    if kb:
        print(f"   {kb}")
    print()


def print_menu():
    print("МЕНЮ:")
    print("  1. Список пациентов")
    print("  2. Обработать пациента (OCR + PDF + AI анализ)")
    print("  3. Обработать всех пациентов")
    print("  4. Показать анализ пациента")
    print("  5. Быстрый анализ лабораторий")
    print("  6. Импорт из WhatsApp (INBOX)")
    print("  7. Новый чат с AI-специалистом")
    print("  8. Список отклонений у всех пациентов")
    print("  q. Выход")


def run_interactive():
    print_banner()

    patients = list_patients()
    selected_folder = None

    while True:
        print_menu()
        choice = input("\nВыбор: ").strip().lower()

        if choice == "q":
            break

        elif choice == "1":
            patients = list_patients()
            print(f"\nПациентов: {len(patients)}")
            for i, p in enumerate(patients, 1):
                dob = p.get("dob", "?")
                print(f"  {i:2}. {p['name']}  (р. {dob})")

        elif choice == "2":
            patients = list_patients()
            if not patients:
                print("Нет пациентов.")
                continue
            for i, p in enumerate(patients, 1):
                print(f"  {i}. {p['name']}")
            try:
                idx = int(input("Номер пациента: ")) - 1
                selected_folder = patients[idx]["folder"]
                force = input("Принудительный пересчёт? (y/N): ").strip().lower() == "y"
                print(f"\nОбработка: {patients[idx]['name']}...")
                result = analyze_patient(selected_folder, force=force)
                print(f"Готово: {result}")
            except (ValueError, IndexError):
                print("Неверный выбор.")

        elif choice == "3":
            confirm = input("Обработать всех пациентов? (y/N): ").strip().lower()
            if confirm == "y":
                force = input("Принудительный пересчёт? (y/N): ").strip().lower() == "y"
                from patient_intake import process_all_patients
                count = process_all_patients(force=force)
                print(f"\n✓ Обработано: {count}")

        elif choice == "4":
            patients = list_patients()
            for i, p in enumerate(patients, 1):
                print(f"  {i}. {p['name']}")
            try:
                idx = int(input("Номер пациента: ")) - 1
                selected_folder = patients[idx]["folder"]
                text = show_patient_analysis(selected_folder)
                print("\n" + "─" * 60)
                print(text[:4000])
                if len(text) > 4000:
                    print(f"\n... (ещё {len(text)-4000} символов)")
            except (ValueError, IndexError):
                print("Неверный выбор.")

        elif choice == "5":
            patients = list_patients()
            for i, p in enumerate(patients, 1):
                print(f"  {i}. {p['name']}")
            try:
                idx = int(input("Номер пациента: ")) - 1
                selected_folder = patients[idx]["folder"]
                result = analyze_labs_only(selected_folder)
                print("\n" + result)
            except (ValueError, IndexError):
                print("Неверный выбор.")

        elif choice == "6":
            from patient_intake import process_inbox, INBOX_DIR
            print(f"\nПроверка INBOX: {INBOX_DIR}")
            process_inbox()

        elif choice == "7":
            print("\nЧат с AI-специалистом (введите 'exit' для выхода)")
            print("Контекст: интегративная медицина, Dr. Jaba Tkemaladze")
            history = []
            kb_ctx = knowledge.get_context()
            sys_msg = SYSTEM_PROMPT
            if kb_ctx:
                sys_msg += f"\n\nБаза знаний: {kb_ctx}"

            while True:
                user_input = input("\nВы: ").strip()
                if user_input.lower() in ("exit", "выход", "quit"):
                    break
                if not user_input:
                    continue

                history.append({"role": "user", "content": user_input})
                messages = [{"role": "system", "content": sys_msg}] + history[-10:]

                try:
                    r = ollama.chat(model=MODEL, messages=messages,
                                    options={"temperature": 0.4, "num_predict": 1024})
                    reply = r["message"]["content"].strip()
                    history.append({"role": "assistant", "content": reply})
                    print(f"\nAI: {reply}")
                except Exception as e:
                    print(f"\n[Ошибка: {e}]")

        elif choice == "8":
            print("\nАнализ отклонений у всех пациентов...")
            patients = list_patients()
            all_abnormal = []
            for p in patients:
                result = analyze_labs_only(p["folder"])
                if "↓" in result or "↑" in result or "⚠" in result:
                    all_abnormal.append(f"\n{p['name']}:\n" + result[:600])
            if all_abnormal:
                for block in all_abnormal:
                    print(block)
            else:
                print("Нет данных или отклонений не найдено.")
                print("Сначала обработайте пациентов (пункт 3).")

        else:
            print("Неверный выбор.")


# ── Entry point ────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Integrative Medicine AI System")
    parser.add_argument("--all", action="store_true", help="Process all patients and exit")
    parser.add_argument("--patient", type=str, help="Process specific patient folder and exit")
    parser.add_argument("--force", action="store_true", help="Force re-process")
    parser.add_argument("--import-inbox", action="store_true", help="Process INBOX and exit")
    args = parser.parse_args()

    if args.all:
        print_banner()
        from patient_intake import process_all_patients
        count = process_all_patients(force=args.force)
        print(f"\n✓ Обработано пациентов: {count}")
        return

    if args.patient:
        print_banner()
        result = analyze_patient(args.patient, force=args.force)
        print(result)
        return

    if args.import_inbox:
        print_banner()
        from patient_intake import process_inbox
        process_inbox()
        return

    run_interactive()


if __name__ == "__main__":
    main()
