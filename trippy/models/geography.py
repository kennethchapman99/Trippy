"""Canonical geography models used to separate connector inputs.

These models are intentionally destination-agnostic. They describe resolved airports,
places, and connector-ready locations without teaching Trippy a hardcoded itinerary
for any country or city.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ResolvedAirport(BaseModel):
    """A validated airport reference that may be safely passed to flight APIs."""

    iata_code: str
    name: str = ""
    city: str = ""
    country: str = ""
    role: str = "gateway"
    confidence: float = 0.0
    source: str = "resolver"
    matched_text: str = ""
    requires_user_confirmation: bool = False

    @field_validator("iata_code")
    @classmethod
    def _valid_iata_code(cls, value: str) -> str:
        code = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("iata_code must be a three-letter IATA code")
        return code

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class ResolvedPlace(BaseModel):
    """A non-flight place reference for maps, lodging, cars, and activities."""

    name: str
    kind: str = "place"
    city: str = ""
    region: str = ""
    country: str = ""
    confidence: float = 0.0
    source: str = "resolver"
    use_for: list[str] = Field(default_factory=list)
    raw_text: str = ""

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("place name is required")
        return cleaned

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def search_label(self) -> str:
        pieces = [self.name]
        for value in [self.city, self.region, self.country]:
            if value and value.casefold() not in {piece.casefold() for piece in pieces}:
                pieces.append(value)
        return ", ".join(pieces)


class TripGeography(BaseModel):
    """Connector-safe trip geography.

    Flight connectors consume only airport codes from `origin_airports` and
    `destination_airports`. Non-flight connectors consume `places` and the explicit
    connector input buckets.
    """

    primary_destination_name: str = ""
    origin_airports: list[ResolvedAirport] = Field(default_factory=list)
    destination_airports: list[ResolvedAirport] = Field(default_factory=list)
    in_trip_airports: list[ResolvedAirport] = Field(default_factory=list)
    places: list[ResolvedPlace] = Field(default_factory=list)
    planning_regions: list[str] = Field(default_factory=list)
    map_locations: list[str] = Field(default_factory=list)
    lodging_search_locations: list[str] = Field(default_factory=list)
    car_search_locations: list[str] = Field(default_factory=list)
    activity_search_locations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    def primary_origin_iata(self, fallback: str = "YYZ") -> str:
        if self.origin_airports:
            return self.origin_airports[0].iata_code
        return fallback.strip().upper()

    def primary_destination_iata(self) -> str:
        if self.destination_airports:
            return self.destination_airports[0].iata_code
        return ""

    def connector_inputs(self) -> dict[str, Any]:
        return {
            "flights": {
                "from": self.primary_origin_iata(),
                "to": self.primary_destination_iata(),
                "status": "ready" if self.primary_destination_iata() else "airport_required",
            },
            "lodging": {"locations": self.lodging_search_locations},
            "cars": {"pickup_candidates": self.car_search_locations},
            "activities": {"locations": self.activity_search_locations},
            "maps": {"locations": self.map_locations},
        }
