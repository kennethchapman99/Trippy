from __future__ import annotations

from pathlib import Path

import pytest

from trippy.models.shortlists import (
    AvailabilityStatus,
    FreshnessStatus,
    LiveDataStatus,
    LodgingFitCategory,
    LodgingOption,
    PriceStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
    SourceValidation,
    VerificationStatus,
)
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


def test_firecrawl_adapter_scrapes_source_url_before_search() -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)
    calls: list[str] = []

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(path)
        assert "search" not in path
        assert payload["url"] == "https://example.com/stay"
        return {
            "data": {
                "metadata": {"title": "Family Stay"},
                "markdown": "CAD 780 total. Available now. 3 bedrooms. King bed. Free cancellation.",
            }
        }

    service._request = fake_request  # type: ignore[method-assign]
    adapter = FirecrawlResearchAdapter(service=service)
    request = SourceResearchRequest(
        trip_id="trip-1",
        category=ShortlistCategory.LODGING.value,
        option_id="lodging-1",
        source_name="Booking.com",
        source_url="https://example.com/stay",
        candidate_name="Family Stay",
        adapter_mode=SourceResearchMode.FIRECRAWL,
    )

    result = adapter.research(request, artifact_dir=Path("/tmp/firecrawl-test"))
    fields = {ob.field: ob.value for ob in result.observations}

    assert calls == ["/v1/scrape"]
    assert "3 bedrooms" in str(fields["bed_layout_signal"])
    assert "King bed" in str(fields["bed_layout_signal"])
    assert fields["min_three_beds_satisfied"] is True


def test_firecrawl_adapter_searches_when_source_scrape_has_no_observations() -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)
    calls: list[str] = []

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(path)
        if "scrape" in path and len(calls) == 1:
            return {"data": {"markdown": "401 unauthorized"}}
        if "scrape" in path:
            return {"data": {"markdown": "Available. 3 bedrooms. King bed."}}
        if "search" in path:
            return {
                "data": [
                    {
                        "url": "https://example.com/hotel",
                        "title": "Family Hotel",
                        "markdown": "Available. 3 bedrooms. King bed.",
                    }
                ]
            }
        raise AssertionError(f"unexpected path {path}")

    service._request = fake_request  # type: ignore[method-assign]
    adapter = FirecrawlResearchAdapter(service=service)
    request = SourceResearchRequest(
        trip_id="trip-1",
        category=ShortlistCategory.LODGING.value,
        option_id="lodging-1",
        source_name="Google Hotels (SerpAPI)",
        source_url="https://serpapi.com/search.json?engine=google_hotels",
        candidate_name="Family Hotel",
        adapter_mode=SourceResearchMode.FIRECRAWL,
    )

    result = adapter.research(request, artifact_dir=Path("/tmp/firecrawl-test"))
    fields = {ob.field: ob.value for ob in result.observations}

    assert calls == ["/v1/scrape", "/v1/search", "/v1/scrape"]
    assert "3 bedrooms" in str(fields["bed_layout_signal"])
    assert fields["min_three_beds_satisfied"] is True


def test_firecrawl_booking_shell_does_not_extract_bogus_bed_count() -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "search" in path:
            return {"data": []}
        return {
            "data": {
                "markdown": (
                    "[Skip to main content](https://www.booking.com/searchresults.html) "
                    "2 adults · 0 children · 1 room 2026 Bed"
                )
            }
        }

    service._request = fake_request  # type: ignore[method-assign]
    adapter = FirecrawlResearchAdapter(service=service)
    request = SourceResearchRequest(
        trip_id="trip-1",
        category=ShortlistCategory.LODGING.value,
        option_id="lodging-1",
        source_name="Booking.com",
        source_url="https://www.booking.com/searchresults.html?ss=Octant",
        candidate_name="Octant Ponta Delgada",
        adapter_mode=SourceResearchMode.FIRECRAWL,
    )

    result = adapter.research(request, artifact_dir=Path("/tmp/firecrawl-test"))
    fields = {ob.field: ob.value for ob in result.observations}

    assert "bed_layout_signal" not in fields
    assert "min_three_beds_satisfied" in result.missing_fields


def test_lodging_deep_research_preserves_existing_live_price_when_scrape_is_sparse(
    tmp_path: Path,
) -> None:
    service = FirecrawlService(api_key="test-key", enabled=True)

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "search" in path:
            return {"data": []}
        return {"data": {"markdown": "Sparse hotel shell. Check availability."}}

    service._request = fake_request  # type: ignore[method-assign]
    option = LodgingOption(
        option_id="serpapi-lodging-1",
        rank=1,
        source="Google Hotels (SerpAPI)",
        name="Pedras do Mar Resort & SPA",
        location_area="Sao Miguel",
        island_or_region="Sao Miguel",
        lodging_type="hotel",
        bed_layout="26 Bed",
        min_three_beds_satisfied=False,
        king_bed_preference_satisfied=None,
        family_of_five_fit=None,
        parking_practicality="verify on listing",
        driving_practicality="verify on listing",
        walkability="verify on map",
        cancellation_notes="check listing",
        price_band="CAD 2547 total",
        current_price_signal="CAD 364/night",
        deep_link="https://example.com/hotel",
        friction_score=18,
        family_comfort_score=80,
        recommendation_grade=RecommendationGrade.GOOD,
        live_data_status=LiveDataStatus.LIVE_VERIFIED,
        row_status=ShortlistRowStatus.VERIFIED_LIVE,
        fit_category=LodgingFitCategory.TECHNICAL,
        validation=SourceValidation(
            source_name="Google Hotels (SerpAPI)",
            source_type="live_search",
            freshness_status=FreshnessStatus.CURRENT,
            verification_status=VerificationStatus.LIVE_VERIFIED,
            availability_status=AvailabilityStatus.AVAILABILITY_SIGNAL,
            price_status=PriceStatus.LIVE_SIGNAL,
            extracted_fields={
                "bed_layout_signal": "26 Bed",
                "min_three_beds_satisfied": False,
                "total_rate": "CAD 2547 total",
                "rate_per_night": "CAD 364/night",
            },
        ),
    )
    state = ResearchShortlistState(
        trip_id="trip-1",
        category=ShortlistCategory.LODGING,
        lodging_options=[option],
    )

    researched = SourceResearchService(
        adapters=[FirecrawlResearchAdapter(service=service)],
        research_dir=tmp_path / "research",
    ).research_state(state, adapter_mode="firecrawl")
    researched_option = researched.lodging_options[0]

    assert researched_option.validation.extracted_fields["price_signal"] == "CAD 2547 total"
    assert "bed_layout_signal" not in researched_option.validation.extracted_fields
    assert researched_option.bed_layout == "bed layout not confirmed yet"
    assert "final_total_price" not in researched_option.validation.missing_fields
    assert not any("final total price is not pinned" in flag for flag in researched_option.friction_flags)


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
