"""Canonical Pydantic trip model — the source of truth for all trip state.

This model is designed for:
- JSON serialisation to ~/.trippy/trips/{trip_id}.json
- Injection into agent context
- Round-tripping: sheet → canonical → sheet, email → canonical → sheet
- Deterministic validation of all imported data
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TripStatus(StrEnum):
    DREAM = "dream"
    PLANNED = "planned"
    BOOKED = "booked"
    LIVED = "lived"
    CANCELLED = "cancelled"


class SegmentType(StrEnum):
    FLIGHT = "flight"
    TRAIN = "train"
    FERRY = "ferry"
    BUS = "bus"
    CAR = "car"
    OTHER = "other"


class StayType(StrEnum):
    HOTEL = "hotel"
    AIRBNB = "airbnb"
    VRBO = "vrbo"
    HOSTEL = "hostel"
    HOUSE = "house"
    OTHER = "other"


class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfirmationType(StrEnum):
    FLIGHT = "flight"
    HOTEL = "hotel"
    RENTAL = "rental"
    TOUR = "tour"
    TRANSFER = "transfer"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Traveler
# ---------------------------------------------------------------------------


class Traveler(BaseModel):
    name: str
    passport_country: str | None = None  # ISO 3166-1 alpha-3 (e.g. "CAN")
    passport_expiry: date | None = None
    date_of_birth: date | None = None
    is_minor: bool = False
    dietary_notes: str | None = None
    loyalty_numbers: dict[str, str] = Field(default_factory=dict)  # carrier → number

    @field_validator("passport_country", mode="before")
    @classmethod
    def _normalise_country(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s else None


# ---------------------------------------------------------------------------
# Segment (flight, train, etc.)
# ---------------------------------------------------------------------------


class Segment(BaseModel):
    segment_id: str  # e.g. "leg-1", "AC001-2026-03-15"
    segment_type: SegmentType = SegmentType.FLIGHT
    carrier: str | None = None
    flight_number: str | None = None
    origin: str  # IATA or city
    destination: str
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    cabin_class: str | None = None
    cost_cad: float | None = None
    confirmation_code: str | None = None
    booking_ref: str | None = None
    seat_assignments: dict[str, str] = Field(default_factory=dict)  # traveler → seat
    baggage_included: bool | None = None
    check_in_opens_at: datetime | None = None
    notes: str | None = None

    @property
    def duration_minutes(self) -> int | None:
        if self.depart_at and self.arrive_at:
            delta = self.arrive_at - self.depart_at
            return int(delta.total_seconds() / 60)
        return None

    @property
    def is_confirmed(self) -> bool:
        code = self.confirmation_code or ""
        return bool(code) and not code.upper().startswith("UNKNOWN")


# ---------------------------------------------------------------------------
# Stay (hotel, airbnb, etc.)
# ---------------------------------------------------------------------------


class Stay(BaseModel):
    stay_id: str  # e.g. "stay-1"
    stay_type: StayType = StayType.HOTEL
    property_name: str
    city: str
    country: str
    address: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    check_in_time: str | None = None  # "15:00"
    check_out_time: str | None = None  # "11:00"
    cost_cad: float | None = None
    confirmation_code: str | None = None
    num_rooms: int | None = None
    room_type: str | None = None
    notes: str | None = None

    @property
    def nights(self) -> int | None:
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return None

    @property
    def is_confirmed(self) -> bool:
        code = self.confirmation_code or ""
        return bool(code) and not code.upper().startswith("UNKNOWN")


# ---------------------------------------------------------------------------
# Confirmation (from Gmail / booking email)
# ---------------------------------------------------------------------------


class Confirmation(BaseModel):
    confirmation_id: str  # internal ID
    confirmation_type: ConfirmationType
    confirmation_code: str
    vendor: str
    raw_email_subject: str | None = None
    raw_email_path: str | None = None
    received_at: datetime | None = None
    parsed_at: datetime | None = None
    linked_segment_id: str | None = None
    linked_stay_id: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    @property
    def is_linked(self) -> bool:
        return bool(self.linked_segment_id or self.linked_stay_id)


# ---------------------------------------------------------------------------
# Risk flag (from friction detector)
# ---------------------------------------------------------------------------


class RiskFlag(BaseModel):
    risk_id: str
    severity: RiskSeverity
    category: str  # "layover" | "timing" | "missing_booking" | "document" | "transfer"
    description: str
    affected_ids: list[str] = Field(default_factory=list)  # segment_id or stay_id refs
    recommended_fix: str | None = None
    resolved: bool = False
    detected_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Checklist item
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    item_id: str
    category: str  # "booking" | "document" | "packing" | "logistics" | "visa"
    title: str
    due_by: date | None = None
    completed: bool = False
    assigned_to: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class Budget(BaseModel):
    category: str  # "flights" | "stays" | "transfers" | "activities" | "food" | "total"
    budgeted_cad: float | None = None
    booked_cad: float | None = None
    actual_cad: float | None = None

    @property
    def variance_cad(self) -> float | None:
        if self.budgeted_cad is not None and self.booked_cad is not None:
            return self.booked_cad - self.budgeted_cad
        return None


# ---------------------------------------------------------------------------
# Sync metadata (Google Sheets)
# ---------------------------------------------------------------------------


class SyncMetadata(BaseModel):
    google_sheet_id: str | None = None
    google_sheet_url: str | None = None
    last_synced_at: datetime | None = None
    last_synced_by: str | None = None  # "agent" | "human"
    sync_conflicts: list[str] = Field(default_factory=list)

    @field_validator("google_sheet_url", mode="before")
    @classmethod
    def _derive_url(cls, v: object) -> str | None:
        return str(v) if v else None


# ---------------------------------------------------------------------------
# Trip (root model)
# ---------------------------------------------------------------------------


def _make_trip_id(name: str) -> str:
    """Derive a slug trip ID from a human name like 'Japan 2026'."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


class Trip(BaseModel):
    trip_id: str
    name: str
    status: TripStatus = TripStatus.DREAM
    destination_summary: str = ""
    start_date: date | None = None
    end_date: date | None = None
    travelers: list[Traveler] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    stays: list[Stay] = Field(default_factory=list)
    confirmations: list[Confirmation] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    budgets: list[Budget] = Field(default_factory=list)
    sync: SyncMetadata = Field(default_factory=SyncMetadata)
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="before")
    @classmethod
    def _auto_trip_id(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values.get("trip_id") and values.get("name"):
            values["trip_id"] = _make_trip_id(str(values["name"]))
        return values

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def unconfirmed_segments(self) -> list[Segment]:
        return [s for s in self.segments if not s.is_confirmed]

    @property
    def unconfirmed_stays(self) -> list[Stay]:
        return [s for s in self.stays if not s.is_confirmed]

    @property
    def open_risks(self) -> list[RiskFlag]:
        return [r for r in self.risk_flags if not r.resolved]

    @property
    def high_risks(self) -> list[RiskFlag]:
        return [
            r
            for r in self.risk_flags
            if not r.resolved and r.severity in (RiskSeverity.HIGH, RiskSeverity.CRITICAL)
        ]

    @property
    def total_booked_cad(self) -> float:
        return sum(b.booked_cad or 0.0 for b in self.budgets)

    def get_segment(self, segment_id: str) -> Segment | None:
        return next((s for s in self.segments if s.segment_id == segment_id), None)

    def get_stay(self, stay_id: str) -> Stay | None:
        return next((s for s in self.stays if s.stay_id == stay_id), None)

    def summary(self) -> str:
        """One-line summary for agent context injection."""
        dates = ""
        if self.start_date:
            dates = f" ({self.start_date}"
            if self.end_date:
                dates += f"–{self.end_date}"
            dates += ")"
        risks = f" ⚠ {len(self.high_risks)} high risks" if self.high_risks else ""
        unbooked = len(self.unconfirmed_segments) + len(self.unconfirmed_stays)
        unbooked_str = f" {unbooked} unconfirmed" if unbooked else ""
        return f"{self.name}{dates} [{self.status.value}]{risks}{unbooked_str}"
