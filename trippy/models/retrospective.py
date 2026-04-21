"""Post-trip retrospective models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TripRetrospectiveInput(BaseModel):
    trip_id: str
    worked: list[str] = Field(default_factory=list)
    worth_money: list[str] = Field(default_factory=list)
    friction: list[str] = Field(default_factory=list)
    hard_rules: list[str] = Field(default_factory=list)
    never_repeat: list[str] = Field(default_factory=list)
    favorites: list[str] = Field(default_factory=list)
    pace: str | None = None
    expectations: str | None = None
    notes: str | None = None


class TripRetrospectiveResult(BaseModel):
    trip_id: str
    workflow_id: str
    proposal_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str
