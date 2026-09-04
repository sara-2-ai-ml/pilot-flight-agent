"""Reusable MCP prompt templates for flight and booking servers."""

from __future__ import annotations


def build_search_route_prompt(*, origin: str, destination: str, from_date: str) -> str:
    return (
        f"Find flights from {origin.upper()} to {destination.upper()} "
        f"on {from_date}."
    )


def build_flight_status_prompt(*, flight_number: str, date: str) -> str:
    return f"What is the status of flight {flight_number.upper()} on {date}?"


def build_create_booking_prompt(*, flight_id: str, passenger: str) -> str:
    return f"Book flight {flight_id.upper()} for {passenger.title()}."
