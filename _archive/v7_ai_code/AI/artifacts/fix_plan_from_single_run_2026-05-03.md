# AIM/AI Fix Plan (from shared findings)

**Files:** 14 
**Cited lines:** 0 

## `AI/ai/run_self_diagnostic.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.

## `AI/tests/test_run_self_diagnostic.py`


**Suggestion:** Test quality: add pytest.raises for negative path; freeze datetime.now with monkeypatch.

## `distillation_tracker.py`


**Suggestion:** DB hardening: WAL + UNIQUE index + contextlib.closing(conn) + INSERT OR REPLACE — see CRIT-2 fix pattern.

## `eval_synthesiser.py`


**Suggestion:** L_VERIFIABILITY: route persisted spec through citation_guard.extract — reject if fabricated PMID/DOI present.

## `gap_detector.py`


**Suggestion:** Iterator safety: materialise surrender_list with list(...) before second pass — CRIT-3 generator-safe pattern.

## `reflexion_cluster.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.

## `run_self_diagnostic.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.

## `self_diagnostic.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.

## `test_distillation_tracker.py`


**Suggestion:** DB hardening: WAL + UNIQUE index + contextlib.closing(conn) + INSERT OR REPLACE — see CRIT-2 fix pattern.

## `test_eval_synthesiser.py`


**Suggestion:** L_VERIFIABILITY: route persisted spec through citation_guard.extract — reject if fabricated PMID/DOI present.

## `test_gap_detector.py`


**Suggestion:** Iterator safety: materialise surrender_list with list(...) before second pass — CRIT-3 generator-safe pattern.

## `test_reflexion_cluster.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.

## `test_run_self_diagnostic.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.

## `test_self_diagnostic.py`


**Suggestion:** Read the file at the cited line and decide if the model's concern is real before patching.
