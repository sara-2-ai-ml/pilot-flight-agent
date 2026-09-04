"""Lufthansa MCP server — search_flights, get_flight_status, airport resources."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.servers.airports import get_airport_info
from app.mcp.servers.lufthansa_handlers import get_flight_status_handler, search_flights_handler
from app.mcp.servers.prompts import build_flight_status_prompt, build_search_route_prompt
from app.mcp.servers.resources import airport_catalog

mcp = FastMCP(
    "Lufthansa",
    instructions=(
        "Provides Lufthansa flight schedule search, operational flight status, "
        "and airport metadata resources."
    ),
)


@mcp.tool()
def search_flights(origin: str, destination: str, from_date: str) -> list[dict]:
    """Search scheduled flights between two IATA airports on a given date (YYYY-MM-DD)."""
    return search_flights_handler(
        origin=origin,
        destination=destination,
        from_date=from_date,
    )


@mcp.tool()
def get_flight_status(flight_number: str, date: str) -> dict:
    """Fetch operational status for one flight number on a given date (YYYY-MM-DD)."""
    return get_flight_status_handler(
        flight_number=flight_number,
        date=date,
    )


@mcp.resource("airports://{code}")
def airport(code: str) -> dict:
    """Return metadata for one IATA airport code."""
    return get_airport_info(code)


@mcp.resource("airport://{code}")
def airport_alias(code: str) -> dict:
    """Alias resource URI for one IATA airport code."""
    return get_airport_info(code)


@mcp.resource("airports://catalog")
def airports_catalog() -> dict:
    """Return the list of airports with static MCP metadata."""
    return airport_catalog()


@mcp.prompt()
def search_route(origin: str, destination: str, from_date: str) -> str:
    """Build a natural-language flight search request."""
    return build_search_route_prompt(
        origin=origin,
        destination=destination,
        from_date=from_date,
    )


@mcp.prompt()
def flight_status(flight_number: str, date: str) -> str:
    """Build a natural-language flight status request."""
    return build_flight_status_prompt(flight_number=flight_number, date=date)


def main() -> None:
    """Run the standalone MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
