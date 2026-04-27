"""Trip idea request and comparison models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TripIdeaRequest(BaseModel):
    time_of_year: str | None = None
    duration_days: int | None = None
    budget_cad: float | None = None
    travelers: int = 5
    party_type: str | None = None
    adults: int | None = None
    children: int | None = None
    max_flight_hours: float | None = None
    direct_flight_preferred: bool = True
    goals: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    desired_vibe: str | None = None
    activity_level: str | None = None
    beach_culture_food_adventure: dict[str, int] = Field(default_factory=dict)


class TripConcept(BaseModel):
    concept_id: str
    title: str
    destinations: list[str]
    recommended_duration_days: int
    best_season: str
    estimated_cost_band_cad: str
    estimated_travel_burden: str
    estimated_flight_hours: float
    direct_flight_friendliness: int
    family_fit_score: int
    comfort_convenience_score: int
    food_score: int
    crowd_risk: int
    total_score: int
    country_prior_signals: list[str] = Field(default_factory=list)
    rationale: list[str]
    why_it_may_not_fit: list[str]
    major_risks: list[str]
    required_research: list[str]


class TripComparison(BaseModel):
    request: TripIdeaRequest
    concepts: list[TripConcept]
    recommended_concept_id: str | None = None
    scoring_notes: list[str] = Field(default_factory=list)
    advisor: dict[str, Any] = Field(default_factory=dict)
