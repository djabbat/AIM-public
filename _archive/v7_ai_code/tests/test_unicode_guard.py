"""tests/test_unicode_guard.py — UN1 (2026-05-03)."""
from __future__ import annotations

import pytest

from agents import unicode_guard as ug


# ── normalise ────────────────────────────────────────────────────


def test_normalise_nfc_composes():
    # 'е' + combining grave (U+0300) should compose into 'ѐ' (U+0450).
    s = "ѐ"   # equivalent to ѐ
    out = ug.normalise(s)
    assert out == "ѐ"


def test_normalise_strips_zero_width():
    s = "Hello​World"
    assert ug.normalise(s) == "HelloWorld"


def test_normalise_strips_bom():
    s = "﻿Jaba"
    assert ug.normalise(s) == "Jaba"


def test_normalise_strips_control_but_keeps_newline_tab():
    s = "Line1\nLine2\tdone"
    assert ug.normalise(s) == "Line1\nLine2\tdone"


def test_normalise_rejects_non_str():
    with pytest.raises(TypeError):
        ug.normalise(b"bytes")  # type: ignore


# ── _script ──────────────────────────────────────────────────────


def test_script_cyrillic():
    assert ug._script("И") == "cyrillic"
    assert ug._script("я") == "cyrillic"


def test_script_latin():
    assert ug._script("J") == "latin"


def test_script_georgian():
    assert ug._script("ჯ") == "georgian"


def test_script_non_letter():
    assert ug._script("1") is None
    assert ug._script(" ") is None


# ── mixed_scripts ───────────────────────────────────────────────


def test_mixed_pure_cyrillic():
    assert ug.mixed_scripts("Иванов") == {"cyrillic": 6}


def test_mixed_one_latin_lookalike():
    """'Иванoв' with a Latin 'o' — classic homograph attack.
    String breakdown: 'Иван' (4 cyr) + 'o' (1 lat) + 'в' (1 cyr) = 6 letters."""
    s = "Иванoв"
    out = ug.mixed_scripts(s)
    assert out["cyrillic"] == 5
    assert out["latin"] == 1


def test_mixed_strips_punctuation():
    out = ug.mixed_scripts("Иванов, 1981")
    assert out == {"cyrillic": 6}


# ── is_suspicious ───────────────────────────────────────────────


def test_suspicious_homograph_attack():
    s = "Иванoв"   # 1 latin / 4 cyrillic — minority < 30%
    assert ug.is_suspicious(s) is True


def test_suspicious_pure_script_safe():
    assert ug.is_suspicious("Иванов") is False
    assert ug.is_suspicious("Tkemaladze") is False


def test_suspicious_balanced_bilingual_safe():
    """A bilingual record like 'Tkemaladze (Ткемаладзе)' should NOT be
    flagged — neither script is a clear minority."""
    assert ug.is_suspicious("Tkemaladze Ткемаладзе") is False


# ── safe() ──────────────────────────────────────────────────────


def test_safe_clean_input():
    res = ug.safe("Tkemaladze")
    assert res.text == "Tkemaladze"
    assert res.warnings == []


def test_safe_strips_zero_width_and_warns():
    res = ug.safe("J​aba")
    assert res.text == "Jaba"
    assert any("invisible" in w for w in res.warnings)


def test_safe_mixed_script_warning():
    res = ug.safe("Иванoв")
    assert any("mixed scripts" in w for w in res.warnings)


def test_safe_allow_mixed_disables_warning():
    res = ug.safe("Иванoв", allow_mixed=True)
    assert not any("mixed scripts" in w for w in res.warnings)


def test_safe_normalises_combining_form():
    s = "ѐ"
    res = ug.safe(s)
    assert res.text == "ѐ"
    assert any("NFC" in w for w in res.warnings)


def test_safe_non_string_input():
    res = ug.safe(42)  # type: ignore
    assert res.text == ""
    assert res.warnings == ["non-string input dropped"]


# ── boundary cases ───────────────────────────────────────────────


def test_safe_empty_string():
    res = ug.safe("")
    assert res.text == ""
    assert res.warnings == []


def test_normalise_preserves_text_with_accents():
    """Régime → after NFC stays the same; no warnings expected from safe()."""
    res = ug.safe("Régime")
    assert res.text == "Régime"
    assert res.warnings == []
