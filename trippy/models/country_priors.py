"""Country-level travel preference priors from historical family ratings."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CountryPriorBand(StrEnum):
    STRONG_POSITIVE = "strong_positive"
    MIXED = "mixed"
    CAUTION = "caution"
    NEUTRAL = "neutral"


class CountryPrior(BaseModel):
    country: str
    rating: int | None = None
    band: CountryPriorBand
    confidence: float
    positive_notes: list[str] = Field(default_factory=list)
    caution_notes: list[str] = Field(default_factory=list)
    positive_signals: list[str] = Field(default_factory=list)
    caution_signals: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    planning_rules: list[str] = Field(default_factory=list)


class CountryFitSignal(BaseModel):
    country: str
    rating: int | None = None
    band: CountryPriorBand
    confidence: float
    score_adjustment: int
    rationale: str
    positive_signals: list[str] = Field(default_factory=list)
    caution_signals: list[str] = Field(default_factory=list)
    planning_rules: list[str] = Field(default_factory=list)
