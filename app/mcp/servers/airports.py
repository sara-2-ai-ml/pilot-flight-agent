"""Static airport metadata exposed as MCP resources."""

from __future__ import annotations

AIRPORTS: dict[str, dict[str, str]] = {
    "TIA": {
        "code": "TIA",
        "name": "Tirana International Airport Nënë Tereza",
        "city": "Tirana",
        "country": "Albania",
        "timezone": "Europe/Tirane",
    },
    "FRA": {
        "code": "FRA",
        "name": "Frankfurt Airport",
        "city": "Frankfurt",
        "country": "Germany",
        "timezone": "Europe/Berlin",
    },
    "MUC": {
        "code": "MUC",
        "name": "Munich Airport",
        "city": "Munich",
        "country": "Germany",
        "timezone": "Europe/Berlin",
    },
    "JFK": {
        "code": "JFK",
        "name": "John F. Kennedy International Airport",
        "city": "New York",
        "country": "United States",
        "timezone": "America/New_York",
    },
    "CDG": {
        "code": "CDG",
        "name": "Paris Charles de Gaulle Airport",
        "city": "Paris",
        "country": "France",
        "timezone": "Europe/Paris",
    },
}


def get_airport_info(code: str) -> dict[str, str]:
    """Return metadata for one IATA airport code."""
    normalized = code.strip().upper()
    airport = AIRPORTS.get(normalized)
    if airport is None:
        return {
            "code": normalized,
            "name": "Unknown airport",
            "city": "Unknown",
            "country": "Unknown",
            "timezone": "Unknown",
        }
    return airport
