#!/usr/bin/env python3
"""
Interactive patient case history analysis system.
Dr. Jaba Tkemaladze — patient records from ~/Desktop/AIM/Patients/
"""

import os
import json
import ollama
from datetime import date

from medical_parser import load_all_patients, PatientRecord
from bayesian_medical import build_all, PatientBayesNet, GlobalBayesNet

# MODEL from config
from config import PATIENTS_DIR as DOCUMENTS_DIR, INBOX_DIR, get_logger


def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def ask_llm(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        r = ollama.chat(model=MODEL, messages=messages,
                        options={"temperature": 0.3, "num_predict": 1024})
        return r["message"]["content"].strip()
    except Exception as e:
        return f"[Ошибка LLM: {e}]"


def show_patients(patients: list):
    if not patients:
        print("  Нет пациентов в ~/Desktop/AIM/Patients/")
        return
    print(f"\nПациентов: {len(patients)}")
    for i, p in enumerate(patients, 1):
        n_entries = len(p.entries)
        print(f"  {i}. {p.full_name}  (открыта {p.opened_date}, записей: {n_entries})")


def show_patient_detail(record: PatientRecord):
    print_header(f"История болезни: {record.full_name}")
    print(f"Дата открытия: {record.opened_date}")
    print(f"Записей: {len(record.entries)}")
    print()
    for entry in record.entries:
        print(f"  [{entry.date}] Тип: {entry.entry_type}")
        if entry.history_notes:
            print("  Анамнез:")
            for n in entry.history_notes[:5]:
                print(f"    {n[:100]}")
        if entry.prescriptions:
            print(f"  Назначения ({len(entry.prescriptions)}):")
            for rx in entry.prescriptions[:5]:
                print(f"    {rx[:100]}")
        print()


def analyze_patient_with_llm(record: PatientRecord) -> str:
    """Ask LLM to analyze a patient record and provide summary."""
    system = (
        "Ты — медицинский ИИ-ассистент. Пациенты доктора Джабы Ткемаладзе. "
        "Анализируй истории болезней на основе предоставленных данных. "
        "Язык записей — грузинский. Отвечай на русском языке. "
        "Будь точен, используй медицинскую терминологию."
    )
    prompt = f"""Проанализируй историю болезни пациента.

Пациент: {record.full_name}
Дата открытия: {record.opened_date}

АНАМНЕЗ И ЖАЛОБЫ:
{chr(10).join(e.text[:500] for e in record.entries if e.entry_type in ('history', 'mixed'))[:2000]}

НАЗНАЧЕНИЯ:
{chr(10).join(e.text[:500] for e in record.entries if e.entry_type in ('prescription', 'mixed'))[:2000]}

Задача:
1. Кратко опиши основные проблемы пациента (системы органов)
2. Оцени логику назначений
3. Выдели ключевые паттерны (хронические состояния, психосоматика и т.д.)
4. Предложи вопросы для уточнения диагноза"""

    print(f"\n  Анализирую {record.full_name}...")
    return ask_llm(prompt, system)


def bayesian_menu(patient_nets: list, global_net: GlobalBayesNet):
    while True:
        print_header("БАЙЕСОВСКИЙ АНАЛИЗ")
        print("1. Показать глобальную структуру (все пациенты)")
        print("2. Показать структуру конкретного пациента")
        print("3. Запрос: P(лечение | симптом)")
        print("4. Сохранить структуры в JSON")
        print("5. Назад")

        choice = input("\n👉 ").strip()

        if choice == '1':
            print()
            print(global_net.summary())

        elif choice == '2':
            for i, pn in enumerate(patient_nets, 1):
                print(f"  {i}. {pn.full_name}")
            idx = input("Номер пациента: ").strip()
            try:
                pnet = patient_nets[int(idx) - 1]
                print()
                print(pnet.summary())
                print("\nCPT (P(лечение|симптом)):")
                cpt_dict = pnet.cpt.to_dict()
                for s, t_dict in cpt_dict.items():
                    print(f"  [{s}]:")
                    for t, vals in list(t_dict.items())[:5]:
                        print(f"    → {t}: p={vals['p']:.3f} (n={vals['count']})")
            except (IndexError, ValueError):
                print("❌ Неверный номер")

        elif choice == '3':
            symptom = input("Введите категорию симптома: ").strip()
            top = global_net.cpt.top_treatments(symptom, n=5)
            if top:
                print(f"\nP(лечение | симптом='{symptom}'):")
                for t, p in top:
                    print(f"  {t}: {p:.3f}")
            else:
                print(f"  Нет данных для симптома '{symptom}'")
            print("\nДоступные категории симптомов:")
            for s in sorted(global_net.cpt.table.keys()):
                print(f"  {s}")

        elif choice == '4':
            output = {
                "patients": [p.to_dict() for p in patient_nets],
                "global": global_net.to_dict(),
            }
            out_path = os.path.expanduser("~/Desktop/AIM/medical_bayes.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"  ✅ Сохранено: {out_path}")

        elif choice == '5':
            break


def chat_with_patient(record: PatientRecord):
    """Free-form dialogue about a specific patient."""
    system = (
        "Ты — медицинский ИИ-ассистент доктора Джабы Ткемаладзе. "
        f"Сейчас обсуждаем пациента: {record.full_name} (открыта {record.opened_date}). "
        f"История болезни (кратко):\n{record.raw_text[:3000]}\n\n"
        "Отвечай на русском языке, будь точен медицински."
    )
    print(f"\n  Режим диалога по пациенту {record.full_name}")
    print("  (введите 'выход' для выхода)\n")

    while True:
        q = input("  Вопрос: ").strip()
        if q.lower() in ("выход", "exit", "quit"):
            break
        if not q:
            continue
        answer = ask_llm(q, system)
        print(f"\n  ИИ: {answer}\n")


def main():
    print_header("АНАЛИЗ ИСТОРИЙ БОЛЕЗНЕЙ  |  д-р Джаба Ткемаладзе")
    print("  Загрузка пациентов...")
    patients = load_all_patients()

    print("  Построение байесовских структур...")
    patient_nets, global_net = build_all()

    while True:
        print_header("ГЛАВНОЕ МЕНЮ")
        show_patients(patients)
        print()
        print("A. AI-анализ конкретного пациента (LLM)")
        print("B. Диалог по пациенту")
        print("C. Байесовские структуры")
        print("D. Показать детали записей пациента")
        print("E. Обновить данные (пересканировать Documents)")
        print("Q. Выход")

        choice = input("\n👉 ").strip().upper()

        if choice == 'A':
            show_patients(patients)
            idx = input("Номер пациента: ").strip()
            try:
                record = patients[int(idx) - 1]
                result = analyze_patient_with_llm(record)
                print(f"\n{result}")
                # Save analysis
                out = os.path.join(record.folder_path, "_ai_analysis_v2.txt")
                with open(out, "w", encoding="utf-8") as f:
                    f.write(result)
                print(f"\n  ✅ Анализ сохранён: {out}")
            except (IndexError, ValueError):
                print("❌ Неверный номер")

        elif choice == 'B':
            show_patients(patients)
            idx = input("Номер пациента: ").strip()
            try:
                record = patients[int(idx) - 1]
                chat_with_patient(record)
            except (IndexError, ValueError):
                print("❌ Неверный номер")

        elif choice == 'C':
            bayesian_menu(patient_nets, global_net)

        elif choice == 'D':
            show_patients(patients)
            idx = input("Номер пациента: ").strip()
            try:
                show_patient_detail(patients[int(idx) - 1])
            except (IndexError, ValueError):
                print("❌ Неверный номер")

        elif choice == 'E':
            print("  Пересканирование...")
            patients = load_all_patients()
            patient_nets, global_net = build_all()
            print(f"  ✅ Загружено {len(patients)} пациентов")

        elif choice == 'Q':
            break

        input("\nНажмите Enter для продолжения...")


if __name__ == "__main__":
    main()
