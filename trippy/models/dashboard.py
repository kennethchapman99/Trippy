"""Dashboard models for past trips, planned trips, and ideas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DashboardLink(BaseModel):
    label: str
    url: str


class DashboardTripTile(BaseModel):
    trip_id: str
    name: str
    status: str
    destination: str
    date_label: str
    family_fit_score: int
    comfort_score: int
    budget_band: str
    planning_completeness: int
    hero_label: str
    quick_links: list[DashboardLink] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)


class DashboardIdeaTile(BaseModel):
    concept_id: str
    title: str
    destination: str
    why_interesting: str
    constraints: list[str] = Field(default_factory=list)
    estimated_cost_band: str
    estimated_travel_burden: str
    family_fit_score: int
    comfort_score: int
    comparison_notes: list[str] = Field(default_factory=list)
    promote_to_planning_action: str


class TravelDashboard(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    past_trips: list[DashboardTripTile] = Field(default_factory=list)
    planned_trips: list[DashboardTripTile] = Field(default_factory=list)
    ideas: list[DashboardIdeaTile] = Field(default_factory=list)
    exports: dict[str, str] = Field(default_factory=dict)
