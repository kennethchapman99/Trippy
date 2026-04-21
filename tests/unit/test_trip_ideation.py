"""Tests for family-fit trip concept comparison."""

from __future__ import annotations

from trippy.models.ideas import TripIdeaRequest
from trippy.services.trip_ideation import TripIdeationService


def test_trip_ideas_rank_food_focused_options() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            duration_days=10,
            max_flight_hours=8,
            goals=["food", "culture"],
            avoid=["crowds"],
        )
    )

    assert comparison.concepts
    top = comparison.concepts[0]
    assert top.food_score >= 88
    assert top.required_research
    assert comparison.recommended_concept_id == top.concept_id


def test_trip_ideas_penalize_long_flights_for_short_max() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            duration_days=7,
            max_flight_hours=6,
            goals=["food"],
            avoid=["crowds"],
        )
    )

    japan = next(c for c in comparison.concepts if c.concept_id == "japan-food-rail-cities")
    assert any("exceeds requested max" in reason for reason in japan.why_it_may_not_fit)
