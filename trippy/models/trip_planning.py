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


class TravelAirportRef(BaseModel):
    """Canonical airport reference used by connector adapters."""

    iata_code: str
    name: str | None = None
    city: str | None = None
    country: str | None = None
    role: str = "gateway"

    @field_validator("iata_code")
    @classmethod
    def _iata_code_valid(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", cleaned):
            raise ValueError("iata_code must be a three-letter IATA code")
        return cleaned

    def label(self) -> str:
        parts = [self.iata_code]
        if self.city:
            parts.append(self.city)
        if self.country:
            parts.append(self.country)
        return " · ".join(parts)


class TripMapLocation(BaseModel):
    """Canonical place reference for maps, lodging, cars, and activities."""

    name: str
    kind: str = "place"
    city: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    iata_code: str | None = None
    use_for: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("map location name is required")
        return cleaned

    @field_validator("iata_code")
    @classmethod
    def _optional_iata_code_valid(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", cleaned):
            raise ValueError("iata_code must be a three-letter IATA code")
        return cleaned

    def search_label(self) -> str:
        parts = [self.name]
        for value in [self.city, self.region, self.country]:
            if value and value.casefold() not in {part.casefold() for part in parts}:
                parts.append(value)
        return ", ".join(parts)


class TripGeography(BaseModel):
    """Connector-safe canonical trip geography.

    Flight adapters should only consume ``TravelAirportRef.iata_code`` values.
    Maps, lodging, cars, and activities should consume named locations/regions.
    This prevents neighborhood or itinerary strings from leaking into flight routes.
    """

    primary_destination_name: str = ""
    primary_city: str | None = None
    country: str | None = None
    departure_airports: list[TravelAirportRef] = Field(default_factory=list)
    destination_airports: list[TravelAirportRef] = Field(default_factory=list)
    in_trip_airports: list[TravelAirportRef] = Field(default_factory=list)
    map_locations: list[TripMapLocation] = Field(default_factory=list)
    planning_regions: list[str] = Field(default_factory=list)
    lodging_search_locations: list[str] = Field(default_factory=list)
    car_search_locations: list[str] = Field(default_factory=list)
    activity_search_locations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "planning_regions",
        "lodging_search_locations",
        "car_search_locations",
        "activity_search_locations",
        "warnings",
        mode="before",
    )
    @classmethod
    def _clean_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw: list[object] = [value]
        elif isinstance(value, list):
            raw = value
        else:
            raw = [value]
        return _dedupe_strings(str(item).strip() for item in raw if str(item).strip())

    def primary_origin_iata(self, fallback: str = "YYZ") -> str:
        if self.departure_airports:
            return self.departure_airports[0].iata_code
        return fallback.strip().upper()

    def primary_gateway_iata(self) -> str | None:
        if self.destination_airports:
            return self.destination_airports[0].iata_code
        return None

    def all_airport_codes(self) -> list[str]:
        return _dedupe_strings(
            [
                *(airport.iata_code for airport in self.departure_airports),
                *(airport.iata_code for airport in self.destination_airports),
                *(airport.iata_code for airport in self.in_trip_airports),
            ]
        )

    def region_names(self) -> list[str]:
        regions = list(self.planning_regions)
        regions.extend(location.search_label() for location in self.map_locations if "planning" in location.use_for)
        if not regions and self.primary_destination_name:
            regions.append(self.primary_destination_name)
        return _dedupe_strings(regions)

    def map_seed_queries(self) -> list[str]:
        values = [location.search_label() for location in self.map_locations]
        values.extend(self.region_names())
        if self.primary_gateway_iata():
            values.append(self.primary_gateway_iata() or "")
        return _dedupe_strings(values)

    def lodging_locations(self) -> list[str]:
        values = list(self.lodging_search_locations)
        values.extend(location.search_label() for location in self.map_locations if "lodging" in location.use_for)
        values.extend(self.region_names())
        return _dedupe_strings(values)

    def car_locations(self) -> list[str]:
        values = list(self.car_search_locations)
        values.extend(
            airport.iata_code for airport in [*self.destination_airports, *self.in_trip_airports]
        )
        values.extend(location.search_label() for location in self.map_locations if "car" in location.use_for)
        return _dedupe_strings(values)

    def activity_locations(self) -> list[str]:
        values = list(self.activity_search_locations)
        values.extend(location.search_label() for location in self.map_locations if "activity" in location.use_for)
        values.extend(self.region_names())
        return _dedupe_strings(values)


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
    geography: TripGeography | None = None
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
        self._sync_geography()
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

    def _sync_geography(self) -> None:
        if self.geography is None:
            self.geography = canonicalize_trip_geography(self)
            return
        if not self.geography.departure_airports and self.departure_airports:
            self.geography.departure_airports = [
                TravelAirportRef(iata_code=code, role="origin")
                for code in self.departure_airports
                if _looks_like_iata(code)
            ]
        if not self.geography.primary_destination_name and self.destination_seeds:
            self.geography.primary_destination_name = self.destination_seeds[0]

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
    advisor: dict[str, Any] = Field(default_factory=dict)

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


def canonicalize_trip_geography(intake: TripIntake) -> TripGeography:
    """Create connector-safe geography from raw intake strings.

    This is intentionally deterministic and conservative. Known destinations receive
    strong airport/place structure. Unknown destinations keep map/search places but do
    not invent flight airport codes.
    """
    text = _searchable_intake_text(intake)
    origin_airports = [
        TravelAirportRef(iata_code=code, role="origin")
        for code in intake.departure_airports
        if _looks_like_iata(code)
    ]
    if _looks_like_chile_trip(text):
        return _chile_geography(origin_airports, text)
    if "azores" in text:
        return _azores_geography(origin_airports)
    if _looks_like_grand_cayman_trip(text):
        return _grand_cayman_geography(origin_airports)
    return _generic_geography(intake, origin_airports)


def _searchable_intake_text(intake: TripIntake) -> str:
    parts = [intake.trip_name, *intake.destination_seeds, intake.freeform_notes or ""]
    return " ".join(parts).lower().replace("_", "-")


def _chile_geography(origin_airports: list[TravelAirportRef], text: str) -> TripGeography:
    locations = [
        TripMapLocation(
            name="Santiago",
            kind="city",
            country="Chile",
            iata_code="SCL",
            use_for=["planning", "lodging", "activity", "car"],
        ),
        TripMapLocation(
            name="Providencia",
            kind="neighborhood",
            city="Santiago",
            country="Chile",
            use_for=["lodging", "activity", "map"],
        ),
        TripMapLocation(
            name="Bellavista",
            kind="neighborhood",
            city="Santiago",
            country="Chile",
            use_for=["activity", "map"],
        ),
        TripMapLocation(
            name="Barrio Italia",
            kind="neighborhood",
            city="Santiago",
            country="Chile",
            use_for=["lodging", "activity", "map"],
        ),
        TripMapLocation(
            name="Maipo Valley",
            kind="region",
            region="Santiago Metropolitan Region",
            country="Chile",
            use_for=["activity", "map", "car"],
        ),
    ]
    planning_regions = ["Santiago"]
    activity_locations = ["Santiago", "Providencia", "Bellavista", "Barrio Italia", "Maipo Valley"]
    lodging_locations = ["Providencia, Santiago, Chile", "Barrio Italia, Santiago, Chile", "Santiago, Chile"]
    car_locations = ["SCL", "Santiago, Chile", "Maipo Valley, Chile"]
    in_trip_airports: list[TravelAirportRef] = []
    if "atacama" in text or "san pedro" in text or "calama" in text:
        planning_regions.append("Atacama")
        activity_locations.append("San Pedro de Atacama")
        lodging_locations.append("San Pedro de Atacama, Chile")
        car_locations.append("CJC")
        in_trip_airports.append(
            TravelAirportRef(
                iata_code="CJC",
                name="El Loa Airport",
                city="Calama",
                country="Chile",
                role="in_trip",
            )
        )
        locations.append(
            TripMapLocation(
                name="San Pedro de Atacama",
                kind="town",
                region="Antofagasta Region",
                country="Chile",
                iata_code="CJC",
                use_for=["planning", "lodging", "activity", "car", "map"],
            )
        )
    if "patagonia" in text or "torres del paine" in text or "punta arenas" in text:
        planning_regions.append("Patagonia")
        activity_locations.append("Torres del Paine")
        lodging_locations.append("Puerto Natales, Chile")
        car_locations.append("PUQ")
        in_trip_airports.append(
            TravelAirportRef(
                iata_code="PUQ",
                name="Presidente Carlos Ibanez del Campo International Airport",
                city="Punta Arenas",
                country="Chile",
                role="in_trip",
            )
        )
        locations.append(
            TripMapLocation(
                name="Torres del Paine",
                kind="national_park",
                region="Patagonia",
                country="Chile",
                iata_code="PUQ",
                use_for=["planning", "lodging", "activity", "car", "map"],
            )
        )
    return TripGeography(
        primary_destination_name="Santiago, Chile",
        primary_city="Santiago",
        country="Chile",
        departure_airports=origin_airports,
        destination_airports=[
            TravelAirportRef(
                iata_code="SCL",
                name="Arturo Merino Benitez International Airport",
                city="Santiago",
                country="Chile",
                role="gateway",
            )
        ],
        in_trip_airports=in_trip_airports,
        map_locations=_dedupe_locations(locations),
        planning_regions=_dedupe_strings(planning_regions),
        lodging_search_locations=_dedupe_strings(lodging_locations),
        car_search_locations=_dedupe_strings(car_locations),
        activity_search_locations=_dedupe_strings(activity_locations),
        warnings=[
            "Chile geography normalized: flight search uses SCL; Santiago neighborhoods and Maipo Valley are map/search locations, not flight route codes."
        ],
    )


def _azores_geography(origin_airports: list[TravelAirportRef]) -> TripGeography:
    return TripGeography(
        primary_destination_name="Azores, Portugal",
        country="Portugal",
        departure_airports=origin_airports,
        destination_airports=[
            TravelAirportRef(
                iata_code="PDL",
                name="Joao Paulo II Airport",
                city="Ponta Delgada",
                country="Portugal",
                role="gateway",
            )
        ],
        in_trip_airports=[
            TravelAirportRef(iata_code="PIX", city="Pico", country="Portugal", role="in_trip"),
            TravelAirportRef(iata_code="HOR", city="Horta", country="Portugal", role="in_trip"),
            TravelAirportRef(iata_code="TER", city="Terceira", country="Portugal", role="in_trip"),
        ],
        map_locations=[
            TripMapLocation(name="Sao Miguel", kind="island", country="Portugal", use_for=["planning", "lodging", "activity", "car", "map"]),
            TripMapLocation(name="Ponta Delgada", kind="city", country="Portugal", iata_code="PDL", use_for=["lodging", "activity", "car", "map"]),
            TripMapLocation(name="Pico", kind="island", country="Portugal", iata_code="PIX", use_for=["planning", "lodging", "activity", "car", "map"]),
            TripMapLocation(name="Faial", kind="island", country="Portugal", iata_code="HOR", use_for=["planning", "lodging", "activity", "car", "map"]),
            TripMapLocation(name="Terceira", kind="island", country="Portugal", iata_code="TER", use_for=["planning", "lodging", "activity", "car", "map"]),
        ],
        planning_regions=["Sao Miguel", "Pico or Faial", "Terceira"],
        lodging_search_locations=["Ponta Delgada", "Furnas", "Madalena", "Horta", "Angra do Heroismo"],
        car_search_locations=["PDL", "PIX", "HOR", "TER"],
        activity_search_locations=["Sao Miguel", "Furnas", "Sete Cidades", "Pico", "Faial", "Terceira"],
    )


def _grand_cayman_geography(origin_airports: list[TravelAirportRef]) -> TripGeography:
    return TripGeography(
        primary_destination_name="Grand Cayman, Cayman Islands",
        country="Cayman Islands",
        departure_airports=origin_airports,
        destination_airports=[
            TravelAirportRef(
                iata_code="GCM",
                name="Owen Roberts International Airport",
                city="George Town",
                country="Cayman Islands",
                role="gateway",
            )
        ],
        map_locations=[
            TripMapLocation(name="Seven Mile Beach", kind="beach", country="Cayman Islands", use_for=["planning", "lodging", "activity", "map"]),
            TripMapLocation(name="West Bay", kind="district", country="Cayman Islands", use_for=["planning", "lodging", "activity", "map"]),
            TripMapLocation(name="Rum Point", kind="beach", country="Cayman Islands", use_for=["planning", "lodging", "activity", "map"]),
            TripMapLocation(name="George Town", kind="city", country="Cayman Islands", iata_code="GCM", use_for=["planning", "lodging", "activity", "car", "map"]),
        ],
        planning_regions=["Seven Mile Beach", "West Bay", "Rum Point", "George Town"],
        lodging_search_locations=["Seven Mile Beach", "West Bay", "Rum Point"],
        car_search_locations=["GCM", "Seven Mile Beach"],
        activity_search_locations=["Stingray City", "Seven Mile Beach", "West Bay", "Rum Point"],
    )


def _generic_geography(intake: TripIntake, origin_airports: list[TravelAirportRef]) -> TripGeography:
    seeds = _dedupe_strings(intake.destination_seeds or [intake.trip_name])
    destination_airports = [
        TravelAirportRef(iata_code=seed, role="gateway")
        for seed in seeds
        if _looks_like_iata(seed)
    ]
    non_airport_seeds = [seed for seed in seeds if not _looks_like_iata(seed)]
    destination = ", ".join(non_airport_seeds or seeds) or intake.trip_name
    warnings = []
    if not destination_airports:
        warnings.append(
            "No canonical gateway airport resolved yet; live flight adapters must fail closed until a valid IATA destination is known."
        )
    map_locations = [
        TripMapLocation(name=seed, use_for=["planning", "lodging", "activity", "car", "map"])
        for seed in non_airport_seeds
    ]
    return TripGeography(
        primary_destination_name=destination,
        departure_airports=origin_airports,
        destination_airports=destination_airports,
        map_locations=map_locations,
        planning_regions=non_airport_seeds or seeds,
        lodging_search_locations=non_airport_seeds or seeds,
        car_search_locations=[*(airport.iata_code for airport in destination_airports), *(non_airport_seeds or seeds)],
        activity_search_locations=non_airport_seeds or seeds,
        warnings=warnings,
    )


def _looks_like_iata(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{3}", value.strip()))


def _looks_like_chile_trip(text: str) -> bool:
    return any(
        term in text
        for term in [
            "chile",
            "santiago",
            "providencia",
            "bellavista",
            "barrio italia",
            "barrio-italia",
            "maipo",
            "atacama",
            "patagonia",
            "torres del paine",
        ]
    )


def _looks_like_grand_cayman_trip(text: str) -> bool:
    return any(
        term in text
        for term in [
            "cayman",
            "seven mile beach",
            "west bay",
            "stingray city",
            "rum point",
            "grand cayman",
        ]
    )


def _dedupe_strings(values: list[str] | tuple[str, ...] | object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:  # type: ignore[operator]
        text = " ".join(str(value).strip().split())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _dedupe_locations(locations: list[TripMapLocation]) -> list[TripMapLocation]:
    seen: set[str] = set()
    result: list[TripMapLocation] = []
    for location in locations:
        key = location.search_label().casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(location)
    return result


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
