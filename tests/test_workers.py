"""Worker unit tests — Phase 4.1–4.2 / 6.1, Phase 11.3."""

import inspect

from app.agent.state import AgentState
from app.agent.workers.base import BaseWorker, WorkerResult
from app.agent.workers.booking_worker import BookingWorker
from app.agent.workers.flight_worker import FlightWorker
from app.agent.workers import WorkerRegistry, get_worker
from app.config import Settings
from app.models.booking import BookingStatus
from app.models.planning import Worker
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


def _direct_adapter(tmp_path) -> DirectToolAdapter:
    store = BookingStore(str(tmp_path / "bookings.db"))
    settings = Settings(flight_api_use_mock=True)
    return DirectToolAdapter(
        settings=settings,
        booking_service=BookingService(store=store, settings=settings),
    )


def test_flight_worker_executes_supported_actions(tmp_path) -> None:
    worker = FlightWorker(adapter=_direct_adapter(tmp_path))
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    search = worker.execute("search_flights", state)
    validate = worker.execute("validate_options", state)

    assert search.success is True
    assert "Found 3 mock flights from TIA to FRA" in search.message
    assert validate.success is True
    assert "Selected flight LH001" in validate.message


def test_flight_worker_rejects_unknown_action() -> None:
    worker = FlightWorker()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    result = worker.execute("cancel_booking", state)

    assert result.success is False
    assert "does not support" in result.message


def test_booking_worker_executes_create_booking(tmp_path) -> None:
    worker = BookingWorker(adapter=_direct_adapter(tmp_path))
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.flight_search.selected_option_id = "LH001"

    result = worker.execute("create_booking", state)

    assert result.success is True
    assert "Created booking BK-" in result.message
    assert state.booking.status == BookingStatus.PENDING


def test_workers_implement_shared_base_contract() -> None:
    workers: list[BaseWorker] = [FlightWorker(), BookingWorker()]

    for worker in workers:
        assert isinstance(worker, BaseWorker)
        signature = inspect.signature(worker.execute)
        assert list(signature.parameters) == ["action", "state"]
        assert worker.worker_type in {Worker.FLIGHT, Worker.BOOKING}
        assert worker.supported_actions


def test_worker_registry_returns_typed_workers() -> None:
    registry = WorkerRegistry()

    flight = registry.get(Worker.FLIGHT)
    booking = registry.get(Worker.BOOKING)

    assert isinstance(flight, FlightWorker)
    assert isinstance(booking, BookingWorker)
    assert flight.worker_type == Worker.FLIGHT
    assert booking.worker_type == Worker.BOOKING


def test_get_worker_uses_default_registry() -> None:
    worker = get_worker(Worker.FLIGHT)

    assert isinstance(worker, FlightWorker)
    state = AgentState.new(conversation_id="c", trace_id="t")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    result = worker.execute("search_flights", state)
    assert isinstance(result, WorkerResult)
    assert result.success is True


def test_flight_worker_isolated_does_not_touch_booking_state(tmp_path) -> None:
    worker = FlightWorker(adapter=_direct_adapter(tmp_path))
    state = AgentState.new(conversation_id="conv-isolated-flight", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    search = worker.execute("search_flights", state)
    validate = worker.execute("validate_options", state)

    assert search.success is True
    assert validate.success is True
    assert state.booking.booking_id is None
    assert state.booking.status == BookingStatus.NONE
    assert state.booking.selected_flight is None


def test_flight_worker_isolated_search_populates_flight_domain(tmp_path) -> None:
    worker = FlightWorker(adapter=_direct_adapter(tmp_path))
    state = AgentState.new(conversation_id="conv-flight-domain", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    worker.execute("search_flights", state)

    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "FRA"
    assert state.flight_search.date == "2025-09-15"
    assert len(state.flight_search.results) == 3


def test_flight_worker_isolated_validate_requires_prior_search() -> None:
    worker = FlightWorker()
    state = AgentState.new(conversation_id="conv-validate-only", trace_id="trace1")

    result = worker.execute("validate_options", state)

    assert result.success is False
    assert "Run search first" in result.message


def test_booking_worker_isolated_does_not_run_flight_search(tmp_path) -> None:
    worker = BookingWorker(adapter=_direct_adapter(tmp_path))
    state = AgentState.new(conversation_id="conv-isolated-booking", trace_id="trace1")
    state.user_message = "Book for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"

    result = worker.execute("create_booking", state)

    assert result.success is True
    assert len(state.flight_search.results) == 0
    assert state.flight_search.origin is None


def test_booking_worker_isolated_requires_selected_flight() -> None:
    worker = BookingWorker()
    state = AgentState.new(conversation_id="conv-no-flight", trace_id="trace1")
    state.user_message = "Book for Ana Krasniqi"

    result = worker.execute("create_booking", state)

    assert result.success is False
    assert state.booking.booking_id is None


def test_booking_worker_isolated_persists_to_store(tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    store = BookingStore(str(db_path))
    settings = Settings(flight_api_use_mock=True, booking_db_path=str(db_path))
    adapter = DirectToolAdapter(
        settings=settings,
        booking_service=BookingService(store=store, settings=settings),
    )
    worker = BookingWorker(adapter=adapter)
    state = AgentState.new(conversation_id="conv-persist", trace_id="trace1")
    state.user_message = "Book for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"

    result = worker.execute("create_booking", state)

    assert result.success is True
    assert state.booking.booking_id is not None
    assert store.get(state.booking.booking_id) is not None


def test_unsupported_action_returns_error_code() -> None:
    worker = FlightWorker()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    result = worker.execute("create_booking", state)

    assert result.success is False
    assert result.error_code == "unsupported_action"
