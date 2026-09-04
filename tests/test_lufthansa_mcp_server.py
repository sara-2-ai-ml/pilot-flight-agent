"""Lufthansa MCP server tests — Phase 6.2."""

import pytest

from app.config import Settings
from app.mcp.servers.airports import get_airport_info
from app.mcp.servers import lufthansa_server
from app.mcp.servers.lufthansa_handlers import get_flight_status_handler, search_flights_handler
from app.tools.flight_client import MockFlightApiClient


def test_search_flights_handler_returns_serializable_options() -> None:
    options = search_flights_handler(
        origin="TIA",
        destination="FRA",
        from_date="2025-09-15",
        flight_client=MockFlightApiClient(),
    )

    assert len(options) == 3
    assert options[0]["id"] == "LH001"
    assert options[0]["origin"] == "TIA"
    assert options[0]["destination"] == "FRA"


def test_get_flight_status_handler_returns_status_payload() -> None:
    payload = get_flight_status_handler(
        flight_number="LH400",
        date="2025-09-15",
        flight_client=MockFlightApiClient(),
    )

    assert payload["found"] is True
    assert payload["flight_number"] == "LH400"
    assert payload["status"] == "On Time"


def test_get_airport_info_returns_known_airport() -> None:
    airport = get_airport_info("tia")

    assert airport["code"] == "TIA"
    assert airport["city"] == "Tirana"


def test_get_airport_info_returns_placeholder_for_unknown_code() -> None:
    airport = get_airport_info("ZZZ")

    assert airport["code"] == "ZZZ"
    assert airport["name"] == "Unknown airport"


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_exposes_tools() -> None:
    tools = await lufthansa_server.mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"search_flights", "get_flight_status"}


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_exposes_airport_resource_template() -> None:
    templates = await lufthansa_server.mcp.list_resource_templates()
    uris = {getattr(template, "uri_template", template.uriTemplate) for template in templates}

    assert "airports://{code}" in uris


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_reads_airport_resource() -> None:
    contents = await lufthansa_server.mcp.read_resource("airports://FRA")

    assert contents
    assert "Frankfurt" in contents[0].content


def test_search_flights_tool_uses_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_handler(**kwargs: object) -> list[dict]:
        captured.update({key: str(value) for key, value in kwargs.items()})
        return [{"id": "LH999"}]

    monkeypatch.setattr(lufthansa_server, "search_flights_handler", fake_handler)

    result = lufthansa_server.search_flights("TIA", "FRA", "2025-09-15")

    assert result == [{"id": "LH999"}]
    assert captured["origin"] == "TIA"
    assert captured["destination"] == "FRA"
    assert captured["from_date"] == "2025-09-15"
