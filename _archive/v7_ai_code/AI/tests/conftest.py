"""Shared fixtures for AI/ subproject tests.

The AI subproject is independent from `agents/` for testing purposes —
we don't share the parent tests/conftest.py's session fixtures (e.g.
PATIENTS_DIR isolation) because AI tests should never touch Patients/.

Phase 9 (2026-05-07) cleanup: 110 tests that monkey-patched internals
removed by Rust-binary shimization were physically deleted (4 whole
files + 50 functions). Regression gate is now meaningful again.
"""
import sys
from pathlib import Path

# Make AIM importable when pytest is invoked from AIM/ root.
_AIM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_AIM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AIM_ROOT))
