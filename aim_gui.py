#!/usr/bin/env python3
"""
AIM v6.0 — aim_gui.py
Streamlit GUI — зеркало CLI-меню medical_system.py
Запуск: streamlit run aim_gui.py
"""

import os
import sqlite3
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import date, datetime
from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────────────────────
load_dotenv(Path.home() / ".aim_env")
DB_PATH = Path.home() / "Desktop/AIM/aim.db"
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
TENANT_ID = 1
VERSION = "6.0"

st.set_page_config(
    page_title="AIM v6.0",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── i18n (standalone, no i18n.py import) ─────────────────────────────────────
LABELS = {
    "ru": {
        "nav": ["Список пациентов","Новый пациент","Поиск пациента",
                "AI-консультация","Анализ лабораторных данных",
                "Байесовская диагностика","Протоколы лечения",
                "Ze-статус / HRV","Отчёты"],
        "search_ph": "Введите фамилию или имя...",
        "submit": "Сохранить",
        "send": "Отправить",
        "analyze": "Анализировать",
        "calc_ze": "Рассчитать Ze",
        "surname": "Фамилия",
        "first_name": "Имя",
        "birth_date": "Дата рождения",
        "sex": "Пол",
        "phone": "Телефон",
        "ze_high": "Высокий — отличный биологический резерв",
        "ze_medium": "Средний — умеренный резерв, профилактика",
        "ze_low": "Низкий — сниженный резерв, активное лечение",
        "ze_critical": "Критический — минимальный резерв",
        "diag_ph": "Введите симптомы через запятую...",
        "treat_diag_ph": "Диагноз или состояние...",
        "treat_ctx_ph": "Ze-статус, возраст, сопутствующие болезни...",
        "lab_ph": "Вставьте текст с лабораторными данными...",
        "consult_ph": "Введите вопрос или описание клинической ситуации...",
        "no_patients": "Пациентов не найдено",
        "saved": "Пациент сохранён",
        "not_found": "Не найдено",
        "no_api": "⚠️ DeepSeek API ключ не найден. Проверьте ~/.aim_env",
    },
    "ka": {
        "nav": ["პაციენტების სია","ახალი პაციენტი","პაციენტის ძიება",
                "AI-კონსულტაცია","ლაბ. მონაცემების ანალიზი",
                "ბაიესური დიაგნოსტიკა","მკურნალობის პროტოკოლები",
                "Ze-სტატუსი / HRV","ანგარიშები"],
        "search_ph": "შეიყვანეთ გვარი ან სახელი...",
        "submit": "შენახვა", "send": "გაგზავნა", "analyze": "ანალიზი",
        "calc_ze": "Ze-ის გამოთვლა",
        "surname": "გვარი", "first_name": "სახელი",
        "birth_date": "დაბადების თარიღი", "sex": "სქესი", "phone": "ტელეფონი",
        "ze_high": "მაღალი — შესანიშნავი ბიოლოგიური რეზერვი",
        "ze_medium": "საშუალო — ზომიერი რეზერვი, პრევენცია",
        "ze_low": "დაბალი — შემცირებული რეზერვი, მკურნალობა",
        "ze_critical": "კრიტიკული — მინიმალური რეზერვი",
        "diag_ph": "სიმპტომები მძიმით...", "treat_diag_ph": "დიაგნოზი...",
        "treat_ctx_ph": "Ze-სტატუსი, ასაკი, თანმხლები დაავადებები...",
        "lab_ph": "ლაბ. მონაცემები...", "consult_ph": "კითხვა...",
        "no_patients": "პაციენტები ვერ მოიძებნა",
        "saved": "პაციენტი შენახულია", "not_found": "ვერ მოიძებნა",
        "no_api": "⚠️ DeepSeek API გასაღები არ არის. შეამოწმეთ ~/.aim_env",
    },
    "en": {
        "nav": ["Patient List","New Patient","Search Patient",
                "AI Consultation","Lab Analysis",
                "Bayesian Diagnosis","Treatment Protocols",
                "Ze-Status / HRV","Reports"],
        "search_ph": "Enter surname or name...",
        "submit": "Save", "send": "Send", "analyze": "Analyze",
        "calc_ze": "Calculate Ze",
        "surname": "Surname", "first_name": "First name",
        "birth_date": "Date of birth", "sex": "Sex", "phone": "Phone",
        "ze_high": "High — excellent biological reserve",
        "ze_medium": "Medium — moderate reserve, prevention",
        "ze_low": "Low — reduced reserve, active treatment",
        "ze_critical": "Critical — minimal reserve",
        "diag_ph": "Enter symptoms separated by commas...",
        "treat_diag_ph": "Diagnosis or condition...",
        "treat_ctx_ph": "Ze-status, age, comorbidities...",
        "lab_ph": "Paste lab data text...",
        "consult_ph": "Enter your question or clinical situation...",
        "no_patients": "No patients found",
        "saved": "Patient saved", "not_found": "Not found",
        "no_api": "⚠️ DeepSeek API key not found. Check ~/.aim_env",
    },
}

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚕️ AIM v6.0")
    st.caption("drjaba.com")
    lang = st.selectbox("🌐 Язык / Language", ["ru", "ka", "en"], index=0)
    L = LABELS[lang]
    page = st.radio("", L["nav"], index=0)

# ─── DB helpers ───────────────────────────────────────────────────────────────
def get_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def calc_age(birth_str: str | None) -> int | None:
    if not birth_str:
        return None
    try:
        bd = datetime.strptime(birth_str[:10], "%Y-%m-%d").date()
        today = date.today()
        return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    except Exception:
        return None


# ─── DeepSeek helper ──────────────────────────────────────────────────────────
def ask_deepseek(prompt: str, system: str = "") -> str:
    if not DEEPSEEK_KEY:
        return L["no_api"]
    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model="deepseek-chat", messages=messages, max_tokens=2000
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"Ошибка API: {e}"


SYS_MEDICAL = {
    "ru": "Ты — AIM, ИИ-ассистент интегративной медицины доктора Ткемаладзе. Отвечай структурированно, учитывай Ze-теорию.",
    "ka": "შენ ხარ AIM — დოქტორ თქემალაძის ინტეგრაციული მედიცინის ასისტენტი. Ze-თეორია გაითვალისწინე.",
    "en": "You are AIM, Dr. Tkemaladze's integrative medicine AI. Answer structured, consider Ze-theory.",
}

# ─── Pages ────────────────────────────────────────────────────────────────────

nav = L["nav"]

# 1. Список пациентов ──────────────────────────────────────────────────────────
if page == nav[0]:
    st.header(nav[0])
    conn = get_conn()
    if conn is None:
        st.warning("База данных не найдена. Запустите medical_system.py хотя бы раз для инициализации.")
    else:
        rows = conn.execute(
            "SELECT id, surname, first_name, birth_date, sex, ze_status, biological_age "
            "FROM patients WHERE tenant_id=? ORDER BY surname, first_name",
            (TENANT_ID,)
        ).fetchall()
        conn.close()
        if not rows:
            st.info(L["no_patients"])
        else:
            data = []
            for r in rows:
                data.append({
                    "ID": r["id"],
                    L["surname"]: r["surname"],
                    L["first_name"]: r["first_name"],
                    "Age": calc_age(r["birth_date"]),
                    L["sex"]: r["sex"] or "—",
                    "Ze": f"{r['ze_status']:.0f}" if r["ze_status"] else "—",
                    "BioAge": f"{r['biological_age']:.0f}" if r["biological_age"] else "—",
                })
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"Всего пациентов: {len(data)}")

# 2. Новый пациент ─────────────────────────────────────────────────────────────
elif page == nav[1]:
    st.header(nav[1])
    conn = get_conn()
    if conn is None:
        st.warning("База данных не найдена.")
    else:
        with st.form("new_patient_form"):
            col1, col2 = st.columns(2)
            with col1:
                surname = st.text_input(L["surname"])
                birth_date = st.date_input(L["birth_date"], value=None, min_value=date(1900,1,1))
                phone = st.text_input(L["phone"])
            with col2:
                first_name = st.text_input(L["first_name"])
                sex = st.selectbox(L["sex"], ["", "M", "F"])
            submitted = st.form_submit_button(L["submit"])

        if submitted:
            if not surname or not first_name:
                st.error("Фамилия и имя обязательны.")
            else:
                bd_str = birth_date.strftime("%Y-%m-%d") if birth_date else None
                conn.execute(
                    "INSERT INTO patients (tenant_id, surname, first_name, birth_date, sex, phone) "
                    "VALUES (?,?,?,?,?,?)",
                    (TENANT_ID, surname, first_name, bd_str, sex or None, phone or None)
                )
                conn.commit()
                conn.close()
                st.success(f"{L['saved']}: {surname} {first_name}")

# 3. Поиск пациента ────────────────────────────────────────────────────────────
elif page == nav[2]:
    st.header(nav[2])
    conn = get_conn()
    if conn is None:
        st.warning("База данных не найдена.")
    else:
        query = st.text_input("🔍", placeholder=L["search_ph"])
        if query:
            rows = conn.execute(
                "SELECT id, surname, first_name, birth_date, sex, ze_status "
                "FROM patients WHERE tenant_id=? AND "
                "(surname LIKE ? OR first_name LIKE ? OR phone LIKE ?) "
                "ORDER BY surname",
                (TENANT_ID, f"%{query}%", f"%{query}%", f"%{query}%")
            ).fetchall()
            if not rows:
                st.info(L["not_found"])
            else:
                for r in rows:
                    ze = f" | Ze={r['ze_status']:.0f}" if r["ze_status"] else ""
                    age = calc_age(r["birth_date"])
                    age_str = f", {age} лет" if age else ""
                    st.write(f"**[{r['id']}]** {r['surname']} {r['first_name']}{age_str}{ze}")
        conn.close()

# 4. AI-консультация ───────────────────────────────────────────────────────────
elif page == nav[3]:
    st.header(nav[3])
    question = st.text_area("💬", placeholder=L["consult_ph"], height=120)
    if st.button(L["send"], type="primary") and question.strip():
        with st.spinner("AI анализирует..."):
            answer = ask_deepseek(question, SYS_MEDICAL.get(lang, SYS_MEDICAL["en"]))
        st.markdown("---")
        st.markdown(answer)

# 5. Анализ лаб. данных ────────────────────────────────────────────────────────
elif page == nav[4]:
    st.header(nav[4])
    lab_text = st.text_area("📋", placeholder=L["lab_ph"], height=200)
    if st.button(L["analyze"], type="primary") and lab_text.strip():
        prompt = (
            f"Проанализируй лабораторные данные пациента. "
            f"Укажи отклонения от нормы, клиническое значение, "
            f"рекомендации по дообследованию и коррекции.\n\nДанные:\n{lab_text}"
        )
        with st.spinner("Анализируем..."):
            result = ask_deepseek(prompt, SYS_MEDICAL.get(lang, SYS_MEDICAL["en"]))
        st.markdown("---")
        st.markdown(result)

# 6. Байесовская диагностика ───────────────────────────────────────────────────
elif page == nav[5]:
    st.header(nav[5])
    symptoms = st.text_area("🩺", placeholder=L["diag_ph"], height=100)
    if st.button(L["analyze"], type="primary") and symptoms.strip():
        prompt = (
            f"Проведи дифференциальную диагностику (байесовский подход) "
            f"для симптомов: {symptoms}.\n"
            f"Перечисли диагнозы с вероятностью (%), ключевыми признаками и необходимыми тестами."
        )
        with st.spinner("Байесовский анализ..."):
            result = ask_deepseek(prompt, SYS_MEDICAL.get(lang, SYS_MEDICAL["en"]))
        st.markdown("---")
        st.markdown(result)

# 7. Протоколы лечения ─────────────────────────────────────────────────────────
elif page == nav[6]:
    st.header(nav[6])
    diagnosis = st.text_input("📌 " + L["treat_diag_ph"])
    context = st.text_area("📝 " + L["treat_ctx_ph"], height=80)
    if st.button(L["analyze"], type="primary") and diagnosis.strip():
        prompt = (
            f"Составь протокол интегративного лечения для: {diagnosis}.\n"
            f"Включи: основное лечение, нутрициологическую поддержку, "
            f"Ze-коррекционный компонент, мониторинг."
        )
        if context.strip():
            prompt += f"\n\nКонтекст пациента: {context}"
        with st.spinner("Составляем протокол..."):
            result = ask_deepseek(prompt, SYS_MEDICAL.get(lang, SYS_MEDICAL["en"]))
        st.markdown("---")
        st.markdown(result)

# 8. Ze-статус / HRV ───────────────────────────────────────────────────────────
elif page == nav[7]:
    st.header(nav[7])
    col1, col2, col3 = st.columns(3)
    with col1:
        sdnn = st.number_input("SDNN (мс)", min_value=0.0, max_value=300.0, value=50.0, step=1.0)
    with col2:
        rmssd = st.number_input("RMSSD (мс)", min_value=0.0, max_value=300.0, value=30.0, step=1.0)
    with col3:
        lf_hf = st.number_input("LF/HF ratio", min_value=0.0, max_value=20.0, value=1.5, step=0.1)

    if st.button(L["calc_ze"], type="primary"):
        ze = (
            0.4 * min(sdnn / 100.0, 1.0) * 100
            + 0.4 * min(rmssd / 50.0, 1.0) * 100
            + 0.2 * max(0.0, (3.0 - lf_hf) / 3.0) * 100
        )
        ze = round(ze, 1)

        st.metric("Ze-статус", f"{ze}/100")
        st.progress(ze / 100.0)

        if ze >= 80:
            st.success(f"🟢 {L['ze_high']}")
        elif ze >= 50:
            st.warning(f"🟡 {L['ze_medium']}")
        elif ze >= 20:
            st.error(f"🔴 {L['ze_low']}")
        else:
            st.error(f"⚫ {L['ze_critical']}")

        if DEEPSEEK_KEY:
            prompt = (
                f"Проинтерпретируй данные HRV в контексте Ze-теории:\n"
                f"SDNN={sdnn} мс, RMSSD={rmssd} мс, LF/HF={lf_hf}.\n"
                f"Ze-статус (расчётный): {ze}/100.\n"
                f"Клиническая интерпретация и рекомендации."
            )
            with st.spinner("AI интерпретирует..."):
                interp = ask_deepseek(prompt, SYS_MEDICAL.get(lang, SYS_MEDICAL["en"]))
            st.markdown("---")
            st.markdown(interp)

# 9. Отчёты ────────────────────────────────────────────────────────────────────
elif page == nav[8]:
    st.header(nav[8])
    conn = get_conn()
    if conn is None:
        st.warning("База данных не найдена.")
    else:
        total = conn.execute(
            "SELECT COUNT(*) FROM patients WHERE tenant_id=?", (TENANT_ID,)
        ).fetchone()[0]

        ze_rows = conn.execute(
            "SELECT ze_status FROM patients WHERE tenant_id=? AND ze_status IS NOT NULL",
            (TENANT_ID,)
        ).fetchall()
        conn.close()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Всего пациентов", total)

        if ze_rows:
            ze_vals = [r[0] for r in ze_rows]
            avg_ze = sum(ze_vals) / len(ze_vals)
            high = sum(1 for z in ze_vals if z >= 80)
            med = sum(1 for z in ze_vals if 50 <= z < 80)
            low = sum(1 for z in ze_vals if z < 50)
            col2.metric("Средний Ze", f"{avg_ze:.1f}")
            col3.metric("🟢 Высокий Ze", high)
            col4.metric("🔴 Низкий Ze", low)

            st.subheader("Распределение Ze-статуса")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(6, 3))
            fig.patch.set_facecolor('#0e1117')
            ax.set_facecolor('#1a1a2e')
            ax.bar(["Высокий\n(≥80)", "Средний\n(50-79)", "Низкий\n(<50)"],
                   [high, med, low],
                   color=["#2ecc71", "#f39c12", "#e74c3c"])
            ax.set_ylabel("Пациентов", color='white')
            ax.tick_params(colors='white')
            for sp in ax.spines.values():
                sp.set_edgecolor('#333')
            st.pyplot(fig)
            plt.close(fig)
        else:
            col2.metric("Ze данных", "нет")

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("AIM v6.0 · Tkemaladze J. (2023) PMID 36583780 · drjaba.com")
