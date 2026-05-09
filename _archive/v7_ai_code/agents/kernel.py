"""
agents/kernel.py — thin shim re-exporting `aim_kernel` Rust C-extension (HW1, 2026-05-07).

The canonical implementation lives in `rust-core/crates/aim-kernel-py/src/lib.rs`
(PyO3 wrapper around `aim-kernel` pure Rust crate). Build: `maturin develop`
in venv from the `aim-kernel-py` crate dir.

Backward-compatible — every name previously importable from
`agents.kernel` is re-exported here, so existing 7 production agents +
80 test cases work unchanged.

Legacy Python implementation preserved as `agents/kernel_legacy.py` for
side-by-side validator + rollback (`AIM_USE_LEGACY_KERNEL=1`).
"""
from __future__ import annotations

import os

if os.environ.get("AIM_USE_LEGACY_KERNEL") == "1":
    # Rollback path — use Python implementation that was authoritative
    # before the Rust port. Keeps the option of A/B comparison.
    from agents.kernel_legacy import *  # noqa: F401,F403
else:
    # Default — Rust kernel via PyO3.
    from aim_kernel import (  # noqa: F401
        Decision,
        LawsResult,
        ScoringResult,
        Scored,
        OverrideContext,
        KernelWeights,
        KernelViolation,
        evaluate_l0,
        evaluate_l1,
        evaluate_l2,
        evaluate_l3,
        evaluate_laws,
        evaluate_l_privacy,
        impedance_checklist,
        impedance,
        expected_impedance_after,
        instant_c,
        phi_ze_path_integral,
        ethics_ze_score,
        ethics_autonomy,
        ethics_beneficence,
        ethics_nonmaleficence,
        ethics_justice,
        ethics_composite,
        score_decision,
        decide,
        format_compact,
        format_verbose,
        needs_clarification,
        log_decision,
    )
    # ── verifiability + extended + consent: keep Python ──────────────────
    # Rust core has the trait-based hooks but the actual integrations live
    # in Python:
    #   • `tools.literature.enforce_citations` — PubMed/Crossref verification
    #   • `agents.permission.broker` — interactive TUI / Telegram consent
    # When those are ported to Rust, these can move too.
    from agents.kernel_legacy import (  # noqa: F401
        ExtendedLawsResult,
        evaluate_l_verifiability,
        evaluate_l_consent,
        evaluate_extended,
        evaluate_l_agency,
        AGENCY_ACTIONS,
    )
