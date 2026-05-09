"""tests/test_coach_shim.py — shim parity for `agents/coach.py` over
`aim-coach` Rust binary (P2.1, 2026-05-07).

Tests only the deterministic surface (classify / next_move /
system_prompt / detect_codesign_intent). The LLM-routing path
(`coach_reply`, `_ask_llm`) is tested via separate mocks elsewhere
(future work — added if/when llm_client.py becomes default path).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_classify_change_talk_ru():
    from agents import coach
    assert coach.classify("я хочу попробовать ходить по 30 минут") == "change_talk"


def test_classify_change_talk_en():
    from agents import coach
    assert coach.classify("i want to try walking 30 minutes daily") == "change_talk"


def test_classify_sustain_talk():
    from agents import coach
    assert coach.classify("это слишком сложно, не получится") == "sustain_talk"


def test_classify_resistance():
    from agents import coach
    assert coach.classify("вы не понимаете, оставьте меня") == "resistance"


def test_classify_neutral_returns_neutral():
    from agents import coach
    assert coach.classify("я ел овсянку на завтрак") == "neutral"


def test_classify_empty_string_safe():
    from agents import coach
    # Empty must not crash; must return "neutral" or similar.
    out = coach.classify("")
    assert out == "neutral"


def test_next_move_change_talk_l3_is_affirmation():
    from agents import coach
    assert coach.next_move("change_talk", 3) == "affirmation"


def test_next_move_resistance_overrides_level():
    from agents import coach
    assert coach.next_move("resistance", 1) == "roll_with_resistance"
    assert coach.next_move("resistance", 4) == "roll_with_resistance"


def test_next_move_l1_disengaged_builds_rapport():
    from agents import coach
    assert coach.next_move("change_talk", 1) == "build_rapport"
    assert coach.next_move("neutral", 0) == "build_rapport"


def test_next_move_l4_neutral_is_open_question():
    from agents import coach
    assert coach.next_move("neutral", 4) == "open_question"


def test_system_prompt_en_has_oars():
    from agents import coach
    p = coach.system_prompt("en")
    assert "OARS" in p
    assert "autonomy" in p.lower()


def test_system_prompt_ru_has_motivational_interviewing():
    from agents import coach
    p = coach.system_prompt("ru")
    assert "мотивационного интервью" in p


def test_detect_codesign_agreed_ru():
    from agents import coach
    assert coach.detect_codesign_intent("давайте попробуем") == "agreed"
    assert coach.detect_codesign_intent("я согласен") == "agreed"


def test_detect_codesign_agreed_en():
    from agents import coach
    assert coach.detect_codesign_intent("i'll try") == "agreed"
    assert coach.detect_codesign_intent("sounds good") == "agreed"


def test_detect_codesign_modified_overrides_agreed():
    from agents import coach
    # "but if" must register as modified, not agreed (modification check first)
    assert coach.detect_codesign_intent("but if i could do less reps") == "modified"


def test_detect_codesign_none_for_neutral():
    from agents import coach
    assert coach.detect_codesign_intent("i ate breakfast") is None
    assert coach.detect_codesign_intent("") is None


def test_detect_codesign_does_not_false_positive_on_question():
    from agents import coach
    # Question without commitment should not register
    assert coach.detect_codesign_intent("как часто я должен это делать?") is None
