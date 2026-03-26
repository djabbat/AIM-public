#!/usr/bin/env python3
"""
aim_gui.py — AIM Desktop GUI (customtkinter)
Правило: меню GUI == меню терминала (medical_system.py).
"""

import os, sys, threading, subprocess
from pathlib import Path

AI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AI_DIR)
_sp = __import__("glob").glob(os.path.expanduser("~/Desktop/AIM/venv/lib/python3.*/site-packages"))
if _sp: sys.path.insert(0, _sp[0])

import customtkinter as ctk
import i18n as _i18n
import db as _db
import auth as _auth
from medical_system import (
    list_patients, analyze_patient, show_patient_analysis,
    analyze_labs_only, show_aging_prediction, show_ze_history,
    search_patients_by_symptom, db_stats, search_protocols,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONT_T  = ("Helvetica", 18, "bold")
FONT_M  = ("Helvetica", 13)
FONT_B  = ("Helvetica", 12)
FONT_C  = ("Courier",   11)
FONT_S  = ("Helvetica", 10)
C_ACC   = "#1f6aa5"
C_SIDE  = "#1a1a2e"
C_SEP   = "#2d2d4e"
C_ERR   = "#f44336"

NEWS_TOPICS = [
    ("🧬 Aging / Geroscience",   "centriole damage aging stem cells geroscience longevity 2024 2025"),
    ("🫀 Integrative Medicine",  "integrative medicine holistic cardiology nutrition 2024 2025"),
    ("💗 HRV / Ze-Theory",       "heart rate variability HRV biomarker aging cognitive 2024 2025"),
    ("🏔 Kartvely / Caucasus",   "Georgian history Caucasus archaeology Khvamli petroglyphs 2024 2025"),
    ("🌌 Šamnu Azuzi / Gilgamesh","Gilgamesh opera Georgian polyphony ancient Mesopotamia 2024 2025"),
    ("🔬 CDATA / Centrioles",    "centriole mother daughter spindle fidelity stem cell aging 2024 2025"),
    ("📖 Ze Publications",       "Ze velocity information theory neuroscience brain dynamics 2024 2025"),
]


# ── Login ──────────────────────────────────────────────────────────────────────

class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        _i18n.load()
        if not _i18n.LANG_FILE.exists():
            self._lang_dialog()
        self.title("AIM — Login")
        self.geometry("420x520")
        self.resizable(False, False)
        self._user = None
        self._build()

    def _lang_dialog(self):
        d = ctk.CTkToplevel(self); d.title("Language"); d.geometry("280x320"); d.grab_set()
        ctk.CTkLabel(d, text="Select Language / Выберите язык", font=FONT_B).pack(pady=14)
        for code, name in _i18n.LANG_NAMES.items():
            ctk.CTkButton(d, text=name, command=lambda c=code: (_i18n.set_lang(c), d.destroy()),
                          font=FONT_M).pack(fill="x", padx=24, pady=3)
        self.wait_window(d)

    def _build(self):
        t = _i18n.t
        self.configure(fg_color="#16213e")
        fr = ctk.CTkFrame(self, corner_radius=16, fg_color="#0f3460")
        fr.pack(expand=True, fill="both", padx=40, pady=40)
        ctk.CTkLabel(fr, text="🔐  AIM", font=("Helvetica",28,"bold"), text_color="white").pack(pady=(28,4))
        ctk.CTkLabel(fr, text=t("banner_title"), font=FONT_S, text_color="#aaaacc").pack(pady=(0,22))
        ctk.CTkLabel(fr, text=t("email_prompt").strip(), font=FONT_B, anchor="w").pack(fill="x", padx=28)
        self.ev = ctk.StringVar()
        ctk.CTkEntry(fr, textvariable=self.ev, placeholder_text="email",
                     height=38, font=FONT_B).pack(fill="x", padx=28, pady=(2,10))
        ctk.CTkLabel(fr, text=t("password_prompt").strip(), font=FONT_B, anchor="w").pack(fill="x", padx=28)
        self.pv = ctk.StringVar()
        ctk.CTkEntry(fr, textvariable=self.pv, show="●", height=38,
                     font=FONT_B).pack(fill="x", padx=28, pady=(2,10))
        self.rv = ctk.BooleanVar()
        ctk.CTkCheckBox(fr, text=t("remember_me").strip().rstrip("?:"),
                        variable=self.rv, font=FONT_S).pack(padx=28, anchor="w", pady=(0,14))
        self.mv = ctk.StringVar()
        ctk.CTkLabel(fr, textvariable=self.mv, text_color=C_ERR, font=FONT_S).pack()
        ctk.CTkButton(fr, text=t("login_header"), height=40, font=FONT_M,
                      command=self._login).pack(fill="x", padx=28, pady=(8,20))
        self.bind("<Return>", lambda e: self._login())

    def _login(self):
        _db.init_db(); _auth.init_auth_tables(); _auth._ensure_admin_exists()
        u = _auth.login(self.ev.get().strip(), self.pv.get(), remember_me=self.rv.get())
        if u: self._user = u; self.destroy()
        else: self.mv.set("✗  " + _i18n.t("wrong_creds", n="?"))

    def get_user(self): return self._user


# ── Main ───────────────────────────────────────────────────────────────────────

class AimGUI(ctk.CTk):
    def __init__(self, user):
        super().__init__()
        self.user = user
        _i18n.load()
        self.title("AIM — " + _i18n.t("banner_title"))
        self.geometry("1200x760")
        self.minsize(900, 600)
        self._build()
        self._go("patients")

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sb = ctk.CTkScrollableFrame(self, width=244, corner_radius=0, fg_color=C_SIDE)
        self.sb.grid(row=0, column=0, sticky="nsew")

        rp = ctk.CTkFrame(self, corner_radius=0, fg_color="#1e1e2e")
        rp.grid(row=0, column=1, sticky="nsew")
        rp.grid_rowconfigure(1, weight=1)
        rp.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(rp, height=48, fg_color="#252540", corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew"); hdr.grid_columnconfigure(0, weight=1)
        self.hv = ctk.StringVar()
        ctk.CTkLabel(hdr, textvariable=self.hv, font=FONT_T, anchor="w").grid(
            row=0, column=0, padx=20, pady=10, sticky="w")
        ctk.CTkLabel(hdr, text=f"  {self.user.get('display_name','?')}  [{self.user.get('role','?')}]",
                     font=FONT_S, text_color="#8888aa").grid(row=0, column=1, padx=12)

        self.cf = ctk.CTkFrame(rp, fg_color="#1e1e2e", corner_radius=0)
        self.cf.grid(row=1, column=0, sticky="nsew")
        self.cf.grid_rowconfigure(0, weight=1)
        self.cf.grid_columnconfigure(0, weight=1)

        self._build_sb()

    def _build_sb(self):
        t = _i18n.t
        self._btns = {}

        ctk.CTkLabel(self.sb, text="AIM", font=("Helvetica",22,"bold"),
                     text_color="white").pack(pady=(18,4))
        ctk.CTkLabel(self.sb, text=t("banner_doctor"),
                     font=FONT_S, text_color="#8888aa").pack(pady=(0,14))

        def sep(txt=""):
            ctk.CTkLabel(self.sb, text=txt, font=("Helvetica",10),
                         text_color="#555577").pack(pady=(8,2), padx=8, anchor="w")

        def btn(key, label):
            b = ctk.CTkButton(self.sb, text=label, anchor="w", font=FONT_S,
                              height=32, corner_radius=6, fg_color="transparent",
                              hover_color=C_SEP, command=lambda k=key: self._go(k))
            b.pack(fill="x", padx=8, pady=2)
            self._btns[key] = b

        for k, lk in [("patients","m1"),("process1","m2"),("process_all","m3"),
                      ("analysis","m4"),("labs","m5"),("chat","m7"),
                      ("deviations","m8"),("search","m9"),("stats","m0")]:
            btn(k, t(lk))

        sep("── " + t("msep1").lstrip("─ "))
        for k, lk in [("aging","ma"),("ze_hrv","mb"),("protocols","mc"),
                      ("wearable","mw"),("cdata_gui","mgui"),("clusters","mk")]:
            btn(k, t(lk))

        btn("news", t("mnews"))

        if self.user.get("role") == "admin":
            sep("── " + t("msep2").lstrip("─ "))
            btn("reg_user",   t("mu"))
            btn("list_users", t("mU"))

        sep()
        ctk.CTkButton(self.sb, text="g  " + t("ml"), anchor="w",
                      font=FONT_S, height=32, corner_radius=6,
                      fg_color="transparent", hover_color=C_SEP,
                      command=self._chg_lang).pack(fill="x", padx=8, pady=2)
        ctk.CTkButton(self.sb, text="L  " + t("mL"), anchor="w",
                      font=FONT_S, height=32, corner_radius=6,
                      fg_color="#3d1515", hover_color="#5c2020",
                      command=self._logout).pack(fill="x", padx=8, pady=(8,20))

    # ── Router ─────────────────────────────────────────────────────────────────

    TITLES = {"patients":"m1","process1":"m2","process_all":"m3","analysis":"m4",
              "labs":"m5","chat":"m7","deviations":"m8","search":"m9","stats":"m0",
              "aging":"ma","ze_hrv":"mb","protocols":"mc","wearable":"mw",
              "cdata_gui":"mgui","clusters":"mk","news":"mnews",
              "reg_user":"mu","list_users":"mU"}

    def _go(self, key):
        for k, b in self._btns.items():
            b.configure(fg_color=C_ACC if k == key else "transparent")
        for w in self.cf.winfo_children(): w.destroy()
        self.hv.set(_i18n.t(self.TITLES.get(key, key)))
        getattr(self, f"_s_{key}", lambda: None)()

    # ── Widget helpers ─────────────────────────────────────────────────────────

    def _out(self, parent=None, height=None):
        p = parent or self.cf
        w = ctk.CTkTextbox(p, font=FONT_C, fg_color="#0d1117",
                           text_color="#c9d1d9", wrap="word",
                           height=height or 400)
        w.pack(fill="both", expand=True, padx=12, pady=8)
        w.configure(state="disabled")
        return w

    def _write(self, w, text, clear=True):
        w.configure(state="normal")
        if clear: w.delete("1.0","end")
        w.insert("end", text + "\n")
        w.see("end")
        w.configure(state="disabled")

    def _bg(self, fn, out, *args):
        self._write(out, "⏳ ...")
        def _t():
            try: r = fn(*args)
            except Exception as e: r = f"✗ {e}"
            self.after(0, lambda: self._write(out, str(r)))
        threading.Thread(target=_t, daemon=True).start()

    def _patient_split(self, fn):
        """Left patient list + right output; click = run fn(patient)."""
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True)
        fr.grid_columnconfigure(1, weight=1); fr.grid_rowconfigure(0, weight=1)
        lb = ctk.CTkScrollableFrame(fr, width=220, fg_color="#13131f")
        lb.grid(row=0, column=0, sticky="nsew", padx=(12,6), pady=12)
        out = ctk.CTkTextbox(fr, font=FONT_C, fg_color="#0d1117",
                             text_color="#c9d1d9", wrap="word")
        out.grid(row=0, column=1, sticky="nsew", padx=(0,12), pady=12)
        out.configure(state="disabled")
        for p in list_patients():
            ctk.CTkButton(lb, text=p["name"], anchor="w", font=FONT_S,
                          height=30, fg_color="transparent", hover_color=C_SEP,
                          command=lambda p=p: self._bg(fn, out, p)
                          ).pack(fill="x", pady=1)

    # ── Sections ───────────────────────────────────────────────────────────────

    def _s_patients(self):
        sc = ctk.CTkScrollableFrame(self.cf, fg_color="transparent")
        sc.pack(fill="both", expand=True, padx=12, pady=12)
        ps = list_patients()
        ctk.CTkLabel(sc, text=f"Всего: {len(ps)}", font=FONT_B, anchor="w").pack(fill="x", pady=(0,8))
        for p in ps:
            row = ctk.CTkFrame(sc, height=44, corner_radius=8, fg_color="#252540")
            row.pack(fill="x", pady=3); row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=p["name"], font=FONT_B, anchor="w").grid(
                row=0, column=0, padx=14, pady=8, sticky="w")
            ctk.CTkLabel(row, text=f"р. {p.get('dob') or '?'}", font=FONT_S,
                         text_color="#8888aa").grid(row=0, column=1, padx=8, sticky="w")
            if p.get("ze_v") is not None:
                icon = {"healthy":"💚","stress":"🟡","arrhythmia":"🔴",
                        "tachyarrhythmia":"🔴","bradyarrhythmia":"🟠"}.get(p.get("ze_state",""),"⚪")
                ctk.CTkLabel(row, text=f"Ze {p['ze_v']:.3f} {icon}", font=FONT_S
                             ).grid(row=0, column=2, padx=14)

    def _s_process1(self):
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True)
        fr.grid_columnconfigure(1, weight=1); fr.grid_rowconfigure(0, weight=1)
        lb = ctk.CTkScrollableFrame(fr, width=220, fg_color="#13131f")
        lb.grid(row=0, column=0, sticky="nsew", padx=(12,6), pady=12)
        rp = ctk.CTkFrame(fr, fg_color="transparent")
        rp.grid(row=0, column=1, sticky="nsew", padx=(0,12), pady=12)
        rp.grid_rowconfigure(1, weight=1); rp.grid_columnconfigure(0, weight=1)
        ctrl = ctk.CTkFrame(rp, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0,8))
        sel_lbl = ctk.CTkLabel(ctrl, text="—", font=FONT_B)
        sel_lbl.pack(side="left", padx=8)
        fv = ctk.BooleanVar()
        ctk.CTkCheckBox(ctrl, text=_i18n.t("force_reprocess").strip().rstrip("?"),
                        variable=fv, font=FONT_S).pack(side="left", padx=10)
        run_btn = ctk.CTkButton(ctrl, text="▶ Run", state="disabled",
                                font=FONT_S, width=100)
        run_btn.pack(side="right", padx=8)
        out = ctk.CTkTextbox(rp, font=FONT_C, fg_color="#0d1117",
                             text_color="#c9d1d9", wrap="word")
        out.grid(row=1, column=0, sticky="nsew")
        out.configure(state="disabled")
        def _sel(p):
            sel_lbl.configure(text=p["name"])
            run_btn.configure(state="normal",
                              command=lambda: self._bg(
                                  lambda p=p: analyze_patient(p["folder"], force=fv.get()), out, ))
            run_btn.configure(command=lambda p=p: self._bg(
                lambda: analyze_patient(p["folder"], force=fv.get()), out))
        for p in list_patients():
            ctk.CTkButton(lb, text=p["name"], anchor="w", font=FONT_S,
                          height=30, fg_color="transparent", hover_color=C_SEP,
                          command=lambda p=p: _sel(p)).pack(fill="x", pady=1)

    def _s_process_all(self):
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        fv = ctk.BooleanVar()
        ctrl = ctk.CTkFrame(fr, fg_color="transparent")
        ctrl.pack(fill="x", pady=(0,8))
        ctk.CTkCheckBox(ctrl, text=_i18n.t("force_reprocess").strip().rstrip("?"),
                        variable=fv, font=FONT_B).pack(side="left")
        out = self._out(fr)
        def _run():
            self._write(out, "⏳ ...")
            def _t():
                try:
                    from patient_intake import process_all_patients
                    c = process_all_patients(force=fv.get())
                    self.after(0, lambda: self._write(out, f"✓ {c}"))
                except Exception as e:
                    self.after(0, lambda: self._write(out, f"✗ {e}"))
            threading.Thread(target=_t, daemon=True).start()
        ctk.CTkButton(ctrl, text="▶ " + _i18n.t("m3"), command=_run,
                      font=FONT_B).pack(side="right")

    def _s_analysis(self):
        self._patient_split(lambda p: show_patient_analysis(p["folder"]))

    def _s_labs(self):
        self._patient_split(lambda p: analyze_labs_only(p["folder"]))

    def _s_aging(self):
        self._patient_split(lambda p: show_aging_prediction(p["folder"]))

    def _s_ze_hrv(self):
        self._patient_split(lambda p: show_ze_history(p["folder"]))

    def _s_wearable(self):
        import medical_system as _ms
        self._patient_split(lambda p: _ms.start_wearable(p["folder"]))

    def _s_deviations(self):
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        out = self._out(fr)
        def _run():
            self._write(out, "⏳ ...")
            def _t():
                lines = []
                for p in list_patients():
                    r = analyze_labs_only(p["folder"])
                    if any(s in r for s in ("↓","↑","⚠")):
                        lines.append(f"\n{'─'*50}\n{p['name']}:\n{r[:600]}")
                self.after(0, lambda: self._write(out,
                    "\n".join(lines) if lines else _i18n.t("no_patients")))
            threading.Thread(target=_t, daemon=True).start()
        ctk.CTkButton(fr, text="▶ " + _i18n.t("m8"), command=_run,
                      font=FONT_B).pack(anchor="w", pady=(0,8))

    def _s_search(self):
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        ctrl = ctk.CTkFrame(fr, fg_color="transparent")
        ctrl.pack(fill="x", pady=(0,8)); ctrl.grid_columnconfigure(0, weight=1)
        e = ctk.CTkEntry(ctrl, placeholder_text=_i18n.t("search_prompt").strip(),
                         font=FONT_B, height=38)
        e.grid(row=0, column=0, sticky="ew", padx=(0,8))
        out = self._out(fr)
        def _run():
            q = e.get().strip()
            if q: self._bg(search_patients_by_symptom, out, q)
        ctk.CTkButton(ctrl, text="🔍", width=48, height=38,
                      command=_run).grid(row=0, column=1)
        e.bind("<Return>", lambda ev: _run())

    def _s_stats(self):
        out = self._out()
        self._write(out, db_stats())

    def _s_protocols(self):
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        ctrl = ctk.CTkFrame(fr, fg_color="transparent")
        ctrl.pack(fill="x", pady=(0,8)); ctrl.grid_columnconfigure(0, weight=1)
        e = ctk.CTkEntry(ctrl, placeholder_text=_i18n.t("protocol_search").strip(),
                         font=FONT_B, height=38)
        e.grid(row=0, column=0, sticky="ew", padx=(0,8))
        out = self._out(fr)
        def _run():
            q = e.get().strip()
            if q: self._bg(search_protocols, out, q)
        ctk.CTkButton(ctrl, text="🔍", width=48, height=38,
                      command=_run).grid(row=0, column=1)
        e.bind("<Return>", lambda ev: _run())

    def _s_chat(self):
        from llm import ask_llm as _ask
        from medical_system import SYSTEM_PROMPT, knowledge
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        fr.grid_rowconfigure(0, weight=1); fr.grid_columnconfigure(0, weight=1)
        hist = []
        kb = knowledge.get_context()
        sys_msg = SYSTEM_PROMPT + (f"\n\nБаза знаний: {kb}" if kb else "")
        out = ctk.CTkTextbox(fr, font=FONT_C, fg_color="#0d1117",
                             text_color="#c9d1d9", wrap="word")
        out.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0,8))
        out.configure(state="disabled")
        bot = ctk.CTkFrame(fr, fg_color="transparent")
        bot.grid(row=1, column=0, columnspan=2, sticky="ew")
        bot.grid_columnconfigure(0, weight=1)
        e = ctk.CTkEntry(bot, placeholder_text="...", font=FONT_B, height=40)
        e.grid(row=0, column=0, sticky="ew", padx=(0,8))
        def _send():
            q = e.get().strip()
            if not q: return
            e.delete(0,"end"); hist.append({"role":"user","content":q})
            self._write(out, f"\n▶ {q}", clear=False)
            def _t():
                ctx = "\n".join(f"{'Врач' if m['role']=='user' else 'AI'}: {m['content']}"
                                for m in hist[:-1])
                p = (f"История:\n{ctx}\n\n{q}" if ctx else q)
                try: r = _ask(p, system=sys_msg, max_tokens=1024, temperature=0.4)
                except Exception as ex: r = f"✗ {ex}"
                hist.append({"role":"assistant","content":r})
                self.after(0, lambda: self._write(out, f"\n◀ AI:\n{r}", clear=False))
            threading.Thread(target=_t, daemon=True).start()
        ctk.CTkButton(bot, text="➤", width=48, height=40,
                      command=_send).grid(row=0, column=1)
        e.bind("<Return>", lambda ev: _send())

    def _s_cdata_gui(self):
        out = self._out()
        gui = Path.home() / "Desktop/CDATA/target/release/cell_dt_gui"
        if gui.exists():
            subprocess.Popen([str(gui)])
            self._write(out, "✓ CDATA GUI запущен.")
        else:
            self._write(out, f"✗ Не найден:\n{gui}\n\nСобрать:\n  cd ~/Desktop/CDATA\n  cargo build --release -p cell_dt_gui")

    # ── News ───────────────────────────────────────────────────────────────────

    def _s_news(self):
        from llm import ask_llm as _ask
        t = _i18n.t

        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        fr.grid_rowconfigure(1, weight=1); fr.grid_columnconfigure(0, weight=1)

        # Topic buttons
        top = ctk.CTkScrollableFrame(fr, height=80, fg_color="transparent",
                                     orientation="horizontal")
        top.grid(row=0, column=0, sticky="ew", pady=(0,8))

        out = ctk.CTkTextbox(fr, font=FONT_C, fg_color="#0d1117",
                             text_color="#c9d1d9", wrap="word")
        out.grid(row=1, column=0, sticky="nsew")
        out.configure(state="disabled")

        def _fetch(label, query):
            self._write(out, f"⏳ {t('news_loading')} [{label}]...")
            def _t():
                prompt = (
                    f"Найди и кратко опиши 5-7 самых важных научных новостей, статей или публикаций "
                    f"по теме: {query}\n\n"
                    f"Формат каждой новости:\n"
                    f"• [Год] Заголовок — краткое описание (1-2 предложения). Источник/журнал.\n\n"
                    f"Сосредоточься на 2024-2025 году. Если нет свежих данных — возьми самые значимые последние публикации."
                )
                sys = (
                    "Ты — научный аналитик. Отвечай только фактами. "
                    "Указывай реальные журналы и авторов если знаешь. "
                    "Если не уверен — пиши 'предположительно' или 'по данным на 2024 год'."
                )
                try:
                    r = _ask(prompt, system=sys, model="deepseek-chat",
                             max_tokens=1200, temperature=0.3)
                except Exception as e:
                    r = f"✗ {e}"
                self.after(0, lambda: self._write(out, f"📰 {label}\n{'─'*50}\n{r}"))
            threading.Thread(target=_t, daemon=True).start()

        for label, query in NEWS_TOPICS:
            ctk.CTkButton(top, text=label, font=FONT_S, height=34,
                          corner_radius=20, fg_color=C_SEP, hover_color=C_ACC,
                          command=lambda l=label, q=query: _fetch(l, q)
                          ).pack(side="left", padx=4)

        # Custom query
        bot = ctk.CTkFrame(fr, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", pady=(8,0))
        bot.grid_columnconfigure(0, weight=1)
        ce = ctk.CTkEntry(bot, placeholder_text=t("search_prompt").strip(),
                          font=FONT_B, height=36)
        ce.grid(row=0, column=0, sticky="ew", padx=(0,8))
        ctk.CTkButton(bot, text="🔍", width=48, height=36,
                      command=lambda: _fetch(ce.get().strip(), ce.get().strip())
                      ).grid(row=0, column=1)
        ce.bind("<Return>", lambda ev: _fetch(ce.get().strip(), ce.get().strip()))

        # Auto-load first topic
        self.after(200, lambda: _fetch(*NEWS_TOPICS[0]))

    # ── Clusters ───────────────────────────────────────────────────────────────

    def _s_clusters(self):
        import patient_network as _pnet
        t = _i18n.t
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(fill="both", expand=True, padx=12, pady=8)
        fr.grid_rowconfigure(1, weight=1); fr.grid_columnconfigure(0, weight=1)

        ctrl = ctk.CTkFrame(fr, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0,6))
        tip = ctk.CTkLabel(ctrl, text=t("mk_tip"), font=FONT_S, text_color="#8888aa")
        tip.pack(side="left", padx=4)
        out = ctk.CTkTextbox(fr, font=FONT_C, fg_color="#0d1117",
                             text_color="#c9d1d9", wrap="none")
        out.grid(row=1, column=0, sticky="nsew")
        out.configure(state="disabled")

        def _refresh():
            try:
                text = _pnet.show_patient_map()
            except Exception as e:
                text = f"✗ {e}"
            self._write(out, text)

        ctk.CTkButton(ctrl, text=t("mk_refresh"), font=FONT_S,
                      width=90, height=28, command=_refresh).pack(side="right", padx=4)
        _refresh()

    # ── Admin sections ─────────────────────────────────────────────────────────

    def _s_reg_user(self):
        t = _i18n.t
        if self.user.get("role") != "admin":
            self._write(self._out(), t("admin_only")); return
        fr = ctk.CTkFrame(self.cf, fg_color="transparent")
        fr.pack(expand=True, padx=80, pady=30)
        ctk.CTkLabel(fr, text=t("reg_header"), font=FONT_T).pack(pady=(0,16))
        flds = {}
        for k, ph, pw in [("email",t("email_prompt").strip(),False),
                           ("pw",t("password_prompt").strip(),True),
                           ("pw2",t("pw_confirm").strip(),True),
                           ("name",t("name_prompt").strip(),False)]:
            ctk.CTkLabel(fr, text=ph, font=FONT_B, anchor="w").pack(fill="x")
            e = ctk.CTkEntry(fr, font=FONT_B, height=34, show="●" if pw else "")
            e.pack(fill="x", pady=(2,8)); flds[k] = e
        rv = ctk.StringVar(value="doctor")
        ctk.CTkLabel(fr, text=t("role_prompt").strip(), font=FONT_B, anchor="w").pack(fill="x")
        ctk.CTkSegmentedButton(fr, values=["doctor","admin","readonly"],
                               variable=rv, font=FONT_B).pack(fill="x", pady=(2,8))
        mv = ctk.StringVar()
        ctk.CTkLabel(fr, textvariable=mv, text_color=C_ERR, font=FONT_S).pack()
        def _sub():
            if flds["pw"].get() != flds["pw2"].get():
                mv.set(t("pw_mismatch")); return
            try:
                uid = _auth.create_user(flds["email"].get().strip(), flds["pw"].get(),
                                        role=rv.get(), display_name=flds["name"].get().strip(),
                                        created_by=self.user["id"])
                mv.set(f"✓ {t('user_created',email=flds['email'].get(),role=rv.get(),uid=uid)}")
                for e in flds.values(): e.delete(0,"end")
            except ValueError as e: mv.set(f"✗ {e}")
        ctk.CTkButton(fr, text="✓ " + t("mu"), command=_sub,
                      font=FONT_B, height=38).pack(fill="x", pady=(10,0))

    def _s_list_users(self):
        t = _i18n.t
        if self.user.get("role") != "admin":
            self._write(self._out(), t("admin_only")); return
        users = _auth.list_users()
        sc = ctk.CTkScrollableFrame(self.cf, fg_color="transparent")
        sc.pack(fill="both", expand=True, padx=12, pady=12)
        hdr = ctk.CTkFrame(sc, fg_color="#252540", corner_radius=6)
        hdr.pack(fill="x", pady=(0,4))
        for col, w in [(t("col_id"),80),(t("col_email"),240),(t("col_role"),100),
                       (t("col_name"),180),(t("col_created"),100)]:
            ctk.CTkLabel(hdr, text=col, font=("Helvetica",11,"bold"),
                         width=w, anchor="w").pack(side="left", padx=8, pady=6)
        for u in users:
            row = ctk.CTkFrame(sc, fg_color="#1a1a2e", corner_radius=4)
            row.pack(fill="x", pady=2)
            for val, w in [(u["id"][:8],80),(u["email"],240),(u["role"],100),
                           (u.get("display_name") or "",180),(u["created_at"][:10],100)]:
                ctk.CTkLabel(row, text=str(val), font=FONT_S,
                             width=w, anchor="w").pack(side="left", padx=8, pady=6)

    # ── Language / Logout ──────────────────────────────────────────────────────

    def _chg_lang(self):
        d = ctk.CTkToplevel(self); d.title(_i18n.t("ml"))
        d.geometry("260x310"); d.grab_set()
        for code, name in _i18n.LANG_NAMES.items():
            ctk.CTkButton(d, text=name, font=FONT_M,
                          command=lambda c=code: (_i18n.set_lang(c), d.destroy(),
                                                  self._rebuild())
                          ).pack(fill="x", padx=20, pady=3)

    def _rebuild(self):
        for w in self.sb.winfo_children(): w.destroy()
        self._build_sb()
        self._go("patients")

    def _logout(self):
        _auth.logout(); self.destroy()


# ── Entry ──────────────────────────────────────────────────────────────────────

def main():
    _db.init_db()
    login = LoginWindow(); login.mainloop()
    user = login.get_user()
    if not user: return
    AimGUI(user).mainloop()

if __name__ == "__main__":
    main()
