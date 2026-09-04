"""Flight domain models — search params, results, status."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class FlightOption(BaseModel):
    """One searchable flight option."""

    id: str = Field(min_length=1)
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_time: str
    arrival_time: str
    carrier: str = "LH"

    @classmethod
    def from_lufthansa_flight(cls, flight: dict[str, Any]) -> FlightOption | None:
        """Build a domain option from one Lufthansa schedule flight object."""
        departure = flight.get("Departure", {})
        arrival = flight.get("Arrival", {})
        origin = departure.get("AirportCode")
        destination = arrival.get("AirportCode")
        departure_time = departure.get("ScheduledTimeLocal")
        arrival_time = arrival.get("ScheduledTimeLocal")

        if not all([origin, destination, departure_time, arrival_time]):
            return None

        carrier_info = flight.get("MarketingCarrier", {})
        carrier = (
            carrier_info.get("AirlineID")
            or flight.get("OperatingCarrier", {}).get("AirlineID")
            or "LH"
        )
        flight_number = carrier_info.get("FlightNumber") or flight.get("FlightNumber") or "000"
        flight_id = f"{carrier}{flight_number}"

        return cls(
            id=flight_id,
            origin=str(origin).upper(),
            destination=str(destination).upper(),
            departure_time=str(departure_time),
            arrival_time=str(arrival_time),
            carrier=str(carrier).upper(),
        )

    @classmethod
    def from_aviationstack_flight(cls, flight: dict[str, Any]) -> FlightOption | None:
        """Build a domain option from one AviationStack flight object."""
        departure = flight.get("departure", {})
        arrival = flight.get("arrival", {})
        origin = departure.get("iata")
        destination = arrival.get("iata")
        departure_time = departure.get("scheduled") or departure.get("estimated")
        arrival_time = arrival.get("scheduled") or arrival.get("estimated")

        if not all([origin, destination, departure_time, arrival_time]):
            return None

        flight_info = flight.get("flight", {})
        airline = flight.get("airline", {})
        flight_id = (
            flight_info.get("iata")
            or flight_info.get("icao")
            or f"{airline.get('iata', 'XX')}{flight_info.get('number', '000')}"
        )
        carrier = airline.get("iata") or "XX"

        return cls(
            id=str(flight_id).upper(),
            origin=str(origin).upper(),
            destination=str(destination).upper(),
            departure_time=str(departure_time),
            arrival_time=str(arrival_time),
            carrier=str(carrier).upper(),
        )


class FlightStatusInfo(BaseModel):
    """Operational status for one flight on a given date."""

    flight_number: str = Field(min_length=1)
    date: str = Field(min_length=1)
    origin: str | None = None
    destination: str | None = None
    scheduled_departure: str | None = None
    scheduled_arrival: str | None = None
    status: str = "Unknown"

    @classmethod
    def from_lufthansa_flight(cls, flight: dict[str, Any]) -> FlightStatusInfo | None:
        """Build domain status from one Lufthansa flight status object."""
        departure = flight.get("Departure", {})
        arrival = flight.get("Arrival", {})
        flight_number = flight.get("FlightNumber")
        if not flight_number:
            carrier_info = flight.get("MarketingCarrier", {})
            airline = carrier_info.get("AirlineID", "LH")
            number = carrier_info.get("FlightNumber")
            if number:
                flight_number = f"{airline}{number}"
        if not flight_number:
            return None

        scheduled_departure = departure.get("ScheduledTimeLocal")
        status_block = flight.get("FlightStatus", {})
        status_text = "Unknown"
        if isinstance(status_block, dict):
            status_text = status_block.get("Definition") or status_block.get("Code") or status_text

        travel_date = (
            scheduled_departure.split("T", maxsplit=1)[0]
            if scheduled_departure
            else date.today().isoformat()
        )

        return cls(
            flight_number=str(flight_number).upper(),
            date=travel_date,
            origin=departure.get("AirportCode"),
            destination=arrival.get("AirportCode"),
            scheduled_departure=scheduled_departure,
            scheduled_arrival=arrival.get("ScheduledTimeLocal"),
            status=str(status_text),
        )

    @classmethod
    def from_aviationstack_flight(cls, flight: dict[str, Any]) -> FlightStatusInfo | None:
        """Build domain status from one AviationStack flight object."""
        flight_info = flight.get("flight", {})
        flight_number = (
            flight_info.get("iata")
            or flight_info.get("icao")
            or flight_info.get("number")
        )
        if not flight_number:
            return None

        departure = flight.get("departure", {})
        arrival = flight.get("arrival", {})
        scheduled_departure = departure.get("scheduled") or departure.get("estimated")
        travel_date = flight.get("flight_date") or (
            scheduled_departure.split("T", maxsplit=1)[0]
            if scheduled_departure
            else date.today().isoformat()
        )
        status_text = _format_aviationstack_status(flight.get("flight_status"))

        return cls(
            flight_number=str(flight_number).upper(),
            date=str(travel_date),
            origin=departure.get("iata"),
            destination=arrival.get("iata"),
            scheduled_departure=scheduled_departure,
            scheduled_arrival=arrival.get("scheduled") or arrival.get("estimated"),
            status=status_text,
        )


class FlightSearchState(BaseModel):
    origin: str | None = None
    destination: str | None = None
    date: str | None = None
    trip_type: str | None = None
    return_date: str | None = None
    passengers: int = 1
    time_of_day: str | None = None
    airline_preference: str | None = None
    cabin_class: str | None = None
    return_results: list[FlightOption] = Field(default_factory=list)
    trip_details_asked: bool = False
    preferences_asked: bool = False
    results: list[FlightOption] = Field(default_factory=list)
    selected_option_id: str | None = None
    last_status: FlightStatusInfo | None = None


def _format_aviationstack_status(raw_status: Any) -> str:
    if not raw_status:
        return "Unknown"
    normalized = str(raw_status).replace("_", " ").strip().lower()
    return normalized.title()


def normalize_aviationstack_flights_payload(payload: dict[str, Any]) -> list[FlightOption]:
    """Convert an AviationStack /flights payload into domain flight options."""
    options: list[FlightOption] = []
    seen_ids: set[str] = set()

    for entry in _as_list(payload.get("data")):
        option = FlightOption.from_aviationstack_flight(entry)
        if option is None or option.id in seen_ids:
            continue
        seen_ids.add(option.id)
        options.append(option)

    return options


def normalize_aviationstack_status_payload(payload: dict[str, Any]) -> FlightStatusInfo | None:
    """Convert an AviationStack /flights payload into one domain status record."""
    for entry in _as_list(payload.get("data")):
        status = FlightStatusInfo.from_aviationstack_flight(entry)
        if status is not None:
            return status
    return None


def normalize_schedule_payload(payload: dict[str, Any]) -> list[FlightOption]:
    """Convert a Lufthansa schedules API payload into domain flight options."""
    schedule_resource = payload.get("ScheduleResource", {})
    options: list[FlightOption] = []

    for schedule in _as_list(schedule_resource.get("Schedule")):
        for flight in _as_list(schedule.get("Flight")):
            option = FlightOption.from_lufthansa_flight(flight)
            if option is not None:
                options.append(option)

    return options


def normalize_flight_status_payload(payload: dict[str, Any]) -> FlightStatusInfo | None:
    """Convert a Lufthansa flight status payload into a domain model."""
    resource = payload.get("FlightStatusResource", {})
    flights = resource.get("Flights", {})
    flight = flights.get("Flight")
    for entry in _as_list(flight):
        status = FlightStatusInfo.from_lufthansa_flight(entry)
        if status is not None:
            return status
    return None


def normalize_lufthansa_payload(
    payload: dict[str, Any],
) -> list[FlightOption] | FlightStatusInfo | None:
    """Dispatch Lufthansa API JSON to the correct domain normalization."""
    if "ScheduleResource" in payload:
        return normalize_schedule_payload(payload)
    if "FlightStatusResource" in payload:
        return normalize_flight_status_payload(payload)
    return None
