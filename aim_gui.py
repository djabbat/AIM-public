#!/usr/bin/env python3
"""
AIM — Assistant of Integrative Medicine
Graphical interface (tkinter)
Dr. Jaba Tkemaladze
"""

import os
import sys
import json
import threading
import subprocess
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# ── Path setup ─────────────────────────────────────────────────
AIM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AIM_DIR)

VENV_SITE = os.path.join(AIM_DIR, "venv/lib")
for d in Path(VENV_SITE).glob("python3.*/site-packages") if Path(VENV_SITE).exists() else []:
    sys.path.insert(0, str(d))

PATIENTS_DIR = os.path.expanduser("~/AIM/Patients")
INBOX_DIR = os.path.join(PATIENTS_DIR, "INBOX")

# ── Colours ────────────────────────────────────────────────────
BG       = "#0d1b2a"
BG2      = "#1a2e42"
BG3      = "#243b55"
ACCENT   = "#00bcd4"
ACCENT2  = "#26c6da"
TEXT     = "#e0f7fa"
TEXT2    = "#b2ebf2"
MUTED    = "#607d8b"
GREEN    = "#4caf50"
ORANGE   = "#ff9800"
RED      = "#ef5350"
WHITE    = "#ffffff"

FONT_H1  = ("DejaVu Sans", 16, "bold")
FONT_H2  = ("DejaVu Sans", 13, "bold")
FONT_BODY = ("DejaVu Sans", 11)
FONT_MONO = ("DejaVu Sans Mono", 10)
FONT_SMALL = ("DejaVu Sans", 9)


# ── Helpers ────────────────────────────────────────────────────

def run_python(script_args: list, callback=None):
    """Run python script in background thread, call callback(output) when done."""
    python = os.path.join(AIM_DIR, "venv/bin/python3")
    if not os.path.exists(python):
        python = sys.executable

    def _run():
        try:
            result = subprocess.run(
                [python] + script_args,
                capture_output=True, text=True,
                cwd=AIM_DIR, timeout=600
            )
            output = result.stdout + (("\nSTDERR:\n" + result.stderr) if result.stderr else "")
        except subprocess.TimeoutExpired:
            output = "[TIMEOUT after 10 min]"
        except Exception as e:
            output = f"[ERROR: {e}]"
        if callback:
            callback(output)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def list_patients():
    docs = Path(PATIENTS_DIR)
    patients = []
    if not docs.exists():
        return patients
    for d in sorted(docs.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name == "INBOX":
            continue
        parts = d.name.split("_")
        if len(parts) >= 2:
            dob = ""
            if len(parts) >= 5:
                try:
                    dob = f"{parts[4]}.{parts[3]}.{parts[2]}"
                except Exception:
                    pass
            has_analysis = (d / "_ai_analysis.txt").exists()
            n_files = len(list(d.iterdir()))
            patients.append({
                "folder": str(d),
                "name": f"{parts[0]} {parts[1]}",
                "folder_name": d.name,
                "dob": dob,
                "has_analysis": has_analysis,
                "n_files": n_files,
            })
    return patients


def read_analysis(folder_path: str) -> str:
    f = Path(folder_path) / "_ai_analysis.txt"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    return "Анализ не найден.\nЗапустите обработку пациента (кнопка 'Обработать')."


def read_lab_results(folder_path: str) -> str:
    """Read all *_text.txt and *_ocr.txt from folder."""
    lines = []
    folder = Path(folder_path)
    for f in sorted(folder.glob("*_text.txt")):
        lines.append(f"=== {f.stem} ===\n{f.read_text(encoding='utf-8', errors='replace')[:3000]}")
    for f in sorted(folder.glob("*_ocr.txt")):
        lines.append(f"=== {f.stem} (OCR) ===\n{f.read_text(encoding='utf-8', errors='replace')[:3000]}")
    if not lines:
        return "Нет обработанных данных. Запустите обработку."
    return "\n\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ══════════════════════════════════════════════════════════════

class AIMApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AIM — Integrative Medicine Assistant")
        self.geometry("1200x780")
        self.minsize(900, 600)
        self.configure(bg=BG)

        self._load_icon()
        self._build_ui()
        self.after(100, self.refresh_patients)

    def _load_icon(self):
        icon_path = os.path.join(AIM_DIR, "aim_icon.png")
        if os.path.exists(icon_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).resize((32, 32), Image.LANCZOS)
                self._icon = ImageTk.PhotoImage(img)
                self.iconphoto(True, self._icon)
            except Exception:
                pass

    # ── UI construction ────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ──
        top = tk.Frame(self, bg=BG, height=56)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        tk.Label(top, text="⚕ AIM", font=("DejaVu Sans", 18, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left", padx=16, pady=10)
        tk.Label(top, text="Assistant of Integrative Medicine  |  Dr. Jaba Tkemaladze",
                 font=FONT_SMALL, bg=BG, fg=MUTED).pack(side="left", pady=10)

        # Ollama status
        self.status_var = tk.StringVar(value="● Проверка...")
        tk.Label(top, textvariable=self.status_var, font=FONT_SMALL,
                 bg=BG, fg=MUTED).pack(side="right", padx=16)

        # ── Separator ──
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        # ── Main paned layout ──
        main = tk.PanedWindow(self, orient="horizontal", bg=BG,
                               sashwidth=4, sashrelief="flat")
        main.pack(fill="both", expand=True)

        # Left sidebar
        sidebar = tk.Frame(main, bg=BG2, width=280)
        sidebar.pack_propagate(False)
        main.add(sidebar, minsize=220)

        # Right content
        content = tk.Frame(main, bg=BG)
        main.add(content, minsize=500)

        self._build_sidebar(sidebar)
        self._build_content(content)

        # ── Bottom bar ──
        tk.Frame(self, bg=BG3, height=1).pack(fill="x")
        bot = tk.Frame(self, bg=BG3, height=28)
        bot.pack(fill="x", side="bottom")
        bot.pack_propagate(False)
        self.statusbar = tk.Label(bot, text="Готово", font=FONT_SMALL,
                                   bg=BG3, fg=TEXT2)
        self.statusbar.pack(side="left", padx=10)

        self._check_ollama()
        self._start_inbox_watcher()

    def _start_inbox_watcher(self):
        """Запустить INBOX watcher — авто-обработка новых файлов."""
        def _on_new(paths):
            names = ", ".join(p.name for p in paths[:3])
            suffix = f" и ещё {len(paths)-3}" if len(paths) > 3 else ""
            self.after(0, lambda: self._set_status(
                f"INBOX: новые файлы ({names}{suffix}) — обрабатываю..."))
            # После обработки обновить список пациентов
            self.after(8000, self.refresh_patients)

        def _launch():
            try:
                from inbox_watcher import get_watcher
                get_watcher(on_new_files=_on_new)
            except Exception as e:
                log.warning("InboxWatcher init error: %s", e) if False else None

        threading.Thread(target=_launch, daemon=True).start()

    def _build_sidebar(self, parent):
        # Title
        tk.Label(parent, text="ПАЦИЕНТЫ", font=("DejaVu Sans", 10, "bold"),
                 bg=BG2, fg=MUTED).pack(pady=(12, 4), padx=12, anchor="w")

        # Search
        search_frame = tk.Frame(parent, bg=BG2)
        search_frame.pack(fill="x", padx=8, pady=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._filter_patients())
        search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                                bg=BG3, fg=TEXT, insertbackground=TEXT,
                                relief="flat", font=FONT_BODY)
        search_entry.pack(fill="x", ipady=5, padx=4)
        search_entry.insert(0, "Поиск...")
        search_entry.bind("<FocusIn>", lambda e: (search_entry.delete(0, "end")
                           if search_entry.get() == "Поиск..." else None))

        # Patient list
        list_frame = tk.Frame(parent, bg=BG2)
        list_frame.pack(fill="both", expand=True, padx=4)

        scrollbar = tk.Scrollbar(list_frame, bg=BG3, troughcolor=BG2,
                                  activebackground=ACCENT, width=8)
        scrollbar.pack(side="right", fill="y")

        self.patient_listbox = tk.Listbox(
            list_frame,
            bg=BG2, fg=TEXT, selectbackground=ACCENT, selectforeground=BG,
            relief="flat", borderwidth=0, font=FONT_BODY,
            activestyle="none",
            yscrollcommand=scrollbar.set,
        )
        self.patient_listbox.pack(fill="both", expand=True)
        scrollbar.config(command=self.patient_listbox.yview)
        self.patient_listbox.bind("<<ListboxSelect>>", self._on_patient_select)

        # Buttons
        btn_frame = tk.Frame(parent, bg=BG2)
        btn_frame.pack(fill="x", pady=8, padx=8)

        self._btn(btn_frame, "＋ Новый пациент", self._new_patient, ACCENT).pack(fill="x", pady=2)
        self._btn(btn_frame, "⚡ Sync WhatsApp", self._sync_whatsapp, "#1a6b4a").pack(fill="x", pady=2)
        self._btn(btn_frame, "↑ Импорт файлов", self._import_inbox, BG3).pack(fill="x", pady=2)
        self._btn(btn_frame, "⟳ Обработать всех", self._process_all, BG3).pack(fill="x", pady=2)

        self._patients = []
        self._filtered = []

    def _build_content(self, parent):
        # Notebook tabs
        style = ttk.Style()
        style.theme_use("default")
        style.configure("AIM.TNotebook", background=BG, borderwidth=0)
        style.configure("AIM.TNotebook.Tab",
                         background=BG3, foreground=TEXT2,
                         padding=[14, 6], font=FONT_BODY,
                         borderwidth=0)
        style.map("AIM.TNotebook.Tab",
                   background=[("selected", BG), ("active", BG2)],
                   foreground=[("selected", ACCENT)])

        self.notebook = ttk.Notebook(parent, style="AIM.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Patient overview
        self._tab_overview = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self._tab_overview, text="  Пациент  ")
        self._build_tab_overview(self._tab_overview)

        # Tab 2: AI Analysis
        self._tab_analysis = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self._tab_analysis, text="  AI Анализ  ")
        self._build_tab_analysis(self._tab_analysis)

        # Tab 3: Lab results
        self._tab_labs = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self._tab_labs, text="  Лаборатория  ")
        self._build_tab_labs(self._tab_labs)

        # Tab 4: AI Chat
        self._tab_chat = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self._tab_chat, text="  AI Чат  ")
        self._build_tab_chat(self._tab_chat)

        # Tab 5: System
        self._tab_system = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self._tab_system, text="  Система  ")
        self._build_tab_system(self._tab_system)

        # Tab 6: Nutrition
        self._tab_nutrition = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self._tab_nutrition, text="  🥗 Питание  ")
        self._build_tab_nutrition(self._tab_nutrition)

    # ── Tab: Overview ─────────────────────────────────────────

    def _build_tab_overview(self, parent):
        self.overview_frame = tk.Frame(parent, bg=BG)
        self.overview_frame.pack(fill="both", expand=True, padx=20, pady=16)
        self._show_no_patient()

    def _show_no_patient(self):
        for w in self.overview_frame.winfo_children():
            w.destroy()
        tk.Label(self.overview_frame,
                 text="Выберите пациента из списка слева",
                 font=FONT_H2, bg=BG, fg=MUTED).pack(expand=True)

    def _show_patient_overview(self, p: dict):
        for w in self.overview_frame.winfo_children():
            w.destroy()

        # Header
        hdr = tk.Frame(self.overview_frame, bg=BG)
        hdr.pack(fill="x", pady=(0, 16))

        tk.Label(hdr, text=p["name"], font=FONT_H1, bg=BG, fg=WHITE).pack(side="left")
        dob_text = f"  р. {p['dob']}" if p.get("dob") else ""
        tk.Label(hdr, text=dob_text, font=FONT_BODY, bg=BG, fg=TEXT2).pack(side="left", padx=8)

        # Action buttons
        act = tk.Frame(self.overview_frame, bg=BG)
        act.pack(fill="x", pady=(0, 12))

        self._btn(act, "▶ Обработать", lambda: self._process_patient(p), ACCENT).pack(side="left", padx=(0, 8))
        self._btn(act, "⟳ Принудительно", lambda: self._process_patient(p, force=True), BG3).pack(side="left", padx=(0, 8))
        self._btn(act, "📁 Открыть папку", lambda: os.system(f'xdg-open "{p["folder"]}"'), BG3).pack(side="left")

        # Info cards
        cards = tk.Frame(self.overview_frame, bg=BG)
        cards.pack(fill="x")

        files = list(Path(p["folder"]).iterdir())
        jpegs = [f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
        pdfs = [f for f in files if f.suffix.lower() == ".pdf"]
        ocr_done = [f for f in files if f.name.endswith("_ocr.txt")]
        pdf_done = [f for f in files if f.name.endswith("_text.txt")]

        def card(parent, label, value, color=ACCENT):
            f = tk.Frame(parent, bg=BG3, padx=16, pady=12)
            f.pack(side="left", padx=(0, 8))
            tk.Label(f, text=str(value), font=("DejaVu Sans", 18, "bold"),
                     bg=BG3, fg=color).pack()
            tk.Label(f, text=label, font=FONT_SMALL, bg=BG3, fg=MUTED).pack()

        card(cards, "Скринов", len(jpegs))
        card(cards, "PDF", len(pdfs))
        card(cards, "OCR готово", len(ocr_done),
             GREEN if len(ocr_done) == len(jpegs) and jpegs else ORANGE)
        card(cards, "PDF готово", len(pdf_done),
             GREEN if len(pdf_done) == len(pdfs) and pdfs else ORANGE)
        card(cards, "Анализ AI", "✓" if p["has_analysis"] else "—",
             GREEN if p["has_analysis"] else MUTED)

        # File list
        tk.Label(self.overview_frame, text="Файлы пациента:",
                 font=FONT_H2, bg=BG, fg=TEXT2).pack(anchor="w", pady=(16, 4))
        fl = scrolledtext.ScrolledText(self.overview_frame, height=12,
                                        bg=BG2, fg=TEXT2, font=FONT_MONO,
                                        relief="flat", state="normal")
        fl.pack(fill="both", expand=True)
        fl.delete("1.0", "end")
        for f in sorted(files):
            size = f.stat().st_size if f.is_file() else 0
            fl.insert("end", f"  {f.name:<50} {size//1024:>4} KB\n")
        fl.configure(state="disabled")

    # ── Tab: Analysis ─────────────────────────────────────────

    def _build_tab_analysis(self, parent):
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", padx=12, pady=8)
        tk.Label(toolbar, text="Медицинский анализ AI:", font=FONT_H2,
                 bg=BG, fg=TEXT2).pack(side="left")
        self._btn(toolbar, "Обновить", self._refresh_analysis, BG3).pack(side="right")

        self.analysis_text = scrolledtext.ScrolledText(
            parent, bg=BG2, fg=TEXT, font=FONT_BODY,
            relief="flat", padx=12, pady=8,
            insertbackground=TEXT, wrap="word",
        )
        self.analysis_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.analysis_text.insert("end", "Выберите пациента для просмотра анализа.")
        self.analysis_text.configure(state="disabled")

    def _refresh_analysis(self):
        p = self._current_patient()
        if not p:
            return
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("end", read_analysis(p["folder"]))
        self.analysis_text.configure(state="disabled")

    # ── Tab: Labs ─────────────────────────────────────────────

    def _build_tab_labs(self, parent):
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", padx=12, pady=8)
        tk.Label(toolbar, text="Лабораторные данные:", font=FONT_H2,
                 bg=BG, fg=TEXT2).pack(side="left")
        self._btn(toolbar, "Анализ отклонений", self._run_lab_analysis, ACCENT).pack(side="right")
        self._btn(toolbar, "Обновить", self._refresh_labs, BG3).pack(side="right", padx=(0, 8))

        self.labs_text = scrolledtext.ScrolledText(
            parent, bg=BG2, fg=TEXT, font=FONT_MONO,
            relief="flat", padx=12, pady=8,
            insertbackground=TEXT,
        )
        self.labs_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.labs_text.insert("end", "Выберите пациента.")
        self.labs_text.configure(state="disabled")

    def _refresh_labs(self):
        p = self._current_patient()
        if not p:
            return
        self.labs_text.configure(state="normal")
        self.labs_text.delete("1.0", "end")
        self.labs_text.insert("end", read_lab_results(p["folder"]))
        self.labs_text.configure(state="disabled")

    def _run_lab_analysis(self):
        p = self._current_patient()
        if not p:
            messagebox.showinfo("AIM", "Сначала выберите пациента")
            return
        self.labs_text.configure(state="normal")
        self.labs_text.delete("1.0", "end")
        self.labs_text.insert("end", "Анализ отклонений...\n")
        self.labs_text.configure(state="disabled")

        def done(out):
            self.after(0, lambda: (
                self.labs_text.configure(state="normal"),
                self.labs_text.delete("1.0", "end"),
                self.labs_text.insert("end", out),
                self.labs_text.configure(state="disabled"),
            ))

        run_python([
            "-c",
            f"""
import sys; sys.path.insert(0, '{AIM_DIR}')
from medical_system import analyze_labs_only
print(analyze_labs_only('{p["folder"]}'))
"""
        ], callback=done)

    # ── Tab: Chat ─────────────────────────────────────────────

    def _build_tab_chat(self, parent):
        tk.Label(parent, text="AI Специалист — Интегративная медицина",
                 font=FONT_H2, bg=BG, fg=TEXT2).pack(padx=12, pady=(12, 4), anchor="w")

        self.chat_display = scrolledtext.ScrolledText(
            parent, bg=BG2, fg=TEXT, font=FONT_BODY,
            relief="flat", padx=12, pady=8,
            insertbackground=TEXT, state="disabled", wrap="word",
        )
        self.chat_display.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # Tags for styling
        self.chat_display.tag_configure("user", foreground=ACCENT2, font=("DejaVu Sans", 11, "bold"))
        self.chat_display.tag_configure("ai", foreground=TEXT)
        self.chat_display.tag_configure("thinking", foreground=MUTED, font=("DejaVu Sans", 10, "italic"))

        # Input row
        inp_frame = tk.Frame(parent, bg=BG)
        inp_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.chat_input = tk.Text(inp_frame, height=3, bg=BG2, fg=TEXT,
                                   insertbackground=TEXT, relief="flat",
                                   font=FONT_BODY, wrap="word")
        self.chat_input.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.chat_input.bind("<Return>", self._chat_enter)
        self.chat_input.bind("<Shift-Return>", lambda e: None)

        self._btn(inp_frame, "Отправить\n(Enter)", self._chat_send, ACCENT).pack(side="right", padx=(4, 0))

        self._voice_btn = self._btn(inp_frame, "🎙 Голос", self._voice_start, BG3)
        self._voice_btn.pack(side="right", padx=(4, 0))
        self._voice_recording = False

        self._chat_history = []
        self._chat_file = os.path.join(AIM_DIR, "chat_history.json")
        self._load_chat_history()
        self._welcome_message()

    def _load_chat_history(self):
        try:
            if os.path.exists(self._chat_file):
                with open(self._chat_file, encoding="utf-8") as f:
                    self._chat_history = json.load(f)
        except Exception:
            self._chat_history = []

    def _save_chat_history(self):
        try:
            with open(self._chat_file, "w", encoding="utf-8") as f:
                json.dump(self._chat_history[-100:], f, ensure_ascii=False)
        except Exception:
            pass

    def _welcome_message(self):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", "AI Специалист:\n", "ai")
        self.chat_display.insert("end",
            "Здравствуйте! Я — цифровой специалист по интегративной медицине.\n"
            "Помогу с анализом лабораторных данных, симптомов и разработкой "
            "индивидуального протокола лечения.\n\n"
            "Вы можете спросить о конкретном пациенте или задать общий медицинский вопрос.\n\n",
            "ai"
        )
        self.chat_display.configure(state="disabled")

    def _chat_enter(self, event):
        if not event.state & 1:  # Shift not held
            self._chat_send()
            return "break"

    def _chat_send(self):
        msg = self.chat_input.get("1.0", "end").strip()
        if not msg:
            return
        self.chat_input.delete("1.0", "end")

        # Show user message
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"Вы:\n", "user")
        self.chat_display.insert("end", f"{msg}\n\n")
        self.chat_display.insert("end", "AI: думает...\n\n", "thinking")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

        self._chat_history.append({"role": "user", "content": msg})

        # Add patient context if selected
        p = self._current_patient()
        patient_ctx = ""
        if p:
            analysis = read_analysis(p["folder"])[:1500]
            patient_ctx = f"\n\nТекущий пациент: {p['name']}\nАнализ:\n{analysis}"

        history_copy = list(self._chat_history[-10:])

        # Tag the "думает..." marker so we can delete it precisely
        thinking_mark = f"thinking_{id(msg)}"

        def done(reply):
            """Called in main thread via after() — safe to update GUI."""
            self._chat_history.append({"role": "assistant", "content": reply})
            self._save_chat_history()
            self.chat_display.configure(state="normal")
            # Remove "думает..." by tag marks (reliable, no string search)
            try:
                self.chat_display.delete(thinking_mark + "_start",
                                          thinking_mark + "_end")
            except Exception:
                pass
            self.chat_display.insert("end", "AI Специалист:\n", "ai")
            self.chat_display.insert("end", f"{reply}\n\n", "ai")
            self.chat_display.see("end")
            self.chat_display.configure(state="disabled")
            self._set_status("Готово")

        # Mark the "думает..." span for later deletion
        self.chat_display.configure(state="normal")
        self.chat_display.mark_set(thinking_mark + "_start", "end-1c")
        self.chat_display.configure(state="disabled")

        def run_in_thread():
            """Runs in background thread — never touches GUI directly."""
            try:
                from llm import ask_llm
                from medical_system import SYSTEM_PROMPT
                system = SYSTEM_PROMPT + (
                    f"\n\nКОНТЕКСТ ТЕКУЩЕГО ПАЦИЕНТА:\n{patient_ctx}" if patient_ctx else ""
                )
                # Build prompt from history
                hist_text = "\n".join(
                    f"{'Врач' if m['role']=='user' else 'AI'}: {m['content']}"
                    for m in history_copy[:-1]
                )
                last = history_copy[-1]["content"] if history_copy else ""
                prompt = (f"История:\n{hist_text}\n\n{last}" if hist_text else last)
                reply = ask_llm(prompt, system=system, max_tokens=1024, temperature=0.4)
            except Exception as e:
                reply = f"[Ошибка: {e}]"
            # Schedule GUI update in main thread
            self.after(0, lambda: done(reply))

        threading.Thread(target=run_in_thread, daemon=True).start()

    # ── Voice input ───────────────────────────────────────────

    def _voice_start(self):
        """Toggle: начать / остановить запись голоса."""
        if self._voice_recording:
            self._voice_stop()
        else:
            self._voice_begin()

    def _voice_begin(self):
        try:
            from voice_input import VoiceRecorder
        except ImportError:
            messagebox.showerror("Голос", "Установите: pip install sounddevice")
            return
        try:
            self._recorder = VoiceRecorder()
            self._recorder.start()
        except RuntimeError as e:
            messagebox.showerror("Голос", str(e))
            return
        self._voice_recording = True
        self._voice_btn.configure(text="⏹ Стоп", bg=RED)
        self._set_status("🎙 Запись... нажмите ещё раз чтобы остановить")

    def _voice_stop(self):
        self._voice_recording = False
        self._voice_btn.configure(text="🎙 Голос", bg=BG3)
        self._set_status("⏳ Транскрипция...")

        def transcribe():
            try:
                text = self._recorder.stop_and_transcribe()
            except Exception as e:
                text = ""
                self.after(0, lambda: self._set_status(f"Ошибка голоса: {e}"))
            if text:
                self.after(0, lambda: self._voice_insert(text))
            else:
                self.after(0, lambda: self._set_status("Голос: ничего не распознано"))

        threading.Thread(target=transcribe, daemon=True).start()

    def _voice_insert(self, text: str):
        """Вставить распознанный текст в поле чата и сразу отправить."""
        self.chat_input.delete("1.0", "end")
        self.chat_input.insert("1.0", text)
        self._set_status("Готово")
        self._chat_send()

    # ── Tab: System ───────────────────────────────────────────

    # ── Tab: Nutrition ────────────────────────────────────────

    def _build_tab_nutrition(self, parent):
        """Editable forbidden/allowed foods list. Changes rebuild AIM core."""
        try:
            from space_nutrition import FORBIDDEN_FOODS, ALLOWED_FOODS, save_rules
            self._nutr_forbidden = [dict(f) for f in FORBIDDEN_FOODS]
            self._nutr_allowed   = [dict(a) for a in ALLOWED_FOODS]
        except Exception as e:
            tk.Label(parent, text=f"Ошибка загрузки питания: {e}",
                     bg=BG, fg=RED).pack(padx=20, pady=20)
            return

        # ── Header ────────────────────────────────────────────
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(hdr, text="🥗 Протокол питания доктора Джабы Ткемаладзе",
                 font=FONT_H1, bg=BG, fg=TEXT).pack(side="left")
        self._btn(hdr, "💾 СОХРАНИТЬ В ЯДРО AIM",
                  self._nutrition_save, ACCENT).pack(side="right", padx=4)

        # ── Split pane ────────────────────────────────────────
        pane = tk.Frame(parent, bg=BG)
        pane.pack(fill="both", expand=True, padx=12, pady=4)
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)

        # Left: Forbidden
        left = tk.Frame(pane, bg=BG2, bd=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        tk.Label(left, text="❌ ЗАПРЕЩЕНО", font=FONT_H2,
                 bg=BG2, fg=RED).pack(padx=10, pady=(8, 2), anchor="w")

        f_scroll = tk.Frame(left, bg=BG2)
        f_scroll.pack(fill="both", expand=True, padx=6, pady=2)
        self._nutr_f_lb = tk.Listbox(
            f_scroll, bg=BG3, fg="#ef9a9a", font=FONT_BODY,
            selectbackground=RED, selectforeground=WHITE,
            relief="flat", bd=0, activestyle="none",
        )
        f_sb = tk.Scrollbar(f_scroll, orient="vertical",
                            command=self._nutr_f_lb.yview)
        self._nutr_f_lb.config(yscrollcommand=f_sb.set)
        f_sb.pack(side="right", fill="y")
        self._nutr_f_lb.pack(fill="both", expand=True)
        self._nutr_f_lb.bind("<<ListboxSelect>>", self._nutr_select_forbidden)

        f_btns = tk.Frame(left, bg=BG2)
        f_btns.pack(fill="x", padx=6, pady=4)
        self._btn(f_btns, "+ Добавить",
                  self._nutr_add_forbidden, BG3).pack(side="left", padx=2)
        self._btn(f_btns, "✏ Изменить",
                  self._nutr_edit_forbidden, BG3).pack(side="left", padx=2)
        self._btn(f_btns, "✕ Удалить",
                  self._nutr_del_forbidden, RED).pack(side="right", padx=2)

        # Right: Allowed
        right = tk.Frame(pane, bg=BG2, bd=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        tk.Label(right, text="✅ РАЗРЕШЕНО", font=FONT_H2,
                 bg=BG2, fg=GREEN).pack(padx=10, pady=(8, 2), anchor="w")

        a_scroll = tk.Frame(right, bg=BG2)
        a_scroll.pack(fill="both", expand=True, padx=6, pady=2)
        self._nutr_a_lb = tk.Listbox(
            a_scroll, bg=BG3, fg="#a5d6a7", font=FONT_BODY,
            selectbackground=GREEN, selectforeground=WHITE,
            relief="flat", bd=0, activestyle="none",
        )
        a_sb = tk.Scrollbar(a_scroll, orient="vertical",
                            command=self._nutr_a_lb.yview)
        self._nutr_a_lb.config(yscrollcommand=a_sb.set)
        a_sb.pack(side="right", fill="y")
        self._nutr_a_lb.pack(fill="both", expand=True)
        self._nutr_a_lb.bind("<<ListboxSelect>>", self._nutr_select_allowed)

        a_btns = tk.Frame(right, bg=BG2)
        a_btns.pack(fill="x", padx=6, pady=4)
        self._btn(a_btns, "+ Добавить",
                  self._nutr_add_allowed, BG3).pack(side="left", padx=2)
        self._btn(a_btns, "✏ Изменить",
                  self._nutr_edit_allowed, BG3).pack(side="left", padx=2)
        self._btn(a_btns, "✕ Удалить",
                  self._nutr_del_allowed, RED).pack(side="right", padx=2)

        # ── Detail panel ──────────────────────────────────────
        detail_frame = tk.Frame(parent, bg=BG3)
        detail_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(detail_frame, text="Подробности:", font=FONT_SMALL,
                 bg=BG3, fg=MUTED).pack(padx=8, pady=(4, 0), anchor="w")
        self._nutr_detail = tk.Text(
            detail_frame, bg=BG3, fg=TEXT2, font=FONT_BODY,
            height=5, relief="flat", wrap="word", state="disabled",
        )
        self._nutr_detail.pack(fill="x", padx=8, pady=(2, 6))

        self._nutr_refresh_lists()

    def _nutr_refresh_lists(self):
        self._nutr_f_lb.delete(0, "end")
        self._nutr_f_idx = []   # maps listbox index → item index (or None for headers)
        cur_cat = None
        for i, f in enumerate(self._nutr_forbidden):
            cat = f.get("category", "")
            if cat != cur_cat:
                cur_cat = cat
                self._nutr_f_lb.insert("end", f"── {cat} ──")
                self._nutr_f_idx.append(None)
            self._nutr_f_lb.insert("end", f"  ❌  {f['name']}")
            self._nutr_f_idx.append(i)

        self._nutr_a_lb.delete(0, "end")
        self._nutr_a_idx = []
        cur_cat = None
        for i, a in enumerate(self._nutr_allowed):
            cat = a.get("category", "")
            if cat != cur_cat:
                cur_cat = cat
                self._nutr_a_lb.insert("end", f"── {cat} ──")
                self._nutr_a_idx.append(None)
            self._nutr_a_lb.insert("end", f"  ✅  {a['name']}")
            self._nutr_a_idx.append(i)

    def _nutr_show_detail(self, text: str):
        self._nutr_detail.configure(state="normal")
        self._nutr_detail.delete("1.0", "end")
        self._nutr_detail.insert("end", text)
        self._nutr_detail.configure(state="disabled")

    def _nutr_select_forbidden(self, _event=None):
        sel = self._nutr_f_lb.curselection()
        if not sel:
            return
        real_idx = self._nutr_f_idx[sel[0]] if hasattr(self, "_nutr_f_idx") else sel[0]
        if real_idx is None:
            return
        f = self._nutr_forbidden[real_idx]
        txt = (f"❌ {f['name']}\n\n"
               f"ПОЧЕМУ (из «Места Силы» Том 3):\n{f.get('reason', '—')}\n\n"
               f"ЧТО ПРОИСХОДИТ В ТЕЛЕ:\n{f.get('effect', '—')}\n\n"
               f"ЧЕМ ЗАМЕНИТЬ:\n{f.get('substitute', '—')}")
        self._nutr_show_detail(txt)

    def _nutr_select_allowed(self, _event=None):
        sel = self._nutr_a_lb.curselection()
        if not sel:
            return
        real_idx = self._nutr_a_idx[sel[0]] if hasattr(self, "_nutr_a_idx") else sel[0]
        if real_idx is None:
            return
        a = self._nutr_allowed[real_idx]
        self._nutr_show_detail(f"✅ {a['name']}\n\n{a.get('note', '—')}")

    def _nutr_edit_dialog(self, title: str, data: dict, is_forbidden: bool) -> dict | None:
        """Generic edit dialog. Returns updated dict or None if cancelled."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.geometry("600x520")
        dlg.grab_set()
        result = {}

        fields = [
            ("name",      "Название продукта:"),
            ("aliases_str", "Ключевые слова (через запятую):"),
        ]
        if is_forbidden:
            fields += [
                ("reason",     "ПОЧЕМУ запрещён (из «Места Силы»):"),
                ("effect",     "ЧТО ПРОИСХОДИТ В ТЕЛЕ:"),
                ("substitute", "ЧЕМ ЗАМЕНИТЬ:"),
            ]
        else:
            fields += [("note", "Описание / примечание:")]

        widgets = {}
        for key, label in fields:
            tk.Label(dlg, text=label, font=FONT_SMALL, bg=BG, fg=TEXT2).pack(
                padx=16, pady=(8, 0), anchor="w")
            if key in ("reason", "effect", "substitute", "note"):
                w = tk.Text(dlg, bg=BG2, fg=TEXT, font=FONT_BODY,
                            height=3, relief="flat", wrap="word")
                val = data.get(key, "")
                w.insert("1.0", val)
            else:
                w = tk.Entry(dlg, bg=BG2, fg=TEXT, font=FONT_BODY,
                             relief="flat", insertbackground=TEXT)
                if key == "aliases_str":
                    val = ", ".join(data.get("aliases", []))
                else:
                    val = data.get(key, "")
                w.insert(0, val)
            w.pack(fill="x", padx=16, pady=(2, 0))
            widgets[key] = w

        def _save():
            for key, _ in fields:
                w = widgets[key]
                val = w.get("1.0", "end").strip() if isinstance(w, tk.Text) else w.get().strip()
                result[key] = val
            # Convert aliases_str back to list
            if "aliases_str" in result:
                result["aliases"] = [x.strip() for x in result.pop("aliases_str").split(",") if x.strip()]
            dlg.destroy()

        def _cancel():
            result.clear()
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(pady=12)
        self._btn(btn_row, "💾 Сохранить", _save, ACCENT).pack(side="left", padx=6)
        self._btn(btn_row, "Отмена", _cancel, BG3).pack(side="left", padx=6)
        dlg.wait_window()
        return result if result else None

    def _nutr_add_forbidden(self):
        data = self._nutr_edit_dialog("Добавить запрещённый продукт",
                                      {}, is_forbidden=True)
        if data and data.get("name"):
            self._nutr_forbidden.append(data)
            self._nutr_refresh_lists()

    def _nutr_edit_forbidden(self):
        sel = self._nutr_f_lb.curselection()
        if not sel:
            return
        real_idx = self._nutr_f_idx[sel[0]] if hasattr(self, "_nutr_f_idx") else sel[0]
        if real_idx is None:
            return
        data = self._nutr_edit_dialog("Изменить запрещённый продукт",
                                      dict(self._nutr_forbidden[real_idx]), is_forbidden=True)
        if data and data.get("name"):
            self._nutr_forbidden[real_idx] = data
            self._nutr_refresh_lists()

    def _nutr_del_forbidden(self):
        sel = self._nutr_f_lb.curselection()
        if not sel:
            return
        real_idx = self._nutr_f_idx[sel[0]] if hasattr(self, "_nutr_f_idx") else sel[0]
        if real_idx is None:
            return
        name = self._nutr_forbidden[real_idx]["name"]
        if messagebox.askyesno("Удалить", f"Удалить «{name}» из запрещённых?"):
            self._nutr_forbidden.pop(real_idx)
            self._nutr_refresh_lists()
            self._nutr_show_detail("")

    def _nutr_add_allowed(self):
        data = self._nutr_edit_dialog("Добавить разрешённый продукт",
                                      {}, is_forbidden=False)
        if data and data.get("name"):
            self._nutr_allowed.append(data)
            self._nutr_refresh_lists()

    def _nutr_edit_allowed(self):
        sel = self._nutr_a_lb.curselection()
        if not sel:
            return
        real_idx = self._nutr_a_idx[sel[0]] if hasattr(self, "_nutr_a_idx") else sel[0]
        if real_idx is None:
            return
        data = self._nutr_edit_dialog("Изменить разрешённый продукт",
                                      dict(self._nutr_allowed[real_idx]), is_forbidden=False)
        if data and data.get("name"):
            self._nutr_allowed[real_idx] = data
            self._nutr_refresh_lists()

    def _nutr_del_allowed(self):
        sel = self._nutr_a_lb.curselection()
        if not sel:
            return
        real_idx = self._nutr_a_idx[sel[0]] if hasattr(self, "_nutr_a_idx") else sel[0]
        if real_idx is None:
            return
        name = self._nutr_allowed[real_idx]["name"]
        if messagebox.askyesno("Удалить", f"Удалить «{name}» из разрешённых?"):
            self._nutr_allowed.pop(real_idx)
            self._nutr_refresh_lists()
            self._nutr_show_detail("")

    def _nutrition_save(self):
        """Save changes → rebuild AIM core knowledge."""
        try:
            from space_nutrition import save_rules
            save_rules(self._nutr_forbidden, self._nutr_allowed)
            self._nutr_show_detail(
                "✅ Сохранено в nutrition_rules.json\n"
                "✅ Ядро знаний AIM перестроено\n"
                "✅ SYSTEM_PROMPT обновлён\n\n"
                f"Запрещено: {len(self._nutr_forbidden)} продуктов\n"
                f"Разрешено:  {len(self._nutr_allowed)} продуктов"
            )
            self._set_status("✅ Правила питания сохранены в ядро AIM")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _build_tab_system(self, parent):
        tk.Label(parent, text="Управление системой AIM",
                 font=FONT_H1, bg=BG, fg=TEXT).pack(padx=20, pady=(16, 4), anchor="w")
        tk.Label(parent, text=f"Путь: {AIM_DIR}",
                 font=FONT_SMALL, bg=BG, fg=MUTED).pack(padx=20, anchor="w")

        # Action buttons grid
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x", padx=20, pady=16)

        actions = [
            ("⟳ Обработать всех пациентов",
             lambda: self._run_cmd(["patient_intake.py", "--all"]),
             ACCENT),
            ("⟳ Принудительный пересчёт всех",
             lambda: self._run_cmd(["patient_intake.py", "--all", "--force"]),
             BG3),
            ("↑ Обработать INBOX",
             lambda: self._run_cmd(["patient_intake.py"]),
             BG3),
            ("📊 Список всех пациентов",
             lambda: self._run_cmd(["patient_intake.py", "--list"]),
             BG3),
        ]
        for i, (label, cmd, color) in enumerate(actions):
            self._btn(grid, label, cmd, color).grid(
                row=i // 2, column=i % 2, padx=6, pady=4, sticky="ew"
            )
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        # ── Data backup ────────────────────────────────────────
        data_frame = tk.Frame(parent, bg=BG2)
        data_frame.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(data_frame, text="💾 Бэкап данных пациентов",
                 font=FONT_H2, bg=BG2, fg=TEXT2).pack(side="left", padx=10, pady=6)
        self._btn(data_frame, "💾 Создать бэкап сейчас",
                  self._data_backup, "#2E7D32").pack(side="right", padx=8, pady=4)
        self._btn(data_frame, "📋 Список бэкапов",
                  self._data_backup_list, BG3).pack(side="right", padx=4, pady=4)

        # ── GitHub backup ──────────────────────────────────────
        backup_frame = tk.Frame(parent, bg=BG2)
        backup_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(backup_frame, text="☁ GitHub (код)",
                 font=FONT_H2, bg=BG2, fg=TEXT2).pack(side="left", padx=10, pady=6)
        self._btn(backup_frame, "☁ Бэкап кода на GitHub",
                  self._github_backup, "#1565C0").pack(side="right", padx=8, pady=4)
        self._btn(backup_frame, "👁 Git status",
                  self._github_status, BG3).pack(side="right", padx=4, pady=4)

        tk.Label(parent, text="Вывод команды:", font=FONT_H2,
                 bg=BG, fg=TEXT2).pack(padx=20, pady=(8, 4), anchor="w")

        self.sys_output = scrolledtext.ScrolledText(
            parent, bg=BG2, fg=TEXT2, font=FONT_MONO,
            relief="flat", padx=10, pady=8,
        )
        self.sys_output.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.sys_output.insert("end", "Система готова.\n")

    def _run_cmd(self, args: list):
        self.sys_output.delete("1.0", "end")
        self.sys_output.insert("end", f"Запуск: python3 {' '.join(args)}\n")
        self.sys_output.insert("end", "─" * 40 + "\n")
        self._set_status("Выполняется...")

        def done(out):
            self.after(0, lambda: (
                self.sys_output.insert("end", out + "\n"),
                self.sys_output.see("end"),
                self._set_status("Готово"),
                self.refresh_patients(),
            ))

        run_python([os.path.join(AIM_DIR, args[0])] + args[1:], callback=done)

    def _data_backup(self):
        """Create encrypted data backup from GUI."""
        self.sys_output.delete("1.0", "end")
        self.sys_output.insert("end", "💾 Создаю зашифрованный бэкап данных...\n" + "─" * 40 + "\n")
        self._set_status("Бэкап данных...")

        def run():
            import io, contextlib
            sys.path.insert(0, AIM_DIR)
            from backup_data import create_backup
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = create_backup(verbose=True)
            return buf.getvalue(), result is not None

        def done():
            try:
                out, success = run()
            except Exception as e:
                out, success = str(e), False
            icon = "✅" if success else "❌"
            self.after(0, lambda: (
                self.sys_output.insert("end", out + "\n"),
                self.sys_output.see("end"),
                self._set_status(f"{icon} {'Бэкап создан' if success else 'Ошибка бэкапа'}"),
            ))

        import threading
        threading.Thread(target=done, daemon=True).start()

    def _data_backup_list(self):
        """Show list of backups in output panel."""
        self.sys_output.delete("1.0", "end")
        sys.path.insert(0, AIM_DIR)
        from backup_data import backup_info
        self.sys_output.insert("end", backup_info())
        self.sys_output.see("end")

    def _github_backup(self):
        """Manual GitHub backup from GUI."""
        self.sys_output.delete("1.0", "end")
        self.sys_output.insert("end", "☁ Запуск бэкапа на GitHub...\n" + "─" * 40 + "\n")
        self._set_status("Бэкап на GitHub...")

        def run():
            import sys as _sys
            _sys.path.insert(0, AIM_DIR)
            from backup_github import backup
            lines = []
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                success = backup(dry_run=False, verbose=True)
            return buf.getvalue(), success

        def done():
            try:
                out, success = run()
            except Exception as e:
                out, success = str(e), False
            icon = "✅" if success else "❌"
            self.after(0, lambda: (
                self.sys_output.insert("end", out + "\n"),
                self.sys_output.see("end"),
                self._set_status(f"{icon} {'Бэкап загружен на GitHub' if success else 'Ошибка бэкапа'}"),
            ))

        import threading
        threading.Thread(target=done, daemon=True).start()

    def _github_status(self):
        """Show git status in output panel."""
        self.sys_output.delete("1.0", "end")
        import subprocess
        result = subprocess.run(
            ["git", "status"], cwd=AIM_DIR, capture_output=True, text=True
        )
        out = result.stdout + result.stderr
        self.sys_output.insert("end", out)
        self.sys_output.see("end")

    # ── Patient actions ────────────────────────────────────────

    def _process_patient(self, p: dict, force: bool = False):
        self._set_status(f"Обработка: {p['name']}...")
        self.notebook.select(self._tab_analysis)

        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("end", f"Обработка {p['name']}...\n")
        self.analysis_text.configure(state="disabled")

        args = [os.path.join(AIM_DIR, "patient_intake.py"),
                "--folder", p["folder"]]
        if force:
            args.append("--force")

        def done(out):
            self.after(0, lambda: (
                self.analysis_text.configure(state="normal"),
                self.analysis_text.delete("1.0", "end"),
                self.analysis_text.insert("end", read_analysis(p["folder"])),
                self.analysis_text.configure(state="disabled"),
                self._set_status("Готово"),
                self.refresh_patients(),
            ))

        run_python(args, callback=done)

    def _process_all(self):
        self.notebook.select(self._tab_system)
        self._run_cmd(["patient_intake.py", "--all"])

    def _new_patient(self):
        win = tk.Toplevel(self, bg=BG)
        win.title("Новый пациент")
        win.geometry("440x300")
        win.resizable(False, False)

        tk.Label(win, text="Новый пациент", font=FONT_H1, bg=BG, fg=TEXT).pack(pady=16)

        fields = {}
        for label, key in [("Фамилия:", "last"), ("Имя:", "first"),
                            ("Дата рождения (ГГГГ_ММ_ДД):", "dob")]:
            row = tk.Frame(win, bg=BG)
            row.pack(fill="x", padx=24, pady=4)
            tk.Label(row, text=label, font=FONT_BODY, bg=BG, fg=TEXT2,
                     width=28, anchor="w").pack(side="left")
            e = tk.Entry(row, bg=BG2, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=FONT_BODY)
            e.pack(side="left", fill="x", expand=True, ipady=4)
            fields[key] = e

        def create():
            last = fields["last"].get().strip().capitalize()
            first = fields["first"].get().strip().capitalize()
            dob = fields["dob"].get().strip()
            if not last or not first:
                messagebox.showerror("Ошибка", "Введите фамилию и имя")
                return
            folder_name = f"{last}_{first}" + (f"_{dob}" if dob else "")
            folder_path = os.path.join(PATIENTS_DIR, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            messagebox.showinfo("AIM", f"Создан пациент:\n{folder_path}")
            win.destroy()
            self.refresh_patients()

        self._btn(win, "Создать", create, ACCENT).pack(pady=16)

    def _sync_whatsapp(self):
        """Auto-extract patients from running WhatsApp Desktop via CDP."""
        self.notebook.select(self._tab_system)
        self.sys_output.delete("1.0", "end")
        self.sys_output.insert("end", "Подключение к WhatsApp Desktop...\n")
        self.sys_output.insert("end", "─" * 40 + "\n")
        self._set_status("WhatsApp sync...")

        def done(out):
            self.after(0, lambda: (
                self.sys_output.insert("end", out + "\n"),
                self.sys_output.see("end"),
                self._set_status("Готово"),
                self.refresh_patients(),
            ))

        run_python([os.path.join(AIM_DIR, "wa_extractor.py")], callback=done)

    def _import_inbox(self):
        # Let user pick a folder to use as inbox or use default
        path = filedialog.askdirectory(
            title="Выберите папку с экспортом WhatsApp или файлами пациента",
            initialdir=INBOX_DIR if os.path.exists(INBOX_DIR) else PATIENTS_DIR
        )
        if path:
            self.notebook.select(self._tab_system)
            self._run_cmd(["patient_intake.py", "--inbox", path])

    # ── Patients list management ───────────────────────────────

    def refresh_patients(self):
        self._patients = list_patients()
        self._filter_patients()
        self._set_status(f"Пациентов: {len(self._patients)}")

    def _filter_patients(self):
        query = self.search_var.get().lower()
        if query in ("", "поиск..."):
            self._filtered = self._patients
        else:
            self._filtered = [p for p in self._patients
                               if query in p["name"].lower()]

        self.patient_listbox.delete(0, "end")
        for p in self._filtered:
            indicator = "✓" if p["has_analysis"] else "·"
            self.patient_listbox.insert("end", f" {indicator} {p['name']}")

    def _on_patient_select(self, event):
        sel = self.patient_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._filtered):
            return
        p = self._filtered[idx]
        self._selected_patient = p
        self._show_patient_overview(p)
        self._refresh_analysis()
        self._refresh_labs()

    def _current_patient(self):
        return getattr(self, "_selected_patient", None)

    # ── Utility ───────────────────────────────────────────────

    def _btn(self, parent, text, command, bg=BG3, fg=WHITE):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=bg, fg=fg, activebackground=ACCENT, activeforeground=BG,
            relief="flat", font=FONT_BODY, padx=12, pady=6,
            cursor="hand2", borderwidth=0,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=ACCENT if bg != ACCENT else ACCENT2))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    def _set_status(self, msg: str):
        self.after(0, lambda: self.statusbar.configure(text=msg))

    def _check_ollama(self):
        def check():
            try:
                from llm import _get_api_key
                key = _get_api_key()
                if key:
                    status = "● DeepSeek: API ключ найден"
                else:
                    status = "● DeepSeek: ключ не задан (~/.aim_env)"
            except Exception as e:
                status = f"● DeepSeek: ошибка ({e})"
            self.after(0, lambda: self.status_var.set(status))
        threading.Thread(target=check, daemon=True).start()


# ══════════════════════════════════════════════════════════════

def _start_telegram_bot():
    """Launch telegram_bot.py as background subprocess."""
    python = os.path.join(AIM_DIR, "venv/bin/python3")
    if not os.path.exists(python):
        python = sys.executable
    bot_script = os.path.join(AIM_DIR, "telegram_bot.py")
    if not os.path.exists(bot_script):
        return
    # Check token present
    env_file = os.path.expanduser("~/.aim_env")
    has_token = False
    if os.path.exists(env_file):
        for line in open(env_file):
            if line.strip().startswith("TELEGRAM_BOT_TOKEN=") and "=" in line:
                val = line.strip().split("=", 1)[1]
                if val and val != "...":
                    has_token = True
    if not has_token:
        return
    def _run():
        try:
            subprocess.run([python, bot_script], cwd=AIM_DIR)
        except Exception:
            pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def main():
    # Try to install Pillow if missing
    try:
        from PIL import Image
    except ImportError:
        pass

    # Auto-start Telegram bot in background
    threading.Thread(target=_start_telegram_bot, daemon=True).start()

    app = AIMApp()
    app.mainloop()


if __name__ == "__main__":
    main()
