# Engineering Log

Incremental build diary for **Pilot Flight Agent** — what was built at each step, where it lives, and how it was verified. Use this alongside [README.md](README.md) (how to run) and [docs/](docs/) (design and security).

## At a glance

| Metric | Value |
|--------|-------|
| Phases complete | 0–12 ✅ · 13 partial (13.1–13.6 ✅) |
| Test suite | **452** pytest tests |
| Eval cases | 16 across 5 datasets + 10-case regression gate |
| Default mode | Mock planner + mock flights (no API keys) |
| API surface | `GET /health` · `POST /chat` · `GET/POST /approvals/*` |

## Phase index

| Phase | Theme | Status |
|-------|-------|--------|
| 0 | Setup & skeleton | ✅ |
| 1 | AgentState & loop | ✅ |
| 2 | Structured planning | ✅ |
| 3 | Evaluator & replanning | ✅ |
| 4 | Coordinator & workers | ✅ |
| 5 | Direct tools (flight API + SQLite) | ✅ |
| 6 | MCP layer | ✅ |
| 7 | Human-in-the-loop | ✅ |
| 8 | Security guardrails | ✅ |
| 9 | Reliability | ✅ |
| 10 | Observability | ✅ |
| 11 | Tests (unit & integration) | ✅ |
| 12 | Agent evaluations | ✅ |
| 13 | Docs & production polish | 🔄 13.6 ✅ · 13.7 optional |

## Documentation map

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Quick start, env, curl examples |
| [docs/architecture.md](docs/architecture.md) | System design and diagrams |
| [docs/decisions.md](docs/decisions.md) | Architecture decision records |
| [docs/guardrails.md](docs/guardrails.md) | Guard chain order and config |
| [docs/threat-model.md](docs/threat-model.md) | Threats, mitigations, residual risks |

---

### 0.1 — Folder structure ✅
- Created full project layout per system design
- Packages: `app/`, `tests/`, `evals/`, `docs/`
- Module placeholders with docstrings only (no implementation yet)

### 0.2 — Dependencies & config ✅
- `requirements.txt` — FastAPI, uvicorn, pydantic-settings, httpx, anthropic, pytest
- `app/config.py` — `Settings` + `get_settings()` (env, defaults, agent budget)
- `.env.example` — documented variables for all phases
- `tests/test_config.py` — defaults and settings cache

### 0.3 — FastAPI entry point ✅
- `app/main.py` — `create_app()`, lifespan, `app` instance for uvicorn
- `app/api/router.py` — aggregates API routers
- `app/api/chat.py` — empty chat router (routes in 0.5)
- `tests/test_main.py` — app factory and startup smoke test

### 0.4 — Health check ✅
- `app/api/health.py` — `GET /health` → `{"status": "ok"}`
- Registered via `app/api/router.py`
- `tests/test_health.py` — status 200 + body

### 0.5 — Chat stub ✅
- `app/models/agent.py` — `ChatRequest`, `ChatResponse`
- `app/core/tracing.py` — `generate_trace_id()`
- `app/api/chat.py` — `POST /chat` stub with trace + conversation ids
- `tests/test_chat.py` — trace_id, conversation reuse, validation

### 0.6 — Structured logging ✅
- `app/core/logging.py` — JSON logs, `setup_logging()`, `get_logger()`
- `app/core/middleware.py` — `TraceMiddleware` per request
- `app/core/tracing.py` — context var `get_trace_id()` / `set_trace_id()`
- `app/main.py` — logging on startup + middleware
- `app/api/chat.py` — logs with shared trace_id
- `tests/test_logging.py` — trace_id in headers and log records

## Phase 0 — complete ✅

## Phase 1 — AgentState & loop

### 1.1 — AgentState model ✅
- `app/models/planning.py`, `flight.py`, `booking.py` — nested state models
- `app/models/agent.py` — `Language`, `ToolCallRecord`, `ReflectionRecord`
- `app/agent/state.py` — `AgentState` + `AgentState.new()`
- `tests/test_state.py` — JSON round-trip and default fields

### 1.2 — Request fields in state ✅
- `detect_language()` — minimal SQ/EN hint
- `update_from_user_message()` — writes `trace_id`, `user_message`, `language`
- `create_state_for_turn()` — new session from one user turn
- `new_conversation_id()` — helper for new conversations

### 1.3 — In-memory state store ✅
- `StateStore` protocol — contract for future Redis/DB backends
- `InMemoryStateStore` — `get()`, `save()`, `clear()` with deep copies
- `get_state_store()` — app-wide singleton
- `tests/test_state.py` — persistence, same conversation, copy isolation

### 1.4 — Agent loop ✅
- `app/agent/loop.py` — `run_chat()` load → update → save
- Reuses existing session or creates new one
- Increments `iteration_count` per turn
- `tests/test_loop.py` — create, reuse, language detection

### 1.5 — Agent budget ✅
- `app/agent/budget.py` — `AgentBudget.from_settings()`, `is_exceeded()`
- `run_chat()` stops when iteration/LLM/tool/token limits exceeded
- `tests/test_budget.py`, budget test in `tests/test_loop.py`

### 1.6 — Chat → agent loop ✅
- `app/api/chat.py` — thin handler delegates to `run_chat()`
- Logs `chat_response` with `iteration_count`
- `tests/conftest.py` — clears state store between tests
- `tests/test_chat.py` — end-to-end state persistence

## Phase 1 — complete ✅

## Phase 2 — Planning

### 2.1 — Plan models ✅
- `Plan`, `PlanStep` with `Worker`, `StepStatus`, `PlanStatus` enums
- Dependency graph validation (unique ids, known `depends_on`)
- `tests/test_planning.py` — sample JSON, round-trip, invalid plans

### 2.2 — Planner interface ✅
- `Planner` protocol + `PlanningError`
- `MockPlanner` — deterministic valid plan from `AgentState`
- `build_default_flight_plan()` — shared search → select → booking template
- `get_planner()` — factory (mock now, LLM in 2.3)
- `tests/test_planner.py` — mock planner returns valid plan

### 2.3 — LLM planner ✅
- `LlmPlanner` — Claude returns structured JSON → `Plan`
- `extract_json_object()`, `parse_plan_payload()` — safe parsing/validation
- `PLANNER_USE_MOCK` config — mock default, LLM when false + API key
- `tests/test_llm_planner.py` — mocked Anthropic client, no live API calls

### 2.4 — Plan on AgentState ✅
- `assign_plan_to_state()` — writes `state.plan` with `PENDING` + `current_step=0`
- `ensure_plan()` — planner runs once when session has no steps
- `run_chat()` calls `ensure_plan()` before save
- Tests in `test_planner.py` and `test_loop.py`

### 2.5 — Coordinator step selection ✅
- `find_next_executable_step_index()` — first pending step with satisfied `depends_on`
- `select_current_step()` — sets `current_step`, marks plan `IN_PROGRESS`
- `run_chat()` calls coordinator after planning
- `tests/test_coordinator.py`, loop integration test

### 2.6 — Stub step execution ✅
- `execute_step_stub()` — marks step `completed`, appends `tool_history`
- `run_chat()` executes selected step after planning
- Response includes stub execution summary
- Follow-up messages advance to next ready step

## Phase 2 — complete ✅

## Phase 3 — Evaluator & replanning

### 3.1 — EvaluationResult model ✅
- `EvaluationStatus` enum — `CONTINUE`, `RETRY`, `REPLAN`, `ASK_USER`, `FAIL`
- `EvaluationResult` — structured evaluator output with optional `issue` / `message`
- `ReflectionRecord.status` now uses `EvaluationStatus`
- `tests/test_evaluation.py` — enum, validation, JSON round-trip

### 3.2 — Evaluator ✅
- `evaluate_step_result()` — rules-based evaluation of one step
- `evaluate_latest_tool_result()` — reads last `tool_history` entry
- `evaluate_and_record()` — persists to `reflection_history`
- `run_chat()` evaluates after stub step execution
- `tests/test_reflection.py` — CONTINUE, RETRY, history recording

### 3.3 — CONTINUE advances plan ✅
- `_execute_plan_until_pause()` — inner loop while evaluator returns `CONTINUE`
- One user turn can complete all pending plan steps
- Stops on non-`CONTINUE`, no next step, or budget limit
- Updated loop/chat tests for multi-step execution

### 3.4 — RETRY with max attempts ✅
- `step_retry_counts` on `AgentState`, `MAX_STEP_RETRIES` in config
- Failed stub steps stay `pending` and retry up to limit
- After max retries → `FAIL` recorded in `reflection_history`
- `set_stub_failures()` test hook for simulated step failures

### 3.5 — REPLAN replaces plan ✅
- `replan_for_state()` — calls planner again, replaces plan via `assign_plan_to_state`
- `replan_count` on `AgentState`, `MAX_REPLAN_ATTEMPTS` in config
- Loop continues with new plan after `REPLAN`; fails after max replans
- `set_stub_replan()` test hook triggers REPLAN after named steps succeed

### 3.6 — ASK_USER pauses loop ✅
- Evaluator returns `ASK_USER` when user requests fares the API cannot provide
- `pending_question` on `AgentState`; cleared when the user sends the next message
- Loop stops and returns the evaluator's user-facing message
- `set_stub_ask_user()` test hook for deterministic ASK_USER in tests

### 3.7 — FAIL graceful ✅
- Loop returns user-facing failure message (no stub internals in response)
- `mark_plan_failed()` sets `plan.status = FAILED`
- `set_stub_fail_evaluation()` test hook for terminal FAIL
- `PlanningError` caught in `run_chat()` with safe message
- Global exception handlers — controlled 500 JSON with `trace_id`, no stack trace

### 3.8 — reflection_history complete ✅
- `ReflectionRecord` enriched — `message`, `step_id`, `trace_id`, `iteration`
- Every evaluator decision records full audit context on `AgentState`
- History survives JSON round-trip and grows across conversation turns
- Tests cover all five `EvaluationStatus` values in persisted history

## Phase 3 — complete ✅

## Phase 4 — Coordinator & Workers

### 4.1 — Worker delegation ✅
- `execute_step()` delegates to `FlightWorker` or `BookingWorker` via `get_worker(step.worker)`
- Workers return `WorkerResult`; coordinator updates step status and `tool_history`
- `execute_step_stub()` kept as alias for compatibility
- `tests/test_workers.py` + delegation tests in `test_coordinator.py`

### 4.2 — Shared worker interface ✅
- `BaseWorker` ABC — `worker_type`, `supported_actions`, `execute(action, state)`
- Shared action validation in base class; workers implement `_run()`
- `WorkerRegistry` maps `Worker` enum → implementation
- `FlightWorker` and `BookingWorker` both implement the same contract

### 4.3 — Flight worker actions ✅
- `FlightSearchService` in `app/tools/flight_service.py` — shared search/validate logic
- `search_flights` parses route from user message, fills `state.flight_search.results`
- `validate_options` selects first option into `selected_option_id`
- `FlightOption` model; mock results when `FLIGHT_API_USE_MOCK=true`
- `tests/test_flight_service.py`, `tests/test_flight_worker.py`

### 4.4 — Booking worker stub ✅
- `BookingService` in `app/tools/booking_service.py` — shared `create_booking` logic
- Requires validated flight (`selected_option_id`); writes mock `booking_id` to state
- `BookingStatus.PENDING` until HITL in Phase 7
- `tests/test_booking_service.py`, `tests/test_booking_worker.py`

### 4.5 — Coordinator isolation ✅
- `coordinator.py` delegates only via `get_worker()` — no `app.tools` or API imports
- Architecture test guards against Lufthansa/HTTP/client leakage into coordinator

### 4.6 — tool_history complete ✅
- `ToolCallRecord` enriched — `step_id`, `trace_id`, `message`, `iteration`
- `record_tool_call()` centralizes audit entries for every worker execution
- Retries record each attempt; full plan run produces 3 audited tool calls

## Phase 4 — complete ✅

## Phase 5 — Direct tools (Flight API + Booking store)

### 5.1 — Lufthansa HTTP client ✅
- `LufthansaClient` in `app/tools/lufthansa_client.py` — isolated httpx wrapper
- OAuth token exchange + `get_schedules()` + `get_flight_status()` skeleton
- `FLIGHT_API_CLIENT_SECRET` added to config / `.env.example`
- `tests/test_lufthansa_client.py` — mock transport, no live API calls

### 5.2 — Live search via env flag ✅
- `FlightSearchService` calls `LufthansaClient` when `FLIGHT_API_USE_MOCK=false`
- `flight_normalizer.py` maps schedule JSON → `FlightOption`
- Mock mode unchanged; live errors return graceful worker failure
- `tests/test_flight_normalizer.py` + live-path tests in `test_flight_service.py`

### 5.3 — get_flight_status ✅
- `FlightStatusInfo` model + `last_status` on `FlightSearchState`
- `FlightSearchService.get_flight_status()` — mock/live via `FLIGHT_API_USE_MOCK`
- `normalize_flight_status_response()` maps API JSON to domain model
- `parse_flight_number()` helper for user messages

### 5.4 — Normalize results into domain models ✅
- Normalization moved to `app/models/flight.py` — `FlightOption.from_lufthansa_flight()`, `FlightStatusInfo.from_lufthansa_flight()`
- `normalize_schedule_payload()`, `normalize_flight_status_payload()`, `normalize_lufthansa_payload()` unified entry
- `flight_normalizer.py` keeps backward-compatible re-exports; services import from domain models
- State holds Pydantic models only — no raw Lufthansa API dicts in `flight_search`

### 5.5 — SQLite booking store ✅
- `BookingRecord` model + `BookingStore` CRUD (`create`, `get`, `cancel`)
- `BookingService` persists pending bookings to `data/bookings.db` (configurable via `BOOKING_DB_PATH`)
- `tests/test_booking_store.py` — create/get/cancel/idempotency

### 5.6 — Flight worker wired to client only ✅
- `FlightApiClient` protocol + `MockFlightApiClient` in `app/tools/flight_client.py`
- `LufthansaFlightApiClient` in `lufthansa_client.py` — sole provider-specific module (paths, auth, HTTP)
- `FlightSearchService` depends on `FlightApiClient` only; no direct Lufthansa imports
- Architecture tests in `tests/test_flight_architecture.py`

### 5.7 — Results in session state ✅
- Search → `state.flight_search` (`origin`, `destination`, `date`, `results[]`, `selected_option_id`)
- Status lookup → `state.flight_search.last_status`
- Booking → `state.booking` (`booking_id`, `passenger`, `selected_flight`, `status`)
- Domain state persists across turns and JSON round-trip
- `tests/test_state_domain.py` — end-to-end via `run_chat` and `/chat`

## Phase 5 — complete ✅

## Phase 6 — MCP layer

### 6.1 — Tool adapter interface ✅
- `ToolAdapter` protocol in `app/tools/adapters/base.py`
- `DirectToolAdapter` — in-process `FlightSearchService` + `BookingService`
- `McpToolAdapter` — routes actions through `McpClient`
- `InProcessMcpClient` bridge in `app/mcp/client.py` until standalone servers (6.2–6.4)
- Workers depend on `ToolAdapter`; `create_tool_adapter()` selects mode via `TOOLS_MODE`
- `tests/test_tool_adapters.py`, `tests/test_worker_architecture.py`

### 6.2 — Lufthansa MCP server ✅
- Standalone `MCPServer` in `app/mcp/servers/lufthansa_server.py`
- Tools: `search_flights`, `get_flight_status` via `FlightApiClient`
- Resource template: `airports://{code}` with static IATA metadata
- Run locally: `python -m app.mcp.servers.lufthansa_server`
- `tests/test_lufthansa_mcp_server.py` — handlers + tool/resource registration

### 6.3 — Booking MCP server ✅
- Standalone `FastMCP` server in `app/mcp/servers/booking_server.py`
- Tools: `create_booking`, `get_booking`, `cancel_booking` via `BookingStore`
- Resource template: `bookings://{booking_id}`
- Run locally: `python -m app.mcp.servers.booking_server`
- `tests/test_booking_mcp_server.py` — handlers + tool/resource registration

### 6.4 — Real MCP client ✅
- `RemoteMcpClient` spawns stdio MCP servers and calls tools/resources
- `stdio_transport.py` wraps MCP `ClientSession` with sync `asyncio.run()` bridge
- `worker_bridge.py` maps MCP payloads onto `AgentState`
- `InProcessMcpClient` kept for tests via `MCP_USE_INPROCESS=true`
- Config: `MCP_USE_INPROCESS`, `MCP_PYTHON_EXECUTABLE`
- `tests/test_mcp_client.py` — parsing, discovery, end-to-end worker flow

### 6.5 — Switch via TOOLS_MODE config ✅
- `configure_worker_registry(settings)` binds workers to direct or MCP adapters
- Called from app startup (`main.py`) and each `run_chat()` turn
- Coordinator/workers unchanged — mode selected only through config/factory
- `tests/test_tools_mode_switch.py` — direct vs MCP end-to-end + architecture guards

### 6.6 — MCP prompts and resources ✅
- Shared templates in `app/mcp/servers/prompts.py` and static payloads in `resources.py`
- Lufthansa server: prompts `search_route`, `flight_status`; resources `airports://{code}`, `airport://{code}` (alias), `airports://catalog`
- Booking server: prompt `create_booking_request`; resource `bookings://help`
- `RemoteMcpClient`: `list_prompts()`, `get_prompt()`, URI-based server routing in `read_resource()`
- `tests/test_mcp_prompts_resources.py` — prompt rendering, catalog/help resources, client discovery

## Phase 6 — complete ✅

## Phase 7 — Human-in-the-loop & permissions

### 7.1 — Tool permission model ✅
- `ToolPermission` enum (`READ`, `WRITE`) in `app/guardrails/permissions.py`
- Registry covers worker actions and MCP tools: `search_flights`, `validate_options`, `get_flight_status`, `get_booking` = READ; `create_booking`, `cancel_booking` = WRITE
- Helpers: `get_tool_permission()`, `requires_approval()`, `get_worker_action_permission()`
- `tests/test_permissions.py` — registry coverage; `create_booking` classified as WRITE

### 7.2 — READ tools execute directly ✅
- `executes_directly()` helper; coordinator routes READ steps through `_run_worker_step()` without approval
- `search_flights` and `validate_options` run immediately; READ steps ignore stale `pending_approval`
- WRITE path left in place until 7.3 approval gate
- `tests/test_hitl_read_execution.py` — direct search execution, no `pending_approval` side effects

### 7.3 — WRITE tools queue pending_approval ✅
- `app/guardrails/approval.py` builds booking approval payloads without DB writes
- Coordinator `_queue_pending_approval()` for WRITE steps; booking step stays `IN_PROGRESS`
- Agent loop pauses when `pending_approval` is set
- `tests/test_hitl_write_approval.py` — approval queued, SQLite unchanged after full search plan

### 7.4 — Confirm / cancel endpoints ✅
- `POST /approvals/confirm` and `POST /approvals/cancel` with `{ conversation_id }`
- `app/agent/approval_flow.py` — confirm runs approved WRITE via `execute_approved_step()`; cancel clears approval and resets step
- Confirm creates real booking in SQLite; cancel aborts with no DB write
- `tests/test_hitl_confirm_cancel.py` — API + flow coverage

### 7.5 — Full approval payload ✅
- `BookingApprovalPayload` with nested `route` (origin, destination, date, cities) and `flight` (id, times, carrier)
- `POST /chat` returns `pending_approval` in response; `GET /approvals/pending?conversation_id=`
- Rich user-facing approval message with route and schedule summary
- `tests/test_hitl_approval_payload.py` — payload shape + API exposure

### 7.6 — Clean state after deny ✅
- `finalize_approval_denial()` clears `pending_approval`, resets `BookingState`, marks booking step `SKIPPED`, completes plan
- Cancel records `cancelled` in tool history; flight search results preserved; no SQLite rows
- Follow-up `/chat` after cancel does not create bookings
- `tests/test_hitl_cancel_clean_state.py` — deny cleanup + no side effects

## Phase 7 — complete ✅

## Phase 8 — Security guardrails

### 8.1 — Input validation ✅
- `validate_user_message()` in `app/guardrails/input_guard.py` — trim, min/max length, control-char rejection
- Config: `MIN_USER_MESSAGE_LENGTH`, `MAX_USER_MESSAGE_LENGTH`
- `POST /chat` rejects empty/whitespace-only/too-long input with `400`
- `tests/test_input_guard.py` — unit + API coverage

### 8.2 — Prompt injection detection ✅
- Heuristic rules in `detect_prompt_injection()` — ignore/disregard instructions, role override, jailbreak, role markers
- Config: `PROMPT_INJECTION_GUARD_ENABLED`, `PROMPT_INJECTION_BLOCK` (warn-only when block=false)
- `PromptInjectionError` blocks suspicious input before agent loop
- `tests/test_input_guard.py` — pattern detection + `/chat` block coverage

### 8.3 — Rate limiting ✅
- `InMemoryRateLimiter` in `app/guardrails/rate_limit.py` — per-IP and per-conversation windows
- `RateLimitMiddleware` returns `429` + `Retry-After`; `/health` excluded
- Conversation limits enforced in `/chat` and `/approvals/*`
- Config: `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW_SECONDS`, `RATE_LIMIT_IP_REQUESTS`, `RATE_LIMIT_CONVERSATION_REQUESTS`
- `tests/test_rate_limit.py` — IP/conversation limits + API coverage

### 8.4 — Output guard ✅
- `filter_user_response()` blocks tracebacks/SQL dumps and redacts secrets, paths, env assignments
- Applied to `/chat` and `/approvals/*` responses via `safe_user_message()`
- Config: `OUTPUT_GUARD_ENABLED`
- `tests/test_output_guard.py` — filtering rules + API coverage

### 8.5 — PII redaction ✅
- `redact_pii()` masks emails and phone numbers in `app/guardrails/pii.py`
- Applied to API responses (after output guard) and structured log payloads
- Config: `PII_REDACTION_ENABLED`
- `tests/test_pii.py` — redaction rules, logging, and `/chat` coverage

### 8.6 — Guard chain before agent loop ✅
- `app/guardrails/chain.py` — `run_inbound_chat_guards()`, `run_inbound_approval_guards()`, `run_outbound_guards()`
- `/chat` and `/approvals/*` use the chain so security runs at the API boundary, not only in LLM/tool code
- `docs/guardrails.md` — inbound/outbound order, middleware, HITL, and request-flow diagram
- `tests/test_guard_chain.py` — orchestration, ordering, and documentation coverage

## Phase 8 — complete ✅

## Phase 9 — Reliability

### 9.1 — Retry with exponential backoff ✅
- `retry_with_backoff()` in `app/core/retry.py` — max 3 attempts, exponential delay capped by config
- `LufthansaClient` retries transient HTTP failures (503, network errors) on token and JSON requests
- Config: `RETRY_ENABLED`, `RETRY_MAX_ATTEMPTS`, `RETRY_BASE_DELAY_SECONDS`, `RETRY_MAX_DELAY_SECONDS`
- `tests/test_retry.py` — backoff math and retry behavior
- `tests/test_lufthansa_client.py` — flaky API succeeds on 3rd attempt, fails after 3 attempts

### 9.2 — External call timeouts ✅
- `app/core/timeout.py` — `ExternalCallTimeoutError`, `await_with_timeout()`, `httpx_timeout_from_settings()`
- Lufthansa HTTP client uses `EXTERNAL_HTTP_TIMEOUT_SECONDS` and raises clear timeout errors
- MCP stdio transport wraps tool/resource/prompt calls with `EXTERNAL_MCP_TIMEOUT_SECONDS`
- LLM planner passes `EXTERNAL_LLM_TIMEOUT_SECONDS` to Anthropic client
- `tests/test_timeout.py` — HTTP hang, MCP hang, and LLM timeout coverage

### 9.3 — Circuit breaker ✅
- `InMemoryCircuitBreaker` in `app/core/circuit_breaker.py` — failure threshold + sliding window
- `LufthansaClient` opens circuit after repeated transient failures and fails fast while open
- Config: `CIRCUIT_BREAKER_ENABLED`, `CIRCUIT_BREAKER_FAILURE_THRESHOLD`, `CIRCUIT_BREAKER_WINDOW_SECONDS`, `CIRCUIT_BREAKER_OPEN_SECONDS`
- `tests/test_circuit_breaker.py` — open/fail-fast/recovery and Lufthansa integration

### 9.4 — Booking idempotency ✅
- `build_booking_idempotency_key()` in `app/core/idempotency.py` — deterministic key per conversation + flight
- `BookingStore.create_idempotent()` stores `idempotency_key` and returns existing booking on replay
- `BookingService` and MCP `create_booking_handler` use idempotency keys so retries create one SQLite row
- `tests/test_idempotency.py` — key stability, handler replay, and service retry coverage

### 9.5 — Graceful worker errors ✅
- `GracefulError` hierarchy and `graceful_error_from_exception()` in `app/core/errors.py`
- `BaseWorker.execute()` converts raw exceptions into safe `WorkerResult` failures with `error_code`
- Flight and booking services raise `FlightUnavailableError` / `BookingUnavailableError` instead of leaking internals
- MCP client and Lufthansa handlers map provider failures to graceful errors
- `tests/test_graceful_errors.py` — mapping rules and worker-safe failure coverage

### 9.6 — Evaluator FAIL when circuit open ✅
- `ToolCallRecord.error_code` persisted from failed worker results
- Evaluator maps `circuit_open` to `EvaluationStatus.FAIL` with a user-friendly message (no retry loop)
- Flight API circuit-open failures propagate `ErrorCode.CIRCUIT_OPEN` through client, worker, and evaluator
- `tests/test_reflection.py` and `tests/test_evaluator_circuit_open.py` — FAIL path and `/chat` integration

## Phase 9 — complete ✅

## Phase 10 — Observability

### 10.1 — Structured logging ✅
- `app/core/observability.py` — `log_extra()`, `elapsed_ms()` for consistent structured fields
- `StructuredFormatter` auto-injects `trace_id` from request context when missing
- `TraceMiddleware` logs `latency_ms` on `request_completed`
- Coordinator emits `step_executed` logs with `step`, `success`, and `latency_ms`
- `tests/test_observability_logging.py` — trace_id, step, and latency in JSON logs

### 10.2 — Span tracing ✅
- `app/core/tracing.py` — `SpanRecord`, `trace_span()`, `build_trace_tree()`, `format_trace_tree()`
- Request span in middleware; plan span in `ensure_plan()`; worker spans in coordinator; tool spans in workers
- `request_completed` logs include nested `trace_tree` JSON and readable `trace_tree_text`
- `tests/test_tracing_spans.py` — parent/child spans and `/chat` trace tree integration

### 10.3 — Metrics counters ✅
- `app/core/metrics.py` — `TurnMetrics`, `SessionMetrics`, `MetricsSnapshot`, `log_turn_metrics()`
- `LlmPlanner` records Anthropic `input_tokens` + `output_tokens` on `state.token_usage`
- `run_chat()` emits `turn_metrics` with turn latency, tool count, LLM calls, and token usage
- `chat_response` log includes cumulative session counters from state
- `tests/test_metrics.py` — snapshot deltas, LLM token tracking, and log integration

### 10.4 — Booking audit trail ✅
- `BookingAuditRecord` model and `booking_audit` SQLite table — who, when, and what for each write
- `app/tools/booking_audit.py` — audit context helpers and structured `booking_audit` logs
- `BookingStore.create()` / `cancel()` append audit rows; idempotent replays skip duplicate writes
- `BookingService` and MCP handlers pass actor (`conversation_id`) and `trace_id` context
- `tests/test_booking_audit.py` — create/cancel audit, idempotency, service/MCP integration, logs

### 10.5 — Cost tracking ✅
- `app/core/cost.py` — `CostSummary`, `session_cost()`, `build_cost_debug_payload()`, `log_cost_tracking()`
- `run_chat()` emits `cost_tracking` logs with session and turn `llm_call_count` / `token_usage`
- `ChatResponse.debug.cost` included when `DEBUG=true` (`response_model_exclude_none` keeps prod responses clean)
- `tests/test_cost.py` — cost counters, logs, and debug response integration

## Phase 10 — complete ✅

## Phase 11 — Tests (unit & integration)

### 11.1 — `test_planning.py` ✅
- Extended planning tests for mock LLM JSON → valid `Plan` pipeline
- Covers fenced JSON extraction, schema validation, `LlmPlanner` mock responses, and `ensure_plan()`
- Rejects invalid mock LLM JSON and broken dependency graphs with `PlanningError`

### 11.2 — `test_reflection.py` ✅
- Evaluator unit tests for `CONTINUE`, `ASK_USER`, and `REPLAN` via `evaluate_step_result()` and `evaluate_and_record()`
- Integration tests via `run_chat()` — multi-step CONTINUE, REPLAN with plan replacement, ASK_USER with `pending_question`
- Pricing-intent and stub-hook coverage for ask-user and replan triggers

### 11.3 — `test_workers.py` ✅
- Isolated flight worker tests — search/validate populate flight domain without touching booking state
- Isolated booking worker tests — create_booking with injected adapter, no flight search side effects
- Validate requires prior search; booking requires selected flight; unsupported action returns `unsupported_action`
- Booking worker persists to SQLite through isolated adapter/store wiring

### 11.4 — `test_security.py` ✅
- Consolidated prompt injection coverage — validator blocks known patterns; `/chat` rejects before agent loop
- IP and conversation rate limits at unit and HTTP `/chat` level (429 + `Retry-After`)
- Inbound guard chain blocks injection and enforces approval rate limits
- Control-character rejection at `/chat` boundary

### 11.5 — `test_mcp.py` ✅
- Stdio transport discovers tools on Lufthansa and Booking MCP servers
- `RemoteMcpClient` invokes `search_flights` and `create_booking` against live server subprocesses
- Resource reads, full search → validate → book flow, and `McpToolAdapter` remote integration
- In-process vs remote client parity for flight search

### 11.6 — `test_booking.py` ✅
- HITL flow: `/chat` queues approval with no SQLite write until confirm
- Confirm creates one booking row; cancel aborts with zero rows
- Idempotent replay after confirm — service retry returns existing booking, stable idempotency key
- HTTP `/chat` → `/approvals/confirm` integration and guard against double confirm

### 11.7 — `test_chat.py` ✅
- Full `/chat` end-to-end integration with mock flight API and default planner
- HTTP pipeline: search → validate → HITL with plan step, tool, and reflection assertions
- Full journey: `/chat` → `/approvals/confirm` → follow-up turn preserves booking
- Ask-user pause via HTTP for cheapest-fare intent; cancel flow via `/approvals/cancel`
- Multi-turn chat after completed booking does not re-execute plan steps

## Phase 11 — complete ✅

## Phase 12 — Agent evaluations

### 12.1 — `evals/datasets/` ✅
- Pydantic models for eval cases: turns, expectations, categories (`happy_path`, `ambiguous`, `injection`, `hitl`, `safety`)
- JSON datasets with representative scenarios aligned to mock agent behavior
- Loader utilities: `load_dataset()`, `load_all_cases()`, `list_dataset_files()`
- `tests/test_eval_datasets.py` — schema validation, unique ids, category coverage

### 12.2 — `evals/runners/` ✅
- `EvalHttpRunner` executes dataset turns via HTTP (`/chat`, `/approvals/confirm`, `/approvals/cancel`)
- Checks expectations: HTTP status, outcome, message fragments, plan status, booking write
- `run_eval_case()`, `run_category_evals()`, `run_all_evals()` with isolated mock settings per run
- `tests/test_eval_runner.py` — automatic execution of full eval suite (16 cases)

### 12.3 — `evals/metrics/` ✅
- Outcome, trajectory, and safety scores (0–1) per eval case
- Outcome: expected vs observed terminal state; trajectory: plan steps, tool calls, HITL discipline
- Safety: guard blocking, unauthorized writes, unsafe output markers
- Aggregate `EvalRunMetrics` on `EvalRunSummary`; per-case metrics on `EvalCaseResult`
- `tests/test_eval_metrics.py` — scoring units and full-suite aggregate metrics

### 12.4 — Regression set ✅
- `evals/datasets/regression.json` — curated 10-case manifest with minimum score thresholds
- `load_regression_manifest()`, `resolve_regression_cases()`, `run_regression_evals()` regression gate
- `RegressionGateError` when pass rate or outcome/trajectory/safety scores fall below baseline
- `tests/test_eval_regression.py` — regression suite passes; gate fails on broken expectations

### 12.5 — Eval report ✅
- `build_eval_report()` — structured report from `EvalRunSummary` (cases, metrics, pass rate)
- `format_eval_report_json()` and `format_eval_report_markdown()` for demo/README output
- `write_eval_report()` writes paired `.json` and `.md` files to a target directory
- `tests/test_eval_report.py` — JSON validity, markdown tables, failure section, file export

## Phase 12 — complete ✅

## Phase 13 — Docs & production polish

### 13.1 — `README.md` ✅
- Prerequisites, virtualenv setup, and `pip install -r requirements.txt`
- `.env` configuration table with local-dev defaults (mock planner + mock flights)
- Run instructions (`python -m app.main`, uvicorn, `/health` check)
- Example `curl` flows for `/chat`, `/approvals/confirm`, and `/approvals/cancel`
- Test, eval, regression, and report generation commands
- Project layout and links to `docs/`

### 13.2 — `docs/architecture.md` ✅
- High-level and sequence diagrams (request flow, HITL booking)
- Agent runtime, workers, tool modes, state model, security, observability
- API surface and module map aligned with current code layout

### 13.3 — `docs/decisions.md` ✅
- ADR format: context, decision, consequences, code references
- 13 records: planning, state, workers, MCP adapter, HITL, guardrails, mocks, reflection, SQLite, budget, idempotency, eval runner, thin HTTP
- Deferred/out-of-scope table for pilot boundaries

### 13.4 — `docs/threat-model.md` ✅
- Scope, assets, trust-boundary diagram
- 12 threats (STRIDE-aligned): injection, unauthorized write, session hijack, leakage, PII, DoS, input abuse, replay, SQLi, MCP, credentials, guard bypass
- Mitigation summary diagram, residual risks, verification matrix, hardening checklist

### 13.5 — `ENGINEERING_LOG.md` ✅
- At-a-glance metrics, phase index, and documentation map
- Phase 0–2 marked complete (consistent with phases 3–12)
- Full step-by-step history from 0.1 through 13.4 preserved
- Demo verification checklist (D1–D7) for end-to-end project sign-off

### 13.6 — Docker / `docker-compose` ✅
- `Dockerfile` — Python 3.11-slim, uvicorn, built-in `/health` HEALTHCHECK
- `docker-compose.yml` — port 8000, named volume for SQLite, mock defaults
- `.dockerignore` — excludes venv, tests, local DB files, secrets
- README Docker section — `docker compose up --build` + health check

---

## Demo verification checklist

Manual sign-off scenarios aligned with the original project roadmap. Run with default mock settings unless noted.

| # | Scenario | Expected result | How to verify |
|---|----------|-----------------|---------------|
| **D1** | “Find flights TIA to FRA on Sep 15” | Plan → search → flight list | `POST /chat`; response mentions flights; `flight_search.results` populated |
| **D2** | “Book the first one” (after search) | Approval payload → confirm → booking ID | `/chat` queues `pending_approval`; `POST /approvals/confirm` returns booking id; row in SQLite |
| **D3** | “Cheapest flight” | `ASK_USER` — API has no fares | Response asks for clarification; `pending_question` set; no booking |
| **D4** | Prompt injection in input | Blocked / safe response | e.g. “Ignore previous instructions…” → **400** before agent loop |
| **D5** | API down (mock/simulated) | Retry → circuit → graceful message | Circuit-open path returns user-safe FAIL (see Phase 9.6 tests) |
| **D6** | Same conversation, 2 messages | State persists; full trace | Reuse `conversation_id`; plan advances; `trace_id` per request |
| **D7** | `TOOLS_MODE=mcp` | Same flow via MCP | Set env; restart app; search → validate → HITL still holds |

Automated coverage: **452** unit/integration tests · **16** eval cases · **10** regression gate cases.

```bash
pytest -q
python -m evals.regression
```

---

## Build summary

The project was built **incrementally** — one verifiable step at a time — from an empty folder structure (0.1) through a production-style pilot with guardrails, HITL, MCP, observability, tests, and evals. Each phase entry above lists the modules touched and the tests that prove the step.

**Remaining roadmap (optional):** 13.7 CI (GitHub Actions).

## Phase 14 — Frontend

### 14.1 — React UI (Vite + TypeScript) ✅
- `frontend/` — Tyconic-style landing (hero + glass booking coupon)
- Dribbble-inspired seat picker (interactive map, summary sidebar)
- Chat panel with agent messages, HITL confirm/cancel
- `lucide-react` icons, Inter font, responsive layout

### 14.2 — API integration + CORS ✅
- `frontend/src/api/client.ts` — `/chat`, `/approvals/confirm`, `/cancel`
- Vite dev proxy `/api` → `localhost:8000`
- `CORS_ORIGINS` in `app/config.py` + `CORSMiddleware` in `app/main.py`

### 14.3 — FE-1 Chat bazë ✅
- `ChatInput` — free-text message + Send in `ChatPanel`
- `sendUserMessage()` — shared `POST /chat` handler with `conversation_id` persistence
- Multi-turn thread (user/agent bubbles), auto-scroll, empty-state hint
- “Ask PILOT” opens chat panel; coupon search still sends first message

