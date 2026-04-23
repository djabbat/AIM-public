"""
AIM v7.0 — DoctorAgent
Дифференциальная диагностика, протоколы лечения, клинические рекомендации.
"""

import logging
from typing import Optional

from llm import ask, ask_deep
from db import save_message, get_history, cache_get, cache_set
from i18n import t
from agents.interactions import (
    check_regimen,
    format_regimen_report,
    Interaction,
)

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

    def triage(
        self,
        symptoms: str,
        patient: dict,
        lang: str = "ru",
        session_id: Optional[int] = None,
        verbose: bool = False,
        override=None,
    ) -> dict:
        """Kernel-powered diagnostic triage (Phase 1 per Q7=A, Q13=E).

        Отличается от diagnose():
        - Использует decision kernel (agents/kernel.py): L0-L3 filter + utility ranking
        - Возвращает structured dict: {recommendation, scoring, laws, alternatives, clarify}
        - Если impedance > 0.7 — возвращает clarifying questions вместо decision
        - Логирует в SQLite ai_events + Patients/<id>/AI_LOG.md

        Args:
            symptoms: свободный текст симптомов от пациента
            patient: dict с {id, age, sex, allergies, medications, red_flags, ...}
            lang: язык output
            session_id: для chat history
            verbose: full reasoning breakdown (per Q12, tiered output)
            override: OverrideContext для soft/hard override (per Q5)

        Returns:
            dict:
              status: "clarify" | "decided" | "blocked"
              output: str — formatted для показа user (compact или verbose)
              clarify_questions: list[str] — только если status="clarify"
              scored: Scored — kernel result (только если status="decided")
              error: str — только если status="blocked"
        """
        from agents import kernel

        if not symptoms.strip():
            return {"status": "blocked", "output": t("error", lang),
                    "error": "empty symptoms"}

        # 1. Генерируем alternatives через LLM (raw differential)
        system = _get_system("diagnosis", lang)
        patient_ctx = self._format_patient(patient)
        prompt = (
            f"Пациент:\n{patient_ctx}\n\n"
            f"Жалобы: {symptoms}\n\n"
            "Предложи 3-5 вариантов следующего шага (каждый как отдельный вариант): "
            "тесты/анализы, imaging, дифф. диагноз, направление к специалисту, "
            "эмпирическое лечение (если оправдано), или наблюдение. "
            "Формат: JSON array с полями {id, action_type, description, payload}. "
            "action_type ∈ {test, imaging, dx, referral, treatment, wait, clarify}. "
            "Только JSON, без текста вокруг."
        )

        # Оценка impedance до решения
        impedance_before = kernel.impedance(patient, {})
        if kernel.needs_clarification(patient, {}):
            # Clarifying-first branch per Q12
            clarify_prompt = (
                f"Пациент: {patient_ctx}\nЖалобы: {symptoms}\n\n"
                "Impedance (неопределённость модели) > 0.7. "
                "Задай 2-3 уточняющих вопроса для reducing uncertainty. "
                "Короткие, конкретные. Формат: пронумерованный список."
            )
            questions_raw = ask_deep(clarify_prompt, system=system, lang=lang)
            return {
                "status": "clarify",
                "output": questions_raw,
                "clarify_questions": self._parse_questions(questions_raw),
                "impedance": impedance_before,
            }

        # 2. LLM генерит JSON alternatives
        raw_alts = ask_deep(prompt, system=system, lang=lang)
        try:
            alternatives = self._parse_alternatives(raw_alts)
        except Exception as e:
            log.warning(f"triage: failed to parse alternatives: {e}. Raw: {raw_alts[:200]}")
            return {"status": "blocked", "output": raw_alts,
                    "error": f"parse_failed: {e}"}

        # 3. Пропускаем через kernel
        try:
            scored = kernel.decide(
                alternatives,
                patient,
                context={"symptoms": symptoms, "impedance_before": impedance_before},
                override=override or kernel.OverrideContext(),
                agent="doctor.triage",
                patient_id=patient.get("id", ""),
                session_id=str(session_id) if session_id else None,
                decision_type="triage",
            )
        except kernel.KernelViolation as e:
            log.warning(f"triage: all alternatives blocked: {e}")
            return {"status": "blocked", "output": str(e), "error": "all_blocked"}

        # 4. Формат output per tier
        output = (kernel.format_verbose(scored, lang) if verbose
                  else kernel.format_compact(scored, lang))
        output = _ensure_disclaimer(output, lang)

        if session_id:
            save_message(session_id, "user", f"[Triage] {symptoms}", provider="user")
            save_message(session_id, "assistant", output)

        return {
            "status": "decided",
            "output": output,
            "scored": scored,
            "impedance": impedance_before,
        }

    @staticmethod
    def _format_patient(patient: dict) -> str:
        parts = []
        if patient.get("age"):
            parts.append(f"возраст {patient['age']}")
        if patient.get("sex"):
            parts.append(f"пол {patient['sex']}")
        if patient.get("allergies"):
            parts.append(f"аллергии: {', '.join(patient['allergies'])}")
        if patient.get("medications"):
            meds = ", ".join(m.get("name", "") for m in patient["medications"])
            parts.append(f"принимает: {meds}")
        if patient.get("red_flags"):
            parts.append(f"red flags: {'; '.join(patient['red_flags'])}")
        return " · ".join(parts) or "нет данных"

    @staticmethod
    def _parse_alternatives(raw: str) -> list:
        """Parse JSON array of alternatives из LLM output в list[Decision]."""
        from agents.kernel import Decision
        import json as _json
        # Найти JSON array
        s = raw.strip()
        if "```" in s:
            # Strip code fence
            s = s.split("```")[1]
            if s.startswith("json"):
                s = s[4:]
        start = s.find("[")
        end = s.rfind("]")
        if start < 0 or end < 0:
            raise ValueError(f"No JSON array в response")
        data = _json.loads(s[start:end+1])
        result = []
        for item in data:
            result.append(Decision(
                id=str(item.get("id", f"opt_{len(result)}")),
                description=item.get("description", ""),
                action_type=item.get("action_type", "dx"),
                payload=item.get("payload", {}),
            ))
        return result

    @staticmethod
    def _parse_questions(raw: str) -> list[str]:
        """Парсим пронумерованный список из LLM."""
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        questions = []
        for line in lines:
            # Skip non-question lines
            if any(line.startswith(p) for p in ("1.", "2.", "3.", "4.", "5.", "- ", "* ")):
                q = line.lstrip("0123456789.-* ").strip()
                if q:
                    questions.append(q)
        return questions

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

    def check_patient_regimen(
        self,
        patient_meds: list[str],
        lang: str = "ru",
        session_id: Optional[int] = None,
        include_no_known: bool = False,
    ) -> str:
        """
        Проверка лекарственного режима пациента на взаимодействия.

        Использует локальную статическую таблицу AIM (stub, ~30 пар).
        Возвращает отформатированный отчёт c дисклеймером.
        """
        if not patient_meds:
            return t("error", lang)

        log.info(
            f"DoctorAgent.check_patient_regimen: lang={lang}, "
            f"n_drugs={len(patient_meds)}"
        )

        results: list[Interaction] = check_regimen(patient_meds)
        report = format_regimen_report(
            results, lang=lang, include_no_known=include_no_known
        )
        report = _ensure_disclaimer(report, lang)

        if session_id:
            save_message(
                session_id, "user",
                f"[Regimen check] {', '.join(patient_meds)}",
                provider="user",
            )
            save_message(session_id, "assistant", report)

        return report

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
