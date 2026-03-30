"""
AIM v6.0 — llm.py
DeepSeek API wrapper. Единственная точка входа для всех LLM-вызовов в системе.

Поддерживаемые языки: RU / EN / FR / ES / AR / ZH / KA (ООН-6 + грузинский).

Маршрутизация моделей (route_model):
    task_type="fast"   → deepseek-chat    (быстрые запросы, все языки)
    task_type="reason" → deepseek-reasoner (сложные рассуждения, дифдиагноз)
    task_type="medical"→ deepseek-reasoner (медицинский анализ с контекстом)
    offline            → ollama/llama3.2   (если нет DeepSeek ключа)

Использование:
    from llm import ask_llm, ask_deep

    answer = ask_llm("Объясни результаты анализов пациента", lang="ru")
    answer = ask_llm("Explain lab results", lang="en", task_type="fast")
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
    "en": (
        "You are AIM, an integrative medicine AI assistant for Dr. Tkemaladze. "
        "Answer accurately, structured, in English. "
        "Always consider Ze-theory (biological age, Ze-status). "
        "If uncertain, honestly indicate the need for additional testing."
    ),
    "fr": (
        "Vous êtes AIM, l'assistant IA en médecine intégrative du Dr Tkemaladze. "
        "Répondez avec précision et structure, en français. "
        "Tenez compte de la théorie Ze (âge biologique, statut Ze). "
        "En cas d'incertitude, indiquez honnêtement la nécessité d'examens complémentaires."
    ),
    "es": (
        "Eres AIM, el asistente de IA en medicina integrativa del Dr. Tkemaladze. "
        "Responde con precisión y estructura, en español. "
        "Considera siempre la teoría Ze (edad biológica, estado Ze). "
        "Ante la incertidumbre, indica honestamente la necesidad de pruebas adicionales."
    ),
    "ar": (
        "أنت AIM، مساعد الذكاء الاصطناعي للطب التكاملي للدكتور تكيمالادزي. "
        "أجب بدقة وبشكل منظم باللغة العربية. "
        "ضع دائماً في الاعتبار نظرية Ze (العمر البيولوجي، حالة Ze). "
        "عند عدم اليقين، أشر بصدق إلى الحاجة لفحوصات إضافية."
    ),
    "zh": (
        "您是AIM——Tkemaladze博士整合医学AI助手。"
        "请用中文准确、有条理地回答。"
        "始终考虑Ze理论（生物年龄、Ze状态）。"
        "如有不确定，请如实指出需要进一步检查。"
    ),
    "ka": (
        "შენ ხარ AIM — დოქტორ თქემალაძის ინტეგრაციული მედიცინის ასისტენტი. "
        "უპასუხე ზუსტად, სტრუქტურირებულად, ქართულ ენაზე. "
        "გაითვალისწინე Ze-თეორია (ბიოლოგიური ასაკი, Ze-სტატუსი)."
    ),
    # Backward-compat: Kazakh (not in official 7, kept for existing integrations)
    "kz": (
        "Сіз — Дәрігер Ткемаладзенің AIM интегративті медицина жасанды интеллект көмекшісісіз. "
        "Дәл, құрылымды, қазақ тілінде жауап беріңіз. "
        "Ze-теориясын ескеріңіз (биологиялық жас, Ze-мәртебесі)."
    ),
}

# ============================================================================
# Маршрутизация моделей
# ============================================================================

def route_model(task_type: str = "fast", model_override: str = None) -> str:
    """
    Выбрать модель DeepSeek по типу задачи.

    Правила маршрутизации:
        "fast"   → deepseek-chat    (быстрые запросы, перевод, объяснения)
        "reason" → deepseek-reasoner (дифдиагноз, сложные рассуждения)
        "medical"→ deepseek-reasoner (медицинский анализ с контекстом пациента)

    Все 7 языков (RU/EN/FR/ES/AR/ZH/KA) поддерживаются обеими моделями.
    Offline fallback (ollama/llama3.2) применяется в _call_deepseek при недоступности ключа.

    Args:
        task_type:      Тип задачи: "fast" | "reason" | "medical"
        model_override: Явное указание модели (переопределяет маршрутизацию)

    Returns:
        Строка с названием модели DeepSeek
    """
    if model_override:
        return model_override
    if task_type in ("reason", "medical"):
        return cfg.DEEPSEEK_MODEL_REASON
    return cfg.DEEPSEEK_MODEL_FAST


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
    task_type: str = "fast",
) -> str:
    """
    Запрос к DeepSeek с автоматической маршрутизацией по задаче и языку.
    Fallback на Ollama если нет ключа.

    Args:
        prompt:      Запрос пользователя
        lang:        Язык ответа (ru/en/fr/es/ar/zh/ka). По умолчанию cfg.DEFAULT_LANG
        system:      Системный промпт (переопределяет встроенный)
        temperature: Температура генерации (по умолчанию cfg.LLM_TEMPERATURE)
        max_tokens:  Максимум токенов (по умолчанию cfg.LLM_MAX_TOKENS)
        model:       Явное указание модели (переопределяет route_model)
        task_type:   Тип задачи: "fast" | "reason" | "medical" (влияет на выбор модели)

    Returns:
        Ответ модели как строка
    """
    lang = lang or cfg.DEFAULT_LANG
    temperature = temperature if temperature is not None else cfg.LLM_TEMPERATURE
    max_tokens = max_tokens or cfg.LLM_MAX_TOKENS
    selected_model = route_model(task_type, model_override=model)

    sys_prompt = system or SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["ru"])

    if cfg.has_deepseek() and _openai_available:
        return _call_deepseek(prompt, sys_prompt, selected_model, temperature, max_tokens)
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
    анализа лабораторных данных. Поддерживает все 7 языков AIM.

    Args:
        prompt: Сложный запрос для глубокого рассуждения
        lang:   Язык ответа (ru/en/fr/es/ar/zh/ka)
        system: Системный промпт (опционально)

    Returns:
        Ответ с полной цепочкой рассуждений
    """
    return ask_llm(
        prompt=prompt,
        lang=lang,
        system=system,
        task_type="reason",
        temperature=0.1,  # Детерминированный для медицинских рассуждений
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
    """Ответ когда LLM недоступен (все 7 языков AIM + KZ backward-compat)"""
    messages = {
        "ru": "[LLM недоступен. Установите DEEPSEEK_API_KEY в ~/.aim_env или запустите Ollama]",
        "en": "[LLM unavailable. Set DEEPSEEK_API_KEY in ~/.aim_env or start Ollama]",
        "fr": "[LLM indisponible. Définissez DEEPSEEK_API_KEY dans ~/.aim_env ou lancez Ollama]",
        "es": "[LLM no disponible. Configure DEEPSEEK_API_KEY en ~/.aim_env o inicie Ollama]",
        "ar": "[LLM غير متوفر. أضف DEEPSEEK_API_KEY في ~/.aim_env أو شغّل Ollama]",
        "zh": "[LLM不可用。请在~/.aim_env中设置DEEPSEEK_API_KEY或启动Ollama]",
        "ka": "[LLM მიუწვდომელია. დააყენეთ DEEPSEEK_API_KEY ან გაუშვით Ollama]",
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
