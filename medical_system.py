"""
AIM v7.0 — Точка входа
Гибридный медицинский ассистент: Groq · DeepSeek · KIMI · Qwen
"""

import sys
import logging
from pathlib import Path

from config import VERSION, APP_NAME, DEFAULT_LANG, SUPPORTED_LANGS, PATIENTS_DIR
from llm import ask, ask_deep, ask_long, providers_status
from i18n import t, lang_name, lang_menu
from db import list_patients, get_patient, upsert_patient, new_session, save_message, get_history
from agents import DoctorAgent, IntakeAgent, LangAgent
from agents.lang import LANG_NAMES

# ── Логирование ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/aim.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("aim")

# ── AIM App ───────────────────────────────────────────────────────────────────

class AIM:
    def __init__(self):
        self.lang = DEFAULT_LANG
        self.patient = None          # dict или None
        self.session_id = None       # int
        self.doctor = DoctorAgent()
        self.intake = IntakeAgent()
        self.lang_agent = LangAgent()

    # ── Утилиты ───────────────────────────────────────────────────────────────

    def print_header(self):
        print("\n" + "═" * 50)
        print(f"  {t('menu_title', self.lang)}")
        print(f"  v{VERSION}  |  {lang_name(self.lang)}")
        status = providers_status()
        icons = {k: "✓" if v else "✗" for k, v in status.items()}
        print(f"  LLM: Groq{icons['groq']} DS{icons['deepseek']} "
              f"KIMI{icons['kimi']} Qwen{icons['qwen']}")
        if self.patient:
            print(f"  Пациент: {self.patient['name']}")
        print("═" * 50)

    def menu(self):
        keys = ["m1","m2","m3","m4","m5","m6","m7","m8","mq"]
        for k in keys:
            print(f"  {t(k, self.lang)}")
        print()

    def input(self, prompt: str = "> ") -> str:
        try:
            return input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            return "0"

    # ── Пункты меню ───────────────────────────────────────────────────────────

    def new_patient(self):
        print("\n── Новый пациент ──")
        name = self.input("Имя (Фамилия Имя): ")
        if not name:
            return
        from datetime import date
        folder = name.upper().replace(" ", "_") + "_" + date.today().strftime("%Y_%m_%d")
        patient_dir = PATIENTS_DIR / folder
        patient_dir.mkdir(parents=True, exist_ok=True)
        pid = upsert_patient(folder, name, self.lang)
        self.patient = get_patient(folder)
        self.session_id = new_session(pid, self.lang)
        print(f"✓ Пациент создан: {folder}")

    def open_patient(self):
        print("\n── Открыть пациента ──")
        query = self.input("Поиск (имя/папка): ")
        from db import search_patients
        results = search_patients(query)
        if not results:
            print(t("patient_not_found", self.lang))
            return
        for i, p in enumerate(results[:10]):
            print(f"  {i+1}. {p['name']}  [{p['folder']}]")
        choice = self.input("Выбор: ")
        try:
            idx = int(choice) - 1
            self.patient = results[idx]
            self.session_id = new_session(self.patient["id"], self.lang)
            print(f"✓ Открыт: {self.patient['name']}")
        except (ValueError, IndexError):
            print("Отмена.")

    def lab_intake(self):
        print("\n── Анализы (OCR/PDF) ──")
        print("1. Загрузить файл  2. Сканировать INBOX  0. Назад")
        choice = self.input()
        if choice == "1":
            path_str = self.input("Путь к файлу (PDF/PNG/JPG/TXT): ")
            path = Path(path_str)
            if not path.exists():
                print(f"Файл не найден: {path}")
                return
            print(f"\n{t('thinking', self.lang)}")
            result = self.intake.process_file(path, lang=self.lang,
                                              session_id=self.session_id)
            print(f"\n{result}\n")
        elif choice == "2":
            print(f"\n{t('thinking', self.lang)}")
            items = self.intake.scan_inbox(lang=self.lang)
            if not items:
                print("INBOX пуст.")
                return
            for item in items:
                print(f"\n── {item['path'].name} [{item['type']}] ──")
                result = self.intake.analyze_labs(item["text"], lang=self.lang,
                                                  session_id=self.session_id)
                print(f"{result}\n")

    def diagnose(self):
        print("\n── Диагностика ──")
        complaint = self.input("Жалобы / симптомы: ")
        if not complaint:
            return
        context = f"Пациент: {self.patient['name']}\n" if self.patient else ""
        print(f"\n{t('thinking', self.lang)}")
        result = self.doctor.diagnose(complaint, patient_context=context,
                                      lang=self.lang, session_id=self.session_id)
        print(f"\n{result}\n")

    def treatment(self):
        print("\n── Протокол лечения ──")
        diagnosis = self.input("Диагноз: ")
        if not diagnosis:
            return
        context = f"Пациент: {self.patient['name']}\n" if self.patient else ""
        print(f"\n{t('thinking', self.lang)}")
        result = self.doctor.treatment_plan(diagnosis, patient_context=context,
                                            lang=self.lang, session_id=self.session_id)
        print(f"\n{result}\n")

    def translate(self):
        print("\n── Перевод документа ──")
        langs_str = "  ".join(f"{c}={LANG_NAMES.get(c,c)}"
                               for c in SUPPORTED_LANGS)
        print(f"Языки: {langs_str}")
        target = self.input("Целевой язык (код): ")
        if target not in SUPPORTED_LANGS:
            print("Неизвестный язык.")
            return
        print("Тип: 1=медицинский  2=научный  3=для пациента  4=общий")
        type_map = {"1": "medical", "2": "scientific", "3": "patient", "4": "general"}
        ttype = type_map.get(self.input("Тип [1]: ") or "1", "medical")
        text = self.input("Текст:\n")
        if not text:
            return
        print(f"\n{t('thinking', self.lang)}")
        result = self.lang_agent.translate(text, target_lang=target,
                                           translation_type=ttype,
                                           session_id=self.session_id)
        print(f"\n{result}\n")

    def consult(self):
        print("\n── AI-консультация (free chat) ──")
        print("(Enter для выхода)\n")
        if not self.session_id:
            self.session_id = new_session(None, self.lang)
        while True:
            user_input = self.input("Вы: ")
            if not user_input:
                break
            print(f"{t('thinking', self.lang)}")
            history = get_history(self.session_id, limit=6)
            result = self.doctor.chat(user_input, history=history,
                                      lang=self.lang, session_id=self.session_id)
            print(f"\nAIM: {result}\n")

    def settings(self):
        print("\n── Настройки ──")
        print("1. Сменить язык")
        print("2. Статус провайдеров")
        print("0. Назад")
        choice = self.input()
        if choice == "1":
            print(lang_menu())
            idx = self.input("Номер: ")
            try:
                self.lang = SUPPORTED_LANGS[int(idx) - 1]
                print(f"{t('lang_changed', self.lang)}: {lang_name(self.lang)}")
            except (ValueError, IndexError):
                print("Отмена.")
        elif choice == "2":
            print(f"\n{t('providers_status', self.lang)}:")
            for name, ok in providers_status().items():
                icon = "✓" if ok else "✗"
                print(f"  {icon} {name}")

    # ── Главный цикл ──────────────────────────────────────────────────────────

    def run(self):
        while True:
            self.print_header()
            self.menu()
            choice = self.input()
            if   choice == "1": self.new_patient()
            elif choice == "2": self.open_patient()
            elif choice == "3": self.lab_intake()
            elif choice == "4": self.diagnose()
            elif choice == "5": self.treatment()
            elif choice == "6": self.translate()
            elif choice == "7": self.consult()
            elif choice == "8": self.settings()
            elif choice == "0":
                print("Bye.")
                break
            else:
                print("?")

# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = AIM()
    app.run()
