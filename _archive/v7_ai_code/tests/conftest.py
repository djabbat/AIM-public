"""Pytest: глобальная изоляция Patients/ от тестовых side-effects.

Тесты используют patient_id-строки ("S01", "T01", "LAB_1", "TEST_Patient_*")
которые kernel.log_decision() записывает как папки в PATIENTS_DIR.
Без этого conftest каждый pytest run загрязнял реальный Patients/.

Здесь PATIENTS_DIR временно переключается на tests/_runtime_fixtures/
на всё время сессии. Артефакты тестов больше не попадают в production.

Также (G2 sandbox, 2026-05-02): pytest tmp_path лежит под /tmp, что
вне дефолтного AIM_GENERALIST_ROOT (~/Desktop). Чтобы существующие
тесты не падали с ERROR:PERMISSION при write_file/edit_file/apply_patch
в tmp_path, мы выставляем AIM_GENERALIST_ROOT=/tmp на всё время сессии.
Тесты, которые специально проверяют sandbox, переопределяют переменную
через monkeypatch.
"""
import os
from pathlib import Path
import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_patients_dir(tmp_path_factory):
    """Глобальный monkey-patch PATIENTS_DIR на сессию pytest."""
    runtime = Path(__file__).parent / "_runtime_fixtures"
    runtime.mkdir(parents=True, exist_ok=True)

    import config
    original = config.PATIENTS_DIR
    config.PATIENTS_DIR = runtime

    # Также переопределить в модулях, которые импортировали PATIENTS_DIR by-value
    import agents.kernel as _kernel
    import agents.patient_memory as _pm
    _kernel.PATIENTS_DIR = runtime
    _pm.PATIENTS_DIR = runtime

    yield runtime

    config.PATIENTS_DIR = original
    _kernel.PATIENTS_DIR = original
    _pm.PATIENTS_DIR = original


@pytest.fixture(autouse=True, scope="session")
def _allow_tmp_writes_for_tests():
    """G2 sandbox: extend AIM_GENERALIST_ROOT to cover /tmp during tests."""
    prev = os.environ.get("AIM_GENERALIST_ROOT")
    os.environ["AIM_GENERALIST_ROOT"] = "/tmp"
    yield
    if prev is None:
        os.environ.pop("AIM_GENERALIST_ROOT", None)
    else:
        os.environ["AIM_GENERALIST_ROOT"] = prev
