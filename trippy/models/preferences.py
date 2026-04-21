"""Family travel preference model — durable, agent-readable, evidence-backed."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class OptimizationPriority(StrEnum):
    COMFORT = "comfort"
    SCHEDULE = "schedule"
    DIRECT_FLIGHT = "direct_flight"
    LOCATION = "location"
    PRICE = "price"


class DepartureTimePreference(BaseModel):
    earliest_acceptable: str = "07:00"  # Will accept this departure time
    preferred_earliest: str = "08:30"  # Prefers no earlier than this
    hard_no_before: str = "05:30"  # Never book before this (exceptions below)
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
    avoid_metro_with_luggage: bool = True  # Family + bags + metro = friction
    avoid_bus_at_night: bool = True
    pre_book_preferred: bool = True  # Pre-book transfers rather than taxi queue


class StayPreference(BaseModel):
    min_checkin_hour: int = 15  # 3 PM minimum expected check-in
    preferred_checkin_hour: int = 15
    checkout_hour: int = 11
    require_family_room_setup: bool = True  # Must fit 5 people
    min_beds_for_family: int = 3
    prefer_king_bed_for_adults: bool = True
    queen_requires_compelling_upside: bool = True
    preferred_room_configs: list[str] = Field(
        default_factory=lambda: ["2_queens", "2_doubles", "suite", "2_rooms"]
    )
    preferred_stay_types: list[str] = Field(default_factory=lambda: ["hotel", "house", "vrbo"])
    min_nights_per_destination: int = 2  # Avoid single-night hotel stops
    preferred_nights_per_destination: int = 3


class LodgingContextPreference(BaseModel):
    city_prefer_urban_core: bool = True
    city_prefer_boutique_hotel: bool = True
    city_airbnb_requires_exceptional_upside: bool = True
    non_city_prefer_private_rental: bool = True
    require_safe_location_signal: bool = True
    require_parking_practicality_for_rentals: bool = True


class FoodPreference(BaseModel):
    food_is_major_objective: bool = True
    value_street_food_to_michelin_range: bool = True
    score_food_access_highly: bool = True


class CrowdPreference(BaseModel):
    avoid_huge_crowds_when_possible: bool = True
    prefer_lower_crowd_alternatives: bool = True


class GroundTransportPreference(BaseModel):
    comfortable_driving_many_places: bool = True
    avoid_cramped_roads_and_bad_parking: bool = True
    city_public_transit_ok: bool = True


class ActivityPreference(BaseModel):
    prefer_safe_well_reviewed_tours: bool = True
    prefer_small_group_experiences: bool = True
    avoid_mass_market_crowd_experiences: bool = True
    prefer_activity_chill_balance: bool = True


class DestinationReadinessPreference(BaseModel):
    require_local_currency_guidance: bool = True
    require_entry_requirements_summary: bool = True
    require_health_precautions_summary: bool = True


class FlightPreference(BaseModel):
    preferred_cabin_short_haul: str = "economy"
    preferred_cabin_long_haul: str = "premium_economy"  # 6+ hours
    long_haul_threshold_hours: float = 6.0
    seat_preference: str = "window_aisle_pairs"  # Family can't always sit together
    prefer_direct: bool = True
    max_stops: int = 1


class FamilyTravelPreferences(BaseModel):
    departure_time: DepartureTimePreference = Field(default_factory=DepartureTimePreference)
    layover: LayoverPreference = Field(default_factory=LayoverPreference)
    transfer: TransferPreference = Field(default_factory=TransferPreference)
    stay: StayPreference = Field(default_factory=StayPreference)
    lodging_context: LodgingContextPreference = Field(default_factory=LodgingContextPreference)
    food: FoodPreference = Field(default_factory=FoodPreference)
    crowd: CrowdPreference = Field(default_factory=CrowdPreference)
    ground_transport: GroundTransportPreference = Field(default_factory=GroundTransportPreference)
    activity: ActivityPreference = Field(default_factory=ActivityPreference)
    destination_readiness: DestinationReadinessPreference = Field(
        default_factory=DestinationReadinessPreference
    )
    flight: FlightPreference = Field(default_factory=FlightPreference)

    # Airport logistics
    airport_buffer_minutes_domestic: int = 120
    airport_buffer_minutes_international: int = 180

    # Pacing
    max_destinations_per_week: int = 3
    prefer_slow_travel: bool = True  # Depth > breadth

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
    confidence: float = 0.5  # Starts low; increases as evidence accumulates
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
            f"- Family sleeping fit: at least {self.stay.min_beds_for_family} beds; king bed strongly preferred",
            f"- City lodging: central/walkable boutique hotel preferred: {self.lodging_context.city_prefer_boutique_hotel}",
            f"- Outside major cities: private rental preferred: {self.lodging_context.non_city_prefer_private_rental}",
            f"- Food priority: major trip objective: {self.food.food_is_major_objective}",
            f"- Avoid huge crowds when reasonable: {self.crowd.avoid_huge_crowds_when_possible}",
            f"- Prefer small-group safe tours: {self.activity.prefer_small_group_experiences}",
            f"- Require cash/entry/health guidance: {self.destination_readiness.require_local_currency_guidance}",
            f"- Min nights per destination: {self.stay.min_nights_per_destination}",
            f"- Airport buffer (domestic): {self.airport_buffer_minutes_domestic} min",
            f"- Airport buffer (international): {self.airport_buffer_minutes_international} min",
            f"- Optimization priority: {' > '.join(p.value for p in self.priority_order)}",
            f"- Confidence: {self.confidence:.0%} (based on {len(self.source_trips)} trips)",
        ]
        return "\n".join(lines)
