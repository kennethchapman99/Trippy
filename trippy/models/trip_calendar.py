"""Canonical trip calendar and booking-integrity models.

The calendar is the source of truth for date-sensitive planning. Intake dates are
rough signals, selected envelope flights lock the outer trip dates, and stay /
transfer / car / activity segments must prove they align with the current calendar
version before they can become booking-safe.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TripCalendarStatus(StrEnum):
    IDEA_WINDOW = "idea_window"
    TARGET_WINDOW = "target_window"
    OUTBOUND_SELECTED = "outbound_selected"
    ENVELOPE_LOCKED = "envelope_locked"
    STAY_PLAN_PROPOSED = "stay_plan_proposed"
    TRANSFERS_PRICED = "transfers_priced"
    CALENDAR_COMMITTED = "calendar_committed"
    BOOKING_SAFE = "booking_safe"


class CalendarDependencyStatus(StrEnum):
    UNKNOWN = "unknown"
    CURRENT = "current"
    STALE_CALENDAR_CHANGED = "stale_calendar_changed"
    PROVISIONAL_NO_ENVELOPE = "provisional_no_envelope"
    MISSING_DATES = "missing_dates"
    INVALID_REGION = "invalid_region"


class CalendarSegmentStatus(StrEnum):
    PROPOSED = "proposed"
    SELECTED = "selected"
    QUOTED = "quoted"
    BOOKED = "booked"
    STALE = "stale"


class CalendarRoughWindow(BaseModel):
    label: str | None = None
    season: str | None = None
    start_date: str = ""
    end_date: str = ""
    duration_days: int | None = None
    duration_min_days: int | None = None
    duration_max_days: int | None = None
    confidence: float = 0.35
    source: str = "intake"

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class TripEnvelope(BaseModel):
    locked: bool = False
    outbound_flight_option_id: str = ""
    return_flight_option_id: str = ""
    trip_start_datetime: str = ""
    trip_start_date: str = ""
    trip_end_datetime: str = ""
    trip_end_date: str = ""
    home_return_datetime: str = ""
    origin_airport: str = ""
    destination_airport: str = ""
    return_airport: str = ""
    home_arrival_airport: str = ""
    trip_days: int | None = None
    trip_nights: int | None = None
    timezone_notes: list[str] = Field(default_factory=list)
    source: str = "selected_flight_datetimes"


class StaySegment(BaseModel):
    segment_id: str
    sequence: int
    region: str
    location_label: str = ""
    start_date: str = ""
    end_date: str = ""
    nights: int
    lodging_option_id: str = ""
    status: CalendarSegmentStatus = CalendarSegmentStatus.PROPOSED
    check_in_status: str = "date_required"
    check_out_status: str = "date_required"
    constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("nights")
    @classmethod
    def _nights_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("stay segment nights cannot be negative")
        return value


class TransferSegment(BaseModel):
    transfer_id: str
    sequence: int
    from_region: str
    to_region: str
    from_airport: str = ""
    to_airport: str = ""
    date: str = ""
    mode: str = "unknown"
    selected_option_id: str = ""
    candidate_option_ids: list[str] = Field(default_factory=list)
    price_status: str = "unknown"
    friction_score: int | None = None
    booking_safe: bool = False
    warnings: list[str] = Field(default_factory=list)

    @field_validator("friction_score")
    @classmethod
    def _score_range(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return max(0, min(100, value))


class ActivitySlot(BaseModel):
    activity_id: str
    option_id: str = ""
    region: str = ""
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    fixed_or_flexible: str = "flexible"
    status: CalendarSegmentStatus = CalendarSegmentStatus.PROPOSED
    dependency_status: CalendarDependencyStatus = CalendarDependencyStatus.UNKNOWN
    warnings: list[str] = Field(default_factory=list)


class CarSegment(BaseModel):
    car_segment_id: str
    pickup_location: str = ""
    dropoff_location: str = ""
    pickup_datetime: str = ""
    dropoff_datetime: str = ""
    selected_option_id: str = ""
    status: CalendarSegmentStatus = CalendarSegmentStatus.PROPOSED
    dependency_status: CalendarDependencyStatus = CalendarDependencyStatus.UNKNOWN
    warnings: list[str] = Field(default_factory=list)


class TripCalendarConstraints(BaseModel):
    min_nights_by_region: dict[str, int] = Field(default_factory=dict)
    max_nights_by_region: dict[str, int] = Field(default_factory=dict)
    required_regions: list[str] = Field(default_factory=list)
    optional_regions: list[str] = Field(default_factory=list)
    avoid_transfer_after_red_eye: bool = True
    avoid_activity_on_arrival_day: bool = True
    avoid_early_activity_after_late_arrival: bool = True
    family_pace_rules: list[str] = Field(default_factory=list)
    budget_targets: dict[str, Any] = Field(default_factory=dict)
    school_or_work_constraints: list[str] = Field(default_factory=list)
    user_fixed_dates: list[str] = Field(default_factory=list)


class CalendarInvalidation(BaseModel):
    invalidated_at: datetime = Field(default_factory=datetime.utcnow)
    reason: str
    previous_calendar_version: int
    invalidated_categories: list[str] = Field(default_factory=list)
    invalidated_option_ids: list[str] = Field(default_factory=list)


class CalendarIntegrity(BaseModel):
    invariant_results: dict[str, bool] = Field(default_factory=dict)
    booking_safe: bool = False
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stale_option_ids: list[str] = Field(default_factory=list)


class TripCalendarState(BaseModel):
    trip_id: str
    schema_version: str = "trippy.trip_calendar.v1"
    status: TripCalendarStatus = TripCalendarStatus.IDEA_WINDOW
    calendar_version: int = 1
    date_dependency_hash: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    source_summary: list[str] = Field(default_factory=list)
    rough_window: CalendarRoughWindow = Field(default_factory=CalendarRoughWindow)
    trip_envelope: TripEnvelope = Field(default_factory=TripEnvelope)
    stay_segments: list[StaySegment] = Field(default_factory=list)
    transfer_segments: list[TransferSegment] = Field(default_factory=list)
    activity_slots: list[ActivitySlot] = Field(default_factory=list)
    car_segments: list[CarSegment] = Field(default_factory=list)
    constraints: TripCalendarConstraints = Field(default_factory=TripCalendarConstraints)
    invalidations: list[CalendarInvalidation] = Field(default_factory=list)
    integrity: CalendarIntegrity = Field(default_factory=CalendarIntegrity)
    artifacts: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_calendar_version(self) -> TripCalendarState:
        if self.calendar_version < 1:
            self.calendar_version = 1
        return self

    @property
    def trip_nights(self) -> int | None:
        return self.trip_envelope.trip_nights

    @property
    def envelope_locked(self) -> bool:
        return bool(self.trip_envelope.locked)

    def stay_nights_total(self) -> int:
        return sum(segment.nights for segment in self.stay_segments)
