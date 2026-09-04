"""Flight worker tests — Phase 4.3 / 6.1."""

from app.agent.state import AgentState
from app.agent.workers.flight_worker import FlightWorker
from app.config import Settings
from app.tools.adapters.direct import DirectToolAdapter


def test_flight_worker_search_updates_state() -> None:
    worker = FlightWorker(
        adapter=DirectToolAdapter(settings=Settings(flight_api_use_mock=True)),
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    result = worker.execute("search_flights", state)

    assert result.success is True
    assert len(state.flight_search.results) == 3


def test_flight_worker_validate_requires_prior_search() -> None:
    worker = FlightWorker()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    result = worker.execute("validate_options", state)

    assert result.success is False


def test_flight_worker_runs_search_then_validate() -> None:
    worker = FlightWorker(
        adapter=DirectToolAdapter(settings=Settings(flight_api_use_mock=True)),
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    search = worker.execute("search_flights", state)
    validate = worker.execute("validate_options", state)

    assert search.success is True
    assert validate.success is True
    assert state.flight_search.selected_option_id == "LH001"
