"""Booking MCP server — create, get, cancel bookings and booking resources."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.servers.booking_handlers import (
    cancel_booking_handler,
    create_booking_handler,
    get_booking_handler,
)
from app.mcp.servers.prompts import build_create_booking_prompt
from app.mcp.servers.resources import BOOKING_HELP

mcp = FastMCP(
    "Booking",
    instructions=(
        "Provides booking persistence tools backed by the local SQLite store: "
        "create, get, and cancel bookings."
    ),
)


@mcp.tool()
def create_booking(
    conversation_id: str,
    flight_id: str,
    passenger: str,
    booking_id: str | None = None,
) -> dict:
    """Create a pending booking for a conversation, flight, and passenger."""
    return create_booking_handler(
        conversation_id=conversation_id,
        flight_id=flight_id,
        passenger=passenger,
        booking_id=booking_id,
    )


@mcp.tool()
def get_booking(booking_id: str) -> dict:
    """Fetch one booking record by booking id."""
    return get_booking_handler(booking_id=booking_id)


@mcp.tool()
def cancel_booking(booking_id: str) -> dict:
    """Cancel one booking by booking id."""
    return cancel_booking_handler(booking_id=booking_id)


@mcp.resource("bookings://{booking_id}")
def booking(booking_id: str) -> dict:
    """Return one booking record as a read-only MCP resource."""
    return get_booking_handler(booking_id=booking_id)


@mcp.resource("bookings://help")
def booking_help() -> dict:
    """Describe the booking MCP workflow and available tools."""
    return BOOKING_HELP


@mcp.prompt()
def create_booking_request(flight_id: str, passenger: str) -> str:
    """Build a natural-language booking request."""
    return build_create_booking_prompt(flight_id=flight_id, passenger=passenger)


def main() -> None:
    """Run the standalone MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
