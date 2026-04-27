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
            max_flight_hours=6,
            goals=["food"],
            avoid=["crowds"],
        ),
        limit=20,
    )

    japan = next(c for c in comparison.concepts if c.concept_id == "japan-food-rail-cities")
    assert any("exceeds requested max" in reason for reason in japan.why_it_may_not_fit)


def test_trip_ideas_respect_short_duration_before_generic_ranking() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            duration_days=6,
            travelers=2,
            max_flight_hours=8,
            goals=["food", "nature", "low-friction"],
            avoid=["too long", "huge crowds"],
        ),
        limit=3,
    )

    assert len(comparison.concepts) == 3
    assert all(concept.recommended_duration_days <= 6 for concept in comparison.concepts)
    assert not any(
        concept.concept_id in {"mexico-city-oaxaca-food", "portugal-food-cities-coast"}
        for concept in comparison.concepts
    )
    assert any("Requested duration is 6" in note for note in comparison.scoring_notes)


def test_trip_ideas_respect_explicit_caribbean_region_intent() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            duration_days=6,
            travelers=2,
            max_flight_hours=8,
            goals=["Caribbean", "beach", "great food"],
            avoid=["huge crowds", "stressful transfers"],
        ),
        limit=3,
    )

    concept_ids = {concept.concept_id for concept in comparison.concepts}
    assert len(comparison.concepts) == 3
    assert "azores-sao-miguel-short-comfort" not in concept_ids
    assert concept_ids <= {
        "belize-reef-jungle-short",
        "curacao-color-beach-drivable-short",
        "st-lucia-private-rental-food-short",
        "mexico-caribbean-food-beach-short",
    }
    assert all(concept.recommended_duration_days <= 6 for concept in comparison.concepts)
    assert any(
        "Explicit destination intent detected: caribbean" in note
        for note in comparison.scoring_notes
    )


def test_trip_ideas_treat_snorkeling_as_required_experience() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            time_of_year="march break",
            duration_days=7,
            travelers=5,
            max_flight_hours=5,
            goals=["great food", "low friction", "memorable snorkling"],
            avoid=["huge crowds", "stressful transfers"],
        ),
        limit=3,
    )

    concept_ids = {concept.concept_id for concept in comparison.concepts}
    assert len(comparison.concepts) == 3
    assert concept_ids <= {
        "belize-reef-jungle-short",
        "cayman-reef-food-easy-week",
        "curacao-color-beach-drivable-short",
        "mexico-caribbean-food-beach-short",
    }
    assert "quebec-city-montreal-food-short" not in concept_ids
    assert "mexico-city-food-short" not in concept_ids
    assert "azores-sao-miguel-short-comfort" not in concept_ids
    assert all(
        any("snorkeling" in item for item in concept.rationale) for concept in comparison.concepts
    )
    assert any(
        "Required experience detected: snorkeling" in note for note in comparison.scoring_notes
    )


def test_trip_ideas_include_country_prior_rationale() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(duration_days=14, goals=["food", "culture"]),
        limit=10,
    )

    japan = next(c for c in comparison.concepts if c.concept_id == "japan-food-rail-cities")
    italy = next(c for c in comparison.concepts if c.concept_id == "italy-food-culture-rail")

    assert japan.country_prior_signals
    assert any("past country-level history" in item for item in japan.rationale)
    assert any("expense" in item for item in japan.why_it_may_not_fit)
    assert any("summer heat" in item for item in italy.why_it_may_not_fit)
