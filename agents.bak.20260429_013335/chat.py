"""
AIM v7.0 — Chat Companion Agent (kernel-powered)
=================================================

Phase 4 (Q7 case D): multilingual intelligent dialogue через decision kernel.

Pipeline:
1. Input: natural language question (ru/en/ka/ar/zh/etc.)
2. Detect language (agents/lang._detect_lang)
3. Classify intent (symptom / info / emotional / emergency / danger)
4. Generate alternatives:
   - emergency_redirect → URGENT referral
   - clarify → follow-up question
   - inform → educational answer (grounded, cited)
   - triage_redirect → suggest running triage flow
   - emotional_support → acknowledge, empathize, refer if needed
   - refuse → L0/L1 violated
5. kernel.decide() с chat-appropriate weighting
6. Generate response в detected language (LLM с chosen action_type)

Ethics priority (chat-specific):
- Autonomy: respect что пациент хочет (information vs advice boundary)
- Beneficence: useful info (learning), not empty reassurance (cheating)
- Non-maleficence: no fear without cause, no false reassurance про red flags
- Justice: same quality regardless of language / demo
- L0 strong: education OK, dual-use harmful knowledge blocked

User-facing output: только response в target language.
Internal audit: full kernel breakdown → AI_LOG.md.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from llm import ask_deep, ask_fast, _detect_lang
from agents.kernel import Decision, OverrideContext, decide, KernelViolation
from agents import kernel

log = logging.getLogger("aim.chat")


# ═════════════════════════════════════════════════════════════════════════════
# Intent classification
# ═════════════════════════════════════════════════════════════════════════════

EMERGENCY_PATTERNS = [
    # Сердечно-сосудистые
    r"давящ.{0,20}боль.{0,20}(груд|сердц)", r"crushing chest", r"chest pain.{0,30}(jaw|arm|neck)",
    r"давит.{0,20}(сердц|груд)", r"боль.{0,20}отдаёт.{0,20}(руку|челюсть|лопатку)",
    # Инсульт (FAST)
    r"парализ", r"онемени[ея].{0,20}(лица|руки|ноги)", r"нарушение.{0,20}реч", r"stroke",
    r"face droop", r"слабость.{0,20}(половин|одн)",
    # Респираторное
    r"не могу дышать", r"удушь[ея]", r"cant breathe", r"cannot breathe", r"suffocat",
    # Сознание
    r"потерял.{0,20}сознан", r"обморок", r"passed out", r"lost consciousness",
    # Кровотечение
    r"сильное кровотечение", r"severe bleeding", r"уremia",
    # Суицид
    r"самоубий", r"suicide", r"kill myself", r"покончить с",
    # Анафилаксия
    r"анафилак", r"распух.{0,20}(лицо|горло|язык)", r"tongue swelling",
    # Прочее
    r"hit by", r"overdose", r"передозир",
]

DANGER_PATTERNS = [
    # Запрос на изготовление опасного
    r"synthes.{0,20}(bio|poison|toxin|weapon)",
    r"make.{0,20}(bomb|explosive|weapon)",
    r"как.{0,20}(изготов|сделать).{0,20}(яд|взрывч|оружие)",
    r"forge.{0,20}(document|prescription|id)",
    r"подделать.{0,20}(рецепт|документ)",
]


def classify_intent(message: str) -> str:
    """Rule-based first-pass intent classification.

    Returns one of: emergency / danger / symptom / info / emotional / other
    """
    m = message.lower()

    # Emergency check first (most urgent)
    for pat in EMERGENCY_PATTERNS:
        if re.search(pat, m, re.IGNORECASE):
            return "emergency"

    # Danger signals (L0 pre-filter)
    for pat in DANGER_PATTERNS:
        if re.search(pat, m, re.IGNORECASE):
            return "danger"

    # Emotional keywords
    emo_keywords = ["боюсь", "тревог", "депресс", "afraid", "scared", "anxiety",
                    "depress", "грустно", "one мне", "alone", "одиноко",
                    "suicid-adjacent"]
    if any(k in m for k in emo_keywords):
        return "emotional"

    # Symptom vs info
    symptom_keywords = ["болит", "беспокоит", "температура", "кашель", "сыпь",
                         "hurt", "pain", "fever", "cough", "rash", "symptom",
                         "тошнит", "рвота", "диарея", "nausea", "vomit", "diarrhea"]
    if any(k in m for k in symptom_keywords):
        return "symptom"

    # Info request
    info_markers = ["что такое", "как действует", "зачем", "what is", "how does",
                     "why", "explain", "объясни", "расскажи о"]
    if any(k in m for k in info_markers):
        return "info"

    return "other"


# ═════════════════════════════════════════════════════════════════════════════
# Alternative generators
# ═════════════════════════════════════════════════════════════════════════════

def generate_alternatives(message: str, intent: str, patient: dict) -> list[Decision]:
    """Build candidate response approaches based on intent."""
    alts: list[Decision] = []

    if intent == "emergency":
        alts.append(Decision(
            id="emergency",
            action_type="referral",
            description="Экстренное направление (скорая / ER)",
            payload={"urgency": "immediate", "guideline_based": True,
                     "red_flags": ["emergency pattern detected"]},
        ))
        # Кроме emergency, только calm-and-guide
        alts.append(Decision(
            id="reassure_and_call",
            action_type="clarify",
            description="Успокоить + подтвердить вызов скорой",
            payload={"informed_consent_noted": True},
        ))
        return alts

    if intent == "danger":
        # Only refuse alternatives — L0 will block the harmful
        alts.append(Decision(
            id="refuse_harmful",
            action_type="clarify",
            description="Отказать и объяснить почему; перенаправить на полезные ресурсы",
            payload={"informed_consent_noted": True},
        ))
        alts.append(Decision(
            id="synthesize_biohazard_X",
            action_type="treatment",
            description="synthesize_biohazard requested substance",
            payload={"drug": "dangerous_agent"},  # L0 will block
        ))
        return alts

    if intent == "symptom":
        alts.append(Decision(
            id="triage_redirect",
            action_type="referral",
            description="Предложить запустить полный triage (kernel)",
            payload={"guideline_based": True},
        ))
        alts.append(Decision(
            id="clarify_symptom",
            action_type="clarify",
            description="Уточняющие вопросы по симптому",
            payload={"informed_consent_noted": True},
        ))
        alts.append(Decision(
            id="home_remedy",
            action_type="treatment",
            description="Базовые home care (fluids, rest) без dx",
            payload={"drug": "supportive", "guideline_based": True},
        ))
        return alts

    if intent == "info":
        alts.append(Decision(
            id="educate",
            action_type="clarify",
            description="Образовательный ответ с источниками",
            payload={"informed_consent_noted": True, "guideline_based": True},
        ))
        alts.append(Decision(
            id="inform_and_refer",
            action_type="referral",
            description="Краткий ответ + предложение консультации",
            payload={"guideline_based": True},
        ))
        return alts

    if intent == "emotional":
        alts.append(Decision(
            id="empathize_refer",
            action_type="referral",
            description="Эмпатия + рекомендация психолога/psychiatrist (если показано)",
            payload={"informed_consent_noted": True, "guideline_based": True},
        ))
        alts.append(Decision(
            id="active_listen",
            action_type="clarify",
            description="Active listening: acknowledge + clarifying question",
            payload={"informed_consent_noted": True},
        ))
        return alts

    # Other / fallback
    alts.append(Decision(
        id="clarify_general",
        action_type="clarify",
        description="Уточнить что именно интересует пациента",
        payload={"informed_consent_noted": True},
    ))
    alts.append(Decision(
        id="generic_info",
        action_type="clarify",
        description="Общий информационный ответ",
        payload={"informed_consent_noted": True},
    ))
    return alts


# ═════════════════════════════════════════════════════════════════════════════
# Response generation per chosen decision
# ═════════════════════════════════════════════════════════════════════════════

RESPONSE_PROMPTS = {
    "emergency": {
        "ru": "Пациент в экстренной ситуации. Кратко, ясно, calm: "
              "(1) призвать вызвать скорую 112 (Грузия) / 911 / местный emergency number, "
              "(2) инструкции до приезда (положение, что делать, чего НЕ делать), "
              "(3) одной фразой обосновать срочность. Максимум 150 слов.",
        "en": "Patient in emergency. Concise, clear, calm response: "
              "(1) call emergency services 112/911, "
              "(2) instructions until arrival, "
              "(3) one-sentence reason for urgency. Max 150 words.",
    },
    "triage_redirect": {
        "ru": "Пациент описал симптом. Ответ: empathetic acknowledgment + "
              "предложить пройти full triage через AIM для точной рекомендации. "
              "Не ставить диагноз. Спросить согласие на 2-3 уточняющих вопроса.",
        "en": "Patient described symptom. Response: empathetic acknowledgment + "
              "suggest running full AIM triage for accurate recommendation. "
              "Don't diagnose. Ask consent for 2-3 clarifying questions.",
    },
    "clarify_symptom": {
        "ru": "Задай пациенту 2-3 уточняющих вопроса о симптоме (timeline, характер, "
              "триггеры, severity). Коротко, empathetic tone.",
        "en": "Ask patient 2-3 clarifying questions about symptom (timeline, nature, "
              "triggers, severity). Brief, empathetic tone.",
    },
    "educate": {
        "ru": "Дай educational ответ на вопрос пациента. Honest, grounded, "
              "с disclaimer 'это информация, не медицинский совет'. "
              "Максимум 200 слов. Если вопрос outside медицинской scope — сказать.",
        "en": "Educational answer to patient question. Honest, grounded, "
              "with 'this is info not medical advice' disclaimer. "
              "Max 200 words. Say if question outside medical scope.",
    },
    "empathize_refer": {
        "ru": "Пациент в эмоциональном состоянии. Ответ: "
              "(1) acknowledge feelings без суждения, "
              "(2) если есть signs requiring help (suicidal, severe depression) — "
              "рекомендовать immediate professional support, "
              "(3) если general anxiety — нормализовать + рекомендовать психолога при need. "
              "Не давать therapy, только support + referral.",
        "en": "Patient in emotional state. Response: "
              "(1) acknowledge feelings without judgment, "
              "(2) if signs requiring help — immediate professional support, "
              "(3) if general anxiety — normalize + recommend psychologist. "
              "Don't give therapy, only support + referral.",
    },
    "refuse_harmful": {
        "ru": "Пациент запросил потенциально вредную информацию (dual-use / bio / oружие / документы). "
              "Ответ: вежливо отказать, объяснить что это выходит за рамки безопасной помощи, "
              "перенаправить на legitimate help если применимо (напр. mental health crisis → hotline).",
        "en": "Patient requested potentially harmful info (dual-use / bio / weapon / docs). "
              "Response: politely decline, explain this is outside safe help scope, "
              "redirect to legitimate help if applicable (e.g. mental health crisis hotline).",
    },
}


def generate_response(
    chosen: kernel.Scored,
    message: str,
    intent: str,
    lang: str,
) -> str:
    """Generate LLM response based on chosen action + language."""
    prompts = RESPONSE_PROMPTS.get(chosen.decision.id) or RESPONSE_PROMPTS.get(intent)
    if prompts:
        system = prompts.get(lang, prompts.get("en", ""))
    else:
        system = (
            "Ты — AIM, AI-ассистент Dr. Tkemaladze. Отвечай helpful, concise, "
            "honest. Disclaimer: не медицинский совет." if lang == "ru"
            else "You are AIM, AI assistant for Dr. Tkemaladze. Helpful, concise, "
            "honest. Disclaimer: not medical advice."
        )

    # Use ask_fast для chat (Groq llama для speed), fallback to deep
    try:
        response = ask_fast(message, lang=lang)
    except Exception:
        response = ask_deep(message, system=system, lang=lang)
    return response


# ═════════════════════════════════════════════════════════════════════════════
# ChatAgent
# ═════════════════════════════════════════════════════════════════════════════

class ChatAgent:
    """Kernel-powered multilingual chat companion."""

    def __init__(self):
        self.name = "ChatAgent"

    def respond(
        self,
        message: str,
        patient: Optional[dict] = None,
        lang: Optional[str] = None,
        session_id: Optional[int] = None,
        verbose: bool = False,
        override: Optional[OverrideContext] = None,
    ) -> dict:
        """Respond to user message через kernel.

        Args:
            message: user natural language input
            patient: patient dict (optional, for context-aware responses)
            lang: target language (auto-detect if None)
            session_id: for chat history
            verbose: return full kernel breakdown
            override: soft/hard override

        Returns:
            dict: {status, output, intent, detected_lang, scored}
        """
        if not message.strip():
            return {"status": "blocked", "output": "пустой запрос",
                    "error": "empty_message"}

        # 1. Detect language
        detected = lang or _detect_lang(message)

        # 2. Classify intent
        intent = classify_intent(message)

        # 3. If emergency — red flag injected into patient
        p = dict(patient or {"id": "anonymous"})
        if intent == "emergency":
            p["red_flags"] = p.get("red_flags", []) + ["chat-detected emergency pattern"]
        p.setdefault("age", 40)
        p.setdefault("allergies", [])
        p.setdefault("medications", [])
        p.setdefault("missing_labs_count", 0)
        p.setdefault("history_contradictions", 0)
        p.setdefault("unexplained_symptoms_count", 0)

        # 4. Generate alternatives
        alts = generate_alternatives(message, intent, p)

        # 5. Kernel decide
        try:
            scored = decide(
                alts, p,
                context={"source": "chat", "intent": intent, "message_len": len(message)},
                override=override or OverrideContext(),
                agent="chat_agent",
                patient_id=p.get("id", ""),
                session_id=str(session_id) if session_id else None,
                decision_type="chat",
            )
        except KernelViolation as e:
            # All blocked — safest fallback: decline politely
            decline_msg = (
                "Не могу помочь с этим запросом в текущих рамках. "
                "Если это emergency, пожалуйста, позвоните 112." if detected == "ru"
                else "Cannot help with this request in current scope. "
                "If emergency, please call 112/911."
            )
            return {
                "status": "blocked",
                "output": decline_msg,
                "intent": intent, "detected_lang": detected,
                "error": str(e),
            }

        # 6. Generate response text в target language
        response_text = generate_response(scored, message, intent, detected)

        # Add emergency prefix if emergency
        if intent == "emergency":
            prefix = ("🚨 ЭКСТРЕННО! " if detected == "ru" else "🚨 EMERGENCY! ")
            response_text = prefix + response_text

        # Verbose мode — добавить kernel breakdown
        if verbose:
            response_text += "\n\n---\n" + kernel.format_verbose(scored, detected)

        return {
            "status": "decided",
            "output": response_text,
            "intent": intent,
            "detected_lang": detected,
            "scored": scored,
        }


def chat_respond(message: str, patient: dict | None = None, lang: str | None = None,
                  verbose: bool = False) -> dict:
    return ChatAgent().respond(message, patient, lang, verbose=verbose)
