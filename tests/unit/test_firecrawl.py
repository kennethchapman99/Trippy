from __future__ import annotations

from pathlib import Path

import pytest

from trippy.models.shortlists import ResearchShortlistState, ShortlistCategory
from trippy.models.source_research import (
    SourceAdapterCapability,
    SourceResearchMode,
    SourceResearchRequest,
)
from trippy.models.trip_planning import (
    TravelerAgeBand,
    TravelWindow,
    TripIntake,
    TripIntakeMode,
    TripParty,
    TripPartyType,
    TripTraveler,
)
from trippy.services.firecrawl import FirecrawlService
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.source_research import FirecrawlResearchAdapter, SourceResearchService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService
from trippy.services.web_intelligence import TravelWebIntelligenceService


def test_firecrawl_missing_key_returns_unavailable_result() -> None:
    service = FirecrawlService(api_key="", enabled=True)
    result = service.search("family resorts porto", limit=1)[0]

    assert result.extraction_type == "unavailable"
    assert "missing" in result.warnings[0].lower()


def test_firecrawl_research_uses_mocked_endpoints() -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "search" in path:
            return {"data": [{"url": "https://example.com/hotel", "title": "Hotel Example"}]}
        return {"data": {"markdown": "Family suite, free parking, cancellation until 24h."}}

    service._request = fake_request  # type: ignore[method-assign]
    rows = service.research("porto family hotel", limit=1)

    assert rows
    assert rows[0].source_url == "https://example.com/hotel"
    assert "Family suite" in rows[0].raw_markdown_excerpt


def test_web_intelligence_models_are_normalized() -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "search" in path:
            return {
                "data": [
                    {
                        "url": "https://example.com/activity",
                        "title": "Whale Tour",
                        "description": "Family tour",
                    }
                ]
            }
        return {"data": {"markdown": "Open daily. 3 hour tour. Minimum age 6. Cancel 48h."}}

    service._request = fake_request  # type: ignore[method-assign]
    web = TravelWebIntelligenceService(firecrawl=service)

    activities = web.research_activities_web("whale tour azores")

    assert activities
    assert activities[0].name == "Whale Tour"
    assert activities[0].source_urls == ["https://example.com/activity"]
    assert activities[0].age_restrictions


def test_firecrawl_adapter_returns_observations() -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "search" in path:
            return {"data": [{"url": "https://example.com/airline", "title": "Fare Rules"}]}
        return {
            "data": {"markdown": "Carry-on 1 bag. Checked baggage 23kg. Changes allowed with fee."}
        }

    service._request = fake_request  # type: ignore[method-assign]
    adapter = FirecrawlResearchAdapter(service=service)
    request = SourceResearchRequest(
        trip_id="trip-1",
        category=ShortlistCategory.FLIGHTS.value,
        option_id="flight-1",
        source_name="Google Flights",
        source_url="https://example.com/airline",
        candidate_name="AC123",
        adapter_mode=SourceResearchMode.FIRECRAWL,
    )

    result = adapter.research(request, artifact_dir=Path("/tmp/firecrawl-test"))

    assert result.adapter_used == SourceAdapterCapability.FIRECRAWL
    assert result.observations
    assert any(ob.field in {"baggage_signal", "fare_rules"} for ob in result.observations)


def test_firecrawl_merges_into_shortlist_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trippy import config

    monkeypatch.setattr(config, "INTAKES_PATH", tmp_path / "intakes")
    monkeypatch.setattr(config, "PLANS_PATH", tmp_path / "plans")
    monkeypatch.setattr(config, "SHORTLISTS_PATH", tmp_path / "shortlists")
    monkeypatch.setattr(config, "RESEARCH_PATH", tmp_path / "research")
    monkeypatch.setattr(config, "LEARNING_PATH", tmp_path / "learning")
    monkeypatch.setattr(config, "MEMORY_PATH", tmp_path / "memory.json")
    monkeypatch.setattr(config, "TRIPS_PATH", tmp_path / "trips")

    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Azores Firecrawl 2027",
        destination_seeds=["Azores"],
        travel_window=TravelWindow(label="summer 2027"),
        duration_days=9,
        travelers=5,
        party=TripParty(
            party_type=TripPartyType.WHOLE_FAMILY,
            adults=2,
            children=3,
            roster=[
                TripTraveler(name="Ken", age_band=TravelerAgeBand.ADULT),
                TripTraveler(name="Sue", age_band=TravelerAgeBand.ADULT),
                TripTraveler(name="Kid 1", age=14),
                TripTraveler(name="Kid 2", age=11),
                TripTraveler(name="Kid 3", age=8),
            ],
        ),
        departure_airports=["YYZ"],
    )
    intake_service = TripIntakeService()
    created = intake_service.create(intake)
    planner = TripPlannerService(intake_service)
    planner.draft(created.trip_id)
    planner.select_option(created.trip_id, "azores-two-island-balanced")
    state: ResearchShortlistState = FlightShortlistService(intake_service, planner).build(
        created.trip_id
    )

    firecrawl = FirecrawlService(api_key="test-key", enabled=True)

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "search" in path:
            return {"data": [{"url": "https://example.com/airline-policy", "title": "Policy"}]}
        return {
            "data": {"markdown": "Carry-on 1 bag. Checked baggage 23kg. Changes allowed with fee."}
        }

    firecrawl._request = fake_request  # type: ignore[method-assign]

    researched = SourceResearchService(
        adapters=[FirecrawlResearchAdapter(service=firecrawl)]
    ).research_state(state, adapter_mode="firecrawl")
    option = researched.flight_options[0]

    assert option.validation.adapter_used == SourceAdapterCapability.FIRECRAWL.value
    assert option.validation.evidence_url
    assert option.validation.extracted_fields
