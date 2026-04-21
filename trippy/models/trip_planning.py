"""Models for new-trip intake, deterministic planning drafts, and workspaces."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TripIntakeMode(StrEnum):
    IDEA = "idea"
    SELECTED_DESTINATION = "selected_destination"


class TripPace(StrEnum):
    RELAXED = "relaxed"
    BALANCED = "balanced"
    ACTIVE = "active"


class CrowdTolerance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FoodPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TripPartyType(StrEnum):
    WHOLE_FAMILY = "whole_family"
    ADULTS_ONLY = "adults_only"
    COUPLE = "couple"
    SUBSET_FAMILY = "subset_family"
    FAMILY_PLUS_OTHERS = "family_plus_others"
    CUSTOM = "custom"


class TravelerAgeBand(StrEnum):
    ADULT = "adult"
    TEEN = "teen"
    CHILD = "child"
    INFANT = "infant"


class WorkspaceStatus(StrEnum):
    PREPARED_LOCAL = "prepared_local"
    SHEET_CREATED = "sheet_created"
    SHEET_FAILED = "sheet_failed"


class TravelWindow(BaseModel):
    label: str | None = None
    season: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> TravelWindow:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("travel window end_date must be on or after start_date")
        return self

    def display(self) -> str:
        if self.start_date and self.end_date:
            return f"{self.start_date} to {self.end_date}"
        if self.start_date:
            return str(self.start_date)
        return self.label or self.season or "timing TBD"


class FlightPreferenceInput(BaseModel):
    prefer_direct: bool = True
    max_stops: int | None = 1
    preferred_cabin: str | None = None
    loyalty_programs: list[str] = Field(default_factory=lambda: ["Aeroplan"])
    notes: str | None = None


class LodgingPreferenceInput(BaseModel):
    preferred_types: list[str] = Field(default_factory=list)
    city_strategy: str = "central boutique hotel when in cities"
    non_city_strategy: str = (
        "private rental or small hotel with safe location and practical parking"
    )
    min_beds: int = 3
    king_bed_preferred: bool = True
    notes: str | None = None


class CarRentalExpectation(BaseModel):
    needed: bool | None = None
    preferred_vehicle: str | None = "comfortable SUV or minivan for family of 5 plus bags"
    notes: str | None = None


class TripTraveler(BaseModel):
    name: str
    age: int | None = None
    age_band: TravelerAgeBand | None = None
    is_child: bool | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("traveler name is required")
        return cleaned

    @field_validator("age")
    @classmethod
    def _age_valid(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("traveler age cannot be negative")
        return value

    @model_validator(mode="after")
    def _infer_child_status(self) -> TripTraveler:
        if self.is_child is None:
            if self.age is not None:
                self.is_child = self.age < 18
            elif self.age_band is not None:
                self.is_child = self.age_band != TravelerAgeBand.ADULT
        return self

    def label(self) -> str:
        details = []
        if self.age is not None:
            details.append(f"age {self.age}")
        elif self.age_band:
            details.append(self.age_band.value)
        if self.notes:
            details.append(self.notes)
        return self.name if not details else f"{self.name} ({', '.join(details)})"


class TripParty(BaseModel):
    party_type: TripPartyType = TripPartyType.WHOLE_FAMILY
    adults: int = 2
    children: int = 3
    child_ages: list[int] = Field(default_factory=list)
    roster: list[TripTraveler] = Field(default_factory=list)
    total_travelers: int = 0
    explicit: bool = False
    defaulted_from_family_profile: bool = True
    sleeping_considerations: str | None = None
    separate_rooms_preferred: bool = False
    privacy_needs: str | None = None
    mobility_notes: str | None = None
    child_friendliness_notes: str | None = None
    notes: str | None = None

    @field_validator("adults", "children")
    @classmethod
    def _counts_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("traveler counts cannot be negative")
        return value

    @field_validator("child_ages")
    @classmethod
    def _child_ages_valid(cls, value: list[int]) -> list[int]:
        if any(age < 0 for age in value):
            raise ValueError("child ages cannot be negative")
        return value

    @model_validator(mode="after")
    def _sync_roster_counts(self) -> TripParty:
        if self.roster:
            self.adults = sum(1 for traveler in self.roster if traveler.is_child is False)
            self.children = sum(1 for traveler in self.roster if traveler.is_child is True)
            unknown = len(self.roster) - self.adults - self.children
            if unknown:
                self.adults += unknown
            self.child_ages = [
                traveler.age
                for traveler in self.roster
                if traveler.is_child is True and traveler.age is not None
            ]
        if self.party_type == TripPartyType.COUPLE:
            self.adults = max(self.adults, 2)
            self.children = 0
        elif self.party_type == TripPartyType.ADULTS_ONLY:
            self.children = 0
        self.total_travelers = len(self.roster) if self.roster else self.adults + self.children
        return self

    @property
    def has_children(self) -> bool:
        return self.children > 0

    def traveler_labels(self) -> list[str]:
        if self.roster:
            return [traveler.label() for traveler in self.roster]
        labels = [f"Adult {idx}" for idx in range(1, self.adults + 1)]
        labels.extend(f"Child {idx}" for idx in range(1, self.children + 1))
        return labels

    def summary(self) -> str:
        pieces = [
            self.party_type.value.replace("_", " "),
            f"{self.total_travelers} traveler(s)",
            f"{self.adults} adult(s)",
            f"{self.children} child(ren)",
        ]
        if self.child_ages:
            pieces.append("child ages " + ", ".join(str(age) for age in self.child_ages))
        if not self.explicit:
            pieces.append("defaulted; confirm roster")
        return "; ".join(pieces)


class TripIntake(BaseModel):
    trip_id: str = ""
    mode: TripIntakeMode = TripIntakeMode.SELECTED_DESTINATION
    trip_name: str
    destination_seeds: list[str] = Field(default_factory=list)
    travel_window: TravelWindow = Field(default_factory=TravelWindow)
    duration_days: int | None = None
    duration_min_days: int | None = None
    duration_max_days: int | None = None
    duration_label: str | None = None
    travelers: int = 5
    party: TripParty = Field(default_factory=TripParty)
    departure_airports: list[str] = Field(default_factory=lambda: ["YYZ"])
    budget_cad: float | None = None
    max_travel_time_hours: float | None = None
    flight_preferences: FlightPreferenceInput = Field(default_factory=FlightPreferenceInput)
    goals: list[str] = Field(default_factory=list)
    avoidances: list[str] = Field(default_factory=list)
    pace: TripPace = TripPace.BALANCED
    crowd_tolerance: CrowdTolerance = CrowdTolerance.LOW
    food_priority: FoodPriority = FoodPriority.HIGH
    lodging_preferences: LodgingPreferenceInput = Field(default_factory=LodgingPreferenceInput)
    car_rental_expectations: CarRentalExpectation = Field(default_factory=CarRentalExpectation)
    freeform_notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="before")
    @classmethod
    def _coerce_duration_input(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw_duration = data.get("duration_days")
        raw_label = data.get("duration_label")
        parsed = _parse_duration(raw_duration if raw_duration not in (None, "") else raw_label)
        if parsed:
            target, min_days, max_days, label = parsed
            data.setdefault("duration_min_days", min_days)
            data.setdefault("duration_max_days", max_days)
            data.setdefault("duration_label", label)
            data["duration_days"] = target
        return data

    @field_validator("trip_name")
    @classmethod
    def _trip_name_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("trip_name is required")
        return cleaned

    @field_validator(
        "destination_seeds", "departure_airports", "goals", "avoidances", mode="before"
    )
    @classmethod
    def _clean_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raw: list[object] = value if isinstance(value, list) else [value]
        return [str(item).strip() for item in raw if str(item).strip()]

    @field_validator("travelers")
    @classmethod
    def _travelers_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("travelers must be positive")
        return value

    @field_validator("duration_days")
    @classmethod
    def _duration_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("duration_days must be positive")
        return value

    @model_validator(mode="after")
    def _validate_mode(self) -> TripIntake:
        if not self.trip_id:
            self.trip_id = make_trip_slug(self.trip_name)
        if self.mode == TripIntakeMode.SELECTED_DESTINATION and not self.destination_seeds:
            raise ValueError("selected_destination intake requires at least one destination seed")
        if not self.departure_airports:
            self.departure_airports = ["YYZ"]
        self._sync_party_with_travelers()
        self._sync_duration_range()
        return self

    def _sync_party_with_travelers(self) -> None:
        party_total = self.party.total_travelers
        if self.party.explicit:
            self.travelers = party_total
            return
        if party_total != self.travelers:
            adults = min(2, self.travelers)
            self.party.adults = adults
            self.party.children = max(0, self.travelers - adults)
            self.party.total_travelers = self.travelers
            self.party.defaulted_from_family_profile = True

    def _sync_duration_range(self) -> None:
        if self.duration_days is not None:
            if self.duration_min_days is None:
                self.duration_min_days = self.duration_days
            if self.duration_max_days is None:
                self.duration_max_days = self.duration_days
        if (
            self.duration_min_days is not None
            and self.duration_max_days is not None
            and self.duration_max_days < self.duration_min_days
        ):
            raise ValueError("duration_max_days must be on or after duration_min_days")
        if (
            self.duration_days is None
            and self.duration_min_days is not None
            and self.duration_max_days is not None
        ):
            self.duration_days = round((self.duration_min_days + self.duration_max_days) / 2)

    def duration_display(self) -> str:
        if self.duration_label:
            return self.duration_label
        if (
            self.duration_min_days
            and self.duration_max_days
            and self.duration_min_days != self.duration_max_days
        ):
            return f"{self.duration_min_days}-{self.duration_max_days} days"
        if self.duration_days:
            return f"{self.duration_days} days"
        return "duration TBD"

    def party_summary(self) -> str:
        return self.party.summary()


class TripPlanOption(BaseModel):
    option_id: str
    title: str
    summary: str
    duration_days: int
    regions: list[str]
    nights_by_region: dict[str, int] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    travel_burden: str
    island_region_movement_friction: str
    family_comfort_score: int
    food_fit: str
    driving_fit: str
    crowd_fit: str
    major_risks: list[str] = Field(default_factory=list)
    recommendation_strength: int
    lodging_strategy: str
    car_strategy: str
    country_prior_signals: list[str] = Field(default_factory=list)
    map_seed_queries: list[str] = Field(default_factory=list)
    required_research: list[str] = Field(default_factory=list)

    @field_validator("family_comfort_score", "recommendation_strength")
    @classmethod
    def _score_range(cls, value: int) -> int:
        return max(0, min(100, value))


class TripPlanDraft(BaseModel):
    trip_id: str
    intake_mode: TripIntakeMode
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    options: list[TripPlanOption]
    recommended_option_id: str | None = None
    selected_option_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)

    def get_option(self, option_id: str | None = None) -> TripPlanOption | None:
        selected = option_id or self.selected_option_id or self.recommended_option_id
        if not selected:
            return None
        return next((option for option in self.options if option.option_id == selected), None)


class WorkspaceTab(BaseModel):
    name: str
    headers: list[str]
    rows: list[list[Any]] = Field(default_factory=list)


class TripWorkspaceState(BaseModel):
    trip_id: str
    plan_option_id: str
    status: WorkspaceStatus
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    canonical_trip_path: str | None = None
    local_workspace_path: str | None = None
    google_sheet_id: str | None = None
    google_sheet_url: str | None = None
    tabs: list[WorkspaceTab] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


def make_trip_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "trip"


def _parse_duration(value: object) -> tuple[int, int, int, str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("duration_days must be positive")
        return value, value, value, f"{value} days"
    text = str(value).strip().lower()
    if not text:
        return None
    range_match = re.search(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", text)
    if range_match:
        low = int(range_match.group(1))
        high = int(range_match.group(2))
        if low <= 0 or high <= 0:
            raise ValueError("duration range must be positive")
        if high < low:
            low, high = high, low
        target = round((low + high) / 2)
        return target, low, high, f"{low}-{high} days"
    single = re.search(r"(\d+)", text)
    if single:
        days = int(single.group(1))
        if days <= 0:
            raise ValueError("duration_days must be positive")
        return days, days, days, f"{days} days"
    return None
