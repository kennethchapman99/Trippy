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

    long_burden = next(
        c for c in comparison.concepts if c.concept_id == "json-first-activity-led-sampler"
    )
    assert any("exceeds requested max" in reason for reason in long_burden.why_it_may_not_fit)


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
    assert {concept.concept_id for concept in comparison.concepts} <= {
        "json-first-low-friction-single-base",
        "json-first-food-culture-base",
        "json-first-nature-water-base",
    }
    assert any("Requested duration is 6" in note for note in comparison.scoring_notes)


def test_trip_ideas_do_not_convert_region_words_to_destination_catalog() -> None:
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

    assert len(comparison.concepts) == 3
    output_text = " ".join(
        [
            *(concept.title for concept in comparison.concepts),
            *(slot for concept in comparison.concepts for slot in concept.destinations),
            *comparison.scoring_notes,
        ]
    ).lower()
    assert "caribbean" not in output_text
    assert all(not concept.country_prior_signals for concept in comparison.concepts)
    assert all(concept.recommended_duration_days <= 6 for concept in comparison.concepts)
    assert any(
        "Regional wording was treated as user intent only" in note
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

    assert len(comparison.concepts) == 3
    output_text = " ".join(
        [
            *(concept.title for concept in comparison.concepts),
            *(slot for concept in comparison.concepts for slot in concept.destinations),
        ]
    ).lower()
    assert "cayman" not in output_text
    assert "belize" not in output_text
    assert all(
        any("snorkeling" in item for item in concept.rationale) for concept in comparison.concepts
    )
    assert any(
        "Required experience detected: snorkeling" in note for note in comparison.scoring_notes
    )


def test_trip_ideas_do_not_include_country_prior_rationale() -> None:
    comparison = TripIdeationService().compare(
        TripIdeaRequest(duration_days=14, goals=["food", "culture"]),
        limit=10,
    )

    assert all(not concept.country_prior_signals for concept in comparison.concepts)
    assert not any(
        "past country-level history" in item
        for concept in comparison.concepts
        for item in concept.rationale
    )
    assert any("destination-agnostic scanner briefs" in note for note in comparison.scoring_notes)
