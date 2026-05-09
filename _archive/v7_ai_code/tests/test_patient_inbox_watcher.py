"""tests/test_patient_inbox_watcher.py — PA1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PATIENTS_DIR", str(tmp_path / "Patients"))
    (tmp_path / "Patients" / "INBOX").mkdir(parents=True)
    import importlib, sys
    if "agents.patient_inbox_watcher" in sys.modules:
        importlib.reload(sys.modules["agents.patient_inbox_watcher"])
    return tmp_path


# ── DOB normaliser ───────────────────────────────────────────────


def test_normalise_dob_full_year(isolated):
    from agents.patient_inbox_watcher import _normalise_dob
    assert _normalise_dob(20, 12, 1981) == dt.date(1981, 12, 20)


def test_normalise_dob_two_digit_year_old(isolated):
    """81 → 1981; 25 → 2025."""
    from agents.patient_inbox_watcher import _normalise_dob
    assert _normalise_dob(20, 12, 81) == dt.date(1981, 12, 20)
    assert _normalise_dob(20, 12, 5) == dt.date(2005, 12, 20)


def test_normalise_dob_invalid(isolated):
    from agents.patient_inbox_watcher import _normalise_dob
    assert _normalise_dob(35, 13, 2025) is None


# ── candidates ───────────────────────────────────────────────────


def test_candidates_picks_only_ocr_extensions(isolated):
    inbox = isolated / "Patients" / "INBOX"
    (inbox / "lab.pdf").write_bytes(b"%PDF-1.4")
    (inbox / "scan.jpg").write_bytes(b"\xff\xd8\xff")
    (inbox / "notes.txt").write_text("text-only")
    (inbox / "subdir").mkdir()
    from agents.patient_inbox_watcher import candidates
    names = sorted(p.name for p in candidates())
    assert names == ["lab.pdf", "scan.jpg"]


def test_candidates_empty_inbox(isolated):
    from agents.patient_inbox_watcher import candidates
    assert candidates() == []


# ── classification ───────────────────────────────────────────────


def test_classify_extracts_name_and_dob(isolated, monkeypatch):
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Пациент Феридзе Майя\nДата рождения: 20.12.1981\nResults follow.")
    cls = piw.classify(isolated / "x.pdf")
    assert cls.surname == "Феридзе"
    assert cls.name == "Майя"
    assert cls.dob == dt.date(1981, 12, 20)


def test_classify_falls_back_to_generic_date(isolated, monkeypatch):
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Беридзе Кетеван  03.05.1990 — анализ крови")
    cls = piw.classify(isolated / "x.pdf")
    assert cls.surname == "Беридзе"
    assert cls.dob == dt.date(1990, 5, 3)


def test_classify_dob_missing(isolated, monkeypatch):
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Пациент Иванов Иван — общая жалоба")
    cls = piw.classify(isolated / "x.pdf")
    assert cls.surname == "Иванов"
    assert cls.dob is None


def test_classify_ocr_failed(isolated, monkeypatch):
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text", lambda p: None)
    assert piw.classify(isolated / "x.pdf") is None


# ── folder routing ──────────────────────────────────────────────


def test_patient_folder_with_known_dob(isolated):
    from agents.patient_inbox_watcher import _patient_folder, Classification
    c = Classification(surname="Феридзе", name="Майя",
                        dob=dt.date(1981, 12, 20), text_excerpt="")
    folder = _patient_folder(c)
    assert folder.name == "Феридзе_Майя_1981_12_20"


def test_patient_folder_sentinel_dob(isolated):
    from agents.patient_inbox_watcher import _patient_folder, Classification
    c = Classification(surname="Иванов", name="Иван",
                        dob=None, text_excerpt="")
    folder = _patient_folder(c)
    assert folder.name == "Иванов_Иван_2000_01_01"


# ── process_one / process_inbox ─────────────────────────────────


def test_process_one_ambiguous_keeps_file(isolated, monkeypatch):
    inbox = isolated / "Patients" / "INBOX"
    f = inbox / "scan.jpg"
    f.write_bytes(b"\xff\xd8\xff")
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text", lambda p: "no patient name in this file")
    res = piw.process_one(f, dry_run=False)
    assert res.reason == "ambiguous"
    assert f.exists()


def test_process_one_dry_run_does_not_move(isolated, monkeypatch):
    inbox = isolated / "Patients" / "INBOX"
    f = inbox / "lab.pdf"
    f.write_bytes(b"%PDF-1.4")
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Феридзе Майя\nДР: 20.12.1981")
    res = piw.process_one(f, dry_run=True)
    assert res.reason.startswith("moved (dry-run")
    assert f.exists()


def test_process_one_actually_moves(isolated, monkeypatch):
    inbox = isolated / "Patients" / "INBOX"
    f = inbox / "lab.pdf"
    f.write_bytes(b"%PDF-1.4")
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Феридзе Майя\nДР: 20.12.1981")
    res = piw.process_one(f, dry_run=False)
    assert res.reason == "moved"
    assert not f.exists()
    target = isolated / "Patients" / "Феридзе_Майя_1981_12_20" / "lab.pdf"
    assert target.exists()


def test_process_appends_log(isolated, monkeypatch):
    inbox = isolated / "Patients" / "INBOX"
    f = inbox / "lab.pdf"
    f.write_bytes(b"%PDF-1.4")
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Феридзе Майя\nДР: 20.12.1981")
    piw.process_one(f, dry_run=False)
    log = isolated / "Patients" / "Феридзе_Майя_1981_12_20" / "AI_LOG.md"
    assert log.exists()
    text = log.read_text()
    assert "intake:" in text
    assert "lab.pdf" in text
    assert "1981-12-20" in text


def test_process_inbox_iterates(isolated, monkeypatch):
    inbox = isolated / "Patients" / "INBOX"
    (inbox / "a.pdf").write_bytes(b"%PDF-1.4")
    (inbox / "b.jpg").write_bytes(b"\xff\xd8\xff")
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text", lambda p: "no name")
    out = piw.process_inbox(dry_run=True)
    assert len(out) == 2
    assert all(a.reason == "ambiguous" for a in out)


def test_process_one_preserves_existing_target(isolated, monkeypatch):
    """Don't clobber a file already in the patient folder."""
    inbox = isolated / "Patients" / "INBOX"
    folder = isolated / "Patients" / "Феридзе_Майя_1981_12_20"
    folder.mkdir(parents=True)
    (folder / "lab.pdf").write_bytes(b"existing")
    f = inbox / "lab.pdf"
    f.write_bytes(b"%PDF-1.4")
    from agents import patient_inbox_watcher as piw
    monkeypatch.setattr(piw, "_ocr_text",
                        lambda p: "Феридзе Майя\nДР: 20.12.1981")
    res = piw.process_one(f, dry_run=False)
    assert res.reason == "moved"
    # Existing file untouched.
    assert (folder / "lab.pdf").read_bytes() == b"existing"
    # New file landed with a stamp suffix.
    matched = sorted(p.name for p in folder.iterdir())
    assert any(name != "lab.pdf" and name != "AI_LOG.md"
                for name in matched)


# ── unknown file ─────────────────────────────────────────────────


def test_process_one_missing_file(isolated):
    from agents.patient_inbox_watcher import process_one
    res = process_one(isolated / "ghost.pdf", dry_run=True)
    assert res.reason == "not_found"
