# Architecture Decision Records

Design decisions for the Pilot Flight Agent pilot. Each record captures **context**, the **decision**, and **consequences** so future changes stay intentional.

Status key: **Accepted** — implemented and current.

---

## ADR-001 — Structured JSON planning

**Status:** Accepted

**Context:** Free-form LLM agents are hard to test, observe, and constrain. We need predictable step ordering (search before validate before book) and a stable contract for workers.

**Decision:** The planner returns a validated `Plan` JSON object (`goal`, `steps[]` with `worker`, `action`, `depends_on`) — not open-ended tool-calling prose. A mock planner (`PLANNER_USE_MOCK=true`) and an Anthropic-backed planner share the same schema.

**Consequences:**

- Plans are inspectable in `AgentState` and eval datasets
- Coordinator can enforce dependency order without parsing LLM text
- Invalid planner output fails fast with `PlanningError`
- LLM cost is bounded to planning/replanning, not every micro-step

**References:** `app/agent/planning.py`, `app/models/planning.py`

---

## ADR-002 — AgentState as single source of truth

**Status:** Accepted

**Context:** Multi-turn chat needs session memory: plan progress, flight results, pending approval, tool history, and budget counters. Scattering this across request locals or worker globals makes HITL and evals unreliable.

**Decision:** One `AgentState` Pydantic model per `conversation_id` holds all session data. HTTP handlers and `run_chat()` read/write through a `StateStore` interface. Production pilot uses `InMemoryStateStore`; the store is swappable without changing the loop.

**Consequences:**

- `/chat`, `/approvals/*`, and eval runners share consistent state
- Restarting the process clears sessions (acceptable for pilot/dev)
- Tests can inject or reset state via the store API

**References:** `app/agent/state.py`, `app/agent/loop.py`

---

## ADR-003 — Coordinator + domain workers

**Status:** Accepted

**Context:** Flight search and booking have different failure modes, permissions, and side effects. A monolithic “agent function” would mix orchestration with domain logic.

**Decision:** The **coordinator** selects plan steps, enforces READ vs WRITE gates, and delegates to **workers** (`FlightWorker`, `BookingWorker`) via a shared `execute(action, state)` contract. Workers call tools only through the tool adapter — never SQLite or HTTP directly from the coordinator.

**Consequences:**

- Workers are unit-testable in isolation
- New domains add a worker + plan actions without rewriting the loop
- Coordinator stays thin: no business rules about fares or bookings

**References:** `app/agent/coordinator.py`, `app/agent/workers/`

---

## ADR-004 — Tool adapter: direct vs MCP

**Status:** Accepted

**Context:** We want local development without subprocess overhead, but also a credible MCP integration path for demo and future tool hosting.

**Decision:** Workers depend on `ToolAdapter` (`DirectToolAdapter` | `McpToolAdapter`). Mode is selected by `TOOLS_MODE=direct|mcp`. MCP uses stdio subprocess servers under `app/mcp/servers/`; optional `MCP_USE_INPROCESS` supports in-process clients in tests.

**Consequences:**

- Same worker code runs in both modes
- Switching modes is configuration-only
- MCP adds latency and process management; direct mode is the default for dev

**References:** `app/tools/adapters/`, `app/mcp/client.py`, `app/config.py`

---

## ADR-005 — Human-in-the-loop for WRITE tools

**Status:** Accepted

**Context:** Booking creation mutates persistent state and may incur real cost. Autonomous WRITE without user consent is unacceptable for a pilot booking agent.

**Decision:** Tools are classified READ or WRITE in a central registry. READ actions (`search_flights`, `validate_options`) execute during `/chat`. WRITE actions (`create_booking`) **never** persist during `/chat`; the coordinator queues `pending_approval` and stops the turn. Persistence happens only after `POST /approvals/confirm`. Cancel clears approval without touching SQLite.

**Consequences:**

- Evals can assert “no unauthorized write” as a safety metric
- UX requires a two-step confirm flow for bookings
- Approval payload is structured and auditable before confirm

**References:** `app/guardrails/permissions.py`, `app/guardrails/approval.py`, `app/api/approvals.py`

---

## ADR-006 — Guardrails at the API boundary

**Status:** Accepted

**Context:** Prompt-only safety is bypassable once tools exist. Injection, rate abuse, and leaky responses must be blocked regardless of planner or worker behavior.

**Decision:** Run a fixed **inbound** chain before `run_chat()` and an **outbound** chain before every user-visible response: validation, injection heuristics, IP and per-conversation rate limits, output filtering, and PII redaction. Guards live in `app/guardrails/` and are orchestrated from `chain.py`, not embedded in workers.

**Consequences:**

- Security policy is centralized and testable (`tests/test_security.py`)
- Middleware handles IP limits; handlers handle conversation limits
- Logs apply PII redaction independently of API responses

**References:** `docs/guardrails.md`, `app/guardrails/chain.py`

---

## ADR-007 — Mock-by-default for planner and flights

**Status:** Accepted

**Context:** Contributors and CI should run the full stack without API keys, network flakiness, or LLM spend.

**Decision:** Default settings use `PLANNER_USE_MOCK=true` and `FLIGHT_API_USE_MOCK=true`. Mock planner emits a standard search → validate → book plan; mock flight service returns deterministic fixtures. Live Anthropic and Lufthansa paths are opt-in via environment variables.

**Consequences:**

- README quick start works with zero secrets
- Eval regression runs are reproducible
- Live-mode behavior must be validated separately before production use

**References:** `app/config.py`, `app/tools/flight_service.py`, `README.md`

---

## ADR-008 — Reflection loop with explicit outcomes

**Status:** Accepted

**Context:** Tool and worker failures need structured recovery instead of unbounded retries or silent stalls.

**Decision:** After each step, the evaluator returns one of: `CONTINUE`, `RETRY`, `REPLAN`, `ASK_USER`, or `FAIL`. Retries and replans are capped (`MAX_STEP_RETRIES`, `MAX_REPLAN_ATTEMPTS`). `ASK_USER` sets `pending_question` (e.g. price-preference clarification). Terminal failures map to user-safe messages, not stack traces.

**Consequences:**

- Loop behavior is deterministic enough for trajectory evals
- Price-intent heuristics support EN and SQ keywords
- Circuit-open and terminal worker errors surface as `FAIL`, not raw exceptions

**References:** `app/agent/reflection.py`, `app/agent/replanning.py`, `app/agent/loop.py`

---

## ADR-009 — SQLite for booking persistence

**Status:** Accepted

**Context:** The pilot needs durable bookings, audit history, and idempotent writes without operating a separate database service.

**Decision:** Store bookings in SQLite at `BOOKING_DB_PATH` (default `data/bookings.db`). Booking service handles create with audit logging. Schema and migrations stay minimal for the pilot scope.

**Consequences:**

- Single-file DB is easy to reset in dev and isolate per eval case
- Not suitable for high-concurrency multi-instance deployment without external DB
- File path must stay consistent when workers run in MCP subprocess mode

**References:** `app/tools/booking_store.py`, `app/tools/booking_audit.py`

---

## ADR-010 — Agent budget limits

**Status:** Accepted

**Context:** Adversarial input, planner loops, or flaky tools could otherwise consume unbounded LLM calls, tool calls, tokens, or wall time.

**Decision:** `AgentState` tracks iteration, LLM, tool, token, and latency usage against configurable ceilings (`MAX_ITERATIONS`, `MAX_LLM_CALLS`, `MAX_TOOL_CALLS`, `MAX_TOKENS`, `MAX_LATENCY_SECONDS`). The loop stops when a budget is exhausted.

**Consequences:**

- Predictable worst-case cost per conversation
- Eval runner can disable rate limits but still respects agent budgets
- Tuning budgets affects success rate on complex multi-turn flows

**References:** `app/agent/budget.py`, `app/config.py`

---

## ADR-011 — Idempotent booking writes

**Status:** Accepted

**Context:** Network retries, double-clicks on confirm, or client replays could create duplicate bookings for the same approval.

**Decision:** `create_booking` accepts an `idempotency_key` derived from the approval context. Repeated confirms with the same key return the original booking without a second insert.

**Consequences:**

- Confirm endpoint is safe to retry
- Keys must be stable for the lifetime of a pending approval
- Tests cover duplicate confirm behavior

**References:** `app/core/idempotency.py`, `app/tools/booking_service.py`, `app/api/approvals.py`

---

## ADR-012 — HTTP eval runner with isolated state

**Status:** Accepted

**Context:** Unit tests alone do not prove end-to-end behavior across guards, loop, HITL, and persistence. Eval cases need repeatable runs without cross-case pollution.

**Decision:** `evals/runners/http_runner.py` drives the live FastAPI app via HTTP. Each case gets its own SQLite file (`{case.id}.db`), syncs `BOOKING_DB_PATH`, and disables rate limits for throughput. Metrics score outcome, trajectory, and safety per case; regression gate enforces minimum scores on a curated set.

**Consequences:**

- Evals catch integration regressions that mocks miss
- Slower than unit tests; intended for CI nightly or pre-release
- Case isolation depends on per-case DB paths and fresh conversation IDs

**References:** `evals/runners/http_runner.py`, `evals/regression.py`, `evals/metrics/scoring.py`

---

## ADR-013 — Thin HTTP layer

**Status:** Accepted

**Context:** FastAPI routes should not duplicate agent logic, guard rules, or approval semantics.

**Decision:** Routers in `app/api/` validate HTTP input, run guard chains, call `run_chat()` or approval helpers, and map domain errors to status codes. Business logic remains in `app/agent/`, `app/tools/`, and `app/guardrails/`.

**Consequences:**

- OpenAPI surface stays small and stable
- Same agent core could be fronted by CLI or queue workers later
- Integration tests target `/chat` as the primary contract

**References:** `app/api/chat.py`, `app/api/approvals.py`, `app/main.py`

---

## Deferred / out of scope (pilot)

| Topic | Rationale |
|-------|-----------|
| Redis / Postgres session store | In-memory store sufficient for pilot; ADR-002 keeps interface swappable |
| OAuth / user accounts | Single-tenant demo; rate limits use IP + conversation ID |
| Autonomous WRITE after risk scoring | Explicit HITL chosen for trust and auditability (ADR-005) |
| Multi-agent planner swarm | Single planner + workers meets scope and eval stability |

---

## Related docs

- [architecture.md](architecture.md) — system structure and diagrams
- [guardrails.md](guardrails.md) — guard chain detail
- [threat-model.md](threat-model.md) — threats and mitigations
- [../ENGINEERING_LOG.md](../ENGINEERING_LOG.md) — implementation history
