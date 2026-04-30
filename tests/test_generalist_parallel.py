"""tests/test_generalist_parallel.py — parallel tool calls + sub-agent fan-out
+ speculative prefetch + ensemble adjudication.

Network-touching parts are skipped with a real-key fallback;
core mechanics are tested with monkeypatched LLM and tools.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Parallel tool execution ────────────────────────────────────────────────


def test_run_tools_parallel_runs_concurrently():
    from agents.generalist import _run_tools_parallel, register_tool, _TOOLS

    @register_tool("test_sleep", "sleep tool", {"ms": "int"})
    def _sleep(ms: int):
        time.sleep(ms / 1000.0)
        return f"slept {ms}"

    try:
        calls = [{"tool": "test_sleep", "args": {"ms": 200}} for _ in range(4)]
        t0 = time.time()
        out = _run_tools_parallel(calls, max_workers=4)
        elapsed = time.time() - t0
        # 4×200ms = 800ms sequential; concurrent should be ~200-400ms
        assert elapsed < 0.6, f"parallel ran sequentially? {elapsed:.2f}s"
        assert all("slept 200" in r for r in out)
    finally:
        _TOOLS.pop("test_sleep", None)


def test_action_parser_handles_parallel():
    from agents.generalist import _parse_action
    raw = '{"parallel": [{"tool": "a", "args": {}}, {"tool": "b", "args": {}}]}'
    a = _parse_action(raw)
    assert isinstance(a.get("parallel"), list) and len(a["parallel"]) == 2


def test_action_parser_handles_single():
    from agents.generalist import _parse_action
    a = _parse_action('{"tool": "x", "args": {"k": 1}}')
    assert a.get("tool") == "x"


def test_action_parser_handles_final():
    from agents.generalist import _parse_action
    a = _parse_action('{"final": "the answer"}')
    assert a.get("final") == "the answer"


def test_action_parser_extracts_from_fenced_block():
    from agents.generalist import _parse_action
    raw = "Here is my plan:\n```json\n{\"tool\": \"y\", \"args\": {}}\n```\n"
    assert _parse_action(raw).get("tool") == "y"


# ── Speculative prefetch ──────────────────────────────────────────────────


def test_prefetcher_caches_predicted_paths(tmp_path):
    from agents.speculative_prefetch import Prefetcher
    f = tmp_path / "demo.txt"
    f.write_text("hello world", encoding="utf-8")
    pf = Prefetcher()
    history = [{"role": "user", "content": f"please read {f.absolute()}"}]
    pf.observe(history)
    # give background a moment
    time.sleep(0.3)
    cached = pf.consume("read_file", {"path": str(f.absolute()),
                                       "offset": 0, "limit": 200},
                        wait=2.0)
    pf.shutdown()
    assert cached is not None and "hello world" in cached


def test_prefetcher_no_paths_no_work():
    from agents.speculative_prefetch import Prefetcher
    pf = Prefetcher()
    pf.observe([{"role": "user", "content": "no paths here"}])
    assert pf.consume("read_file", {"path": "/nonexistent",
                                     "offset": 0, "limit": 200},
                       wait=0.05) is None
    pf.shutdown()


# ── Ensemble agreement scoring ─────────────────────────────────────────────


def test_agreement_high_for_identical_answers():
    from agents.ensemble import _agreement_score
    answers = [
        "The sky is blue because of Rayleigh scattering of sunlight.",
        "The sky is blue because of Rayleigh scattering of sunlight.",
    ]
    assert _agreement_score(answers) > 0.9


def test_agreement_low_for_unrelated_answers():
    from agents.ensemble import _agreement_score
    answers = [
        "The sky is blue because of Rayleigh scattering.",
        "Photosynthesis converts CO2 to glucose using chlorophyll.",
    ]
    assert _agreement_score(answers) < 0.2


def test_is_critical_heuristic():
    from agents.ensemble import is_critical
    assert is_critical("Should I sign this contract today?")
    assert is_critical("дозы препарата X для пациента")
    assert not is_critical("what's 2+2?")


# ── Vision OCR fallback path (no network) ──────────────────────────────────


def test_vision_pdf_to_png(tmp_path):
    """Render a PDF page to PNG via pymupdf — no network involved."""
    pytest.importorskip("pymupdf")
    import pymupdf
    pdf_path = tmp_path / "x.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "test")
    doc.save(str(pdf_path))
    doc.close()
    from tools.vision import pdf_page_to_png
    out = pdf_page_to_png(pdf_path, page=0)
    assert out.exists() and out.stat().st_size > 100
