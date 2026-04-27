"""Models for preference-rich LLM planning advice."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PlanningAdviceKind(StrEnum):
    TRIP_IDEAS = "trip_ideas"
    TRIP_SHAPE = "trip_shape"
    ISLAND_EXPERIENCE = "island_experience"
    LODGING_STRUCTURE = "lodging_structure"
    NEXT_STEPS = "next_steps"


class PlanningAdviceResult(BaseModel):
    """Structured result from Trippy's planning-advisor LLM call."""

    kind: PlanningAdviceKind
    status: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model: str = ""
    prompt_version: str = "planning-advisor-v1"
    prompt: str = ""
    summary: str = ""
    recommendation: str = ""
    rationale: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    questions_for_user: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_needed: list[str] = Field(default_factory=list)
    stay_strategy: str = ""
    night_plan: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    raw_response: str = ""
    error: str = ""

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))
