"""
AIM v7.0 — LangAgent
Перевод, автодетект языка, научный/медицинский/художественный перевод.
"""

import re
import logging
from typing import Optional

from llm import ask, ask_multilang, _detect_lang
from db import save_message
from i18n import t
from config import SUPPORTED_LANGS, QWEN_LANGS

log = logging.getLogger("aim.lang")

# ── Названия языков ───────────────────────────────────────────────────────────

LANG_NAMES = {
    "ru": "Русский",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "ar": "العربية",
    "zh": "中文",
    "ka": "ქართული",
    "kz": "Қазақша",
    "da": "Dansk",
}

# ── Системные промпты для типов перевода ──────────────────────────────────────

TRANSLATION_SYSTEMS = {
    "medical": {
        "ru": (
            "Ты — медицинский переводчик с 20-летним опытом. "
            "Переводи точно, сохраняя медицинскую терминологию. "
            "Не добавляй комментарии и пояснения, только перевод."
        ),
        "en": (
            "You are a medical translator with 20 years of experience. "
            "Translate accurately, preserving medical terminology. "
            "Do not add comments or explanations, only the translation."
        ),
    },
    "scientific": {
        "ru": (
            "Ты — научный переводчик. Сохраняй академический стиль, "
            "терминологию, структуру. Переводи дословно, без упрощений."
        ),
        "en": (
            "You are a scientific translator. Preserve academic style, "
            "terminology, structure. Translate literally, without simplification."
        ),
    },
    "patient": {
        "ru": (
            "Ты — медицинский переводчик для пациентов. "
            "Переводи понятным, доступным языком. "
            "Медицинские термины объясняй в скобках."
        ),
        "en": (
            "You are a medical translator for patients. "
            "Translate in plain, accessible language. "
            "Explain medical terms in parentheses."
        ),
    },
    "general": {
        "ru": "Ты — профессиональный переводчик. Переводи точно и естественно.",
        "en": "You are a professional translator. Translate accurately and naturally.",
    },
}


def _get_translation_system(translation_type: str, target_lang: str) -> str:
    prompts = TRANSLATION_SYSTEMS.get(translation_type, TRANSLATION_SYSTEMS["general"])
    return prompts.get(target_lang) or prompts.get("en", "")


class LangAgent:
    """
    Агент перевода и работы с языками.

    Методы:
        detect(text) → str                                      — определить язык
        translate(text, target, type, session_id) → str         — перевести
        explain_term(term, lang, session_id) → str              — объяснить термин
        simplify(text, lang, session_id) → str                  — упростить для пациента
    """

    def __init__(self):
        self.name = "LangAgent"

    def detect(self, text: str) -> str:
        """Определить язык текста."""
        detected = _detect_lang(text)
        name = LANG_NAMES.get(detected, detected)
        log.info(f"LangAgent.detect: '{detected}' ({name})")
        return detected

    def translate(
        self,
        text: str,
        target_lang: str,
        translation_type: str = "general",
        source_lang: Optional[str] = None,
        session_id: Optional[int] = None,
    ) -> str:
        """
        Перевести текст на целевой язык.

        Args:
            text:             Текст для перевода
            target_lang:      Код целевого языка (из SUPPORTED_LANGS)
            translation_type: 'medical' | 'scientific' | 'patient' | 'general'
            source_lang:      Исходный язык (если None — определяется автоматически)
            session_id:       ID сессии для сохранения в БД
        """
        if not text.strip():
            return ""
        if target_lang not in SUPPORTED_LANGS:
            return f"[Неподдерживаемый язык: {target_lang}]"

        src = source_lang or self.detect(text)
        if src == target_lang:
            return text  # Уже на нужном языке

        target_name = LANG_NAMES.get(target_lang, target_lang)
        system = _get_translation_system(translation_type, target_lang)
        prompt = (
            f"Переведи следующий текст на язык: {target_name} [{target_lang}].\n"
            f"Тип перевода: {translation_type}.\n\n"
            f"Текст:\n{text}"
        )

        log.info(f"LangAgent.translate: {src}→{target_lang}, type={translation_type}, "
                 f"~{len(text)} chars")

        # Нелатинские скрипты → Qwen
        if target_lang in QWEN_LANGS or src in QWEN_LANGS:
            result = ask_multilang(prompt, lang=target_lang)
        else:
            result = ask(prompt, system=system, lang=target_lang)

        if session_id:
            save_message(session_id, "user",
                         f"[Перевод {src}→{target_lang}]", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def explain_term(
        self,
        term: str,
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Объяснить медицинский термин на нужном языке."""
        if not term.strip():
            return ""

        system_map = {
            "ru": "Ты — врач. Объясни медицинский термин простым языком. 2–3 предложения.",
            "en": "You are a doctor. Explain the medical term in plain language. 2–3 sentences.",
        }
        system = system_map.get(lang) or system_map["en"]
        prompt = f"Объясни медицинский термин: {term}"

        result = ask(prompt, system=system, lang=lang)

        if session_id:
            save_message(session_id, "user", f"[Термин] {term}", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def simplify(
        self,
        text: str,
        lang: str = "ru",
        session_id: Optional[int] = None,
    ) -> str:
        """Упростить медицинский текст для понимания пациентом."""
        if not text.strip():
            return ""

        system_map = {
            "ru": (
                "Перепиши медицинский текст простым языком для пациента. "
                "Избегай терминов или объясняй их в скобках. "
                "Сохрани все важные факты."
            ),
            "en": (
                "Rewrite the medical text in plain language for a patient. "
                "Avoid jargon or explain terms in parentheses. "
                "Preserve all important facts."
            ),
        }
        system = system_map.get(lang) or system_map["en"]
        prompt = f"Упрости для пациента:\n\n{text}"

        result = ask(prompt, system=system, lang=lang)

        if session_id:
            save_message(session_id, "user", "[Упрощение текста]", provider="user")
            save_message(session_id, "assistant", result)

        return result

    def available_langs(self) -> list[dict]:
        """Список доступных языков с именами."""
        return [{"code": c, "name": LANG_NAMES.get(c, c)} for c in SUPPORTED_LANGS]
