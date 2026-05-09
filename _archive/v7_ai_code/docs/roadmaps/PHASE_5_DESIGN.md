# Phase 5 — `llm.py` → `aim-llm` Rust port (design, 2026-05-07)

## Status

- **`aim-llm` Rust crate** (1048 LoC: 620 main + 428 providers) — already
 ~80% built. HTTP service on port 8770. Verified to compile + boot
 cleanly (smoke 2026-05-07).
- **5 providers** (DeepSeek, Groq, Anthropic, Gemini, Ollama) implemented
 with `reqwest` async HTTP. All `is_ready`-gated by env vars.
- **5 tier chains** in `router::tier_chain` matching Python `llm.py` tiers
 (`critical / deep / long / fast / default`).
- **Python `llm.py`** — 1017 LoC. Uses OpenAI client wrapper, has
 TokenBucket rate-limiter, CircuitBreaker, smart_routing integration,
 ensemble + critique helpers, multilang translation tooling.

## Architecture decision

Two paths:

**A. HTTP-service** (preferred). aim-llm runs as systemd unit on port
8770. Python `llm.py` becomes a thin `requests`/`httpx` client. CB +
rate-limit move to Rust side. Multi-process cooperation natural (any
agent can call the service). Performance: ~1ms RTT on localhost.

**B. Subprocess CLI** (Phase 8 pattern). Per-call subprocess spawn of
`aim-llm chat <prompt>`. Simpler — no service to manage. But ~50-100ms
RTT per call (process startup + Tokio runtime init), unacceptable for
hot path (every agent step does at least one LLM call).

**Decision: A**. Same architecture pattern as DiffDiagnosis
(`:8765`) and SSA (`:8766`) — those are HTTP services already.
Phoenix LiveViews already shell out to other Rust binaries; switching
to HTTP for LLM router is consistent.

## Migration plan

### Phase 5a — service hardening (this sprint)
1. Verify each provider against a real API call (need keys in service
 env). Spike: groq quick test.
2. Add health probes for each provider (`is_ready` already exists,
 but doesn't probe). Add lazy probe with 30s TTL.
3. Add per-provider rate-limit (TokenBucket equivalent). Currently
 absent in Rust crate.
4. Add per-provider circuit breaker. Currently absent.
5. Persistence-back cost ledger (`aim-cost-ledger` already a crate).
6. systemd unit file `aim-llm.service` with `EnvironmentFile=~/.aim_env`.

### Phase 5b — Python shim (after 5a)
7. New module `agents/llm_client.py` — thin HTTP client wrapping
 aim-llm endpoints. Same public API as `llm.py`:
 `ask(prompt) / ask_fast(prompt) / ask_deep(prompt) / ask_long(prompt) / ask_critical(prompt)`.
8. Opt-in via env: `AIM_LLM_HTTP_URL=http://127.0.0.1:8770` →
 `llm.py` delegates to `llm_client`. Else fall back to existing
 Python implementation (1017 LoC stays).
9. Side-by-side validator: prompt N=50 across 5 tiers, compare HTTP
 vs Python responses. Track latency + cost parity.
10. After 30 days clean → remove Python provider implementations,
 keep `llm.py` as a thin shim (~150 LoC).

### Phase 5c — unblock dependent ports
11. `agents/resilient_llm.py` — already wraps llm.ask. After llm
 is HTTP-shim, retry/checkpoint logic stays Python (it's 200 LoC
 and not LLM-specific). Could move to Rust later via aim-resilient-llm.
12. `agents/graph.py` — same; the LangGraph state machine + node
 functions (planner/executor/reviewer) call llm.ask_deep. After
 llm is shim, graph.py stays Python orchestration; nodes get the
 same speed regardless.
13. `agents/reflexion.py::on_failure` — calls `llm.ask_fast`. Becomes
 full shim after llm.py shim lands.

## Risks

- **Service availability**: if aim-llm is down, llm.py needs a
 fallback path. Two options:
 (a) fall back to Python implementation (keep 1017 LoC alive).
 (b) circuit-break locally and surface error to caller.
 → Choose (a) initially; deprecate after 30 days uptime.
- **Cost ledger duplication**: Python `cost_monitor.py` already logs
 per-call costs. Rust `aim-cost-ledger` is a separate ledger. Need
 unified view OR explicit "this row from Python, that from Rust".
- **Test parity**: existing `tests/test_llm.py` (if any) uses Python
 mocks heavily. HTTP shim version needs new mocks (httpx_mock or
 responses lib). Adds ~200 LoC test code.
- **Multi-user**: hub/node mode; the aim-llm service is per-node.
 For hub-only deployments, llm.py needs node-aware routing. Already
 exists in `hub_client.py`; integration TBD.

## Effort estimate

- Phase 5a (service hardening): ~3 days × 1 dev
- Phase 5b (Python shim + parity): ~2 days
- Phase 5c (unblock 3 dependents): already-shim modules, ~0.5 days each
- **Total Phase 5: ~6 days, 2 sprints**

## Today's deliverable (2026-05-07)

Smoke verification + this design doc. Not modifying `llm.py` to avoid
breaking 5 production agents (doctor, labs, chat, generalist,
medical_system) without integration testing. Phase 5 work continues in
next session(s) per the order Phase 5 → Phase 4 → Phoenix integration.

## Foundation laid this session

- Confirmed `aim-llm` crate compiles with `cargo build -p aim-llm --release`
- Confirmed service binds port (e.g., `AIM_LLM_PORT=8788./aim-llm`)
- Confirmed `/health` + `/v1/providers` endpoints respond
- Confirmed Ollama provider auto-loads (other 4 require API keys)
- Confirmed tier chains exist in Rust router and match Python contract
