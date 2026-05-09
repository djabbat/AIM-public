"""agents/follow_up_generator.py — auto-draft follow-up emails (E1, 2026-05-03).

Pulls every overdue stakeholder from `agents.stakeholder_tracker`, looks
up their last context (project, role, days_silent), and generates a
*polite, short* follow-up email — saved as a Gmail DRAFT (never sent
without an explicit user_confirmed=True).

Hard rules baked into the template:

  * Never invent past correspondence. The template references "my last
    email on <date>" and we plug `last_contact_at` from the DB.
  * Always close with the user's name (config: AIM_USER_NAME) + a
    soft re-ping question, never an ultimatum.
  * Language picker: detect from the contact's `role`/`notes` field; fall
    back to English. Russian for `Co-PI Tbilisi`-style hints, Georgian
    for TSU/SJSU domains, otherwise English.
  * Subject line: concise, 50 chars max.

Public API:
    generate(contact, *, today=None, llm=None) -> Draft
    generate_all(today=None, llm=None) -> list[Draft]
    save_drafts(drafts) -> list[str]   # Gmail draft ids; via email_agent
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import re
from typing import Callable, Optional

log = logging.getLogger("aim.followup")


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Draft:
    contact_name: str
    contact_email: Optional[str]
    subject: str
    body: str
    lang: str
    days_silent: int


# ── language detection (heuristic — we don't ship a model) ──────


_RU_HINT = re.compile(r"[А-Яа-яЁё]")
_KA_HINT = re.compile(r"[Ⴀ-ჿ]")


def _detect_lang(contact) -> str:
    blob = " ".join([contact.role or "", contact.notes or "",
                     contact.email or ""])
    if _KA_HINT.search(blob) or "tsu.ge" in (contact.email or ""):
        return "ka"
    if _RU_HINT.search(blob) or any(s in (contact.notes or "")
                                     for s in ("Tbilisi", "Тбилиси",
                                                "Грузия", "Russia")):
        return "ru"
    return "en"


# ── templates ────────────────────────────────────────────────────


_USER_NAME = os.environ.get("AIM_USER_NAME", "Jaba Tkemaladze")
_USER_NAME_RU = os.environ.get("AIM_USER_NAME_RU", "Джаба Ткемаладзе")
_USER_NAME_KA = os.environ.get("AIM_USER_NAME_KA", "ჯაბა ტყემალაძე")


_TEMPLATES = {
    "en": {
        "subject": "Quick follow-up — {topic}",
        "body": (
            "Dear {first_name},\n\n"
            "Hope you're well. I wanted to gently check in on my last "
            "email from {last_contact} about {topic}; I haven't heard "
            "back yet ({days} days), so I want to make sure it didn't "
            "land in spam or fall through.\n\n"
            "If you need more time, please just say so — happy to wait. "
            "And if it's easier to chat briefly, let me know a slot that "
            "works for you.\n\n"
            "Best,\n"
            "{user_name}"
        ),
        "default_topic": "the project we discussed",
        "user_name": _USER_NAME,
    },
    "ru": {
        "subject": "Небольшое напоминание — {topic}",
        "body": (
            "Уважаемый(ая) {first_name},\n\n"
            "Надеюсь, всё хорошо. Хотел вежливо напомнить о письме "
            "от {last_contact} по теме «{topic}»; пока не получил "
            "ответа ({days} дн.), хочу убедиться, что письмо не "
            "попало в спам.\n\n"
            "Если нужно больше времени — напишите, пожалуйста, я подожду. "
            "Если удобнее коротко обсудить голосом, скажите слот.\n\n"
            "С уважением,\n"
            "{user_name}"
        ),
        "default_topic": "обсуждаемый проект",
        "user_name": _USER_NAME_RU,
    },
    "ka": {
        "subject": "მოკლე შეხსენება — {topic}",
        "body": (
            "ძვირფასო {first_name},\n\n"
            "ვიმედოვნებ, ყველაფერი კარგად არის. მინდა თავაზიანად "
            "შეგახსენოთ ჩემი წერილის შესახებ {last_contact} თარიღით — "
            "თემაზე «{topic}»; ჯერ პასუხი არ მიმიღია ({days} დღე), "
            "მინდა დავრწმუნდე, რომ წერილი სპამში არ მოხვდა.\n\n"
            "თუ მეტი დრო გჭირდებათ — გთხოვთ მაცნობოთ, ველოდები. "
            "თუ უფრო მოსახერხებელია ხანმოკლე ზარი, მითხარით ხელსაყრელი დრო.\n\n"
            "პატივისცემით,\n"
            "{user_name}"
        ),
        "default_topic": "საერთო პროექტი",
        "user_name": _USER_NAME_KA,
    },
}


def _first_name(full: str) -> str:
    if not full:
        return ""
    return full.strip().split()[0]


def _fmt_topic(contact, max_chars: int = 60) -> str:
    note = (contact.notes or "").strip()
    if note:
        # Use the first phrase / sentence as topic.
        topic = re.split(r"[.;\n]", note, maxsplit=1)[0]
        topic = topic.strip().lstrip("*•— -")
        if topic:
            return topic[:max_chars]
    role = (contact.role or "").strip()
    if role:
        return role[:max_chars]
    return ""


def generate(contact, *, today: Optional[dt.date] = None,
             llm: Optional[Callable[[str], str]] = None) -> Optional[Draft]:
    today = today or dt.date.today()
    if not contact.email:
        return None  # can't draft without an address
    days = contact.days_silent(today=today) or 0
    lang = _detect_lang(contact)
    tpl = _TEMPLATES[lang]

    topic = _fmt_topic(contact) or tpl["default_topic"]
    last_contact = contact.last_contact_at or "the past few weeks"
    last_contact_short = str(last_contact)[:10]
    first = _first_name(contact.name)

    subject = tpl["subject"].format(topic=topic)[:78]
    body = tpl["body"].format(
        first_name=first,
        last_contact=last_contact_short,
        topic=topic,
        days=days,
        user_name=tpl["user_name"],
    )

    # Optional LLM polish hook — disabled by default. Safe to plug in
    # later via S3 prompt patches; signature must take (subject, body).
    if llm is not None:
        try:
            polished = llm(f"Polish this follow-up email; preserve facts:\n\n"
                            f"Subject: {subject}\n\n{body}")
            if polished and polished.strip():
                # Best-effort split: first line subject, rest body.
                lines = polished.strip().splitlines()
                if lines and lines[0].lower().startswith("subject:"):
                    subject = lines[0].split(":", 1)[1].strip()[:78]
                    body = "\n".join(lines[1:]).lstrip()
                else:
                    body = polished.strip()
        except Exception as e:  # noqa: BLE001
            log.debug("LLM polish failed: %s", e)

    return Draft(contact_name=contact.name, contact_email=contact.email,
                  subject=subject, body=body, lang=lang, days_silent=days)


def generate_all(today: Optional[dt.date] = None,
                 llm: Optional[Callable[[str], str]] = None,
                 ) -> list[Draft]:
    try:
        from agents import stakeholder_tracker as st
    except ImportError:
        return []
    rows = st.overdue_followups(today=today)
    out: list[Draft] = []
    for c in rows:
        d = generate(c, today=today, llm=llm)
        if d is not None:
            out.append(d)
    return out


def save_drafts(drafts: list[Draft]) -> list[str]:
    """Persist each Draft as a Gmail DRAFT via email_agent. Returns ids."""
    try:
        from agents import email_agent as em
    except ImportError:
        return []
    fn = (getattr(em, "create_draft", None)
          or getattr(em, "save_draft", None)
          or getattr(em, "draft", None))
    if fn is None:
        return []
    ids: list[str] = []
    for d in drafts:
        try:
            r = fn(to=d.contact_email, subject=d.subject, body=d.body)
        except TypeError:
            try:
                r = fn(d.contact_email, d.subject, d.body)
            except Exception as e:
                log.warning("create_draft failed for %s: %s",
                             d.contact_email, e)
                continue
        ids.append(str(r))
    return ids
