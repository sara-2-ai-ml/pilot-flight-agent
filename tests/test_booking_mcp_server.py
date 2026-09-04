"""Booking MCP server tests — Phase 6.3."""

import pytest

from app.mcp.servers import booking_server
from app.mcp.servers.booking_handlers import (
    cancel_booking_handler,
    create_booking_handler,
    get_booking_handler,
)
from app.models.booking import BookingStatus
from app.tools.booking_store import BookingStore


@pytest.fixture
def store(tmp_path) -> BookingStore:
    return BookingStore(str(tmp_path / "bookings.db"))


def test_create_booking_handler_persists_record(store: BookingStore) -> None:
    payload = create_booking_handler(
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        store=store,
    )

    assert payload["found"] is True
    assert payload["booking_id"].startswith("BK-")
    assert payload["status"] == BookingStatus.PENDING.value
    assert store.get(payload["booking_id"]) is not None


def test_get_booking_handler_returns_missing_payload(store: BookingStore) -> None:
    payload = get_booking_handler(booking_id="BK-MISSING", store=store)

    assert payload == {"found": False, "booking_id": "BK-MISSING"}


def test_cancel_booking_handler_marks_booking_cancelled(store: BookingStore) -> None:
    created = create_booking_handler(
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        store=store,
    )

    payload = cancel_booking_handler(booking_id=created["booking_id"], store=store)

    assert payload["found"] is True
    assert payload["cancelled"] is True
    assert payload["status"] == BookingStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_booking_mcp_server_exposes_tools() -> None:
    tools = await booking_server.mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"create_booking", "get_booking", "cancel_booking"}


@pytest.mark.asyncio
async def test_booking_mcp_server_exposes_booking_resource_template() -> None:
    templates = await booking_server.mcp.list_resource_templates()
    uris = {getattr(template, "uri_template", template.uriTemplate) for template in templates}

    assert "bookings://{booking_id}" in uris


@pytest.mark.asyncio
async def test_booking_mcp_server_reads_booking_resource(store: BookingStore) -> None:
    created = create_booking_handler(
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        store=store,
    )

    contents = await booking_server.mcp.read_resource(f"bookings://{created['booking_id']}")

    assert contents
    assert created["booking_id"] in contents[0].content
    assert "Ana Krasniqi" in contents[0].content


def test_create_booking_tool_uses_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_handler(**kwargs: object) -> dict:
        captured.update({key: str(value) for key, value in kwargs.items()})
        return {"found": True, "booking_id": "BK-FAKE"}

    monkeypatch.setattr(booking_server, "create_booking_handler", fake_handler)

    result = booking_server.create_booking("conv1", "LH001", "Ana Krasniqi")

    assert result == {"found": True, "booking_id": "BK-FAKE"}
    assert captured["conversation_id"] == "conv1"
    assert captured["flight_id"] == "LH001"
    assert captured["passenger"] == "Ana Krasniqi"
