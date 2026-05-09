"""tests/test_patient_dedup.py — DD1 (2026-05-03)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PATIENTS_DIR", str(tmp_path))
    import importlib, sys
    if "agents.patient_dedup" in sys.modules:
        importlib.reload(sys.modules["agents.patient_dedup"])
    return tmp_path


# ── _normalise_name ──────────────────────────────────────────────


def test_normalise_lowercases_and_strips(isolated):
    from agents.patient_dedup import _normalise_name
    assert _normalise_name("Феридзе") == "феридзе"
    assert _normalise_name("Tkemaladze!") == "tkemaladze"


def test_normalise_maps_homograph(isolated):
    """'Иванов' (pure cyrillic) and 'Иванoв' (Latin 'o') should match."""
    from agents.patient_dedup import _normalise_name
    pure = _normalise_name("Иванов")
    homograph = _normalise_name("Иванoв")
    assert pure == homograph


# ── fingerprint ─────────────────────────────────────────────────


def test_fingerprint_with_dob(isolated):
    from agents.patient_dedup import fingerprint
    canon, name_only, dob = fingerprint("Феридзе_Майя_1981_12_20")
    assert dob == "1981-12-20"
    assert canon.endswith("|1981-12-20")
    assert name_only.endswith("|")


def test_fingerprint_without_dob(isolated):
    from agents.patient_dedup import fingerprint
    canon, name_only, dob = fingerprint("Some_Patient_no_dob_here")
    assert dob is None


def test_fingerprint_homograph_collapses(isolated):
    from agents.patient_dedup import fingerprint
    a = fingerprint("Иванов_Иван_1990_01_01")
    b = fingerprint("Иванoв_Иван_1990_01_01")
    assert a[0] == b[0]


# ── duplicates() ────────────────────────────────────────────────


def test_no_dup_when_unique(isolated):
    (isolated / "Феридзе_Майя_1981_12_20").mkdir()
    (isolated / "Иванов_Иван_1990_01_01").mkdir()
    from agents.patient_dedup import duplicates
    assert duplicates() == []


def test_strong_match_same_dob_homograph_name(isolated):
    (isolated / "Иванов_Иван_1990_01_01").mkdir()
    (isolated / "Иванoв_Иван_1990_01_01").mkdir()
    from agents.patient_dedup import duplicates
    out = duplicates()
    assert len(out) == 1
    assert out[0].n_folders == 2
    assert out[0].likely_dob == "1990-01-01"


def test_soft_match_one_sentinel_dob(isolated):
    """Same name, one folder has sentinel 2000_01_01 — likely same patient."""
    (isolated / "Феридзе_Майя_1981_12_20").mkdir()
    (isolated / "Феридзе_Майя_2000_01_01").mkdir()
    from agents.patient_dedup import duplicates
    out = duplicates()
    assert len(out) == 1
    assert out[0].n_folders == 2


def test_no_match_different_known_dobs(isolated):
    """Same name, two distinct real DOBs — different patients."""
    (isolated / "Иванов_Иван_1981_01_01").mkdir()
    (isolated / "Иванов_Иван_1995_06_15").mkdir()
    from agents.patient_dedup import duplicates
    assert duplicates() == []


def test_skips_inbox(isolated):
    (isolated / "INBOX").mkdir()
    (isolated / "X_Y_2000_01_01").mkdir()
    from agents.patient_dedup import duplicates
    # No duplicates expected, INBOX excluded.
    assert duplicates() == []


def test_skipped_when_no_patients_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PATIENTS_DIR", str(tmp_path / "no-such"))
    import importlib, agents.patient_dedup as pd
    importlib.reload(pd)
    assert pd.duplicates() == []


# ── summary ──────────────────────────────────────────────────────


def test_summary_calm_when_clean(isolated):
    from agents.patient_dedup import summary
    assert "no duplicate" in summary()


def test_summary_lists_clusters(isolated):
    (isolated / "Иванов_Иван_1990_01_01").mkdir()
    (isolated / "Иванoв_Иван_1990_01_01").mkdir()
    from agents.patient_dedup import summary
    s = summary()
    assert "Duplicate patient folders" in s
    assert "Иванов_Иван_1990_01_01" in s
    assert "Иванoв_Иван_1990_01_01" in s
