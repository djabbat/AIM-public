"""tests/test_kernel_extended.py — L_PRIVACY / L_CONSENT / L_VERIFIABILITY."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.kernel import (  # noqa: E402
    Decision, evaluate_extended,
)


def _d(action_type: str, payload: dict | None = None) -> Decision:
    return Decision(id="t", description="test", action_type=action_type,
                    payload=payload or {})


def test_privacy_blocks_patient_path_in_email():
    d = _d("email_send", {"body": "see /home/oem/Desktop/AIM/Patients/X/AI_LOG.md"})
    res = evaluate_extended(d)
    assert not res.privacy
    assert not res.passed


def test_privacy_blocks_phone_in_external_call():
    d = _d("external_api_call_with_data", {"data": "patient phone +995 555 185 161"})
    res = evaluate_extended(d)
    assert not res.privacy


def test_privacy_passes_with_consent_flag():
    d = _d("email_send", {"body": "see /home/oem/Desktop/AIM/Patients/X/AI_LOG.md"})
    res = evaluate_extended(d, context={"privacy_consent": True})
    assert res.privacy


def test_consent_blocks_unconfirmed_email():
    d = _d("email_send", {"body": "Hello world"})
    res = evaluate_extended(d)
    assert not res.consent


def test_consent_passes_when_confirmed():
    d = _d("email_send", {"body": "Hello world"})
    res = evaluate_extended(d, context={"user_confirmed": True})
    assert res.consent


def test_consent_blocks_git_push_public_unconfirmed():
    d = _d("git_push_public", {"branch": "main"})
    res = evaluate_extended(d)
    assert not res.consent


def test_consent_no_op_for_non_public_actions():
    d = _d("read_file", {"path": "/tmp/x"})
    res = evaluate_extended(d)
    assert res.consent  # n/a


@pytest.mark.network
def test_verifiability_passes_with_real_pmid():
    d = _d("emit_text", {"text": "See PMID: 28425478."})
    res = evaluate_extended(d)
    assert res.verifiability


@pytest.mark.network
def test_verifiability_fails_with_fake_pmid():
    d = _d("emit_text", {"text": "See fabricated work PMID: 999999999."})
    res = evaluate_extended(d)
    assert not res.verifiability


def test_verifiability_no_op_when_no_citations():
    d = _d("emit_text", {"text": "A plain sentence with no PMID or DOI."})
    res = evaluate_extended(d)
    assert res.verifiability
