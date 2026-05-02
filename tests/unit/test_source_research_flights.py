"""Flight source-research merge behavior."""

from __future__ import annotations

from trippy.models.shortlists import FlightOption, RecommendationGrade, SourceValidation
from trippy.models.source_research import (
    SourceAdapterCapability,
    SourceObservation,
    SourceResearchRequest,
    SourceResearchResult,
    SourceResearchStatus,
)
from trippy.services.source_research import _apply_flight_observations


def test_source_research_does_not_replace_provider_arrival_with_return_date() -> None:
    option = FlightOption(
        option_id="duffel-flight-1",
        rank=1,
        airline="Iberia",
        flight_numbers=["IB3177"],
        departure_date="2026-08-24",
        arrival_date="2026-08-25",
        departure_airport="YYZ",
        arrival_airport="PDL",
        departure_time="5:48 PM",
        arrival_time="4:23 AM",
        stops=0,
        total_travel_duration="6h 35m",
        fare_estimate_cad="CAD 1200 total",
        price_band="CAD 1200 total",
        baggage_cabin_notes="Verify baggage.",
        booking_source="Duffel",
        deep_link="https://www.google.com/travel/flights/search",
        friction_score=10,
        family_comfort_score=90,
        recommendation_grade=RecommendationGrade.STRONG,
        validation=SourceValidation(confidence=0.86),
    )
    result = SourceResearchResult(
        request=SourceResearchRequest(
            trip_id="azores-2026",
            category="flights",
            option_id=option.option_id,
            source_name="Google Flights",
            source_url=option.deep_link,
        ),
        adapter_used=SourceAdapterCapability.FIRECRAWL,
        status=SourceResearchStatus.PARTIAL,
        confidence=0.6,
        observations=[
            SourceObservation(field="departure_date", value="2026-08-24"),
            SourceObservation(field="arrival_date", value="2026-08-31"),
            SourceObservation(field="price_signal", value="$6"),
        ],
    )

    _apply_flight_observations(option, result, run_id="test-run")

    assert option.departure_date == "2026-08-24"
    assert option.arrival_date == "2026-08-25"
    assert option.fare_estimate_cad == "CAD 1200 total"
    assert any("Ignored source-research arrival date" in note for note in option.validation.notes)
    assert any("Ignored source-research price signal" in note for note in option.validation.notes)
