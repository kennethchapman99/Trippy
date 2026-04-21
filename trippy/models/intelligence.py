"""Structured travel intelligence extracted from family trip evidence."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceSourceType(StrEnum):
    TRIP = "trip"
    SHEET = "sheet"
    GMAIL = "gmail"
    FEEDBACK = "feedback"
    MANUAL = "manual"


class IntelligenceCategory(StrEnum):
    LODGING = "lodging"
    FLIGHT = "flight"
    PACING = "pacing"
    FOOD = "food"
    TRANSPORT = "transport"
    VENDOR = "vendor"
    FRICTION = "friction"
    DESTINATION = "destination"


class EvidenceRef(BaseModel):
    source_type: EvidenceSourceType
    source_id: str
    trip_id: str | None = None
    description: str


class PreferenceSignal(BaseModel):
    key: str
    category: IntelligenceCategory
    value: Any
    confidence: float
    support_count: int = 0
    evidence: list[EvidenceRef] = Field(default_factory=list)
    rationale: str


class TravelIntelligenceReport(BaseModel):
    trips_analyzed: int
    lived_trips_analyzed: int
    signals: list[PreferenceSignal] = Field(default_factory=list)
    friction_patterns: list[PreferenceSignal] = Field(default_factory=list)
    destination_affinities: list[PreferenceSignal] = Field(default_factory=list)
    vendor_patterns: list[PreferenceSignal] = Field(default_factory=list)
    summary: str

    @property
    def all_signals(self) -> list[PreferenceSignal]:
        return [
            *self.signals,
            *self.friction_patterns,
            *self.destination_affinities,
            *self.vendor_patterns,
        ]
