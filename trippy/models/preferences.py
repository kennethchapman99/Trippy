"""Family travel preference model — durable, agent-readable, evidence-backed."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OptimizationPriority(str, Enum):
    COMFORT = "comfort"
    SCHEDULE = "schedule"
    DIRECT_FLIGHT = "direct_flight"
    LOCATION = "location"
    PRICE = "price"


class DepartureTimePreference(BaseModel):
    earliest_acceptable: str = "07:00"   # Will accept this departure time
    preferred_earliest: str = "08:30"    # Prefers no earlier than this
    hard_no_before: str = "05:30"        # Never book before this (exceptions below)
    early_exception_savings_cad: float | None = None  # Accept earlier if saves ≥ X/person

    def is_acceptable(self, departure_time: str) -> bool:
        """Check if a departure time (HH:MM) meets the acceptable threshold."""
        return departure_time >= self.earliest_acceptable

    def is_preferred(self, departure_time: str) -> bool:
        return departure_time >= self.preferred_earliest


class LayoverPreference(BaseModel):
    min_connection_minutes_domestic: int = 75
    min_connection_minutes_international: int = 110
    preferred_connection_minutes: int = 120
    max_layover_hours_no_hotel: float = 4.0
    avoid_airport_change: bool = True  # No busing between terminals/airports
    avoid_hubs_known_for_delays: list[str] = Field(default_factory=list)  # e.g. ["ORD", "EWR"]

    def is_connection_safe(self, minutes: int, is_international: bool) -> bool:
        minimum = (
            self.min_connection_minutes_international
            if is_international
            else self.min_connection_minutes_domestic
        )
        return minutes >= minimum

    def is_connection_preferred(self, minutes: int) -> bool:
        return minutes >= self.preferred_connection_minutes


class TransferPreference(BaseModel):
    prefer_direct_shuttle: bool = True
    max_transfer_minutes: int = 60
    avoid_metro_with_luggage: bool = True   # Family + bags + metro = friction
    avoid_bus_at_night: bool = True
    pre_book_preferred: bool = True         # Pre-book transfers rather than taxi queue


class StayPreference(BaseModel):
    min_checkin_hour: int = 15       # 3 PM minimum expected check-in
    preferred_checkin_hour: int = 15
    checkout_hour: int = 11
    require_family_room_setup: bool = True   # Must fit 5 people
    preferred_room_configs: list[str] = Field(
        default_factory=lambda: ["2_queens", "2_doubles", "suite", "2_rooms"]
    )
    preferred_stay_types: list[str] = Field(
        default_factory=lambda: ["hotel", "house", "vrbo"]
    )
    min_nights_per_destination: int = 2   # Avoid single-night hotel stops
    preferred_nights_per_destination: int = 3


class FlightPreference(BaseModel):
    preferred_cabin_short_haul: str = "economy"
    preferred_cabin_long_haul: str = "premium_economy"  # 6+ hours
    long_haul_threshold_hours: float = 6.0
    seat_preference: str = "window_aisle_pairs"  # Family can't always sit together
    prefer_direct: bool = True
    max_stops: int = 1


class FamilyTravelPreferences(BaseModel):
    departure_time: DepartureTimePreference = Field(
        default_factory=DepartureTimePreference
    )
    layover: LayoverPreference = Field(default_factory=LayoverPreference)
    transfer: TransferPreference = Field(default_factory=TransferPreference)
    stay: StayPreference = Field(default_factory=StayPreference)
    flight: FlightPreference = Field(default_factory=FlightPreference)

    # Airport logistics
    airport_buffer_minutes_domestic: int = 120
    airport_buffer_minutes_international: int = 180

    # Pacing
    max_destinations_per_week: int = 3
    prefer_slow_travel: bool = True   # Depth > breadth

    # Optimization
    priority_order: list[OptimizationPriority] = Field(
        default_factory=lambda: [
            OptimizationPriority.COMFORT,
            OptimizationPriority.SCHEDULE,
            OptimizationPriority.DIRECT_FLIGHT,
            OptimizationPriority.LOCATION,
            OptimizationPriority.PRICE,
        ]
    )

    # Self-improvement metadata
    confidence: float = 0.5    # Starts low; increases as evidence accumulates
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    source_trips: list[str] = Field(default_factory=list)  # trip_ids that informed this
    notes: str | None = None

    def to_context_string(self) -> str:
        """Render preferences as a readable string for agent system context."""
        lines = [
            "## Family Travel Preferences",
            f"- Earliest acceptable departure: {self.departure_time.earliest_acceptable}",
            f"- Preferred earliest departure: {self.departure_time.preferred_earliest}",
            f"- Hard no-fly before: {self.departure_time.hard_no_before}",
            f"- Min connection (domestic): {self.layover.min_connection_minutes_domestic} min",
            f"- Min connection (international): {self.layover.min_connection_minutes_international} min",
            f"- Preferred connection: {self.layover.preferred_connection_minutes} min",
            f"- Avoid airport change: {self.layover.avoid_airport_change}",
            f"- Max layover without hotel: {self.layover.max_layover_hours_no_hotel}h",
            f"- Cabin (short haul): {self.flight.preferred_cabin_short_haul}",
            f"- Cabin (long haul >{self.flight.long_haul_threshold_hours}h): {self.flight.preferred_cabin_long_haul}",
            f"- Prefer direct flights: {self.flight.prefer_direct}",
            f"- Hotel check-in expected: {self.stay.min_checkin_hour:02d}:00",
            f"- Min nights per destination: {self.stay.min_nights_per_destination}",
            f"- Airport buffer (domestic): {self.airport_buffer_minutes_domestic} min",
            f"- Airport buffer (international): {self.airport_buffer_minutes_international} min",
            f"- Optimization priority: {' > '.join(p.value for p in self.priority_order)}",
            f"- Confidence: {self.confidence:.0%} (based on {len(self.source_trips)} trips)",
        ]
        return "\n".join(lines)
