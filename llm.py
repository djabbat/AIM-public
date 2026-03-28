"""
AIM v6.0 — llm.py
DeepSeek API wrapper. Единственная точка входа для всех LLM-вызовов в системе.

Использование:
    from llm import ask_llm, ask_deep

    answer = ask_llm("Объясни результаты анализов пациента", lang="ru")
    reasoning = ask_deep("Дифференциальная диагностика: боль в груди + одышка")
"""

import os
import time
import json
import logging
from typing import Optional, Generator

try:
    from openai import OpenAI
    _openai_available = True
except ImportError:
    _openai_available = False

try:
    import ollama as _ollama_lib
    _ollama_available = True
except ImportError:
    _ollama_available = False

from config import cfg

logger = logging.getLogger(__name__)

# ============================================================================
# Системные промпты по языку
# ============================================================================

SYSTEM_PROMPTS = {
    "ru": (
        "Ты — AIM, ИИ-ассистент интегративной медицины доктора Ткемаладзе. "
        "Отвечай точно, структурированно, на русском языке. "
        "Всегда учитывай Ze-теорию (биологический возраст, Ze-статус). "
        "При неопределённости — честно указывай на необходимость дополнительного обследования."
    ),
    "ka": (
        "შენ ხარ AIM — დოქტორ თქემალაძის ინტეგრაციული მედიცინის ასისტენტი. "
        "უპასუხე ზუსტად, სტრუქტურირებულად, ქართულ ენაზე. "
        "გაითვალისწინე Ze-თეორია (ბიოლოგიური ასაკი, Ze-სტატუსი)."
    ),
    "en": (
        "You are AIM, an integrative medicine AI assistant for Dr. Tkemaladze. "
        "Answer accurately, structured, in English. "
        "Always consider Ze-theory (biological age, Ze-status). "
        "If uncertain, honestly indicate the need for additional testing."
    ),
    "kz": (
        "Сіз — Дәрігер Ткемаладзенің AIM интегративті медицина жасанды интеллект көмекшісісіз. "
        "Дәл, құрылымды, қазақ тілінде жауап беріңіз. "
        "Ze-теориясын ескеріңіз (биологиялық жас, Ze-мәртебесі)."
    ),
}

# ============================================================================
# Основные функции
# ============================================================================

def ask_llm(
    prompt: str,
    lang: str = None,
    system: str = None,
    temperature: float = None,
    max_tokens: int = None,
    model: str = None,
) -> str:
    """
    Быстрый запрос к DeepSeek (deepseek-chat).
    Fallback на Ollama если нет ключа.

    Args:
        prompt:      Запрос пользователя
        lang:        Язык ответа ('ru'/'ka'/'en'/'kz'). По умолчанию — cfg.DEFAULT_LANG
        system:      Системный промпт (переопределяет встроенный)
        temperature: Температура генерации (по умолчанию cfg.LLM_TEMPERATURE)
        max_tokens:  Максимум токенов (по умолчанию cfg.LLM_MAX_TOKENS)
        model:       Модель (по умолчанию deepseek-chat)

    Returns:
        Ответ модели как строка
    """
    lang = lang or cfg.DEFAULT_LANG
    temperature = temperature if temperature is not None else cfg.LLM_TEMPERATURE
    max_tokens = max_tokens or cfg.LLM_MAX_TOKENS
    model = model or cfg.DEEPSEEK_MODEL_FAST

    sys_prompt = system or SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["ru"])

    if cfg.has_deepseek() and _openai_available:
        return _call_deepseek(prompt, sys_prompt, model, temperature, max_tokens)
    elif _ollama_available:
        logger.warning("DeepSeek недоступен — используется Ollama fallback")
        return _call_ollama(prompt, sys_prompt)
    else:
        return _no_llm_response(lang)


def ask_deep(
    prompt: str,
    lang: str = None,
    system: str = None,
) -> str:
    """
    Глубокое рассуждение через DeepSeek-Reasoner.
    Для сложных диагностических задач, дифференциальной диагностики,
    анализа лабораторных данных.

    Args:
        prompt: Сложный запрос для глубокого рассуждения
        lang:   Язык ответа
        system: Системный промпт (опционально)

    Returns:
        Ответ с полным цепочкой рассуждений
    """
    return ask_llm(
        prompt=prompt,
        lang=lang,
        system=system,
        model=cfg.DEEPSEEK_MODEL_REASON,
        temperature=0.1,  # Более детерминированный для рассуждений
        max_tokens=8192,
    )


def ask_medical(
    patient_data: dict,
    question: str,
    lang: str = None,
) -> str:
    """
    Специализированный медицинский запрос с контекстом пациента.

    Args:
        patient_data: Словарь с данными пациента (имя, возраст, диагнозы, анализы)
        question:     Медицинский вопрос
        lang:         Язык

    Returns:
        Медицинский ответ с учётом контекста пациента
    """
    lang = lang or cfg.DEFAULT_LANG

    # Форматируем контекст пациента
    context_parts = []
    if patient_data.get("name"):
        context_parts.append(f"Пациент: {patient_data['name']}")
    if patient_data.get("age"):
        context_parts.append(f"Возраст: {patient_data['age']} лет")
    if patient_data.get("diagnoses"):
        context_parts.append(f"Диагнозы: {', '.join(patient_data['diagnoses'])}")
    if patient_data.get("labs"):
        context_parts.append(f"Анализы: {json.dumps(patient_data['labs'], ensure_ascii=False)}")
    if patient_data.get("ze_status"):
        context_parts.append(f"Ze-статус: {patient_data['ze_status']}")

    context = "\n".join(context_parts)
    full_prompt = f"Контекст пациента:\n{context}\n\nВопрос: {question}"

    return ask_deep(full_prompt, lang=lang)


# ============================================================================
# Внутренние функции
# ============================================================================

def _call_deepseek(
    prompt: str,
    system: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Вызов DeepSeek API через OpenAI-совместимый клиент"""
    for attempt in range(cfg.LLM_RETRY_ATTEMPTS):
        try:
            client = OpenAI(
                api_key=cfg.DEEPSEEK_API_KEY,
                base_url=cfg.DEEPSEEK_BASE_URL,
                timeout=cfg.LLM_TIMEOUT_SEC,
            )

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.warning(f"DeepSeek попытка {attempt + 1}/{cfg.LLM_RETRY_ATTEMPTS}: {e}")
            if attempt < cfg.LLM_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)  # Экспоненциальный backoff
            else:
                logger.error(f"DeepSeek недоступен после {cfg.LLM_RETRY_ATTEMPTS} попыток")
                if _ollama_available:
                    logger.info("Переключение на Ollama fallback")
                    return _call_ollama(prompt, system)
                return f"[Ошибка LLM: {e}]"

    return "[Ошибка: не удалось получить ответ]"


def _call_ollama(prompt: str, system: str) -> str:
    """Ollama fallback вызов"""
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        response = _ollama_lib.chat(
            model=cfg.OLLAMA_MODEL,
            messages=messages,
        )
        return response["message"]["content"]
    except Exception as e:
        logger.error(f"Ollama ошибка: {e}")
        return f"[Ошибка Ollama: {e}]"


def _no_llm_response(lang: str) -> str:
    """Ответ когда LLM недоступен"""
    messages = {
        "ru": "[LLM недоступен. Установите DEEPSEEK_API_KEY в ~/.aim_env или запустите Ollama]",
        "ka": "[LLM მიუწვდომელია. დააყენეთ DEEPSEEK_API_KEY ან გაუშვით Ollama]",
        "en": "[LLM unavailable. Set DEEPSEEK_API_KEY in ~/.aim_env or start Ollama]",
        "kz": "[LLM қол жетімсіз. ~/.aim_env ішінде DEEPSEEK_API_KEY орнатыңыз]",
    }
    return messages.get(lang, messages["ru"])


# ============================================================================
# Диагностика
# ============================================================================

def check_llm_status() -> dict:
    """Проверить доступность LLM"""
    status = {
        "deepseek_key": bool(cfg.DEEPSEEK_API_KEY),
        "openai_lib": _openai_available,
        "ollama_lib": _ollama_available,
        "active_backend": None,
    }

    if status["deepseek_key"] and status["openai_lib"]:
        status["active_backend"] = "deepseek"
    elif status["ollama_lib"]:
        status["active_backend"] = "ollama"
    else:
        status["active_backend"] = "none"

    return status


# ============================================================================
# CLI тест
# ============================================================================

if __name__ == "__main__":
    import sys

    status = check_llm_status()
    print(f"LLM статус: {status}")

    if status["active_backend"] == "none":
        print("ОШИБКА: LLM недоступен. Установите DEEPSEEK_API_KEY в ~/.aim_env")
        sys.exit(1)

    print(f"\nТест ask_llm (backend: {status['active_backend']})...")
    result = ask_llm("Скажи 'Тест успешен' и ничего больше.", lang="ru")
    print(f"Ответ: {result}")

    print("\nllm.py работает корректно")
