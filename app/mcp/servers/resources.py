"""Static MCP resource payloads."""

from __future__ import annotations

from app.mcp.servers.airports import AIRPORTS


def airport_catalog() -> dict[str, object]:
    """List supported airport codes exposed as MCP resources."""
    return {
        "resource": "airports",
        "count": len(AIRPORTS),
        "airports": sorted(AIRPORTS.keys()),
    }


BOOKING_HELP = {
    "title": "Booking workflow",
    "steps": [
        "Search flights with the Lufthansa MCP server.",
        "Validate or select a flight option in agent state.",
        "Create a booking with conversation_id, flight_id, and passenger.",
        "Confirm pending bookings through human approval (Phase 7).",
    ],
    "tools": ["create_booking", "get_booking", "cancel_booking"],
}
