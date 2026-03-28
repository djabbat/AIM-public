# -*- coding: utf-8 -*-
"""
AIM v6.0 — medical_system.py
Главный CLI-интерфейс интегративной медицины.

Patient names, diagnoses, notes, and all free-text fields may contain
Georgian (ქართული), Kazakh (Қазақша), Arabic (العربية), or any other
Unicode script. UTF-8 is enforced via config.py at import time.

Запуск:
    python3 medical_system.py
    python3 medical_system.py --all   # обработать всех пациентов
    python3 medical_system.py --lang ka
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Добавляем директорию проекта в путь
sys.path.insert(0, str(Path(__file__).parent))

from config import cfg
from i18n import t, set_lang, choose_language_interactive, get_lang
from db import init_db, fetchall, fetchone, execute, get_db

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aim.main")

# ============================================================================
# Версия и баннер
# ============================================================================

BANNER = r"""
    ___    ____  ___    _   __ ____
   /   |  /  _/ /   |  / | / // __ \
  / /| |  / /  / /| | /  |/ // / / /
 / ___ |_/ /  / ___ |/ /|  // /_/ /
/_/  |_/___/ /_/  |_/_/ |_//_____/

  Ассистент Интегративной Медицины
  Assistant of Integrative Medicine
  v6.0 | drjaba.com
"""

# ============================================================================
# Главный класс системы
# ============================================================================

class AIMSystem:
    """
    Главный координатор AIM v6.0.
    Управляет CLI-сессией врача.
    """

    def __init__(self, lang: str = None):
        self.lang = lang or cfg.DEFAULT_LANG
        set_lang(self.lang)
        self.running = True
        self.current_tenant_id = 1  # По умолчанию — drjaba

        # Lazy imports (модули могут быть ещё не созданы)
        self._llm = None
        self._patient_intake = None
        self._lab_parser = None
        self._diagnosis_engine = None
        self._treatment_recommender = None

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    def _get_llm(self):
        """Lazy load llm модуля"""
        if self._llm is None:
            try:
                from llm import ask_llm, ask_deep, ask_medical, check_llm_status
                self._llm = {
                    "ask": ask_llm,
                    "deep": ask_deep,
                    "medical": ask_medical,
                    "status": check_llm_status,
                }
            except ImportError as e:
                logger.warning(f"llm.py недоступен: {e}")
        return self._llm

    # ------------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------------

    def start(self):
        """Запустить AIM"""
        print(BANNER)
        print(t("welcome", version=cfg.VERSION))
        print(t("doctor"))
        print()

        # Проверка конфигурации
        warnings = cfg.validate()
        if warnings:
            for w in warnings:
                print(f"  ! {w}")
            print()

        # Инициализация БД
        try:
            init_db()
        except Exception as e:
            print(t("err_db", message=str(e)))
            logger.error(f"БД ошибка при запуске: {e}")

        # LLM статус
        llm_mod = self._get_llm()
        if llm_mod:
            status = llm_mod["status"]()
            backend = status.get("active_backend", "none")
            if backend == "none":
                print(f"  ! {t('ai_no_key')}")
            else:
                print(f"  LLM: {backend}")
            print()

        # Система информации
        patient_count = self._count_patients()
        print(t("system_info", version=cfg.VERSION, patients=patient_count, lang=self.lang))
        print()

        # Главный цикл
        self._main_loop()

    def _main_loop(self):
        """Главный цикл меню"""
        while self.running:
            self._show_menu()
            choice = input("\n>> ").strip()
            self._handle_choice(choice)

    def _show_menu(self):
        """Показать главное меню"""
        print("\n" + "="*50)
        print(t("version", version=cfg.VERSION))
        print("="*50)
        print(f"  1. {t('m1')}")
        print(f"  2. {t('m2')}")
        print(f"  3. {t('m3')}")
        print(f"  4. {t('m4')}")
        print(f"  5. {t('m5')}")
        print(f"  6. {t('m6')}")
        print(f"  7. {t('m7')}")
        print(f"  8. {t('m8')}")
        print(f"  9. {t('m9')}")
        print(f"  L. Язык / Language")
        print(f"  0. {t('mw')}")
        print("="*50)

    def _handle_choice(self, choice: str):
        """Обработать выбор меню"""
        handlers = {
            "1": self._menu_patients,
            "2": self._menu_new_patient,
            "3": self._menu_search_patient,
            "4": self._menu_ai_consultation,
            "5": self._menu_lab_analysis,
            "6": self._menu_bayesian_diagnosis,
            "7": self._menu_treatment,
            "8": self._menu_ze_hrv,
            "9": self._menu_reports,
            "l": self._menu_language,
            "L": self._menu_language,
            "0": self._exit,
            "": None,
        }

        handler = handlers.get(choice)
        if handler:
            try:
                handler()
            except KeyboardInterrupt:
                print("\n" + t("cancelled"))
            except Exception as e:
                print(t("error", message=str(e)))
                logger.error(f"Ошибка при выполнении [{choice}]: {e}", exc_info=True)
        elif choice:
            print(t("not_found"))

    # ------------------------------------------------------------------
    # Меню — Список пациентов
    # ------------------------------------------------------------------

    def _menu_patients(self):
        """Список пациентов"""
        print(f"\n{t('patients_title')}")
        patients = fetchall(
            "SELECT id, surname, first_name, birth_date, sex, ze_status, biological_age "
            "FROM patients WHERE tenant_id = ? ORDER BY surname, first_name",
            [self.current_tenant_id]
        )

        if not patients:
            print(t("no_patients"))
            return

        print(f"\n{'ID':>4}  {'Фамилия/Name':<25}  {'Возраст':>7}  {'Пол':>3}  {'Ze':>6}")
        print("-" * 55)
        for p in patients:
            age_str = self._calc_age(p.get("birth_date")) or "—"
            ze_str = f"{p['ze_status']:.0f}" if p.get("ze_status") else "—"
            print(f"  {p['id']:>3}  {p['surname']} {p['first_name']:<20}  {age_str:>7}  {p.get('sex','?'):>3}  {ze_str:>6}")

        print(f"\nВсего: {len(patients)}")

        # Выбор пациента
        pid_str = input("\nВведите ID пациента (или Enter назад): ").strip()
        if pid_str.isdigit():
            self._show_patient(int(pid_str))

    # ------------------------------------------------------------------
    # Меню — Новый пациент
    # ------------------------------------------------------------------

    def _menu_new_patient(self):
        """Создать нового пациента"""
        print(f"\n{t('m2')}")
        print("-" * 30)

        surname = input("Фамилия / Surname: ").strip()
        if not surname:
            print(t("cancelled"))
            return

        first_name = input("Имя / First name: ").strip()
        birth_date = input("Дата рождения (YYYY-MM-DD, Enter пропустить): ").strip() or None
        sex = input("Пол / Sex (M/F, Enter пропустить): ").strip().upper() or None
        if sex and sex not in ("M", "F"):
            sex = None
        phone = input("Телефон / Phone: ").strip() or None

        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO patients (tenant_id, surname, first_name, birth_date, sex, phone)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [self.current_tenant_id, surname, first_name, birth_date, sex, phone]
            )
            new_id = cursor.lastrowid

        # Аудит
        self._audit("create_patient", "patient", str(new_id))

        print(t("patient_created", name=f"{surname} {first_name}"))
        print(f"ID: {new_id}")

    # ------------------------------------------------------------------
    # Меню — Поиск пациента
    # ------------------------------------------------------------------

    def _menu_search_patient(self):
        """Поиск пациента"""
        query = input(t("search_prompt")).strip()
        if not query:
            return

        patients = fetchall(
            """SELECT id, surname, first_name, birth_date, sex, ze_status
               FROM patients
               WHERE tenant_id = ? AND (
                   surname LIKE ? OR first_name LIKE ? OR phone LIKE ?
               )
               ORDER BY surname""",
            [self.current_tenant_id, f"%{query}%", f"%{query}%", f"%{query}%"]
        )

        if not patients:
            print(t("not_found"))
            return

        print(f"\nНайдено: {len(patients)}")
        for p in patients:
            ze_str = f"Ze={p['ze_status']:.0f}" if p.get("ze_status") else ""
            print(f"  [{p['id']}] {p['surname']} {p['first_name']} {ze_str}")

        pid_str = input("\nВведите ID (или Enter назад): ").strip()
        if pid_str.isdigit():
            self._show_patient(int(pid_str))

    # ------------------------------------------------------------------
    # Меню — AI-консультация
    # ------------------------------------------------------------------

    def _menu_ai_consultation(self):
        """AI-консультация"""
        print(f"\n{t('ai_title')}")
        llm_mod = self._get_llm()

        if not llm_mod:
            print(t("ai_no_key"))
            return

        print("Введите вопрос или описание клинической ситуации.")
        print("Введите 'пациент' для консультации с контекстом пациента.")
        print("Для выхода нажмите Enter.\n")

        while True:
            prompt = input(t("ai_prompt")).strip()
            if not prompt:
                break

            print(f"\n{t('ai_thinking')}")
            try:
                if prompt.lower() in ("пациент", "patient"):
                    pid_str = input("ID пациента: ").strip()
                    if pid_str.isdigit():
                        patient = self._get_patient_data(int(pid_str))
                        question = input("Ваш вопрос: ").strip()
                        answer = llm_mod["medical"](patient, question, lang=self.lang)
                    else:
                        print(t("not_found"))
                        continue
                else:
                    answer = llm_mod["deep"](prompt, lang=self.lang)

                print(f"\n{'─'*50}")
                print(answer)
                print(f"{'─'*50}\n")
            except Exception as e:
                print(t("err_llm", message=str(e)))

    # ------------------------------------------------------------------
    # Меню — Лабораторные данные
    # ------------------------------------------------------------------

    def _menu_lab_analysis(self):
        """Анализ лабораторных данных"""
        print(f"\n{t('lab_title')}")
        llm_mod = self._get_llm()

        print("Вставьте текст с лабораторными данными пациента.")
        print("Введите 'END' на новой строке для завершения.\n")

        lines = []
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            lines.append(line)

        if not lines:
            print(t("cancelled"))
            return

        raw_text = "\n".join(lines)
        print(f"\n{t('lab_analyzing')}")

        prompt = (
            f"Проанализируй следующие лабораторные данные пациента. "
            f"Укажи отклонения от нормы, их клиническое значение, "
            f"рекомендации по дообследованию и коррекции.\n\n"
            f"Данные:\n{raw_text}"
        )

        if llm_mod:
            result = llm_mod["deep"](prompt, lang=self.lang)
            print(f"\n{'─'*50}")
            print(result)
            print(f"{'─'*50}")
        else:
            print(t("ai_no_key"))

    # ------------------------------------------------------------------
    # Меню — Байесовская диагностика
    # ------------------------------------------------------------------

    def _menu_bayesian_diagnosis(self):
        """Байесовская дифференциальная диагностика"""
        print(f"\n{t('diag_title')}")
        llm_mod = self._get_llm()

        symptoms_str = input(t("diag_symptoms")).strip()
        if not symptoms_str:
            return

        print(f"\n{t('diag_running')}")

        prompt = (
            f"Проведи дифференциальную диагностику для следующих симптомов, "
            f"используя байесовский подход. Перечисли наиболее вероятные диагнозы "
            f"с указанием вероятности (%), ключевых признаков и необходимых тестов.\n\n"
            f"Симптомы: {symptoms_str}"
        )

        if llm_mod:
            result = llm_mod["deep"](prompt, lang=self.lang)
            print(f"\n{'─'*50}")
            print(result)
            print(f"{'─'*50}")
        else:
            print(t("ai_no_key"))

    # ------------------------------------------------------------------
    # Меню — Протоколы лечения
    # ------------------------------------------------------------------

    def _menu_treatment(self):
        """Протоколы лечения"""
        print(f"\n{t('treatment_title')}")
        llm_mod = self._get_llm()

        print("Введите диагноз или состояние для получения протокола лечения:")
        diagnosis = input(">> ").strip()
        if not diagnosis:
            return

        print("\nУкажите контекст (Ze-статус, возраст, сопутствующие болезни, Enter пропустить):")
        context = input(">> ").strip()

        prompt = (
            f"Составь протокол интегративного лечения для: {diagnosis}.\n"
            f"Включи: основное лечение, нутрициологическую поддержку, "
            f"Ze-коррекционный компонент, мониторинг."
        )
        if context:
            prompt += f"\n\nКонтекст пациента: {context}"

        if llm_mod:
            result = llm_mod["deep"](prompt, lang=self.lang)
            print(f"\n{'─'*50}")
            print(result)
            print(f"{'─'*50}")
        else:
            print(t("ai_no_key"))

    # ------------------------------------------------------------------
    # Меню — Ze/HRV
    # ------------------------------------------------------------------

    def _menu_ze_hrv(self):
        """Ze-статус / HRV"""
        print(f"\n{t('ze_title')}")

        print("Введите SDNN (мс): ", end="")
        sdnn_str = input().strip()
        print("Введите RMSSD (мс): ", end="")
        rmssd_str = input().strip()
        print("Введите LF/HF ratio: ", end="")
        lf_hf_str = input().strip()

        try:
            sdnn = float(sdnn_str) if sdnn_str else None
            rmssd = float(rmssd_str) if rmssd_str else None
            lf_hf = float(lf_hf_str) if lf_hf_str else None
        except ValueError:
            print(t("error", message="Некорректные данные"))
            return

        # Простая оценка Ze-статуса по HRV
        ze_score = self._estimate_ze_from_hrv(sdnn, rmssd, lf_hf)

        print(f"\n{t('ze_status_label')}: {ze_score:.1f}/100")
        if ze_score >= 80:
            print(t("ze_high"))
        elif ze_score >= 50:
            print(t("ze_medium"))
        elif ze_score >= 20:
            print(t("ze_low"))
        else:
            print(t("ze_critical"))

        # AI-интерпретация
        llm_mod = self._get_llm()
        if llm_mod and sdnn:
            prompt = (
                f"Проинтерпретируй данные HRV пациента в контексте Ze-теории:\n"
                f"SDNN={sdnn} мс, RMSSD={rmssd} мс, LF/HF={lf_hf}.\n"
                f"Ze-статус (оценочно): {ze_score:.0f}/100.\n"
                f"Дай клиническую интерпретацию и рекомендации."
            )
            print(f"\n{t('ai_thinking')}")
            result = llm_mod["ask"](prompt, lang=self.lang)
            print(f"\n{result}")

    # ------------------------------------------------------------------
    # Меню — Отчёты
    # ------------------------------------------------------------------

    def _menu_reports(self):
        """Отчёты и экспорт"""
        print(f"\n{t('report_title')}")
        print("1. Сводка по пациентам")
        print("2. Статистика Ze-статуса")
        print("0. Назад")

        choice = input("\n>> ").strip()
        if choice == "1":
            self._report_patients_summary()
        elif choice == "2":
            self._report_ze_stats()

    # ------------------------------------------------------------------
    # Меню — Язык
    # ------------------------------------------------------------------

    def _menu_language(self):
        """Смена языка"""
        lang = choose_language_interactive()
        self.lang = lang
        print(t("success"))

    # ------------------------------------------------------------------
    # Выход
    # ------------------------------------------------------------------

    def _exit(self):
        """Выход из системы"""
        print(f"\n{t('exit')} AIM v{cfg.VERSION}")
        self.running = False

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _show_patient(self, patient_id: int):
        """Показать данные пациента"""
        patient = fetchone(
            "SELECT * FROM patients WHERE id = ? AND tenant_id = ?",
            [patient_id, self.current_tenant_id]
        )
        if not patient:
            print(t("not_found"))
            return

        print(f"\n{'='*50}")
        print(f"Пациент: {patient['surname']} {patient['first_name']}")
        if patient.get("birth_date"):
            age = self._calc_age(patient["birth_date"])
            print(f"Возраст: {age} лет ({patient['birth_date']})")
        if patient.get("sex"):
            print(f"Пол: {patient['sex']}")
        if patient.get("phone"):
            print(f"Телефон: {patient['phone']}")
        if patient.get("ze_status"):
            print(f"Ze-статус: {patient['ze_status']:.1f}/100")
        if patient.get("biological_age"):
            print(f"Биологический возраст: {patient['biological_age']:.0f} лет")

        # Последние анализы
        analyses = fetchall(
            "SELECT id, type, created_at, status FROM analyses "
            "WHERE patient_id = ? ORDER BY created_at DESC LIMIT 5",
            [patient_id]
        )
        if analyses:
            print(f"\nПоследние анализы ({len(analyses)}):")
            for a in analyses:
                print(f"  [{a['id'][:8]}] {a['type']} {a['created_at'][:10]} [{a['status']}]")

        # Диагнозы
        diagnoses = fetchall(
            "SELECT icd11_code, name, confidence, is_primary FROM diagnoses "
            "WHERE patient_id = ? ORDER BY is_primary DESC, confidence DESC LIMIT 5",
            [patient_id]
        )
        if diagnoses:
            print(f"\nДиагнозы:")
            for d in diagnoses:
                primary = " [основной]" if d.get("is_primary") else ""
                conf = f" ({d['confidence']*100:.0f}%)" if d.get("confidence") else ""
                code = f" [{d['icd11_code']}]" if d.get("icd11_code") else ""
                print(f"  {d['name']}{code}{conf}{primary}")

        print("="*50)

        # Подменю пациента
        print(f"\n  1. {t('mp3')} (AI)")
        print(f"  2. {t('mp4')}")
        print(f"  3. {t('mp7')}")
        print(f"  0. {t('mpb')}")

        sub = input("\n>> ").strip()
        if sub == "1":
            self._patient_ai_analysis(patient)
        elif sub == "2":
            self._patient_diagnoses(patient_id)
        elif sub == "3":
            self._patient_ze_history(patient_id)

        # Аудит
        self._audit("view_patient", "patient", str(patient_id))

    def _patient_ai_analysis(self, patient: dict):
        """AI-анализ данных пациента"""
        llm_mod = self._get_llm()
        if not llm_mod:
            print(t("ai_no_key"))
            return

        # Собираем данные
        analyses = fetchall(
            "SELECT type, lab_values, created_at FROM analyses "
            "WHERE patient_id = ? AND lab_values IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 3",
            [patient["id"]]
        )

        patient_data = {
            "name": f"{patient['surname']} {patient['first_name']}",
            "age": self._calc_age(patient.get("birth_date")),
            "sex": patient.get("sex"),
            "ze_status": patient.get("ze_status"),
        }

        if analyses:
            import json as _json
            try:
                patient_data["labs"] = _json.loads(analyses[0]["lab_values"])
            except Exception:
                pass

        print(f"\n{t('ai_thinking')}")
        question = "Проведи комплексный анализ состояния здоровья пациента с учётом Ze-теории."
        result = llm_mod["medical"](patient_data, question, lang=self.lang)
        print(f"\n{'─'*50}")
        print(result)
        print(f"{'─'*50}")

    def _patient_diagnoses(self, patient_id: int):
        """История диагнозов пациента"""
        diagnoses = fetchall(
            "SELECT * FROM diagnoses WHERE patient_id = ? ORDER BY created_at DESC",
            [patient_id]
        )
        if not diagnoses:
            print(t("not_found"))
            return

        for d in diagnoses:
            print(f"\n  {d['created_at'][:10]}: {d['name']}")
            if d.get("icd11_code"):
                print(f"    МКБ-11: {d['icd11_code']}")
            if d.get("ze_context"):
                print(f"    Ze: {d['ze_context']}")

    def _patient_ze_history(self, patient_id: int):
        """Ze/HRV история пациента"""
        readings = fetchall(
            "SELECT * FROM biosense_readings WHERE patient_id = ? ORDER BY measured_at DESC LIMIT 10",
            [patient_id]
        )
        if not readings:
            print(t("not_found"))
            return

        print(f"\n{'Дата':<12} {'Ze':>6} {'SDNN':>6} {'RMSSD':>7} {'LF/HF':>7}")
        print("-" * 45)
        for r in readings:
            date = r["measured_at"][:10] if r.get("measured_at") else "—"
            ze = f"{r['ze_status']:.0f}" if r.get("ze_status") else "—"
            sdnn = f"{r['sdnn']:.0f}" if r.get("sdnn") else "—"
            rmssd = f"{r['rmssd']:.0f}" if r.get("rmssd") else "—"
            lf_hf = f"{r['lf_hf_ratio']:.2f}" if r.get("lf_hf_ratio") else "—"
            print(f"  {date:<10} {ze:>6} {sdnn:>6} {rmssd:>7} {lf_hf:>7}")

    def _estimate_ze_from_hrv(
        self, sdnn: Optional[float], rmssd: Optional[float], lf_hf: Optional[float]
    ) -> float:
        """Простая оценка Ze-статуса по HRV (алгоритм v1)"""
        score = 50.0  # базовый Ze

        if sdnn is not None:
            if sdnn >= 100: score += 20
            elif sdnn >= 70: score += 15
            elif sdnn >= 50: score += 10
            elif sdnn >= 30: score += 0
            elif sdnn >= 20: score -= 10
            else: score -= 20

        if rmssd is not None:
            if rmssd >= 50: score += 10
            elif rmssd >= 30: score += 5
            elif rmssd >= 20: score += 0
            else: score -= 10

        if lf_hf is not None:
            if 1.0 <= lf_hf <= 2.0: score += 5
            elif 0.5 <= lf_hf < 1.0 or 2.0 < lf_hf <= 3.0: score += 0
            else: score -= 5

        return max(0.0, min(100.0, score))

    def _calc_age(self, birth_date_str: Optional[str]) -> Optional[int]:
        """Рассчитать возраст в годах"""
        if not birth_date_str:
            return None
        try:
            birth = datetime.strptime(birth_date_str[:10], "%Y-%m-%d")
            today = datetime.today()
            return (today - birth).days // 365
        except Exception:
            return None

    def _count_patients(self) -> int:
        """Количество пациентов в текущем тенанте"""
        try:
            row = fetchone(
                "SELECT COUNT(*) as cnt FROM patients WHERE tenant_id = ?",
                [self.current_tenant_id]
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def _get_patient_data(self, patient_id: int) -> dict:
        """Получить данные пациента для AI-запроса"""
        patient = fetchone("SELECT * FROM patients WHERE id = ?", [patient_id])
        if not patient:
            return {}
        data = dict(patient)
        data["age"] = self._calc_age(patient.get("birth_date"))
        return data

    def _audit(self, action: str, resource: str, resource_id: str, details: str = None):
        """Записать действие в аудит лог"""
        try:
            with get_db() as db:
                db.execute(
                    """INSERT INTO audit_log (tenant_id, action, resource, resource_id, details)
                       VALUES (?, ?, ?, ?, ?)""",
                    [self.current_tenant_id, action, resource, resource_id, details]
                )
        except Exception as e:
            logger.debug(f"Аудит ошибка: {e}")

    def _report_patients_summary(self):
        """Сводка по пациентам"""
        total = self._count_patients()
        with_ze = fetchone(
            "SELECT COUNT(*) as cnt FROM patients WHERE tenant_id = ? AND ze_status IS NOT NULL",
            [self.current_tenant_id]
        )
        avg_ze = fetchone(
            "SELECT AVG(ze_status) as avg FROM patients WHERE tenant_id = ? AND ze_status IS NOT NULL",
            [self.current_tenant_id]
        )

        print(f"\nСводка пациентов:")
        print(f"  Всего: {total}")
        print(f"  С Ze-статусом: {with_ze['cnt'] if with_ze else 0}")
        if avg_ze and avg_ze.get("avg"):
            print(f"  Средний Ze-статус: {avg_ze['avg']:.1f}")

        # Сохранить отчёт
        report_path = cfg.REPORTS_DIR / f"patients_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            report_path.write_text(
                f"Сводка пациентов AIM v{cfg.VERSION}\n"
                f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"Тенант: {self.current_tenant_id}\n\n"
                f"Всего пациентов: {total}\n"
                f"С Ze-статусом: {with_ze['cnt'] if with_ze else 0}\n"
            )
            print(t("report_generated", path=report_path))
        except Exception as e:
            logger.warning(f"Ошибка сохранения отчёта: {e}")

    def _report_ze_stats(self):
        """Статистика Ze-статуса"""
        stats = fetchall(
            """SELECT
                CASE
                    WHEN ze_status >= 80 THEN 'Высокий (80-100)'
                    WHEN ze_status >= 50 THEN 'Средний (50-80)'
                    WHEN ze_status >= 20 THEN 'Низкий (20-50)'
                    ELSE 'Критический (<20)'
                END as category,
                COUNT(*) as cnt
               FROM patients
               WHERE tenant_id = ? AND ze_status IS NOT NULL
               GROUP BY category""",
            [self.current_tenant_id]
        )

        print(f"\nСтатистика Ze-статуса:")
        for s in stats:
            print(f"  {s['category']}: {s['cnt']} пациентов")


# ============================================================================
# Пакетный режим
# ============================================================================

def process_all_patients():
    """Обработать всех пациентов в INBOX"""
    print("Обработка всех пациентов в INBOX...")
    inbox = cfg.PATIENTS_INBOX

    if not inbox.exists():
        print(f"INBOX не найден: {inbox}")
        return

    files = list(inbox.iterdir())
    if not files:
        print("INBOX пуст")
        return

    print(f"Найдено файлов: {len(files)}")

    # Пробуем импортировать patient_intake если есть
    try:
        from patient_intake import process_inbox
        process_inbox()
    except ImportError:
        print("patient_intake.py не найден — ручная обработка недоступна")
        print("Создайте patient_intake.py (Фаза 3 из TODO.md)")
        for f in files[:5]:
            print(f"  {f.name}")


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AIM v6.0 — Ассистент Интегративной Медицины",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Обработать всех пациентов в INBOX"
    )
    parser.add_argument(
        "--lang", choices=cfg.SUPPORTED_LANGS, default=cfg.DEFAULT_LANG,
        help="Язык интерфейса (ru/ka/en/kz)"
    )
    parser.add_argument(
        "--init-db", action="store_true",
        help="Инициализировать БД и выйти"
    )

    args = parser.parse_args()

    # Инициализация БД
    try:
        init_db()
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
        sys.exit(1)

    if args.init_db:
        print("БД инициализирована")
        sys.exit(0)

    if args.all:
        process_all_patients()
        return

    # Запуск интерактивной системы
    system = AIMSystem(lang=args.lang)
    try:
        system.start()
    except KeyboardInterrupt:
        print(f"\n\nAIM завершён.")
    finally:
        from db import close
        close()


if __name__ == "__main__":
    main()
