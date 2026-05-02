"""Structured exact-research shortlist models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from trippy.models.source_research import EvidenceArtifact


class ShortlistCategory(StrEnum):
    FLIGHTS = "flights"
    LODGING = "lodging"
    CARS = "cars"
    ACTIVITIES = "activities"


class LiveDataStatus(StrEnum):
    LIVE_VERIFIED = "live_verified"
    HANDOFF_REQUIRED = "handoff_required"
    SEARCH_LINK_ONLY = "search_link_only"
    PARTIAL = "partial"


class RecommendationGrade(StrEnum):
    STRONG = "strong"
    GOOD = "good"
    CONDITIONAL = "conditional"
    WEAK = "weak"


class ShortlistRowStatus(StrEnum):
    SEEDED = "seeded"
    RESEARCHED = "researched"
    VERIFIED_LIVE = "verified_live"
    STALE = "stale"
    REJECTED = "rejected"
    APPROVED = "approved"
    BOOKED = "booked"
    CONFIRMED = "confirmed"


class VerificationStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    MANUAL_REQUIRED = "manual_required"
    LINK_VALIDATED = "link_validated"
    LIVE_VERIFIED = "live_verified"
    PARTIAL = "partial"
    FAILED = "failed"


class FreshnessStatus(StrEnum):
    UNKNOWN = "unknown"
    CURRENT = "current"
    STALE = "stale"


class AvailabilityStatus(StrEnum):
    UNKNOWN = "unknown"
    SEARCH_AVAILABLE = "search_available"
    AVAILABILITY_SIGNAL = "availability_signal"
    UNAVAILABLE_SIGNAL = "unavailable_signal"


class PriceStatus(StrEnum):
    UNKNOWN = "unknown"
    ESTIMATED_BAND = "estimated_band"
    LIVE_SIGNAL = "live_signal"


class SourceType(StrEnum):
    SEARCH_HANDOFF = "search_handoff"
    LIVE_SEARCH = "live_search"
    DIRECT_LISTING = "direct_listing"
    VALIDATION = "validation"
    MANUAL = "manual"


class LodgingFitCategory(StrEnum):
    TECHNICAL = "technical_fit"
    COMFORTABLE = "comfortable_fit"
    PREFERRED = "preferred_fit"
    WEAK = "weak_fit"


class SourceValidation(BaseModel):
    source_name: str = ""
    source_type: SourceType = SourceType.SEARCH_HANDOFF
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    verified_at: datetime | None = None
    freshness_status: FreshnessStatus = FreshnessStatus.UNKNOWN
    verification_status: VerificationStatus = VerificationStatus.MANUAL_REQUIRED
    availability_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    price_status: PriceStatus = PriceStatus.ESTIMATED_BAND
    confidence: float = 0.45
    evidence_url: str = ""
    adapter_used: str = ""
    research_run_id: str = ""
    evidence_artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class FlightOption(BaseModel):
    option_id: str
    rank: int
    airline: str
    airline_logo_url: str = ""
    flight_numbers: list[str] = Field(default_factory=list)
    departure_date: str = ""
    arrival_date: str = ""
    departure_airport: str
    arrival_airport: str
    departure_time: str = ""
    arrival_time: str = ""
    stops: int
    layover_airports: list[str] = Field(default_factory=list)
    layover_duration: str | None = None
    total_travel_duration: str
    timing_fit: str = ""
    timing_implication: str = ""
    date_viability_signal: str = ""
    recommendation_label: str = ""
    recommendation_rationale: str = ""
    planning_next_step: str = ""
    fare_estimate_cad: str
    price_band: str
    baggage_cabin_notes: str
    booking_source: str
    deep_link: str
    traveler_count: int = 0
    traveler_fit: str = ""
    comparison_links: dict[str, str] = Field(default_factory=dict)
    aeroplan_relevance: str | None = None
    friction_score: int
    family_comfort_score: int
    recommendation_grade: RecommendationGrade
    tradeoffs: list[str] = Field(default_factory=list)
    friction_flags: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    flight_phase: str = "departure"
    live_data_status: LiveDataStatus = LiveDataStatus.HANDOFF_REQUIRED
    row_status: ShortlistRowStatus = ShortlistRowStatus.RESEARCHED
    validation: SourceValidation = Field(default_factory=SourceValidation)

    @field_validator("friction_score", "family_comfort_score")
    @classmethod
    def _score_range(cls, value: int) -> int:
        return max(0, min(100, value))


class LodgingOption(BaseModel):
    option_id: str
    rank: int
    source: str
    name: str
    location_area: str
    island_or_region: str
    lodging_type: str
    room_layout: str = ""
    bed_layout: str
    adult_child_fit: str = ""
    traveler_roster_supported: bool | None = None
    min_three_beds_satisfied: bool | None
    king_bed_preference_satisfied: bool | None
    family_of_five_fit: bool | None
    separate_room_privacy_fit: bool | None = None
    occupancy_fit: str = ""
    comfort_fit: str = ""
    fit_category: LodgingFitCategory = LodgingFitCategory.TECHNICAL
    bed_layout_confidence: float = 0.35
    current_availability_signal: str = ""
    current_price_signal: str = ""
    parking_practicality: str
    driving_practicality: str
    walkability: str
    cancellation_notes: str
    price_band: str
    deep_link: str
    photo_urls: list[str] = Field(default_factory=list)
    validation_links: dict[str, str] = Field(default_factory=dict)
    friction_score: int
    family_comfort_score: int
    recommendation_grade: RecommendationGrade
    tradeoffs: list[str] = Field(default_factory=list)
    friction_flags: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    live_data_status: LiveDataStatus = LiveDataStatus.HANDOFF_REQUIRED
    row_status: ShortlistRowStatus = ShortlistRowStatus.RESEARCHED
    validation: SourceValidation = Field(default_factory=SourceValidation)

    @field_validator("friction_score", "family_comfort_score")
    @classmethod
    def _score_range(cls, value: int) -> int:
        return max(0, min(100, value))

    @field_validator("bed_layout_confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class CarOption(BaseModel):
    option_id: str
    rank: int
    booking_source: str
    pickup_location: str
    dropoff_location: str
    vehicle_class: str
    price_band: str = "live quote required"
    current_price_signal: str = ""
    seating_capacity: int | None = None
    passenger_fit: str
    luggage_fit: str
    cancellation_notes: str
    fees_caution: str
    deep_link: str
    photo_urls: list[str] = Field(default_factory=list)
    comparison_links: dict[str, str] = Field(default_factory=dict)
    family_comfort_score: int
    luggage_practicality_score: int
    pickup_dropoff_simplicity_score: int
    driving_parking_suitability_score: int
    total_friction_score: int
    recommendation_grade: RecommendationGrade
    tradeoffs: list[str] = Field(default_factory=list)
    friction_flags: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    live_data_status: LiveDataStatus = LiveDataStatus.HANDOFF_REQUIRED
    row_status: ShortlistRowStatus = ShortlistRowStatus.RESEARCHED
    validation: SourceValidation = Field(default_factory=SourceValidation)

    @field_validator(
        "family_comfort_score",
        "luggage_practicality_score",
        "pickup_dropoff_simplicity_score",
        "driving_parking_suitability_score",
        "total_friction_score",
    )
    @classmethod
    def _score_range(cls, value: int) -> int:
        return max(0, min(100, value))


class ActivityOption(BaseModel):
    option_id: str
    rank: int
    activity_name: str
    source: str
    island_location: str
    group_size_signal: str
    review_safety_signal: str
    age_family_fit: str = ""
    price_band: str
    duration: str
    suggested_day: int | None = None
    suggested_date: str = ""
    suggested_start_time: str = ""
    suggested_end_time: str = ""
    scheduling_rationale: str = ""
    scheduled_day: int | None = None
    scheduled_date: str = ""
    scheduled_start_time: str = ""
    scheduled_end_time: str = ""
    scheduled_flexibility: str = "flexible"
    scheduling_notes: str = ""
    deep_link: str
    photo_urls: list[str] = Field(default_factory=list)
    validation_links: dict[str, str] = Field(default_factory=dict)
    family_pace_fit_score: int
    safety_confidence_score: int
    crowd_fit_score: int
    total_friction_score: int
    recommendation_grade: RecommendationGrade
    tradeoffs: list[str] = Field(default_factory=list)
    friction_flags: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    live_data_status: LiveDataStatus = LiveDataStatus.HANDOFF_REQUIRED
    row_status: ShortlistRowStatus = ShortlistRowStatus.RESEARCHED
    validation: SourceValidation = Field(default_factory=SourceValidation)

    @field_validator(
        "family_pace_fit_score",
        "safety_confidence_score",
        "crowd_fit_score",
        "total_friction_score",
    )
    @classmethod
    def _score_range(cls, value: int) -> int:
        return max(0, min(100, value))


class ResearchShortlistState(BaseModel):
    trip_id: str
    category: ShortlistCategory
    selected_plan_option_id: str | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    source_routing: dict[str, Any] = Field(default_factory=dict)
    flight_options: list[FlightOption] = Field(default_factory=list)
    lodging_options: list[LodgingOption] = Field(default_factory=list)
    car_options: list[CarOption] = Field(default_factory=list)
    activity_options: list[ActivityOption] = Field(default_factory=list)
    recommended_option_id: str | None = None
    recommendation_summary: str = ""
    partial_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)

    @property
    def option_count(self) -> int:
        return (
            len(self.flight_options)
            + len(self.lodging_options)
            + len(self.car_options)
            + len(self.activity_options)
        )

    def options_as_dicts(self) -> list[dict[str, Any]]:
        if self.category == ShortlistCategory.FLIGHTS:
            return [option.model_dump(mode="json") for option in self.flight_options]
        if self.category == ShortlistCategory.LODGING:
            return [option.model_dump(mode="json") for option in self.lodging_options]
        if self.category == ShortlistCategory.CARS:
            return [option.model_dump(mode="json") for option in self.car_options]
        return [option.model_dump(mode="json") for option in self.activity_options]
