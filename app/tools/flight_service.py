"""Flight search and validation — shared logic for the flight worker."""

import re

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.config import Settings, get_settings
from app.core.errors import (
    CIRCUIT_OPEN_USER_MESSAGE,
    ErrorCode,
    FlightUnavailableError,
    GracefulError,
)
from app.tools.flight_client import (
    FlightApiClient,
    FlightApiError,
    create_flight_api_client,
    normalize_travel_date,
)

_IATA_ROUTE_PATTERN = re.compile(
    r"\b([A-Za-z]{3})\b\s*(?:to|-)\s*\b([A-Za-z]{3})\b",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{4})?)\b",
)
_FLIGHT_NUMBER_PATTERN = re.compile(r"\b([A-Za-z]{2}\s*\d{1,4})\b")
_OPTION_INDEX_PATTERN = re.compile(
    r"\b(?:option|flight|number|#)\s*(\d+)\b",
    re.IGNORECASE,
)


_INVALID_ROUTE_CODES = frozenset(
    {
        "ONE",
        "WAY",
        "THE",
        "AND",
        "FOR",
        "NOT",
        "YOU",
        "ALL",
        "ANY",
        "BUT",
        "CAN",
        "HAD",
        "HER",
        "WAS",
        "ARE",
        "HAS",
        "HIS",
        "JUST",
        "ME",
    },
)


def parse_route(message: str) -> tuple[str | None, str | None]:
    """Extract origin and destination IATA codes from a user message."""
    match = _IATA_ROUTE_PATTERN.search(message)
    if match is None:
        return None, None
    origin = match.group(1).upper()
    destination = match.group(2).upper()
    if origin in _INVALID_ROUTE_CODES or destination in _INVALID_ROUTE_CODES:
        return None, None
    return origin, destination


def parse_travel_date(message: str) -> str | None:
    """Extract a travel date hint from a user message."""
    match = _DATE_PATTERN.search(message)
    if match is None:
        return None
    return match.group(1)


def parse_flight_number(message: str) -> str | None:
    """Extract a flight number such as LH400 from a user message."""
    for match in _FLIGHT_NUMBER_PATTERN.finditer(message):
        raw = match.group(1).replace(" ", "").upper()
        prefix = message[max(0, match.start() - 4) : match.start()].lower()
        if prefix.endswith("on ") or prefix.endswith("in "):
            continue
        carrier = raw[:2]
        number = raw[2:]
        if carrier in {"ON", "IN", "AT", "TO", "OR", "NO"} and number.isdigit() and len(number) == 4:
            continue
        return raw
    return None


def _format_departure_time(departure_time: str) -> str:
    if "T" in departure_time:
        return departure_time.split("T", maxsplit=1)[1][:5]
    return departure_time


def _departure_hour(departure_time: str) -> int | None:
    if "T" in departure_time:
        try:
            return int(departure_time.split("T", maxsplit=1)[1][:2])
        except ValueError:
            return None
    return None


def _matches_time_of_day(departure_time: str, time_of_day: str) -> bool:
    hour = _departure_hour(departure_time)
    if hour is None:
        return True
    if time_of_day == "morning":
        return hour < 12
    if time_of_day == "afternoon":
        return 12 <= hour < 17
    if time_of_day == "evening":
        return hour >= 17
    return True


def _filter_flight_options(state: AgentState, options: list) -> list:
    filtered = options
    if state.flight_search.airline_preference:
        preferred = state.flight_search.airline_preference.upper()
        airline_matches = [option for option in filtered if option.carrier.upper() == preferred]
        if airline_matches:
            filtered = airline_matches

    if state.flight_search.time_of_day:
        time_matches = [
            option
            for option in filtered
            if _matches_time_of_day(option.departure_time, state.flight_search.time_of_day)
        ]
        if time_matches:
            filtered = time_matches

    return filtered


def format_flight_results_message(state: AgentState, *, source: str) -> str:
    """Build a user-facing list of flight options after search."""
    options = state.flight_search.results
    origin = state.flight_search.origin or "origin"
    destination = state.flight_search.destination or "destination"
    travel_date = state.flight_search.date or "the requested date"
    passengers = state.flight_search.passengers
    preference_bits: list[str] = []
    if state.flight_search.time_of_day:
        preference_bits.append(state.flight_search.time_of_day)
    if state.flight_search.cabin_class:
        preference_bits.append(state.flight_search.cabin_class.replace("_", " "))
    if state.flight_search.airline_preference:
        preference_bits.append(state.flight_search.airline_preference)
    preference_label = f" ({', '.join(preference_bits)})" if preference_bits else ""

    if not options:
        return f"No {source} flights found from {origin} to {destination}."

    trip_label = ""
    if state.flight_search.trip_type == "round_trip":
        return_date = state.flight_search.return_date or "your return date"
        trip_label = f", round-trip returning {return_date}"

    lines = [
        (
            f"Found {len(options)} {source} flights from {origin} to {destination} "
            f"on {travel_date}{trip_label}{preference_label} for {passengers} passenger(s):"
        ),
        "",
        f"Outbound ({origin} → {destination}):",
    ]
    for index, option in enumerate(options, start=1):
        departure = _format_departure_time(option.departure_time)
        arrival = _format_departure_time(option.arrival_time)
        lines.append(
            f"{index}. **{option.id}** — departs {departure}, arrives {arrival} ({option.carrier})",
        )

    return_options = state.flight_search.return_results
    if return_options:
        lines.extend(["", f"Return ({destination} → {origin}):"])
        for index, option in enumerate(return_options, start=1):
            departure = _format_departure_time(option.departure_time)
            arrival = _format_departure_time(option.arrival_time)
            lines.append(
                f"{index}. **{option.id}** — departs {departure}, arrives {arrival} ({option.carrier})",
            )

    lines.extend(
        [
            "",
            "Which flight would you like? Say e.g. “Book LH001” or “the first one”.",
        ],
    )
    return "\n".join(lines)


def _select_flight_option(state: AgentState):
    """Pick a flight from search results using the user's message when possible."""
    results = state.flight_search.results
    if not results:
        return None

    flight_number = parse_flight_number(state.user_message)
    if flight_number:
        for option in results:
            if option.id.upper() == flight_number:
                return option

    lowered = state.user_message.lower()
    if any(hint in lowered for hint in ("first", "e para", "e parën", "e pare")):
        return results[0]

    index_match = _OPTION_INDEX_PATTERN.search(state.user_message)
    if index_match:
        index = int(index_match.group(1)) - 1
        if 0 <= index < len(results):
            return results[index]

    return results[0]


class FlightSearchService:
    """Search and validate flights against session state."""

    def __init__(
        self,
        settings: Settings | None = None,
        flight_client: FlightApiClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._flight_client = create_flight_api_client(
            self._settings,
            flight_client=flight_client,
        )

    def get_flight_status(
        self,
        *,
        flight_number: str,
        travel_date: str | None = None,
        state: AgentState | None = None,
    ) -> WorkerResult:
        """Fetch operational status for a specific flight number."""
        normalized_number = flight_number.replace(" ", "").upper()
        if not normalized_number:
            return WorkerResult(
                message="Please provide a valid flight number (e.g. LH400).",
                success=False,
            )

        api_date = normalize_travel_date(travel_date)
        try:
            status = self._flight_client.get_flight_status(
                flight_number=normalized_number,
                date=api_date,
            )
        except FlightApiError as exc:
            if exc.code == ErrorCode.CIRCUIT_OPEN.value:
                raise GracefulError(
                    user_message=CIRCUIT_OPEN_USER_MESSAGE,
                    code=ErrorCode.CIRCUIT_OPEN,
                    retryable=False,
                ) from exc
            raise FlightUnavailableError(
                user_message=(
                    "I couldn't retrieve live flight status right now. "
                    "Please try again later."
                ),
            ) from exc

        if status is None:
            return WorkerResult(
                message=f"No status found for flight {normalized_number}.",
                success=False,
            )

        if state is not None:
            state.flight_search.last_status = status

        source = "mock" if self._settings.flight_api_use_mock else "live"
        return WorkerResult(
            message=(
                f"{source.capitalize()} status for {status.flight_number} on {status.date}: "
                f"{status.status}."
            ),
            success=True,
        )

    def search_flights(self, state: AgentState) -> WorkerResult:
        origin = state.flight_search.origin
        destination = state.flight_search.destination
        if not origin or not destination:
            parsed_origin, parsed_destination = parse_route(state.user_message)
            origin = origin or parsed_origin
            destination = destination or parsed_destination

        if origin is None or destination is None:
            return WorkerResult(
                message=(
                    "Where would you like to go? Please tell me your departure and "
                    "destination airports (e.g. TIA to FRA) and optionally a date."
                ),
                success=False,
                error_code=ErrorCode.MISSING_ROUTE.value,
            )

        travel_date = state.flight_search.date or parse_travel_date(state.user_message)
        api_date = normalize_travel_date(travel_date)
        try:
            options = self._flight_client.search_schedules(
                origin=origin,
                destination=destination,
                from_date=api_date,
                direct_flights=True,
            )
        except FlightApiError as exc:
            if exc.code == ErrorCode.CIRCUIT_OPEN.value:
                raise GracefulError(
                    user_message=CIRCUIT_OPEN_USER_MESSAGE,
                    code=ErrorCode.CIRCUIT_OPEN,
                    retryable=False,
                ) from exc
            raise FlightUnavailableError(
                user_message=(
                    "I couldn't retrieve live flight schedules right now. "
                    "Please try again later."
                ),
            ) from exc

        if not options:
            return WorkerResult(
                message=f"No flights found from {origin} to {destination} on the requested date.",
                success=False,
            )

        if state.flight_search.trip_type is None:
            state.flight_search.trip_type = "one_way"

        options = _filter_flight_options(state, options)
        if not options:
            return WorkerResult(
                message=(
                    f"No flights matched your preferences from {origin} to {destination} "
                    "on the requested date."
                ),
                success=False,
            )

        return_options = []
        if state.flight_search.trip_type == "round_trip" and state.flight_search.return_date:
            return_api_date = normalize_travel_date(state.flight_search.return_date)
            try:
                return_options = self._flight_client.search_schedules(
                    origin=destination,
                    destination=origin,
                    from_date=return_api_date,
                    direct_flights=True,
                )
            except FlightApiError:
                return_options = []
            return_options = _filter_flight_options(state, return_options)

        state.flight_search.origin = origin
        state.flight_search.destination = destination
        state.flight_search.date = travel_date or api_date
        state.flight_search.results = options
        state.flight_search.return_results = return_options
        state.flight_search.selected_option_id = None

        source = "mock" if self._settings.flight_api_use_mock else "live"
        return WorkerResult(
            message=f"Found {len(options)} {source} flights from {origin} to {destination}.",
            success=True,
        )

    def validate_options(self, state: AgentState) -> WorkerResult:
        if not state.flight_search.results:
            return WorkerResult(
                message="No flight options are available to validate. Run search first.",
                success=False,
            )

        selected = _select_flight_option(state)
        if selected is None:
            return WorkerResult(
                message="No flight options are available to validate. Run search first.",
                success=False,
            )

        state.flight_search.selected_option_id = selected.id
        state.flight_search.origin = selected.origin
        state.flight_search.destination = selected.destination

        return WorkerResult(
            message=(
                f"Selected flight {selected.id} "
                f"({selected.origin} → {selected.destination})."
            ),
            success=True,
        )
