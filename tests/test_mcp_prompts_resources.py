"""MCP prompts and resources tests — Phase 6.6."""

import json

import pytest

from app.config import Settings
from app.mcp.client import RemoteMcpClient
from app.mcp.servers import booking_server, lufthansa_server
from app.mcp.servers.resources import BOOKING_HELP, airport_catalog


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_exposes_prompts() -> None:
    prompts = await lufthansa_server.mcp.list_prompts()
    names = {prompt.name for prompt in prompts}

    assert names == {"search_route", "flight_status"}


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_renders_search_route_prompt() -> None:
    result = await lufthansa_server.mcp.get_prompt(
        "search_route",
        {"origin": "TIA", "destination": "FRA", "from_date": "2025-09-15"},
    )

    assert result.messages
    assert "TIA" in result.messages[0].content.text
    assert "FRA" in result.messages[0].content.text


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_exposes_airport_alias_template() -> None:
    templates = await lufthansa_server.mcp.list_resource_templates()
    uris = {getattr(template, "uri_template", template.uriTemplate) for template in templates}

    assert "airport://{code}" in uris


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_exposes_airport_catalog_resource() -> None:
    resources = await lufthansa_server.mcp.list_resources()
    uris = {str(resource.uri) for resource in resources}

    assert "airports://catalog" in uris


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_reads_airport_alias_resource() -> None:
    contents = await lufthansa_server.mcp.read_resource("airport://TIA")

    assert contents
    assert "Tirana" in contents[0].content


@pytest.mark.asyncio
async def test_lufthansa_mcp_server_reads_airport_catalog_resource() -> None:
    contents = await lufthansa_server.mcp.read_resource("airports://catalog")

    assert contents
    payload = json.loads(contents[0].content)
    assert payload["resource"] == "airports"
    assert "TIA" in payload["airports"]


def test_airport_catalog_matches_static_metadata() -> None:
    catalog = airport_catalog()

    assert catalog["count"] >= 1
    assert "TIA" in catalog["airports"]


@pytest.mark.asyncio
async def test_booking_mcp_server_exposes_prompt() -> None:
    prompts = await booking_server.mcp.list_prompts()
    names = {prompt.name for prompt in prompts}

    assert names == {"create_booking_request"}


@pytest.mark.asyncio
async def test_booking_mcp_server_reads_help_resource() -> None:
    contents = await booking_server.mcp.read_resource("bookings://help")

    assert contents
    payload = json.loads(contents[0].content)
    assert payload["title"] == BOOKING_HELP["title"]
    assert "create_booking" in payload["tools"]


def test_remote_mcp_client_lists_prompts_from_lufthansa_server() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))

    prompts = client.list_prompts(server="lufthansa")

    assert prompts == ["search_route", "flight_status"]


def test_remote_mcp_client_gets_search_route_prompt() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))

    text = client.get_prompt(
        server="lufthansa",
        prompt_name="search_route",
        arguments={"origin": "TIA", "destination": "FRA", "from_date": "2025-09-15"},
    )

    assert text == "Find flights from TIA to FRA on 2025-09-15."


def test_remote_mcp_client_reads_airport_alias_without_server() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))

    payload = client.read_resource(uri="airport://TIA")

    assert "Tirana" in payload


def test_remote_mcp_client_reads_booking_help_resource() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))

    payload = client.read_resource(uri="bookings://help")

    assert "Booking workflow" in payload
