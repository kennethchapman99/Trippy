"""Tests for the OpenClaw read-only research adapter and the anti-friction post-processor.

These tests use the `runner` and `gateway_probe` injection seams on
`OpenClawResearchAdapter` so no real subprocess is launched and no real HTTP probe
runs. Full-pipeline tests mirror the existing
`test_lodging_deep_research_falls_back_when_openclaw_disabled` pattern.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from trippy.models.shortlists import (
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    SourceValidation,
    VerificationStatus,
)
from trippy.models.source_research import (
    SourceAdapterCapability,
    SourceResearchMode,
    SourceResearchRequest,
    SourceResearchStatus,
)
from trippy.models.trip_planning import (
    TravelAirportRef,
    TravelerAgeBand,
    TravelWindow,
    TripGeography,
    TripIntake,
    TripIntakeMode,
    TripMapLocation,
    TripParty,
    TripPartyType,
    TripTraveler,
)
from trippy.services.activity_shortlist import ActivityShortlistService
from trippy.services.car_shortlist import CarShortlistService
from trippy.services.firecrawl import FirecrawlService
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.lodging_shortlist import LodgingShortlistService
from trippy.services.shortlist_friction import apply_shortlist_friction
from trippy.services.source_research import (
    FirecrawlResearchAdapter,
    LinkResearchAdapter,
    OpenClawResearchAdapter,
    PlaywrightCarAdapter,
    PlaywrightLodgingAdapter,
    SourceResearchService,
)
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


def _patch_planning_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from trippy import config

    monkeypatch.setattr(config, "INTAKES_PATH", tmp_path / "intakes")
    monkeypatch.setattr(config, "PLANS_PATH", tmp_path / "plans")
    monkeypatch.setattr(config, "WORKSPACES_PATH", tmp_path / "workspaces")
    monkeypatch.setattr(config, "SHORTLISTS_PATH", tmp_path / "shortlists")
    monkeypatch.setattr(config, "RESEARCH_PATH", tmp_path / "research")
    monkeypatch.setattr(config, "TRIPS_PATH", tmp_path / "trips")
    monkeypatch.setattr(config, "EXPORT_PATH", tmp_path / "export")
    monkeypatch.setattr(config, "LEARNING_PATH", tmp_path / "learning")
    monkeypatch.setattr(config, "MEMORY_PATH", tmp_path / "memory.json")


def _azores_intake() -> TripIntake:
    return TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Azores Family 2027",
        destination_seeds=["Azores"],
        travel_window=TravelWindow(label="summer 2027", season="summer"),
        duration_days=10,
        travelers=5,
        party=TripParty(
            party_type=TripPartyType.WHOLE_FAMILY,
            adults=2,
            children=3,
            child_ages=[15, 12, 10],
            roster=[
                TripTraveler(name="Ken", age_band=TravelerAgeBand.ADULT),
                TripTraveler(name="Adult 2", age_band=TravelerAgeBand.ADULT),
                TripTraveler(name="Teen", age=15),
                TripTraveler(name="Child 2", age=12),
                TripTraveler(name="Child 3", age=10),
            ],
            explicit=True,
            defaulted_from_family_profile=False,
            sleeping_considerations="At least 3 beds.",
        ),
        departure_airports=["YYZ"],
        geography=TripGeography(
            primary_destination_name="Azores, Portugal",
            country="Portugal",
            destination_airports=[
                TravelAirportRef(iata_code="PDL", city="Ponta Delgada", country="Portugal")
            ],
            map_locations=[
                TripMapLocation(
                    name="Ponta Delgada",
                    country="Portugal",
                    use_for=["planning", "lodging", "activity", "car", "map"],
                ),
                TripMapLocation(
                    name="Furnas",
                    country="Portugal",
                    use_for=["planning", "lodging", "activity", "map"],
                ),
            ],
            lodging_search_locations=["Ponta Delgada", "Furnas"],
            activity_search_locations=["Ponta Delgada", "Furnas"],
            car_search_locations=["PDL"],
        ),
        goals=["nature", "family comfort"],
        avoidances=["overpacked days"],
        freeform_notes="OpenClaw test fixture.",
    )


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["openclaw"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _request_for(category: ShortlistCategory) -> SourceResearchRequest:
    return SourceResearchRequest(
        trip_id="trip-test",
        category=category.value,
        option_id=f"{category.value}-1",
        source_name="Booking.com",
        source_url="https://example.com/listing",
        candidate_name="Sample Candidate",
        adapter_mode=SourceResearchMode.OPENCLAW,
    )


def _adapter_with_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str = "",
    returncode: int = 0,
    enabled: bool = True,
    gateway: bool = True,
) -> tuple[OpenClawResearchAdapter, dict[str, object]]:
    monkeypatch.setattr(
        "trippy.services.source_research.shutil.which", lambda command: "/fake/openclaw"
    )
    invocations: dict[str, object] = {"runner": 0, "gateway": 0, "args": []}

    def fake_runner(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        invocations["runner"] = int(invocations["runner"]) + 1
        invocations["args"] = list(args[0]) if args else []
        return _completed(stdout=stdout, returncode=returncode)

    def fake_gateway() -> bool:
        invocations["gateway"] = int(invocations["gateway"]) + 1
        return gateway

    adapter = OpenClawResearchAdapter(
        enabled=enabled,
        runner=fake_runner,
        gateway_probe=fake_gateway,
    )
    return adapter, invocations


def test_openclaw_disabled_does_not_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter, invocations = _adapter_with_runner(monkeypatch, enabled=False)
    request = _request_for(ShortlistCategory.LODGING)

    assert adapter.can_handle(request) is False
    assert invocations["runner"] == 0
    assert invocations["gateway"] == 0


def test_openclaw_gateway_down_does_not_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter, invocations = _adapter_with_runner(monkeypatch, gateway=False)
    request = _request_for(ShortlistCategory.LODGING)

    assert adapter.can_handle(request) is False
    assert invocations["gateway"] == 1
    assert invocations["runner"] == 0


def test_openclaw_valid_json_maps_to_observations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = {
        "observations": [
            {"field": "price_signal", "value": "CAD 780 total", "confidence": 0.82},
            {
                "field": "bed_layout_signal",
                "value": "3 beds incl king",
                "confidence": 0.7,
            },
        ],
        "ready_to_click": "partial",
        "ready_to_click_reason": "price visible but cancellation not pinned",
        "missing_fields": ["cancellation_terms"],
        "warnings": ["dynamic-pricing notice"],
    }
    adapter, invocations = _adapter_with_runner(monkeypatch, stdout=json.dumps(payload))
    request = _request_for(ShortlistCategory.LODGING)

    result = adapter.research(request, artifact_dir=tmp_path)

    assert result.adapter_used == SourceAdapterCapability.OPENCLAW
    assert result.status == SourceResearchStatus.PARTIAL
    fields = {observation.field: observation.value for observation in result.observations}
    assert fields["price_signal"] == "CAD 780 total"
    assert fields["bed_layout_signal"] == "3 beds incl king"
    assert any("ready_to_click=partial" in note for note in result.notes)
    assert any("dynamic-pricing notice" in note for note in result.notes)
    assert invocations["runner"] == 1
    args = invocations["args"]
    assert isinstance(args, list)
    assert "--agent" in args
    assert "main" in args
    assert "--local" in args


def test_openclaw_markdown_fenced_json_parses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inner = json.dumps(
        {
            "observations": [
                {"field": "price_signal", "value": "CAD 780", "confidence": 0.6}
            ]
        }
    )
    fenced = f"Here is the JSON:\n```json\n{inner}\n```\nDone."
    adapter, _ = _adapter_with_runner(monkeypatch, stdout=fenced)
    request = _request_for(ShortlistCategory.LODGING)

    result = adapter.research(request, artifact_dir=tmp_path)

    assert result.status == SourceResearchStatus.PARTIAL
    assert result.observations
    assert result.observations[0].field == "price_signal"


def test_openclaw_malformed_json_blocks_with_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter, _ = _adapter_with_runner(
        monkeypatch, stdout="totally not json {oops"
    )
    request = _request_for(ShortlistCategory.LODGING)

    result = adapter.research(request, artifact_dir=tmp_path)

    assert result.status == SourceResearchStatus.BLOCKED
    assert not result.observations
    assert result.notes  # Should contain explanatory note
    assert any("OpenClaw" in note for note in result.notes)


def _build_state_with_openclaw(
    intake_service: TripIntakeService,
    planner: TripPlannerService,
    *,
    category: ShortlistCategory,
    openclaw_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    runner_returncode: int = 0,
) -> ResearchShortlistState:
    monkeypatch.setattr(
        "trippy.services.source_research.shutil.which", lambda command: "/fake/openclaw"
    )

    def fake_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(stdout=json.dumps(openclaw_payload), returncode=runner_returncode)

    if category == ShortlistCategory.FLIGHTS:
        state = FlightShortlistService(intake_service, planner).add_candidate(
            "azores-family-2027",
            link="https://www.google.com/travel/flights/search",
            notes="YYZ to PDL flight candidate; OpenClaw evidence pending.",
        )
    elif category == ShortlistCategory.LODGING:
        state = LodgingShortlistService(intake_service, planner).build("azores-family-2027")
    elif category == ShortlistCategory.CARS:
        state = CarShortlistService(intake_service, planner).build("azores-family-2027")
    else:
        state = ActivityShortlistService(intake_service, planner).build("azores-family-2027")

    service = SourceResearchService(
        adapters=[
            LinkResearchAdapter(),
            OpenClawResearchAdapter(
                enabled=True,
                runner=fake_runner,
                gateway_probe=lambda: True,
            ),
        ]
    )
    return service.research_state(state, adapter_mode="openclaw")


def test_openclaw_flight_extraction_maps_key_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    payload = {
        "observations": [
            {"field": "airline", "value": "Azores Airlines", "confidence": 0.9},
            {"field": "departure_time", "value": "9:15 PM", "confidence": 0.85},
            {"field": "arrival_time", "value": "7:20 AM", "confidence": 0.85},
            {"field": "total_duration", "value": "5h 55m", "confidence": 0.8},
            {"field": "price_signal", "value": "CAD 1,180 pp", "confidence": 0.75},
            {"field": "baggage_signal", "value": "Checked bag included", "confidence": 0.7},
            {"field": "stops", "value": 0, "confidence": 0.95},
        ],
    }

    researched = _build_state_with_openclaw(
        intake_service,
        planner,
        category=ShortlistCategory.FLIGHTS,
        openclaw_payload=payload,
        monkeypatch=monkeypatch,
    )
    first = researched.flight_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.OPENCLAW.value
    assert first.departure_time == "9:15 PM"
    assert first.arrival_time == "7:20 AM"
    assert first.total_travel_duration == "5h 55m"
    assert first.price_band == "CAD 1,180 pp"
    assert first.airline == "Azores Airlines"
    assert "Checked bag included" in first.baggage_cabin_notes


def test_openclaw_lodging_extraction_maps_key_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    payload = {
        "observations": [
            {"field": "price_signal", "value": "CAD 780 total", "confidence": 0.82},
            {"field": "bed_layout_signal", "value": "3 beds, king", "confidence": 0.78},
            {"field": "min_three_beds_satisfied", "value": True, "confidence": 0.9},
            {"field": "cancellation_signal", "value": "Free cancellation", "confidence": 0.7},
        ],
    }

    researched = _build_state_with_openclaw(
        intake_service,
        planner,
        category=ShortlistCategory.LODGING,
        openclaw_payload=payload,
        monkeypatch=monkeypatch,
    )
    first = researched.lodging_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.OPENCLAW.value
    assert first.current_price_signal == "CAD 780 total"
    assert first.min_three_beds_satisfied is True
    assert first.cancellation_notes == "Free cancellation"
    assert first.bed_layout == "3 beds, king"


def test_auto_lodging_falls_through_firecrawl_when_price_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)
    target = lodging.lodging_options[0]

    firecrawl = FirecrawlService(api_key="test-key", enabled=True)

    def fake_firecrawl_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if "scrape" in path:
            return {"data": {"markdown": "Available. 4 bedrooms. King bed. Parking."}}
        return {
            "data": [
                {
                    "url": "https://www.vrbo.com/search",
                    "title": "VRBO Sao Miguel",
                    "markdown": "Available. 4 bedrooms. King bed. Parking.",
                }
            ]
        }

    firecrawl._request = fake_firecrawl_request  # type: ignore[method-assign]
    payload = {
        "observations": [
            {"field": "price_signal", "value": "CAD 2,950 total", "confidence": 0.84},
            {"field": "bed_layout_signal", "value": "4 bedrooms; king bed", "confidence": 0.78},
            {"field": "min_three_beds_satisfied", "value": True, "confidence": 0.9},
        ],
    }
    openclaw, invocations = _adapter_with_runner(monkeypatch, stdout=json.dumps(payload))

    researched = SourceResearchService(
        adapters=[
            FirecrawlResearchAdapter(service=firecrawl),
            openclaw,
            LinkResearchAdapter(),
        ]
    ).research_state(lodging, adapter_mode="auto", option_ids=[target.option_id])

    updated = next(option for option in researched.lodging_options if option.option_id == target.option_id)
    assert invocations["runner"] == 1
    assert updated.validation.adapter_used == SourceAdapterCapability.OPENCLAW.value
    assert updated.current_price_signal == "CAD 2,950 total"
    assert updated.live_data_status == LiveDataStatus.PARTIAL


def test_openclaw_car_extraction_maps_key_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    payload = {
        "observations": [
            {"field": "total_price", "value": "CAD 540 total incl taxes", "confidence": 0.8},
            {"field": "seats", "value": 7, "confidence": 0.95},
            {"field": "transmission_signal", "value": "automatic", "confidence": 0.9},
            {"field": "cancellation_signal", "value": "Free cancellation 48h", "confidence": 0.7},
            {"field": "insurance_signal", "value": "basic CDW included", "confidence": 0.6},
        ],
    }

    researched = _build_state_with_openclaw(
        intake_service,
        planner,
        category=ShortlistCategory.CARS,
        openclaw_payload=payload,
        monkeypatch=monkeypatch,
    )
    assert researched.artifacts["deep_research"]["status"] != "skipped"
    first = researched.car_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.OPENCLAW.value
    assert first.current_price_signal == "CAD 540 total incl taxes"
    assert first.seating_capacity == 7
    assert "automatic" in first.fees_caution
    assert first.cancellation_notes == "Free cancellation 48h"
    assert "exact_seats" not in first.validation.missing_fields
    assert "transmission" not in first.validation.missing_fields


def test_openclaw_activity_extraction_maps_key_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    payload = {
        "observations": [
            {"field": "price_signal", "value": "EUR 65 pp", "confidence": 0.7},
            {"field": "duration_signal", "value": "3 hours", "confidence": 0.8},
            {"field": "start_time", "value": "10:00 AM", "confidence": 0.6},
            {"field": "availability_signal", "value": "spots remain", "confidence": 0.5},
        ],
    }

    researched = _build_state_with_openclaw(
        intake_service,
        planner,
        category=ShortlistCategory.ACTIVITIES,
        openclaw_payload=payload,
        monkeypatch=monkeypatch,
    )
    first = researched.activity_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.OPENCLAW.value
    assert first.price_band == "EUR 65 pp"
    assert first.duration == "3 hours"
    assert first.suggested_start_time == "10:00 AM"


def test_link_only_row_remains_handoff_not_live_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)

    service = SourceResearchService(
        adapters=[
            LinkResearchAdapter(),
            PlaywrightLodgingAdapter(
                fetcher=lambda url, timeout: (_ for _ in ()).throw(OSError("blocked"))
            ),
            OpenClawResearchAdapter(enabled=False),
        ]
    )
    researched = service.research_state(lodging, adapter_mode="auto")
    first = researched.lodging_options[0]

    assert first.validation.verification_status != VerificationStatus.LIVE_VERIFIED
    assert first.live_data_status in {
        LiveDataStatus.HANDOFF_REQUIRED,
        LiveDataStatus.SEARCH_LINK_ONLY,
        LiveDataStatus.PARTIAL,
    }


def _flight_state_with_late_arrival() -> ResearchShortlistState:
    from trippy.models.shortlists import FlightOption

    safe = FlightOption(
        option_id="flight-safe",
        rank=1,
        airline="Azores Airlines",
        flight_numbers=["S4332"],
        departure_airport="YYZ",
        arrival_airport="PDL",
        departure_time="9:15 PM",
        arrival_time="7:20 AM",
        stops=0,
        total_travel_duration="5h 55m",
        fare_estimate_cad="CAD 1,180",
        price_band="CAD 1,180",
        baggage_cabin_notes="checked included",
        booking_source="Google Flights",
        deep_link="https://example.com/safe",
        friction_score=10,
        family_comfort_score=80,
        recommendation_grade=RecommendationGrade.STRONG,
        validation=SourceValidation(
            extracted_fields={"arrival_time": "7:20 AM"},
        ),
    )
    risky = FlightOption(
        option_id="flight-risky",
        rank=2,
        airline="Air Random",
        flight_numbers=["AB123", "CD456"],
        departure_airport="YYZ",
        arrival_airport="PDL",
        departure_time="5:00 AM",
        arrival_time="11:45 PM",
        stops=1,
        layover_airports=["LIS"],
        layover_duration="0h 35m",
        total_travel_duration="14h 30m",
        fare_estimate_cad="CAD 1,500",
        price_band="CAD 1,500",
        baggage_cabin_notes="",
        booking_source="Generic",
        deep_link="https://example.com/risky",
        friction_score=40,
        family_comfort_score=40,
        recommendation_grade=RecommendationGrade.STRONG,
        live_data_status=LiveDataStatus.LIVE_VERIFIED,
        validation=SourceValidation(
            extracted_fields={"arrival_time": "11:45 PM", "departure_time": "5:00 AM"},
            missing_fields=["exact_fare", "baggage_terms"],
        ),
    )
    return ResearchShortlistState(
        trip_id="trip-test",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[safe, risky],
    )


def test_anti_friction_downgrades_risky_candidate() -> None:
    state = _flight_state_with_late_arrival()
    apply_shortlist_friction(state)

    risky = next(opt for opt in state.flight_options if opt.option_id == "flight-risky")
    safe = next(opt for opt in state.flight_options if opt.option_id == "flight-safe")

    assert risky.recommendation_grade == RecommendationGrade.CONDITIONAL
    assert risky.live_data_status == LiveDataStatus.PARTIAL
    assert any("23:00" in flag for flag in risky.friction_flags)
    assert any("layover under 50 minutes" in flag for flag in risky.friction_flags)
    assert any("multi-airline" in flag for flag in risky.friction_flags)
    assert safe.recommendation_grade == RecommendationGrade.STRONG
    assert state.flight_options[0].option_id == "flight-safe"
    assert state.flight_options[1].option_id == "flight-risky"
    assert state.flight_options[0].rank == 1
    assert state.flight_options[1].rank == 2

    summary = state.artifacts["friction_postprocess"]
    assert summary["category"] == ShortlistCategory.FLIGHTS.value
    assert any(d["option_id"] == "flight-risky" for d in summary["downgrades"])


def test_anti_friction_does_not_touch_safe_candidates() -> None:
    state = _flight_state_with_late_arrival()
    state.flight_options = [state.flight_options[0]]  # only safe option
    apply_shortlist_friction(state)

    safe = state.flight_options[0]
    assert safe.recommendation_grade == RecommendationGrade.STRONG
    assert safe.live_data_status == LiveDataStatus.HANDOFF_REQUIRED  # unchanged default
    summary = state.artifacts["friction_postprocess"]
    assert summary["downgrades"] == []


def _make_flight_state(arrival_time: str, departure_time: str = "10:00 AM") -> ResearchShortlistState:
    from trippy.models.shortlists import FlightOption

    flight = FlightOption(
        option_id="flight-1",
        rank=1,
        airline="Azores Airlines",
        flight_numbers=["S4332"],
        departure_airport="YYZ",
        arrival_airport="PDL",
        departure_time=departure_time,
        arrival_time=arrival_time,
        stops=0,
        total_travel_duration="6h",
        fare_estimate_cad="CAD 1,200",
        price_band="CAD 1,200",
        baggage_cabin_notes="checked included",
        booking_source="Google Flights",
        deep_link="https://example.com",
        friction_score=10,
        family_comfort_score=80,
        recommendation_grade=RecommendationGrade.STRONG,
    )
    return ResearchShortlistState(
        trip_id="trip-x",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[flight],
    )


def _make_lodging_state() -> ResearchShortlistState:
    from trippy.models.shortlists import LodgingFitCategory, LodgingOption

    option = LodgingOption(
        option_id="lodging-1",
        rank=1,
        source="Airbnb",
        name="Nice Villa",
        location_area="Ponta Delgada",
        island_or_region="São Miguel",
        lodging_type="private rental",
        bed_layout="3 beds",
        min_three_beds_satisfied=True,
        king_bed_preference_satisfied=None,
        family_of_five_fit=True,
        fit_category=LodgingFitCategory.PREFERRED,
        parking_practicality="ok",
        driving_practicality="ok",
        walkability="moderate",
        cancellation_notes="",  # no mention of late check-in
        price_band="CAD 400/night",
        current_price_signal="CAD 400/night",
        deep_link="https://airbnb.com/rooms/1",
        friction_score=25,
        family_comfort_score=85,
        recommendation_grade=RecommendationGrade.GOOD,
    )
    return ResearchShortlistState(
        trip_id="trip-x",
        category=ShortlistCategory.LODGING,
        lodging_options=[option],
    )


def _make_activity_state(suggested_day: int | None = None) -> ResearchShortlistState:
    from trippy.models.shortlists import ActivityOption

    option = ActivityOption(
        option_id="activity-1",
        rank=1,
        activity_name="Whale Watching",
        source="GetYourGuide",
        island_location="Pico",
        group_size_signal="small groups up to 12",
        review_safety_signal="4.8/5 certified operator",
        price_band="EUR 60 pp",
        duration="4 hours",
        suggested_day=suggested_day,
        deep_link="https://getyourguide.com/1",
        family_pace_fit_score=85,
        safety_confidence_score=90,
        crowd_fit_score=80,
        total_friction_score=15,
        recommendation_grade=RecommendationGrade.GOOD,
    )
    return ResearchShortlistState(
        trip_id="trip-x",
        category=ShortlistCategory.ACTIVITIES,
        activity_options=[option],
    )


def test_lodging_flags_late_arrival_flight() -> None:
    lodging_state = _make_lodging_state()
    flight_state = _make_flight_state(arrival_time="11:45 PM")  # 23:45

    apply_shortlist_friction(
        lodging_state,
        complementary_states={ShortlistCategory.FLIGHTS: flight_state},
        party_size=5,
    )
    opt = lodging_state.lodging_options[0]
    late_flags = [f for f in opt.friction_flags if "23:00" in f or "late-arriving" in f.lower()]
    assert late_flags, f"Expected late-arrival check-in flag, got: {opt.friction_flags}"


def test_lodging_no_late_arrival_flag_when_arrival_is_early() -> None:
    lodging_state = _make_lodging_state()
    flight_state = _make_flight_state(arrival_time="7:30 AM")

    apply_shortlist_friction(
        lodging_state,
        complementary_states={ShortlistCategory.FLIGHTS: flight_state},
        party_size=5,
    )
    opt = lodging_state.lodging_options[0]
    late_flags = [f for f in opt.friction_flags if "late-arriving" in f.lower()]
    assert not late_flags, f"Should not flag early arrival as late, got: {opt.friction_flags}"


def test_lodging_early_departure_flag() -> None:
    lodging_state = _make_lodging_state()
    flight_state = _make_flight_state(arrival_time="7:30 AM", departure_time="7:00 AM")

    apply_shortlist_friction(
        lodging_state,
        complementary_states={ShortlistCategory.FLIGHTS: flight_state},
        party_size=5,
    )
    opt = lodging_state.lodging_options[0]
    early_flags = [f for f in opt.friction_flags if "early departure" in f.lower()]
    assert early_flags, f"Expected early-departure checkout flag, got: {opt.friction_flags}"


def test_activity_late_arrival_day1_is_high() -> None:
    activity_state = _make_activity_state(suggested_day=1)
    flight_state = _make_flight_state(arrival_time="10:30 PM")  # 22:30

    apply_shortlist_friction(
        activity_state,
        complementary_states={ShortlistCategory.FLIGHTS: flight_state},
    )
    opt = activity_state.activity_options[0]
    late_flags = [f for f in opt.friction_flags if "day-1" in f or "arrival day" in f.lower()]
    assert late_flags, f"Expected day-1 scheduling flag, got: {opt.friction_flags}"
    assert any("[HIGH]" in f for f in opt.friction_flags if "day-1" in f or "arrival day" in f.lower())


def test_activity_late_arrival_no_day_is_low() -> None:
    activity_state = _make_activity_state(suggested_day=None)
    flight_state = _make_flight_state(arrival_time="10:30 PM")

    apply_shortlist_friction(
        activity_state,
        complementary_states={ShortlistCategory.FLIGHTS: flight_state},
    )
    opt = activity_state.activity_options[0]
    late_flags = [f for f in opt.friction_flags if "day-1" in f or "arrival day" in f.lower()]
    assert late_flags
    assert any("[LOW]" in f for f in opt.friction_flags if "day-1" in f or "arrival day" in f.lower())


def test_activity_no_flight_state_no_cross_flags() -> None:
    activity_state = _make_activity_state(suggested_day=1)
    apply_shortlist_friction(activity_state)

    opt = activity_state.activity_options[0]
    cross_flags = [f for f in opt.friction_flags if "flight" in f.lower()]
    assert not cross_flags, f"Should not add flight flags without flight state: {opt.friction_flags}"


def test_playwright_car_adapter_extracts_signals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")
    cars = CarShortlistService(intake_service, planner).build(intake.trip_id)

    fixture_html = """
    <html><body>
    <p>Toyota RAV4 or similar</p>
    <p>Automatic transmission</p>
    <p>5 seats | 2 large suitcases</p>
    <p>Total: CAD 420 for 10 days</p>
    <p>Free cancellation up to 48h before pickup</p>
    <p>CDW included; airport surcharge applies</p>
    </body></html>
    """

    service = SourceResearchService(
        adapters=[
            PlaywrightCarAdapter(
                fetcher=lambda url, timeout: (fixture_html, url, ["fixture fetcher"])
            ),
        ]
    )
    researched = service.research_state(cars, adapter_mode="playwright")
    first = researched.car_options[0]

    assert first.validation is not None
    assert first.validation.adapter_used == SourceAdapterCapability.PLAYWRIGHT.value
    assert first.live_data_status in {LiveDataStatus.PARTIAL, LiveDataStatus.LIVE_VERIFIED}
    assert "CAD 420" in first.current_price_signal or "CAD 420" in first.price_band
    assert "automatic" in first.fees_caution.lower()
    assert "CDW" in first.fees_caution or "cdw" in first.fees_caution.lower()
    assert first.seating_capacity == 5


def test_playwright_car_adapter_falls_back_to_link_on_fetch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")
    cars = CarShortlistService(intake_service, planner).build(intake.trip_id)

    service = SourceResearchService(
        adapters=[
            LinkResearchAdapter(),
            PlaywrightCarAdapter(
                fetcher=lambda url, timeout: (_ for _ in ()).throw(OSError("blocked"))
            ),
            OpenClawResearchAdapter(enabled=False),
        ]
    )
    researched = service.research_state(cars, adapter_mode="auto")
    first = researched.car_options[0]

    assert first.validation is not None
    assert first.live_data_status in {
        LiveDataStatus.HANDOFF_REQUIRED,
        LiveDataStatus.SEARCH_LINK_ONLY,
        LiveDataStatus.PARTIAL,
    }
