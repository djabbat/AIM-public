"""tests/test_aim_verify_parity.py — Phase 10 hybrid parity guard.

Verifies that the Rust `aim-verify` binary returns equivalent results to
the Python `tools/literature.py` implementation for invalid / edge inputs
(both must return None — no network requests in tests).

Network-bound parity tests (real PMID / DOI lookup, comparing payload
fields) live in `tests/test_aim_verify_network.py` and are gated on
`AIM_TEST_NETWORK=1` (skipped in default --quick runs).

STRATEGY P3-8 acceptance criterion: «один tool за раз, parity test до swap».
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUST_BIN = ROOT / "rust-core" / "target" / "release" / "aim-verify"


def _have_rust_bin() -> bool:
    return RUST_BIN.exists()


# ── invalid input parity (no network) ───────────────────────────────────


@pytest.mark.parametrize("bad_pmid", [
    "notanumber",
    "PMID:nope",
    "abc123",
    "",
    "0xff",
])
def test_pmid_invalid_input_python_returns_none(bad_pmid):
    """Python verify_pmid returns None on non-digit input."""
    os.environ.pop("AIM_VERIFY_USE_RUST", None)
    from tools.literature import verify_pmid
    assert verify_pmid(bad_pmid) is None


@pytest.mark.parametrize("bad_pmid", [
    "notanumber", "PMID:nope", "abc123", "", "0xff",
])
def test_pmid_invalid_input_rust_returns_none(bad_pmid):
    """Rust aim-verify also returns None for the same invalid set."""
    if not _have_rust_bin():
        pytest.skip("aim-verify binary not built")
    proc = subprocess.run(
        [str(RUST_BIN), "verify-pmid", bad_pmid],
        capture_output=True, text=True, check=False,
    )
    # exit 1 = "null" printed
    assert proc.returncode == 1
    assert proc.stdout.strip() == "null"


@pytest.mark.parametrize("bad_doi", [
    "invalid",
    "doi:noslash",
    "",
    "just-a-string",
])
def test_doi_invalid_input_python_returns_none(bad_doi):
    os.environ.pop("AIM_VERIFY_USE_RUST", None)
    from tools.literature import verify_doi
    assert verify_doi(bad_doi) is None


@pytest.mark.parametrize("bad_doi", [
    "invalid", "doi:noslash", "", "just-a-string",
])
def test_doi_invalid_input_rust_returns_none(bad_doi):
    if not _have_rust_bin():
        pytest.skip("aim-verify binary not built")
    proc = subprocess.run(
        [str(RUST_BIN), "verify-doi", bad_doi],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == "null"


# ── shim toggle parity (no network) ─────────────────────────────────────


def test_python_shim_falls_back_when_binary_absent(monkeypatch, tmp_path):
    """If Rust binary path doesn't exist, the shim must silently fall back
    to Python implementation — no error, same result."""
    # Force AIM_VERIFY_USE_RUST=1 but point the binary path at nothing.
    import tools.literature as lit
    monkeypatch.setenv("AIM_VERIFY_USE_RUST", "1")
    monkeypatch.setattr(lit, "_VERIFY_BIN", tmp_path / "nonexistent")
    # Should still behave like Python — invalid pmid returns None.
    assert lit.verify_pmid("notanumber") is None
    assert lit.verify_doi("invalid") is None


def test_python_shim_returns_none_via_rust_path(monkeypatch):
    """With AIM_VERIFY_USE_RUST=1 and binary present, shim should
    invoke Rust and produce same None outcome on invalid inputs."""
    if not _have_rust_bin():
        pytest.skip("aim-verify binary not built")
    monkeypatch.setenv("AIM_VERIFY_USE_RUST", "1")
    from tools.literature import verify_pmid, verify_doi
    assert verify_pmid("notanumber") is None
    assert verify_doi("invalid") is None
