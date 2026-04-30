"""
AIM v7.0 — Точка входа
Медицинский ассистент: DeepSeek (chat/reasoner) + Groq (fast).
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
from lab_reference import evaluate, format_result, categories, list_analytes, LAB_RANGES
from agents.ui_theme import ui, install_global_console

# Switch entire AIM CLI session to themed Rich console (cool/cyan, inverted
# Claude Code palette). Disable via AIM_NO_RICH=1.
install_global_console()

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
        from agents.ui_theme import ui
        status = providers_status()
        icons = {k: "✓" if v else "✗" for k, v in status.items()}
        kv = {
            "Version":  f"v{VERSION}",
            "Lang":     lang_name(self.lang),
            "LLM":      f"DeepSeek{icons['deepseek']}  Groq{icons['groq']}",
        }
        if self.patient:
            kv["Patient"] = self.patient['name']
        ui.banner(t('menu_title', self.lang), subtitle="Assistant of Integrative Medicine")
        ui.kv(kv)

    def menu(self):
        from agents.ui_theme import ui
        keys = ["m1","m2","m3","m4","m5","m6","m7","m8","m9","mq"]
        rows = [(t(k, self.lang),) for k in keys]
        rows.append(("T. Triage (kernel)  ·  L. Labs (kernel)  ·  X. Treatment (kernel)  ·  C. Chat (kernel)",))
        ui.table(["Действие"], rows)

    def input(self, prompt: str = "> ") -> str:
        try:
            return input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            return "0"

    # ── Пункты меню ───────────────────────────────────────────────────────────

    def new_patient(self):
        from agents.ui_theme import ui
        ui.divider("Новый пациент")
        name = self.input("Имя (Фамилия Имя): ")
        if not name:
            return
        dob = self.input("Дата рождения (YYYY-MM-DD, Enter если неизвестна): ")
        from db import format_patient_folder
        folder = format_patient_folder(name, dob or None)
        patient_dir = PATIENTS_DIR / folder
        patient_dir.mkdir(parents=True, exist_ok=True)
        pid = upsert_patient(folder, name, self.lang)
        self.patient = get_patient(folder)
        self.session_id = new_session(pid, self.lang)
        ui.success(f"Пациент создан: {folder}")
        if "2000_01_01" in folder and not dob:
            ui.warning("ДР неизвестна — placeholder. Узнать у врача и переименовать папку.")

    def open_patient(self):
        from agents.ui_theme import ui
        ui.divider("Открыть пациента")
        query = self.input("Поиск (имя/папка): ")
        from db import search_patients
        results = search_patients(query)
        if not results:
            ui.warning(t("patient_not_found", self.lang))
            return
        ui.table(["#", "Имя", "Папка"],
                 [(i+1, p['name'], p['folder']) for i, p in enumerate(results[:10])])
        choice = self.input("Выбор: ")
        try:
            idx = int(choice) - 1
            self.patient = results[idx]
            self.session_id = new_session(self.patient["id"], self.lang)
            ui.success(f"Открыт: {self.patient['name']}")
        except (ValueError, IndexError):
            ui.system("Отмена.")

    def lab_intake(self):
        print("\n── Анализы ──")
        print("1. Загрузить файл (PDF/фото)")
        print("2. Сканировать INBOX")
        print("3. Проверить нормы (ввести вручную)")
        print("0. Назад")
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
        elif choice == "3":
            self._lab_manual_check()

    def _lab_manual_check(self):
        """Ручная проверка лабораторных норм."""
        print("\n── Проверка лабораторных норм ──")
        cats = categories()
        for i, c in enumerate(cats, 1):
            print(f"  {i}. {c}")
        print("  0. Ввести код аналита напрямую")
        cat_choice = self.input("Категория: ")
        if cat_choice == "0":
            analytes_list = list(LAB_RANGES.keys())
        else:
            try:
                cat = cats[int(cat_choice) - 1]
                analytes_list = list_analytes(cat)
                print(f"\nАналиты в категории «{cat}»:")
                for i, a in enumerate(analytes_list, 1):
                    print(f"  {i:2}. {a:25} — {LAB_RANGES[a]['display']}")
            except (ValueError, IndexError):
                print("Отмена.")
                return

        values: dict[str, float] = {}
        print("\nВводите: код_аналита значение (Enter без значения — конец)")
        print("Пример: glucose 5.8")
        while True:
            line = self.input("  > ")
            if not line:
                break
            parts = line.split()
            if len(parts) != 2:
                print("  Формат: код значение")
                continue
            code, val_str = parts
            if code not in LAB_RANGES:
                print(f"  Неизвестный аналит: {code}")
                continue
            try:
                values[code] = float(val_str.replace(",", "."))
            except ValueError:
                print(f"  Не число: {val_str}")

        if not values:
            print("Нет данных.")
            return

        print("\n" + "─" * 50)
        for code, val in values.items():
            r = evaluate(code, val)
            print(format_result(r, lang=self.lang))
            print()

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

    def triage(self):
        """Kernel-powered diagnostic triage (Asimov 4 Laws + Ze Theory utility)."""
        print("\n── Triage (kernel-powered) ──")
        complaint = self.input("Жалобы / симптомы: ")
        if not complaint:
            return

        # Load patient memory или создать placeholder если нет
        from agents.patient_memory import load_or_create
        patient_id = (self.patient.get("id") if self.patient
                      else "ANONYMOUS_" + __import__("time").strftime("%Y%m%d_%H%M%S"))
        mem = load_or_create(patient_id,
                             demographics={"age": self.patient.get("age") if self.patient else None,
                                            "sex": self.patient.get("sex") if self.patient else None})
        patient_dict = mem.to_kernel_dict()

        verbose = self.input("Verbose reasoning? [y/N]: ").lower().startswith("y")

        print(f"\n{t('thinking', self.lang)}")
        result = self.doctor.triage(complaint, patient_dict,
                                     lang=self.lang, session_id=self.session_id,
                                     verbose=verbose)

        status = result.get("status", "?")
        print(f"\n[status: {status}] (𝓘 impedance: {result.get('impedance', 0):.2f})\n")

        if status == "clarify":
            print("AIM хочет уточнить перед решением:\n")
            print(result["output"])
            # Second round after user answers
            answers = self.input("\nДополнительная информация: ")
            if answers:
                print(f"\n{t('thinking', self.lang)}")
                result2 = self.doctor.triage(complaint + "\n\nДополнительно: " + answers,
                                              patient_dict, lang=self.lang,
                                              session_id=self.session_id, verbose=verbose)
                print(f"\n{result2.get('output', '')}\n")
        elif status == "blocked":
            print("⚠️ All alternatives blocked by Laws:\n")
            print(result.get("output", "-"))
        else:
            print(result.get("output", "-"))

    def kernel_labs(self):
        """Kernel-powered lab panel interpretation."""
        from agents.labs import LabAgent
        from agents.patient_memory import load_or_create
        print("\n── Labs (kernel) ──")
        print("Enter analytes as: hemoglobin_m=150, glucose=5.5, potassium=4.2, ...")
        raw = self.input("> ")
        if not raw.strip():
            return
        values = {}
        for pair in raw.replace(";", ",").split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                try:
                    values[k.strip()] = float(v.strip())
                except ValueError:
                    pass
        if not values:
            print("Nothing to interpret.")
            return

        patient_id = (self.patient.get("id") if self.patient
                      else "ANONYMOUS_" + __import__("time").strftime("%Y%m%d_%H%M%S"))
        mem = load_or_create(patient_id)
        verbose = self.input("Verbose? [y/N]: ").lower().startswith("y")

        print(f"\n{t('thinking', self.lang)}\n")
        result = LabAgent().interpret(values, mem.to_kernel_dict(),
                                       lang=self.lang, verbose=verbose)
        print(result.get("output", "-"))

    def kernel_treatment(self):
        """Kernel-powered treatment planning (w/ auto interaction check)."""
        from agents.patient_memory import load_or_create
        print("\n── Treatment (kernel) ──")
        dx = self.input("Diagnosis: ")
        if not dx:
            return
        patient_id = (self.patient.get("id") if self.patient
                      else "ANONYMOUS_" + __import__("time").strftime("%Y%m%d_%H%M%S"))
        mem = load_or_create(patient_id)
        verbose = self.input("Verbose? [y/N]: ").lower().startswith("y")

        print(f"\n{t('thinking', self.lang)}\n")
        result = self.doctor.treatment(dx, mem.to_kernel_dict(),
                                        lang=self.lang, session_id=self.session_id,
                                        verbose=verbose)
        print(result.get("output", "-"))

    def kernel_chat(self):
        """Multilingual kernel-powered dialogue."""
        from agents.chat import ChatAgent
        print("\n── Chat (kernel) — q to quit ──")
        agent = ChatAgent()
        patient_ctx = None
        if self.patient:
            from agents.patient_memory import load_or_create
            mem = load_or_create(self.patient.get("id", "ANON"))
            patient_ctx = mem.to_kernel_dict()
        while True:
            msg = self.input("you> ")
            if not msg or msg.lower() == "q":
                break
            print(f"\n{t('thinking', self.lang)}")
            r = agent.respond(msg, patient=patient_ctx,
                               session_id=self.session_id)
            print(f"\nAIM ({r.get('intent', '?')}, {r.get('detected_lang', '?')})>\n{r.get('output', '-')}\n")

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

    def drug_interactions(self):
        """Menu m9 — manual drug-interaction check (v1 hybrid mode).
        v1 scope: manual input only. Future (P1 TODO): auto-fetch from
        patient.medications SQLite column when schema migration is complete.
        """
        from agents.interactions import check_regimen, format_regimen_report
        print(f"\n── {t('m9', self.lang)} ──")
        print(t('m9_prompt', self.lang))
        raw = self.input("> ")
        if not raw.strip():
            print("(пусто — отмена)")
            return
        drugs = [d.strip() for d in raw.replace(";", ",").split(",") if d.strip()]
        if len(drugs) < 2:
            print("Нужно минимум 2 препарата для проверки взаимодействий.")
            return
        results = check_regimen(drugs)
        print(format_regimen_report(results, lang=self.lang))

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
            elif choice == "9": self.drug_interactions()
            elif choice == "t" or choice == "T": self.triage()
            elif choice == "l" or choice == "L": self.kernel_labs()
            elif choice == "x" or choice == "X": self.kernel_treatment()
            elif choice == "c" or choice == "C": self.kernel_chat()
            elif choice == "0":
                print("Bye.")
                break
            else:
                print("?")

# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Multi-user gate: each AIM node validates its identity against the hub on
    # startup. In local-only mode (no AIM_HUB_URL) this is a no-op.
    try:
        from agents import hub_client
        u = hub_client.require_user()
        if not u.get("local_only"):
            print(f"[AIM] authenticated as '{u['username']}' (role={u['role']})")
            hub_client.heartbeat()
    except SystemExit:
        raise
    except Exception as e:
        print(f"[AIM] hub_client error (continuing in local mode): {e}")

    app = AIM()
    app.run()
