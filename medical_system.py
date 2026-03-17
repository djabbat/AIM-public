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
from llm import ask_llm as _ask_llm_deepseek
import db as _db
_db.init_db()
try:
    from filelock import FileLock as _FileLock
    _KNOWLEDGE_LOCK = _FileLock(str(KNOWLEDGE_FILE) + ".lock")
except ImportError:
    import threading
    _KNOWLEDGE_LOCK = threading.Lock()  # type: ignore[assignment]
log = get_logger("medical_system")

# ── LLM ───────────────────────────────────────────────────────
from space_nutrition import NUTRITION_RULES_PROMPT

SYSTEM_PROMPT = """Ты — цифровой ассистент доктора Джаба Ткемаладзе (Dr. Jaba Tkemaladze), \
специалиста по интегративной медицине, Тбилиси.

РОЛЬ И ФИЛОСОФИЯ:
Ты сочетаешь доказательную медицину с интегративным подходом. Болезнь — это адаптивный \
ответ организма, а не только патология. Работай с причиной, не только с симптомом. \
Каждый пациент уникален: учитывай возраст, пол, образ жизни, психоэмоциональный фон, \
питание, культурный контекст (Грузия, Казахстан, Россия).

КЛИНИЧЕСКИЕ ПРИНЦИПЫ:
1. Дифференциальный диагноз — всегда перечисляй 2–4 наиболее вероятных варианта с обоснованием
2. Лабораторные отклонения — интерпретируй в контексте клиники, не изолированно
3. Нутрициология — добавки, дефициты, питание как первая линия при функциональных нарушениях
4. Психосоматика — стресс, сон, эмоциональный фон влияют на физиологию; спрашивай о них
5. Медикаменты — назначай с дозой, длительностью, контролем; предупреждай о побочных эффектах
6. Follow-up — каждая рекомендация должна иметь срок контроля и критерий эффективности

ФОРМАТ ОТВЕТА (всегда использовать эти разделы если применимо):
## Оценка ситуации
## Дифференциальный диагноз
## Лабораторные показатели
## Рекомендации
  ### Питание и образ жизни
  ### Нутрицевтики / добавки
  ### Медикаменты (если необходимо)
## Контроль и follow-up

ЯЗЫК: Отвечай на русском. Если пациент пишет на грузинском или казахском — понимай, \
но отвечай на русском (или на языке пациента если доктор попросит).
СТИЛЬ: Конкретно, без воды. Дозы — цифрами. Сроки — чёткими датами или неделями.
""" + NUTRITION_RULES_PROMPT


def ask_llm(prompt: str, system: str = SYSTEM_PROMPT,
            max_tokens: int = 2048) -> str:
    return _ask_llm_deepseek(prompt, system=system, max_tokens=max_tokens)


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
        return {"patterns": {}, "treatments": {}, "notes": [], "patient_count": 0, "lab_dynamics": {}}

    def save(self):
        with _KNOWLEDGE_LOCK:
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

    def record_lab_snapshot(self, patient_name: str, lab_results: list):
        """Store lab values over time for trend analysis."""
        today = date.today().isoformat()
        if "lab_dynamics" not in self.data:
            self.data["lab_dynamics"] = {}
        if patient_name not in self.data["lab_dynamics"]:
            self.data["lab_dynamics"][patient_name] = {}
        self.data["lab_dynamics"][patient_name][today] = {
            r.param_id: {"value": r.value, "unit": r.unit, "status": r.status}
            for r in lab_results
        }
        self.save()

    def get_lab_trend(self, patient_name: str, param_id: str) -> str:
        """Return trend string for a lab parameter: ↑↓→ over time."""
        history = self.data.get("lab_dynamics", {}).get(patient_name, {})
        if not history:
            return ""
        points = []
        for date_str in sorted(history.keys()):
            entry = history[date_str].get(param_id)
            if entry:
                points.append(f"{date_str}: {entry['value']} {entry['unit']} ({entry['status']})")
        return "\n".join(points) if points else ""

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
    """Return list of patients. Reads from SQLite DB (fast), fallback to filesystem."""
    try:
        rows = _db.list_patients()
        if rows:
            patients = []
            for r in rows:
                info = {
                    "folder": r["folder_path"],
                    "name": f"{r['surname']} {r['name']}",
                    "folder_name": Path(r["folder_path"]).name,
                    "id": r["id"],
                }
                if r["dob"]:
                    parts = r["dob"].split("-")
                    if len(parts) == 3:
                        info["dob"] = f"{parts[2]}.{parts[1]}.{parts[0]}"
                # Ze-статус из БД
                ze = _db.get_latest_ze(r["id"])
                if ze:
                    info["ze_v"]    = ze["ze_v"]
                    info["ze_state"] = ze["ze_state"]
                return patients
            return patients
    except Exception:
        pass

    # Fallback — файловая система
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


def search_patients_by_symptom(query: str) -> str:
    """
    Полнотекстовый поиск по диагнозам и анализам всех пациентов.
    Использует SQLite FTS5 по таблице diagnoses.
    Возвращает форматированный текст с результатами.
    """
    query = query.strip()
    if not query:
        return "Введите поисковый запрос."
    try:
        results = _db.search_diagnoses(query, limit=20)
        if not results:
            # Попробовать LIKE-поиск если FTS не нашёл
            results = _db.search_diagnoses(f'"{query}"', limit=20)
        if not results:
            return f"По запросу «{query}» ничего не найдено."

        lines = [f"Найдено совпадений: {len(results)} по запросу «{query}»\n"]
        seen_patients = set()
        for r in results:
            pid = r["patient_id"]
            patient_label = f"{r['surname']} {r['name']}"
            if patient_label not in seen_patients:
                seen_patients.add(patient_label)
                lines.append(f"─── {patient_label} ───")
            # Выдержка из диагноза (первые 300 символов)
            text = r["llm_text"] or ""
            # Найти фрагмент вокруг запроса
            idx = text.lower().find(query.lower())
            if idx >= 0:
                start = max(0, idx - 80)
                end   = min(len(text), idx + 200)
                snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
            else:
                snippet = text[:280]
            lines.append(f"  [{r['created_at'][:10]}] {snippet.strip()}\n")

        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка поиска: {e}"


def db_stats() -> str:
    """Статистика базы данных AIM."""
    try:
        conn = _db._connect()
        lines = ["База данных AIM:"]
        for table in ["patients", "lab_snapshots", "diagnoses", "ze_hrv", "knowledge", "processed_files"]:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            lines.append(f"  {table}: {n}")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка: {e}"


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
        from diagnosis_engine import bayesian_differential, format_differential, run_diagnosis_ai
        from treatment_recommender import get_protocols, format_treatment

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

        # Diagnosis: Bayesian + DeepSeek R1
        try:
            folder_name = Path(folder_path).name
            patient_name = " ".join(folder_name.split("_")[:2])
            lines.append(run_diagnosis_ai(results, symptom_text="", patient_name=patient_name))

            # Treatment protocols for top-3 diagnoses
            bayes = bayesian_differential(results)
            if bayes:
                top_icd = [d.disease.icd10 for d in bayes[:3]]
                protocols = get_protocols(top_icd)
                if protocols:
                    lines.append(format_treatment(protocols))
        except Exception as e:
            log.warning("Diagnosis error: %s", e)

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
    print("  9. 🔍 Поиск по симптому / диагнозу")
    print("  0. 📊 Статистика базы данных")
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
                ze_info = ""
                if p.get("ze_v") is not None:
                    state_icon = {"healthy": "💚", "stress": "🟡",
                                  "arrhythmia": "🔴", "tachyarrhythmia": "🔴",
                                  "bradyarrhythmia": "🟠"}.get(p.get("ze_state", ""), "⚪")
                    ze_info = f"  Ze:{p['ze_v']:.3f}{state_icon}"
                print(f"  {i:2}. {p['name']}  (р. {dob}){ze_info}")

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

                # для чата передаём историю через системный+user контекст
                full_prompt = "\n".join(
                    f"{'Врач' if m['role']=='user' else 'AI'}: {m['content']}"
                    for m in history[:-1]
                )
                if full_prompt:
                    full_prompt = "История диалога:\n" + full_prompt + "\n\n" + user_input
                else:
                    full_prompt = user_input
                reply = _ask_llm_deepseek(full_prompt, system=sys_msg,
                                          max_tokens=1024, temperature=0.4)
                history.append({"role": "assistant", "content": reply})
                print(f"\nAI: {reply}")

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

        elif choice == "9":
            query = input("\nПоиск (симптом, диагноз, препарат): ").strip()
            if query:
                result = search_patients_by_symptom(query)
                print("\n" + "─" * 60)
                print(result)

        elif choice == "0":
            print("\n" + db_stats())

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
