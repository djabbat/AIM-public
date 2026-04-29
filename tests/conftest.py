"""Pytest: глобальная изоляция Patients/ от тестовых side-effects.

Тесты используют patient_id-строки ("S01", "T01", "LAB_1", "TEST_Patient_*")
которые kernel.log_decision() записывает как папки в PATIENTS_DIR.
Без этого conftest каждый pytest run загрязнял реальный Patients/.

Здесь PATIENTS_DIR временно переключается на tests/_runtime_fixtures/
на всё время сессии. Артефакты тестов больше не попадают в production.
"""
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
