"""
AIM v7.0 — GUI (customtkinter)
Паритет с medical_system.py — все пункты меню совпадают.
"""

import sys
import threading
import logging
from pathlib import Path

import customtkinter as ctk

from config import VERSION, APP_NAME, DEFAULT_LANG, SUPPORTED_LANGS, PATIENTS_DIR
from llm import providers_status
from i18n import t, lang_name, lang_menu
from db import (list_patients, get_patient, upsert_patient,
                new_session, save_message, get_history, search_patients)
from agents import DoctorAgent, IntakeAgent, LangAgent
from agents.lang import LANG_NAMES
from lab_reference import evaluate, format_result, categories, list_analytes, LAB_RANGES

log = logging.getLogger("aim.gui")

# ── Тема ─────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Цвета ─────────────────────────────────────────────────────────────────────

C_BG       = "#1a1a2e"
C_PANEL    = "#16213e"
C_ACCENT   = "#0f3460"
C_BLUE     = "#4a9eff"
C_GREEN    = "#4aff91"
C_YELLOW   = "#ffd700"
C_TEXT     = "#e0e0e0"
C_MUTED    = "#888888"


# ── Главное окно ──────────────────────────────────────────────────────────────

class AIMGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("1100x750")
        self.minsize(900, 600)
        self.configure(fg_color=C_BG)

        self.lang       = DEFAULT_LANG
        self.patient    = None
        self.session_id = None
        self.doctor     = DoctorAgent()
        self.intake     = IntakeAgent()
        self.lang_agent = LangAgent()

        self._build_layout()
        self._update_status_bar()

    # ── Компоновка ────────────────────────────────────────────────────────────

    def _build_layout(self):
        # Левая панель — меню
        self.sidebar = ctk.CTkFrame(self, width=220, fg_color=C_PANEL, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Правая часть
        self.main_area = ctk.CTkFrame(self, fg_color=C_BG)
        self.main_area.pack(side="right", fill="both", expand=True)

        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        # Заголовок
        ctk.CTkLabel(self.sidebar, text="AIM", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=C_BLUE).pack(pady=(20, 2))
        ctk.CTkLabel(self.sidebar, text=f"v{VERSION}", font=ctk.CTkFont(size=11),
                     text_color=C_MUTED).pack(pady=(0, 20))

        # Пациент
        self.patient_label = ctk.CTkLabel(
            self.sidebar, text="Пациент: —",
            font=ctk.CTkFont(size=11), text_color=C_YELLOW, wraplength=200
        )
        self.patient_label.pack(padx=10, pady=(0, 15))

        # Кнопки меню — СТРОГО совпадают с CLI-меню
        menu_buttons = [
            ("m1", self._new_patient),
            ("m2", self._open_patient),
            ("m3", self._lab_intake),
            ("m4", self._diagnose),
            ("m5", self._treatment),
            ("m6", self._translate),
            ("m7", self._consult),
            ("m8", self._settings),
            ("m9", self._drug_interactions),
        ]
        self.menu_btns = {}
        for key, cmd in menu_buttons:
            btn = ctk.CTkButton(
                self.sidebar,
                text=t(key, self.lang),
                command=cmd,
                fg_color=C_ACCENT,
                hover_color=C_BLUE,
                anchor="w",
                width=200,
                font=ctk.CTkFont(size=13),
            )
            btn.pack(padx=10, pady=3)
            self.menu_btns[key] = btn

        # Статус провайдеров
        self.provider_label = ctk.CTkLabel(
            self.sidebar, text="", font=ctk.CTkFont(size=10), text_color=C_MUTED
        )
        self.provider_label.pack(side="bottom", pady=15)

    def _build_main(self):
        # Статус-бар вверху
        self.status_bar = ctk.CTkLabel(
            self.main_area, text="", font=ctk.CTkFont(size=11),
            text_color=C_MUTED, anchor="w"
        )
        self.status_bar.pack(fill="x", padx=15, pady=(8, 0))

        # Текстовое поле вывода
        self.output = ctk.CTkTextbox(
            self.main_area, font=ctk.CTkFont(family="Courier", size=13),
            fg_color=C_PANEL, text_color=C_TEXT, wrap="word", state="disabled",
        )
        self.output.pack(fill="both", expand=True, padx=15, pady=(8, 5))

        # Поле ввода + кнопка отправки
        input_frame = ctk.CTkFrame(self.main_area, fg_color=C_BG)
        input_frame.pack(fill="x", padx=15, pady=(0, 10))

        self.input_field = ctk.CTkEntry(
            input_frame, placeholder_text="Введите запрос...",
            font=ctk.CTkFont(size=13), fg_color=C_PANEL, text_color=C_TEXT,
            height=38,
        )
        self.input_field.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.input_field.bind("<Return>", lambda e: self._send_input())

        ctk.CTkButton(
            input_frame, text="→", width=50, height=38,
            fg_color=C_BLUE, hover_color=C_ACCENT,
            command=self._send_input,
        ).pack(side="right")

        # Ожидающий ввод callback
        self._awaiting_callback = None
        self._awaiting_label = ""

    # ── Утилиты ───────────────────────────────────────────────────────────────

    def _print(self, text: str, color: str = C_TEXT):
        self.output.configure(state="normal")
        self.output.insert("end", text + "\n", color)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _clear(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _set_status(self, text: str):
        self.status_bar.configure(text=text)

    def _update_status_bar(self):
        status = providers_status()
        icons = " | ".join(f"{k[0].upper()}{'✓' if v else '✗'}" for k, v in status.items())
        self.provider_label.configure(text=icons)
        pat_text = f"Пациент: {self.patient['name']}" if self.patient else "Пациент: —"
        self.patient_label.configure(text=pat_text)

    def _update_menu_labels(self):
        for key, btn in self.menu_btns.items():
            btn.configure(text=t(key, self.lang))

    def _await_input(self, label: str, callback):
        """Установить callback для следующего ввода из поля."""
        self._awaiting_label = label
        self._awaiting_callback = callback
        self._set_status(label)
        self.input_field.focus()

    def _send_input(self):
        text = self.input_field.get().strip()
        self.input_field.delete(0, "end")
        if self._awaiting_callback:
            cb = self._awaiting_callback
            self._awaiting_callback = None
            self._set_status("")
            cb(text)

    def _run_async(self, fn, *args):
        """Запустить тяжёлую задачу в потоке, чтобы не замораживать GUI."""
        def worker():
            try:
                fn(*args)
            except Exception as e:
                self._print(f"[Ошибка] {e}", "red")
                log.exception(e)
        threading.Thread(target=worker, daemon=True).start()

    # ── Пункты меню ───────────────────────────────────────────────────────────

    def _new_patient(self):
        self._clear()
        self._print("── Новый пациент ──")
        def on_name(name):
            if not name:
                return
            def on_dob(dob):
                from db import format_patient_folder
                folder = format_patient_folder(name, dob or None)
                patient_dir = PATIENTS_DIR / folder
                patient_dir.mkdir(parents=True, exist_ok=True)
                pid = upsert_patient(folder, name, self.lang)
                self.patient = get_patient(folder)
                self.session_id = new_session(pid, self.lang)
                self._print(f"✓ Пациент создан: {folder}", C_GREEN)
                if "2000_01_01" in folder and not dob:
                    self._print("  ⚠ ДР placeholder — узнать и переименовать", C_YELLOW)
                self._update_status_bar()
            self._await_input("ДР (YYYY-MM-DD, Enter если неизвестна):", on_dob)
        self._await_input("Имя (Фамилия Имя):", on_name)

    def _open_patient(self):
        self._clear()
        self._print("── Открыть пациента ──")
        def on_query(query):
            if not query:
                return
            results = search_patients(query)
            if not results:
                self._print("Пациент не найден.")
                return
            for i, p in enumerate(results[:10]):
                self._print(f"  {i+1}. {p['name']}  [{p['folder']}]")
            def on_choice(choice):
                try:
                    idx = int(choice) - 1
                    self.patient = results[idx]
                    self.session_id = new_session(self.patient["id"], self.lang)
                    self._print(f"✓ Открыт: {self.patient['name']}", C_GREEN)
                    self._update_status_bar()
                except (ValueError, IndexError):
                    self._print("Отмена.")
            self._await_input("Выбор (номер):", on_choice)
        self._await_input("Поиск пациента:", on_query)

    def _lab_intake(self):
        self._clear()
        self._print("── Анализы ──")
        self._print("1. Загрузить файл (PDF/фото)")
        self._print("2. Сканировать INBOX")
        self._print("3. Проверить нормы (ввести вручную)")
        def on_choice(choice):
            if choice == "1":
                def on_path(path_str):
                    path = Path(path_str)
                    if not path.exists():
                        self._print(f"Файл не найден: {path}")
                        return
                    def process():
                        self._print(f"\n{t('thinking', self.lang)}")
                        result = self.intake.process_file(path, lang=self.lang,
                                                          session_id=self.session_id)
                        self._print(result)
                    self._run_async(process)
                self._await_input("Путь к файлу:", on_path)
            elif choice == "2":
                def scan():
                    self._print(f"\n{t('thinking', self.lang)}")
                    items = self.intake.scan_inbox(lang=self.lang)
                    if not items:
                        self._print("INBOX пуст.")
                        return
                    for item in items:
                        self._print(f"\n── {item['path'].name} ──")
                        result = self.intake.analyze_labs(item["text"], lang=self.lang,
                                                          session_id=self.session_id)
                        self._print(result)
                self._run_async(scan)
            elif choice == "3":
                self._lab_manual_check()
        self._await_input("Выбор (1/2/3):", on_choice)

    def _lab_manual_check(self):
        """GUI-версия ручной проверки норм."""
        self._clear()
        self._print("── Проверка лабораторных норм ──")
        cats = categories()
        self._print("Категории: " + " | ".join(f"{i+1}.{c}" for i, c in enumerate(cats)))
        self._print("Формат ввода: код_аналита значение (по одному на строку, пустая строка = конец)")
        self._print("Пример: glucose 5.8")
        self._print("")

        entered_values: dict[str, float] = {}

        def on_line(line):
            if not line:
                # Пустая строка — показать результат
                if not entered_values:
                    self._print("Нет данных.")
                    return
                self._print("\n" + "─" * 50)
                for code, val in entered_values.items():
                    r = evaluate(code, val)
                    self._print(format_result(r, lang=self.lang))
                    self._print("")
                return
            parts = line.split()
            if len(parts) == 2:
                code, val_str = parts
                if code not in LAB_RANGES:
                    self._print(f"Неизвестный аналит: {code}")
                else:
                    try:
                        entered_values[code] = float(val_str.replace(",", "."))
                        self._print(f"  ✓ {code} = {entered_values[code]}")
                    except ValueError:
                        self._print(f"  Не число: {val_str}")
            else:
                self._print("  Формат: код значение")
            # Продолжаем ввод
            self._await_input("Аналит значение (Enter = конец):", on_line)

        self._await_input("Аналит значение (Enter = конец):", on_line)

    def _diagnose(self):
        self._clear()
        self._print("── Диагностика ──")
        def on_symptoms(symptoms):
            if not symptoms:
                return
            context = f"Пациент: {self.patient['name']}\n" if self.patient else ""
            def run():
                self._print(f"\n{t('thinking', self.lang)}")
                result = self.doctor.diagnose(symptoms, patient_context=context,
                                              lang=self.lang, session_id=self.session_id)
                self._print(f"\n{result}")
            self._run_async(run)
        self._await_input("Жалобы и симптомы:", on_symptoms)

    def _treatment(self):
        self._clear()
        self._print("── Протокол лечения ──")
        def on_diagnosis(diagnosis):
            if not diagnosis:
                return
            context = f"Пациент: {self.patient['name']}\n" if self.patient else ""
            def run():
                self._print(f"\n{t('thinking', self.lang)}")
                result = self.doctor.treatment_plan(diagnosis, patient_context=context,
                                                    lang=self.lang, session_id=self.session_id)
                self._print(f"\n{result}")
            self._run_async(run)
        self._await_input("Диагноз:", on_diagnosis)

    def _translate(self):
        self._clear()
        self._print("── Перевод ──")
        langs_str = "  ".join(f"{c}={LANG_NAMES.get(c,c)}" for c in SUPPORTED_LANGS)
        self._print(f"Языки: {langs_str}")
        def on_target(target):
            if target not in SUPPORTED_LANGS:
                self._print(f"Неизвестный язык: {target}")
                return
            self._print("Тип: medical / scientific / patient / general")
            def on_type(ttype):
                if ttype not in ("medical", "scientific", "patient", "general"):
                    ttype = "medical"
                def on_text(text):
                    if not text:
                        return
                    def run():
                        self._print(f"\n{t('thinking', self.lang)}")
                        result = self.lang_agent.translate(
                            text, target_lang=target,
                            translation_type=ttype,
                            session_id=self.session_id,
                        )
                        self._print(f"\n{result}")
                    self._run_async(run)
                self._await_input("Текст:", on_text)
            self._await_input("Тип перевода:", on_type)
        self._await_input("Целевой язык:", on_target)

    def _consult(self):
        self._clear()
        self._print("── Консультация (свободный диалог) ──")
        self._print("Введите вопрос. Пустая строка — выход.")
        if not self.session_id:
            self.session_id = new_session(None, self.lang)

        def on_message(message):
            if not message:
                self._print("Диалог завершён.")
                return
            def run():
                self._print(f"\nВы: {message}", C_YELLOW)
                self._print(f"{t('thinking', self.lang)}")
                history = get_history(self.session_id, limit=6)
                result = self.doctor.chat(message, history=history,
                                          lang=self.lang, session_id=self.session_id)
                self._print(f"\nAIM: {result}")
                # Продолжаем диалог
                self._await_input("Вы:", on_message)
            self._run_async(run)
        self._await_input("Вы:", on_message)

    def _drug_interactions(self):
        """Menu m9 — GUI drug-interaction check (manual mode; v1 hybrid).
        Future P1: add "From patient record" option once patient.medications column exists.
        """
        from agents.interactions import check_regimen, format_regimen_report
        self._clear()
        self._print(f"── {t('m9', self.lang)} ──")
        self._print(t('m9_prompt', self.lang))

        def on_input(raw):
            if not raw or not raw.strip():
                self._print("(пусто — отмена)")
                return
            drugs = [d.strip() for d in raw.replace(";", ",").split(",") if d.strip()]
            if len(drugs) < 2:
                self._print("Нужно минимум 2 препарата для проверки взаимодействий.")
                return
            def run():
                self._print(f"\n{t('thinking', self.lang)}")
                results = check_regimen(drugs)
                self._print("\n" + format_regimen_report(results, lang=self.lang))
            self._run_async(run)
        self._await_input("Препараты через запятую:", on_input)

    def _settings(self):
        self._clear()
        self._print("── Настройки ──")
        langs_list = "\n".join(f"  {i+1}. {c} — {LANG_NAMES.get(c,c)}"
                               for i, c in enumerate(SUPPORTED_LANGS))
        self._print(langs_list)
        def on_choice(choice):
            try:
                self.lang = SUPPORTED_LANGS[int(choice) - 1]
                self._print(f"✓ Язык: {lang_name(self.lang)}", C_GREEN)
                self._update_menu_labels()
            except (ValueError, IndexError):
                self._print("Отмена.")
        self._await_input("Выберите язык (номер):", on_choice)


# ── Точка входа ───────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.WARNING)
    # Multi-user gate. Validates AIM_USER_TOKEN against AIM_HUB_URL once.
    # Local-only (no AIM_HUB_URL) → no-op.
    try:
        from agents import hub_client
        u = hub_client.require_user()
        if not u.get("local_only"):
            log = logging.getLogger("aim.gui")
            log.warning(f"authenticated as '{u['username']}' (role={u['role']})")
            hub_client.heartbeat()
    except SystemExit:
        raise
    except Exception as e:
        logging.getLogger("aim.gui").warning(f"hub_client error: {e}")
    app = AIMGui()
    app.mainloop()


if __name__ == "__main__":
    main()
