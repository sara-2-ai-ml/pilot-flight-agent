"""NLU domain models — extracted travel slots from user messages."""

from pydantic import BaseModel, Field


class TravelSlots(BaseModel):
    """Structured travel parameters understood from natural language."""

    intent: str = "search_flights"
    origin: str | None = None
    destination: str | None = None
    travel_date: str | None = None
    trip_type: str | None = None
    return_date: str | None = None
    passengers: int | None = None
    time_of_day: str | None = None
    airline_preference: str | None = None
    cabin_class: str | None = None
    needs_clarification: bool = False
    clarification_message: str | None = None

    @property
    def has_route(self) -> bool:
        return bool(self.origin and self.destination)
