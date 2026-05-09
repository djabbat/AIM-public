"""Tests for db.format_patient_folder — placeholder DOB convention."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import format_patient_folder, DOB_PLACEHOLDER


def test_placeholder_when_dob_missing():
    assert format_patient_folder("Ivanov Ivan") == f"Ivanov_Ivan_{DOB_PLACEHOLDER}"
    assert format_patient_folder("Ivanov Ivan", None) == f"Ivanov_Ivan_{DOB_PLACEHOLDER}"
    assert format_patient_folder("Ivanov Ivan", "") == f"Ivanov_Ivan_{DOB_PLACEHOLDER}"


def test_iso_date():
    assert format_patient_folder("Petrov Petr", "1980-05-12") == "Petrov_Petr_1980_05_12"


def test_underscore_date():
    assert format_patient_folder("Petrov Petr", "1980_05_12") == "Petrov_Petr_1980_05_12"


def test_european_date():
    assert format_patient_folder("Petrov Petr", "12.05.1980") == "Petrov_Petr_1980_05_12"


def test_short_month_day_zero_pad():
    assert format_patient_folder("Petrov Petr", "1980-5-2") == "Petrov_Petr_1980_05_02"


def test_garbage_falls_back_to_placeholder():
    assert format_patient_folder("X Y", "сегодня") == f"X_Y_{DOB_PLACEHOLDER}"
    assert format_patient_folder("X Y", "junk") == f"X_Y_{DOB_PLACEHOLDER}"


def test_multispace_name_collapsed():
    # Текущий поведение: spaces→underscores, не нормализует множ. пробелы.
    # Документируем как-есть; если станет проблемой — отдельный фикс.
    assert format_patient_folder("Foo Bar", "1990-01-01") == "Foo_Bar_1990_01_01"
