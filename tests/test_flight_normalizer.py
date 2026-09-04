"""Flight normalizer tests — Phase 5.2 / 5.4."""

from app.models.flight import (
    FlightOption,
    FlightStatusInfo,
    normalize_flight_status_payload,
    normalize_lufthansa_payload,
    normalize_schedule_payload,
)
from app.tools.flight_normalizer import (
    normalize_flight_status_response,
    normalize_schedule_response,
)

SAMPLE_SCHEDULE_PAYLOAD = {
    "ScheduleResource": {
        "Schedule": [
            {
                "Flight": [
                    {
                        "MarketingCarrier": {"AirlineID": "LH", "FlightNumber": "400"},
                        "Departure": {
                            "AirportCode": "TIA",
                            "ScheduledTimeLocal": "2025-09-15T06:30",
                        },
                        "Arrival": {
                            "AirportCode": "FRA",
                            "ScheduledTimeLocal": "2025-09-15T08:45",
                        },
                    },
                    {
                        "MarketingCarrier": {"AirlineID": "LH", "FlightNumber": "401"},
                        "Departure": {
                            "AirportCode": "TIA",
                            "ScheduledTimeLocal": "2025-09-15T12:15",
                        },
                        "Arrival": {
                            "AirportCode": "FRA",
                            "ScheduledTimeLocal": "2025-09-15T14:30",
                        },
                    },
                ]
            }
        ]
    }
}


def test_normalize_schedule_response_maps_flights_to_domain_models() -> None:
    options = normalize_schedule_response(SAMPLE_SCHEDULE_PAYLOAD)

    assert len(options) == 2
    assert options[0].id == "LH400"
    assert options[0].origin == "TIA"
    assert options[0].destination == "FRA"
    assert options[0].carrier == "LH"


def test_normalize_schedule_response_handles_single_flight_object() -> None:
    payload = {
        "ScheduleResource": {
            "Schedule": {
                "Flight": {
                    "MarketingCarrier": {"AirlineID": "LH", "FlightNumber": "500"},
                    "Departure": {
                        "AirportCode": "TIA",
                        "ScheduledTimeLocal": "2025-09-15T18:00",
                    },
                    "Arrival": {
                        "AirportCode": "FRA",
                        "ScheduledTimeLocal": "2025-09-15T20:10",
                    },
                }
            }
        }
    }

    options = normalize_schedule_response(payload)

    assert len(options) == 1
    assert options[0].id == "LH500"


SAMPLE_STATUS_PAYLOAD = {
    "FlightStatusResource": {
        "Flights": {
            "Flight": {
                "FlightNumber": "LH400",
                "Departure": {
                    "AirportCode": "FRA",
                    "ScheduledTimeLocal": "2025-09-15T10:00",
                },
                "Arrival": {
                    "AirportCode": "JFK",
                    "ScheduledTimeLocal": "2025-09-15T13:30",
                },
                "FlightStatus": {"Definition": "On Time"},
            }
        }
    }
}


def test_normalize_flight_status_response_maps_status_model() -> None:
    status = normalize_flight_status_response(SAMPLE_STATUS_PAYLOAD)

    assert status is not None
    assert status.flight_number == "LH400"
    assert status.origin == "FRA"
    assert status.destination == "JFK"
    assert status.status == "On Time"
    assert status.date == "2025-09-15"


def test_normalize_lufthansa_payload_dispatches_schedule_payload() -> None:
    result = normalize_lufthansa_payload(SAMPLE_SCHEDULE_PAYLOAD)

    assert isinstance(result, list)
    assert all(isinstance(option, FlightOption) for option in result)


def test_normalize_lufthansa_payload_dispatches_status_payload() -> None:
    result = normalize_lufthansa_payload(SAMPLE_STATUS_PAYLOAD)

    assert isinstance(result, FlightStatusInfo)
    assert result.flight_number == "LH400"


def test_normalize_lufthansa_payload_returns_none_for_unknown_shape() -> None:
    assert normalize_lufthansa_payload({"UnknownResource": {}}) is None


def test_reexport_aliases_match_domain_normalizers() -> None:
    assert normalize_schedule_response(SAMPLE_SCHEDULE_PAYLOAD) == normalize_schedule_payload(
        SAMPLE_SCHEDULE_PAYLOAD
    )
    assert normalize_flight_status_response(SAMPLE_STATUS_PAYLOAD) == normalize_flight_status_payload(
        SAMPLE_STATUS_PAYLOAD
    )
