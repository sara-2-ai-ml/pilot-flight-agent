# Pilot Flight Agent

Stateful agentic flight booking with structured planning, workers, MCP, and human-in-the-loop approval.

The agent accepts English or Albanian chat messages, builds a structured plan, executes flight and booking workers, and pauses for human approval before any write to the booking store.

## Features

- FastAPI API with `POST /chat`, approval endpoints, and structured logging
- Agent loop with plan execution, reflection, replanning, and budget limits
- NLU + conversational prompts (Claude or mock heuristics) for natural EN/SQ chat
- Mock flight API and mock planner for local development (no API keys required)
- Human-in-the-loop booking approval before SQLite writes
- Input/output guardrails, rate limiting, and prompt-injection detection
- MCP tool integration (`TOOLS_MODE=direct` or `TOOLS_MODE=mcp`)
- Eval suite with metrics, regression gate, and JSON/Markdown reports

## Prerequisites

- **Python 3.11+**
- **pip** and **venv**

Optional (only for live integrations):

- `ANTHROPIC_API_KEY` — real NLU, conversational replies, and planning (`NLU_USE_MOCK=false`, `PLANNER_USE_MOCK=false`)
- Lufthansa / Aviationstack credentials — live flight data (`FLIGHT_API_USE_MOCK=false`)

## System design

**Çfarë bën sistemi:** merr mesazhe natyrore (EN/SQ), kupton intentin dhe rrugën, ndërton një plan të strukturuar, ekzekuton kërkim fluturimesh, dhe **ndalon për aprovim njerëzor** para çdo shkrimi në bazë. Çdo bisedë (`conversation_id`) mban gjendjen e plotë — nuk është chat stateless.

### 1. Pamje e përgjithshme (containers)

```mermaid
flowchart LR
    subgraph Client
        UI["React UI\n:5173"]
    end
    subgraph Backend["Python API :8000"]
        API["FastAPI"]
        Agent["Agent runtime"]
        Store["State store\nin-memory"]
    end
    subgraph External
        Claude["Anthropic API\nNLU · planner · prompts"]
        Flights["Flight API\nmock / Aviationstack"]
    end
    subgraph Persist
        SQLite["SQLite\nbookings.db"]
    end

    UI -->|"POST /chat\n/approvals"| API
    API --> Agent
    Agent --> Store
    Agent -.->|"optional"| Claude
    Agent --> Flights
    Agent -->|"only after /confirm"| SQLite
```

| Pjesa | Skop (çfarë bën) |
|-------|-------------------|
| **React UI** | Chat, zgjedhje sedilje, ekran aprovimi — thërret API-n përmes proxy `/api` |
| **FastAPI** | HTTP, guardrails, rate limit, trace_id — s’ka logjikë biznesi të rëndë |
| **Agent runtime** | NLU → sqarim → plan → workers → reflection — truri i produktit |
| **State store** | `AgentState` për çdo `conversation_id` (plan, fluturime, approval në pritje) |
| **Anthropic** | Kur `*_USE_MOCK=false`: kupton tekstin, planifikon, formulon pyetje natyrale |
| **Flight API** | Kthen orare (mock ose live); jo çmime të besueshme në mock |
| **SQLite** | Rezervime vetëm pas `POST /approvals/confirm` |

---

### 2. Shtresat e agentit

```mermaid
flowchart TB
    subgraph Input["Hyrje"]
        MSG["User message"]
        G["Guardrails"]
    end
    subgraph Understand["Kuptim"]
        NLU["NLU\nintent + slots"]
        CONV["Conversational\npyetje natyrale"]
        TD["Travel details\npax · prefs"]
    end
    subgraph Reason["Arsyetim"]
        PL["Planner\nPlan JSON"]
        RP["Replanning"]
    end
    subgraph Act["Veprim"]
        CO["Coordinator"]
        FW["FlightWorker READ"]
        BW["BookingWorker WRITE"]
    end
    subgraph Judge["Gjykim"]
        RF["Reflection"]
        BD["Budget"]
    end

    MSG --> G --> NLU
    NLU -->|mungon info| CONV
    NLU --> TD --> PL --> CO
    CO --> FW & BW --> RF
    RF -->|REPLAN| RP --> PL
    RF -->|RETRY| CO
    BD -.-> CO
```

| Shtresa | Modul | Skop |
|---------|--------|------|
| **Guardrails** | `app/guardrails/` | Blokon input të rrezikshëm, limiton shpejtësinë, pastron output |
| **NLU** | `app/agent/nlu.py` | Nxjerr slots strukturore — jo përgjigje për klientin |
| **Conversational** | `app/agent/conversational_prompts.py` | Tekst bisedor për pyetjet (pa kode aeroporti në copy) |
| **Travel details** | `app/agent/travel_details.py` | Para book: one-way/round-trip, pasagjerë, preferenca |
| **Planner** | `app/agent/planning.py` | Hapa: search → validate → create_booking |
| **Coordinator** | `app/agent/coordinator.py` | Ekzekuton hapin; WRITE → `pending_approval`, jo DB |
| **Reflection** | `app/agent/reflection.py` | Pas çdo hapi: vazhdo, riprovo, replan, pyet user, dështo |

---

### 3. Schema: `AgentState` (gjendja e bisedës)

```mermaid
erDiagram
    AgentState ||--o| Plan : has
    AgentState ||--|| FlightSearchState : has
    AgentState ||--|| BookingState : has
    AgentState ||--o| PendingApproval : may_have
    Plan ||--|{ PlanStep : contains
    FlightSearchState ||--o{ FlightOption : results

    AgentState {
        string conversation_id
        string trace_id
        string user_message
    }
    Plan {
        string goal
        string status
        int current_step
    }
    PlanStep {
        string id
        string worker
        string action
    }
    FlightSearchState {
        string origin
        string destination
        string date
        string selected_option_id
    }
```

| Fushë | Skop |
|-------|------|
| `plan` | Hapat aktualë dhe statusi (pending / in_progress / completed) |
| `flight_search` | Rruga, data, rezultatet, fluturimi i zgjedhur |
| `pending_approval` | Payload për UI — **deri sa user s’konfirmon, s’ka INSERT në SQLite** |
| `pending_question` | Pyetja e fundit për user (sqarim / zgjedhje fluturimi) |
| `reflection_history` | Çfarë vendosi evaluatori pas çdo hapi |
| `tool_history` | Log i thirrjeve READ (search, validate) |

---

### 4. Schema: NLU → `TravelSlots`

```json
{
  "intent": "search_flights | book_flight | greeting | other",
  "origin": "TIA",
  "destination": "FRA",
  "travel_date": "2025-09-15",
  "trip_type": "one_way | round_trip",
  "passengers": 1,
  "needs_clarification": false
}
```

| Slot | Skop |
|------|------|
| `intent` | Kërkim vs rezervim vs përshëndetje |
| `origin` / `destination` | IATA **brenda sistemit** — klienti sheh emra qytetesh në chat |
| `needs_clarification` | Po → loop ndalon dhe pyet përmes conversational layer |

---

### 5. Schema: plani (`Plan` → workers)

```mermaid
flowchart LR
    S["search\nflight.search_flights\nREAD"] --> V["select\nflight.validate_options\nREAD"]
    V --> B["booking\nbooking.create_booking\nWRITE + HITL"]

    style B fill:#f96,stroke:#333
```

| Hapi | Skop |
|------|------|
| **search** | Thirr API / mock → lista `FlightOption` në state |
| **select** | Zgjedh opsionin (“LH001”, “first one”) |
| **booking** | **Nuk shkruan** — vendos `pending_approval`, pret `/confirm` |

**Evaluator:**

| Status | Skop |
|--------|------|
| `CONTINUE` | Hapi tjetër |
| `ASK_USER` | Pauzë (lista fluturimesh, çmim i padisponueshëm) |
| `RETRY` / `REPLAN` / `FAIL` | Riprovo / plan i ri / gabim |

---

### 6. Human-in-the-loop (shkrimi në DB)

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant C as POST /chat
    participant S as AgentState
    participant A as POST /approvals/confirm
    participant D as SQLite

    U->>C: Book / zgjidh LH001
    C->>S: search + validate OK
    C->>S: pending_approval = payload
    Note over D: asnjë INSERT
    C-->>U: Pay and book UI
    U->>A: confirm
    A->>D: create_booking
    A->>S: clear pending_approval
```

| Endpoint | Skop |
|----------|------|
| `POST /chat` | Turn i ri — vetëm READ + approval në pritje |
| `POST /approvals/confirm` | Shkrimi i vetëm i lejuar në DB |
| `POST /approvals/cancel` | Anulon approval, zero DB |

---

### 7. Chat turn (një mesazh)

```mermaid
sequenceDiagram
    participant U as User
    participant L as run_chat
    participant N as NLU
    participant C as Conversational
    participant P as Planner
    participant W as Workers
    participant E as Evaluator

    U->>L: message
    L->>N: extract_travel_slots()
    alt mungon rrugë / datë
        L->>C: pyetje natyrale
        L-->>U: pause
    else gati
        L->>P: ensure_plan()
        loop deri pause
            L->>W: execute step
            W-->>L: result
            L->>E: CONTINUE / ASK_USER / ...
        end
        L-->>U: fluturime / approval / reply
    end
```

---

### 8. Modes (dev vs prod)

| Flag | `true` | `false` |
|------|--------|---------|
| `NLU_USE_MOCK` | Regex + lista qytetesh | Claude NLU |
| `PLANNER_USE_MOCK` | Plan mock | Claude plan JSON |
| `FLIGHT_API_USE_MOCK` | 3 fluturime LH mock | Aviationstack / Lufthansa |
| `TOOLS_MODE` | `direct` | `mcp` stdio |

Vlerat në `.env` kanë prioritet mbi shell env për `NLU_USE_MOCK` / `PLANNER_USE_MOCK`.

---

Më shumë: [docs/architecture.md](docs/architecture.md) · [docs/guardrails.md](docs/guardrails.md) · [docs/threat-model.md](docs/threat-model.md)

## Quick start

From an empty checkout to a working local server in a few minutes:

```bash
# 1. Create and activate a virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment (defaults work out of the box)
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux

# 4. Run the API
python -m app.main
```

The server starts at [http://localhost:8000](http://localhost:8000).

Verify it is running:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Docker

Run the API in a container (mock planner + mock flights, no API keys):

```bash
docker compose up --build
```

Verify health from the host:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Stop the stack:

```bash
docker compose down
```

Notes:

- Bookings persist in the named Docker volume `booking-data` (`BOOKING_DB_PATH=/app/data/bookings.db`).
- Override settings via environment variables in `docker-compose.yml` or a local `.env` file (e.g. `TOOLS_MODE=mcp`).
- For MCP mode in Docker, `MCP_PYTHON_EXECUTABLE=/usr/local/bin/python` is set in the image.

## Frontend

Luxury landing UI (glass booking coupon + seat picker + agent chat):

```bash
# Terminal 1 — API
python -m app.main

# Terminal 2 — UI (http://localhost:5173)
cd frontend
npm install
npm run dev
```

The UI proxies `/api` to the backend via Vite. Set `CORS_ORIGINS` in `.env` if you call the API directly from the browser.

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Important defaults for local dev:

| Variable | Default | Purpose |
|----------|---------|---------|
| `NLU_USE_MOCK` | `true` | Heuristic NLU (no Anthropic key); `false` = Claude NLU + conversational prompts |
| `PLANNER_USE_MOCK` | `true` | Use built-in planner (no Anthropic key) |
| `FLIGHT_API_USE_MOCK` | `true` | Use mock flight search results |
| `TOOLS_MODE` | `direct` | Call tools in-process (`mcp` for MCP servers) |
| `BOOKING_DB_PATH` | `data/bookings.db` | SQLite booking store |
| `RATE_LIMIT_ENABLED` | `true` | Per-IP and per-conversation limits |
| `DEBUG` | `false` | Set `true` to expose cost debug in `/chat` responses |

See `.env.example` for the full list of guardrail, reliability, and budget settings.

## Run the API

```bash
# Development (uses HOST/PORT/DEBUG from .env)
python -m app.main

# Or with uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Example requests

Search flights (mock mode returns TIA → FRA results):

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Find flights TIA to FRA on 2025-09-15\"}"
```

The response includes `conversation_id`, `trace_id`, agent message text, and `pending_approval` when a booking needs confirmation.

Confirm a pending booking:

```bash
curl -X POST http://localhost:8000/approvals/confirm \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\": \"YOUR_CONVERSATION_ID\"}"
```

Cancel a pending booking:

```bash
curl -X POST http://localhost:8000/approvals/cancel \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\": \"YOUR_CONVERSATION_ID\"}"
```

## Run tests

```bash
pytest
```

Run a focused subset:

```bash
pytest tests/test_chat.py tests/test_booking.py -q
```

## Run evals

Full eval suite (16 cases):

```bash
pytest tests/test_eval_runner.py tests/test_eval_metrics.py -q
```

Regression gate (10 critical cases):

```bash
pytest tests/test_eval_regression.py -q
```

Generate a Markdown + JSON eval report from Python:

```python
from evals.regression import run_regression_evals
from evals.report import write_eval_report

summary = run_regression_evals(enforce_thresholds=False)
write_eval_report(summary, "reports", stem="regression-report", run_type="regression")
```

Outputs `reports/regression-report.json` and `reports/regression-report.md`.

## Project layout

```
app/           FastAPI app, agent loop, workers, guardrails, tools
frontend/      React UI — landing, booking coupon, seat picker, chat
evals/         Datasets, runners, metrics, regression gate, reports
tests/         Unit and integration tests
docs/          Architecture, decisions, guardrails, threat model
data/          SQLite booking database (created at runtime)
```

## Documentation

- [ENGINEERING_LOG.md](ENGINEERING_LOG.md) — incremental build log
- [docs/architecture.md](docs/architecture.md) — system design
- [docs/decisions.md](docs/decisions.md) — architecture decision records
- [docs/guardrails.md](docs/guardrails.md) — security guard chain
- [docs/threat-model.md](docs/threat-model.md) — threat model

## License

Internal / portfolio project — add a license if you publish the repository.
