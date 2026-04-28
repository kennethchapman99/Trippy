"""Normalized source-backed web intelligence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WebResearchResult(BaseModel):
    id: str
    query: str
    source_url: str
    source_title: str = ""
    source_domain: str = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    extraction_type: str = "search"
    raw_markdown_excerpt: str = ""
    structured_data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    provider: str = "firecrawl"

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class FlightWebContext(BaseModel):
    airline: str = ""
    route: str = ""
    baggage_policy: str = ""
    carry_on_policy: str = ""
    checked_bag_policy: str = ""
    fare_rules: str = ""
    change_cancel_policy: str = ""
    seat_selection_notes: str = ""
    family_travel_notes: str = ""
    airport_transfer_notes: str = ""
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class LodgingWebOption(BaseModel):
    name: str = ""
    address_or_area: str = ""
    url: str = ""
    property_type: str = ""
    nightly_price_text: str = ""
    fees_text: str = ""
    cancellation_policy: str = ""
    check_in_time: str = ""
    check_out_time: str = ""
    amenities: list[str] = Field(default_factory=list)
    family_fit_notes: str = ""
    parking_notes: str = ""
    pet_policy: str = ""
    accessibility_notes: str = ""
    proximity_notes: str = ""
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class CarRentalWebOption(BaseModel):
    vendor: str = ""
    pickup_location: str = ""
    dropoff_location: str = ""
    vehicle_class: str = ""
    price_text: str = ""
    mileage_policy: str = ""
    insurance_notes: str = ""
    deposit_notes: str = ""
    child_seat_notes: str = ""
    cancellation_policy: str = ""
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class ActivityWebOption(BaseModel):
    name: str = ""
    location: str = ""
    url: str = ""
    category: str = ""
    duration: str = ""
    schedule_or_hours: str = ""
    price_text: str = ""
    age_restrictions: str = ""
    booking_required: str = ""
    cancellation_policy: str = ""
    weather_dependency: str = ""
    family_fit_notes: str = ""
    accessibility_notes: str = ""
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
