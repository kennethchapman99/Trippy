"""Travel source registry models."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class TravelSourceCategory(StrEnum):
    FLIGHTS = "flights"
    CITY_LODGING = "city_lodging"
    PRIVATE_LODGING = "private_lodging"
    TOURS = "tours"
    CAR_RENTALS = "car_rentals"
    DEALS = "deals"
    VALIDATION = "validation"


class SourceAccessMode(StrEnum):
    API = "api"
    MCP = "mcp"
    BROWSER_AUTOMATION = "browser_automation"
    MANUAL_HANDOFF = "manual_handoff"


class SourceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    VALIDATION = "validation"


class TravelSource(BaseModel):
    platform_name: str
    categories: list[TravelSourceCategory]
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    confidence_level: SourceConfidence = SourceConfidence.MEDIUM
    access_modes: list[SourceAccessMode] = Field(default_factory=list)
    supports_api: bool = False
    supports_mcp: bool = False
    supports_browser_automation: bool = False
    supports_manual_handoff: bool = False
    prefer_when: list[str] = Field(default_factory=list)
    avoid_when: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_support_flags(self) -> Self:
        self.supports_api = SourceAccessMode.API in self.access_modes
        self.supports_mcp = SourceAccessMode.MCP in self.access_modes
        self.supports_browser_automation = SourceAccessMode.BROWSER_AUTOMATION in self.access_modes
        self.supports_manual_handoff = SourceAccessMode.MANUAL_HANDOFF in self.access_modes
        return self


class SourcePlan(BaseModel):
    category: TravelSourceCategory
    primary: list[TravelSource] = Field(default_factory=list)
    secondary: list[TravelSource] = Field(default_factory=list)
    validation: list[TravelSource] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
