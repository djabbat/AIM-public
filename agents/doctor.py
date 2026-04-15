"""
AIM v7.0 — DoctorAgent
Дифференциальная диагностика, протоколы лечения, клинические рекомендации.
"""

import logging
from typing import Optional

from llm import ask, ask_deep
from db import save_message, get_history, cache_get, cache_set
from i18n import t

log = logging.getLogger("aim.doctor")

# ── Системные промпты по ролям ────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "diagnosis": {
        "ru": (
            "Ты — опытный врач интегративной медицины. "
            "Проводи дифференциальную диагностику строго по симптомам. "
            "Структурируй ответ: 1) Наиболее вероятный диагноз, "
            "2) Дифференциальный ряд (3–5 вариантов), "
            "3) Необходимые обследования. "
            "НИКОГДА не ставь окончательный диагноз без обследований. "
            "В конце: disclaimer — 'Это информационная поддержка, не медицинский совет.'"
        ),
        "en": (
            "You are an experienced integrative medicine physician. "
            "Perform differential diagnosis strictly based on symptoms. "
            "Structure your answer: 1) Most likely diagnosis, "
            "2) Differential list (3–5 options), "
            "3) Required workup. "
            "NEVER make a final diagnosis without investigations. "
            "End with: disclaimer — 'This is informational support, not medical advice.'"
        ),
    },
    "treatment": {
        "ru": (
            "Ты — врач интегративной медицины. "
            "Составляй протоколы лечения с доказательной базой. "
            "Структура: 1) Конвенциональная терапия (первая линия), "
            "2) Интегративные подходы (нутрицевтики, фитотерапия, физиотерапия), "
            "3) Образ жизни и профилактика. "
            "Указывай уровень доказательности (A/B/C). "
            "Disclaimer в конце обязателен."
        ),
        "en": (
            "You are an integrative medicine physician. "
            "Create evidence-based treatment protocols. "
            "Structure: 1) Conventional therapy (first line), "
            "2) Integrative approaches (nutraceuticals, phytotherapy, physiotherapy), "
            "3) Lifestyle and prevention. "
            "Indicate evidence level (A/B/C). "
            "Disclaimer at the end is mandatory."
        ),
    },
    "labs": {
        "ru": (
            "Ты — клинический лаборант и врач-интерпретатор. "
            "Анализируй лабораторные данные. "
            "Структура: 1) Отклонения от нормы (выделить критические), "
            "2) Клиническое значение, "
            "3) Рекомендации по дообследованию. "
            "Disclaimer обязателен."
        ),
        "en": (
            "You are a clinical laboratory specialist and interpreting physician. "
            "Analyze laboratory data. "
            "Structure: 1) Deviations from normal (highlight critical), "
            "2) Clinical significance, "
            "3) Recommendations for further workup. "
            "Disclaimer is mandatory."
        ),
    },
}

DISCLAIMER = {
    "ru": "\n\n⚠️ Информационная поддержка. Не является медицинским советом. Проконсультируйтесь с лечащим врачом.",
    "en": "\n\n⚠️ Informational support only. Not medical advice. Consult your physician.",
    "fr": "\n\n⚠️ Soutien informationnel uniquement. Pas un avis médical. Consultez votre médecin.",
    "es": "\n\n⚠️ Solo información. No es consejo médico. Consulte a su médico.",
    "ar": "\n\n⚠️ دعم معلوماتي فقط. ليس نصيحة طبية. استشر طبيبك.",
    "zh": "\n\n⚠️ 仅供参考，不构成医疗建议。请咨询您的医生。",
    "ka": "\n\n⚠️ მხოლოდ საინფორმაციო მხარდაჭერა. არ არის სამედიცინო რჩევა. გაიარეთ კონსულტაცია ექიმთან.",
    "kz": "\n\n⚠️ Тек ақпараттық қолдау. Медициналық кеңес емес. Дәрігерге хабарласыңыз.",
    "da": "\n\n⚠️ Kun informationsstøtte. Ikke medicinsk rådgivning. Konsulter din læge.",
}


def _get_system(role: str, lang: str) -> str:
    prompts = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["diagnosis"])
    return prompts.get(lang) or prompts.get("en", "")


def _ensure_disclaimer(text: str, lang: str) -> str:
    """Добавить disclaimer если модель его пропустила."""
    disc = DISCLAIMER.get(lang, DISCLAIMER["en"])
    # Проверяем наличие любого disclaimer в тексте
    markers = ["⚠️", "disclaimer", "Disclaimer", "не является медицинским", "not medical advice"]
    if not any(m in text for m in markers):
        return text + disc
    return text


class DoctorAgent:
    """
    Агент диагностики и лечения.

    Методы:
        diagnose(symptoms, patient_context, lang, session_id) → str
        treatment_plan(diagnosis, lang, session_id) → str
        interpret_labs(lab_text, lang, session_id) → str
        chat(message, history, lang, session_id) → str
    """

    def __init__(self):
        self.name = "DoctorAgent"

    def diagnose(
        self,
        symptoms: str,
        patient_context: str = "",
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Дифференциальная диагностика по симптомам."""
        if not symptoms.strip():
            return t("error", lang)

        system = _get_system("diagnosis", lang)
        prompt_parts = []
        if patient_context:
            prompt_parts.append(f"Контекст пациента:\n{patient_context}\n")
        prompt_parts.append(f"Жалобы и симптомы:\n{symptoms}")
        prompt = "\n".join(prompt_parts)

        # Кэш — диагностика детерминирована при одинаковом вводе
        cache_key = f"dx:{lang}:{hash(prompt)}"
        cached = cache_get(cache_key)
        if cached:
            log.info("DoctorAgent.diagnose: cache hit")
            return cached

        log.info(f"DoctorAgent.diagnose: lang={lang}, ~{len(symptoms)} chars")
        result = ask_deep(prompt, system=system, lang=lang)
        result = _ensure_disclaimer(result, lang)

        cache_set(cache_key, result)

        if session_id:
            save_message(session_id, "user", f"[Диагностика] {symptoms}", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def treatment_plan(
        self,
        diagnosis: str,
        patient_context: str = "",
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Протокол интегративного лечения."""
        if not diagnosis.strip():
            return t("error", lang)

        system = _get_system("treatment", lang)
        prompt_parts = []
        if patient_context:
            prompt_parts.append(f"Контекст пациента:\n{patient_context}\n")
        prompt_parts.append(f"Диагноз:\n{diagnosis}")
        prompt = "\n".join(prompt_parts)

        log.info(f"DoctorAgent.treatment_plan: lang={lang}")
        result = ask_deep(prompt, system=system, lang=lang)
        result = _ensure_disclaimer(result, lang)

        if session_id:
            save_message(session_id, "user", f"[Протокол] {diagnosis}", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def interpret_labs(
        self,
        lab_text: str,
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Интерпретация лабораторных данных."""
        if not lab_text.strip():
            return t("error", lang)

        system = _get_system("labs", lang)
        prompt = f"Лабораторные данные для интерпретации:\n\n{lab_text}"

        log.info(f"DoctorAgent.interpret_labs: lang={lang}, ~{len(lab_text)} chars")
        result = ask(prompt, system=system, lang=lang)
        result = _ensure_disclaimer(result, lang)

        if session_id:
            save_message(session_id, "user", "[Анализы]", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def chat(
        self,
        message: str,
        history: list[dict] = None,
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Свободный диалог с контекстом истории."""
        system = _get_system("diagnosis", lang)

        # Сборка контекста из истории
        hist_text = ""
        if history:
            hist_text = "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in history[-6:]
            )

        prompt = f"{hist_text}\nUSER: {message}" if hist_text else message

        result = ask(prompt, system=system, lang=lang)
        result = _ensure_disclaimer(result, lang)

        if session_id:
            save_message(session_id, "user", message, provider="user")
            save_message(session_id, "assistant", result)

        return result
