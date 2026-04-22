"""Tests for the new-trip intake -> plan -> workspace -> map pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trippy.agent import _execute_tool
from trippy.cli import app
from trippy.memory.store import MemoryStore
from trippy.models.maps import MapPinCategory
from trippy.models.shortlists import (
    FreshnessStatus,
    ShortlistCategory,
    ShortlistRowStatus,
    VerificationStatus,
)
from trippy.models.source_research import SourceAdapterCapability, SourceResearchStatus
from trippy.models.trip_planning import (
    TravelerAgeBand,
    TravelWindow,
    TripIntake,
    TripIntakeMode,
    TripParty,
    TripPartyType,
    TripTraveler,
    WorkspaceStatus,
)
from trippy.services.activity_shortlist import ActivityShortlistService
from trippy.services.car_shortlist import CarShortlistService
from trippy.services.dashboard import DashboardService
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.live_validation import LiveValidationService
from trippy.services.lodging_shortlist import LodgingShortlistService
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.source_research import (
    LinkResearchAdapter,
    OpenClawResearchAdapter,
    PlaywrightFlightAdapter,
    PlaywrightLodgingAdapter,
    SourceResearchService,
)
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_map_builder import TripMapBuilder
from trippy.services.trip_planner import TripPlannerService
from trippy.services.trip_state import TripStateService
from trippy.services.trip_workspace import TripWorkspaceService


def test_azores_golden_path_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    planner = TripPlannerService(intake_service)
    workspace = TripWorkspaceService(intake_service, planner)

    intake = intake_service.create(_azores_intake())
    assert intake.trip_id == "azores-family-2027"
    assert intake_service.require(intake.trip_id).destination_seeds == ["Azores"]
    assert intake.party.explicit is True
    assert intake.party.total_travelers == 5
    assert intake.party.children == 3

    draft = planner.draft(intake.trip_id)
    assert len(draft.options) == 3
    assert draft.recommended_option_id == "azores-two-island-balanced"
    balanced = draft.get_option(draft.recommended_option_id)
    assert balanced is not None
    assert "Sao Miguel" in balanced.regions
    assert balanced.recommendation_strength >= 90
    assert balanced.country_prior_signals

    selected = planner.select_option(intake.trip_id, "azores-two-island-balanced")
    assert selected.selected_option_id == "azores-two-island-balanced"

    state = workspace.prepare(intake.trip_id, create_google_sheet=False)
    assert state.status == WorkspaceStatus.PREPARED_LOCAL
    assert state.local_workspace_path is not None
    assert Path(state.local_workspace_path).exists()
    assert {tab.name for tab in state.tabs} >= {
        "Master Timeline",
        "Flights",
        "Lodging",
        "Cars",
        "Activities",
        "Logistics",
        "Maps",
        "Risks",
    }
    tabs = {tab.name: tab for tab in state.tabs}
    assert tabs["Flights"].rows[0][1] in {"researched", "verified_live"}
    assert tabs["Flights"].rows[0][2] == "yes"
    assert tabs["Lodging"].rows[0][1] in {"recommended", "researched"}
    assert tabs["Cars"].rows[0][7] >= 5
    assert any(row[5] == "activity" for row in tabs["Master Timeline"].rows)
    assert any("Traveler Roster" in row for row in tabs["Overview"].rows)

    canonical = TripStateService().load(intake.trip_id)
    assert canonical is not None
    assert canonical.status.value == "planned"
    assert canonical.stays

    artifact = TripMapBuilder(intake_service, planner).write_artifacts(
        intake.trip_id,
        tmp_path / "export" / "maps",
    )
    assert any(pin.category == MapPinCategory.AIRPORT for pin in artifact.pins)
    assert any(pin.category == MapPinCategory.FOOD for pin in artifact.pins)
    assert any(pin.category == MapPinCategory.ACTIVITY for pin in artifact.pins)
    assert Path(artifact.exports["json"]).exists()

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)
    cars = CarShortlistService(intake_service, planner).build(intake.trip_id)
    activities = ActivityShortlistService(intake_service, planner).build(intake.trip_id)

    assert flights.category == ShortlistCategory.FLIGHTS
    assert flights.recommended_option_id == "flight-direct-yyz-pdl"
    assert "google.com/travel/flights" in flights.flight_options[0].deep_link
    assert lodging.lodging_options
    assert lodging.recommended_option_id is not None
    assert cars.car_options[0].booking_source == "Booking.com"
    assert "cars" in cars.car_options[0].deep_link
    assert "Flights-Search" not in cars.car_options[1].deep_link
    assert "/flights/" not in cars.car_options[2].deep_link
    assert activities.activity_options[0].source == "GetYourGuide"
    assert flights.flight_options[0].row_status == ShortlistRowStatus.RESEARCHED
    assert (
        flights.flight_options[0].validation.verification_status
        == VerificationStatus.MANUAL_REQUIRED
    )
    assert lodging.lodging_options[0].fit_category.value in {
        "preferred_fit",
        "comfortable_fit",
        "technical_fit",
        "weak_fit",
    }

    stored = ShortlistStore().load_all(intake.trip_id)
    assert {state.category for state in stored} == {
        ShortlistCategory.FLIGHTS,
        ShortlistCategory.LODGING,
        ShortlistCategory.CARS,
        ShortlistCategory.ACTIVITIES,
    }

    dashboard = DashboardService().build()
    planned = next(tile for tile in dashboard.planned_trips if tile.trip_id == intake.trip_id)
    assert planned.planning_status["workspace"] == "prepared_local"
    assert planned.shortlist_status["flights"].startswith("3 option")


def test_cli_azores_golden_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    runner = CliRunner()

    intake_result = runner.invoke(
        app,
        [
            "trip-intake",
            "wizard",
            "--no-prompt",
            "--trip-name",
            "Azores 2027",
            "--destination",
            "Azores",
            "--travel-window",
            "summer 2027",
            "--days",
            "10",
            "--party-type",
            "whole_family",
            "--adults",
            "2",
            "--children",
            "3",
            "--traveler",
            "Ken|adult",
            "--traveler",
            "Adult 2|adult",
            "--traveler",
            "Child 1|teen",
            "--traveler",
            "Child 2|child",
            "--traveler",
            "Child 3|child",
            "--departure-airport",
            "YYZ",
            "--goal",
            "nature",
            "--goal",
            "food",
            "--avoid",
            "huge crowds",
            "--json",
        ],
    )
    assert intake_result.exit_code == 0, intake_result.output
    intake_payload = json.loads(intake_result.output)
    trip_id = intake_payload["intake"]["trip_id"]
    assert intake_payload["intake"]["party"]["total_travelers"] == 5
    assert intake_payload["intake"]["party"]["explicit"] is True

    draft_result = runner.invoke(app, ["trip-plan", "draft", "--trip-id", trip_id, "--json"])
    assert draft_result.exit_code == 0, draft_result.output
    draft_payload = json.loads(draft_result.output)
    option_id = draft_payload["draft"]["recommended_option_id"]
    assert option_id == "azores-two-island-balanced"

    select_result = runner.invoke(
        app,
        ["trip-plan", "select", "--trip-id", trip_id, "--option-id", option_id, "--json"],
    )
    assert select_result.exit_code == 0, select_result.output

    workspace_result = runner.invoke(
        app,
        ["trip-plan", "workspace", "--trip-id", trip_id, "--no-google", "--json"],
    )
    assert workspace_result.exit_code == 0, workspace_result.output
    workspace_payload = json.loads(workspace_result.output)
    assert workspace_payload["workspace"]["status"] == "prepared_local"
    workspace_tabs = {tab["name"]: tab for tab in workspace_payload["workspace"]["tabs"]}
    assert "Master Timeline" in workspace_tabs
    assert workspace_tabs["Flights"]["rows"][0][1] in {"researched", "verified_live"}
    assert workspace_tabs["Flights"]["rows"][0][2] == "yes"

    map_result = runner.invoke(
        app,
        [
            "trip-map",
            "build",
            "--trip-id",
            trip_id,
            "--output-dir",
            str(tmp_path / "maps"),
            "--json",
        ],
    )
    assert map_result.exit_code == 0, map_result.output
    map_payload = json.loads(map_result.output)
    assert map_payload["map"]["pins"]
    assert map_payload["workflow_id"].startswith("wf-")

    for command in ("flights", "lodging", "cars", "activities"):
        result = runner.invoke(
            app,
            ["trip-plan", command, "--trip-id", trip_id, "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["shortlist"]["trip_id"] == trip_id
        assert payload["shortlist"]["recommended_option_id"]

    learning_result = runner.invoke(
        app,
        ["trip-plan", "propose-learning", "--trip-id", trip_id, "--json"],
    )
    assert learning_result.exit_code == 0, learning_result.output
    learning_payload = json.loads(learning_result.output)
    assert learning_payload["learning_proposals"]


def test_agent_planning_tool_routes_to_shortlist_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")

    result = json.loads(
        _execute_tool(
            "run_planning_service",
            {"action": "flights", "trip_id": intake.trip_id},
            MemoryStore(tmp_path / "memory.json"),
            TripStateService(trips_dir=tmp_path / "trips"),
            tmp_path / "learning",
        )
    )

    assert result["category"] == "flights"
    assert result["recommended_option_id"] == "flight-direct-yyz-pdl"


def test_intake_accepts_fuzzy_duration_and_party_roster() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Flexible Azores",
        destination_seeds=["Azores"],
        duration_days="6 to 8 days",
        party=TripParty(
            party_type=TripPartyType.SUBSET_FAMILY,
            adults=1,
            children=2,
            roster=[
                TripTraveler(name="Adult", age_band=TravelerAgeBand.ADULT),
                TripTraveler(name="Teen", age=15),
                TripTraveler(name="Kid", age=11),
            ],
            explicit=True,
            defaulted_from_family_profile=False,
            sleeping_considerations="Two beds may be enough for this subset.",
        ),
    )

    assert intake.duration_days == 7
    assert intake.duration_min_days == 6
    assert intake.duration_max_days == 8
    assert intake.duration_display() == "6-8 days"
    assert intake.travelers == 3
    assert intake.party.summary().startswith("subset family; 3 traveler")


def test_live_validation_marks_reachable_rows_without_claiming_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")
    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)

    validator = LiveValidationService(
        fetcher=lambda _url, _timeout: (True, 200, "fake live source OK")
    )
    validated = validator.validate_state(flights, attempt_network=True)
    first = validated.flight_options[0]

    assert first.row_status == ShortlistRowStatus.VERIFIED_LIVE
    assert first.validation.verification_status == VerificationStatus.LINK_VALIDATED
    assert first.validation.freshness_status == FreshnessStatus.CURRENT
    assert "exact_fare" in first.validation.missing_fields
    assert any("exact inventory" in note for note in first.validation.notes)


def test_lodging_deep_research_enriches_existing_shortlist_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)

    html = """
    <html><title>Octant Ponta Delgada</title>
    <body>
      <h1>Octant Ponta Delgada</h1>
      CAD 780 total. Free cancellation. Available rooms.
      3 bedrooms, king bed, parking available. Ponta Delgada waterfront.
    </body></html>
    """
    service = SourceResearchService(
        adapters=[
            PlaywrightLodgingAdapter(fetcher=lambda url, timeout: (html, url, ["fixture HTML"])),
            OpenClawResearchAdapter(enabled=False),
            LinkResearchAdapter(),
        ],
        research_dir=tmp_path / "research",
    )
    researched = service.research_state(lodging, adapter_mode="auto")
    first = researched.lodging_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.PLAYWRIGHT.value
    assert first.validation.verification_status in {
        VerificationStatus.PARTIAL,
        VerificationStatus.LIVE_VERIFIED,
    }
    assert first.row_status == ShortlistRowStatus.VERIFIED_LIVE
    assert first.current_price_signal == "CAD 780 total"
    assert first.min_three_beds_satisfied is True
    assert first.king_bed_preference_satisfied is True
    assert first.validation.evidence_artifacts
    assert first.validation.extracted_fields["price_signal"] == "CAD 780 total"
    assert researched.artifacts["deep_research"]["adapters_used"] == ["playwright"]


def test_lodging_deep_research_falls_back_when_openclaw_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)

    def blocked_fetcher(_url: str, _timeout: float) -> tuple[str, str, list[str]]:
        raise OSError("blocked fixture")

    service = SourceResearchService(
        adapters=[
            PlaywrightLodgingAdapter(fetcher=blocked_fetcher),
            OpenClawResearchAdapter(enabled=False),
            LinkResearchAdapter(),
        ],
        research_dir=tmp_path / "research",
    )
    researched = service.research_state(lodging, adapter_mode="auto")
    first = researched.lodging_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.LINK.value
    assert first.validation.verification_status == VerificationStatus.MANUAL_REQUIRED
    assert first.row_status == ShortlistRowStatus.RESEARCHED
    assert "final_total_price" in first.validation.missing_fields
    assert researched.artifacts["deep_research"]["status"] == SourceResearchStatus.PARTIAL.value


def test_flight_deep_research_enriches_existing_shortlist_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")
    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)

    html = """
    <html><body>
      Google Flights result. Azores Airlines S4 332. Nonstop.
      Departure 9:15 PM. Arrival 7:20 AM. Total duration 5h 55m.
      CAD 1,180 pp. Economy. Checked bag included. Select flight.
    </body></html>
    """
    service = SourceResearchService(
        adapters=[
            PlaywrightFlightAdapter(
                fetcher=lambda url, timeout: (html, url, ["fixture flight HTML"])
            ),
            OpenClawResearchAdapter(enabled=False),
            LinkResearchAdapter(),
        ],
        research_dir=tmp_path / "research",
    )
    researched = service.research_state(flights, adapter_mode="auto")
    first = researched.flight_options[0]

    assert first.validation.adapter_used == SourceAdapterCapability.PLAYWRIGHT.value
    assert first.row_status == ShortlistRowStatus.VERIFIED_LIVE
    assert first.departure_time == "9:15 PM"
    assert first.arrival_time == "7:20 AM"
    assert first.total_travel_duration == "5h 55m"
    assert first.price_band == "CAD 1,180 pp"
    assert first.stops == 0
    assert first.flight_numbers == ["S4332"]
    assert "exact_fare" not in first.validation.missing_fields
    assert "exact_departure_time" not in first.validation.missing_fields
    assert first.validation.evidence_artifacts
    assert researched.artifacts["deep_research"]["adapters_used"] == ["playwright"]
    assert first.recommendation_rationale
    assert first.date_viability_signal


def test_flight_deep_research_handles_partial_secondary_source_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")
    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)
    candidate = flights.flight_options[1]

    html = """
    <html><body>
      Kayak.ca flight result. Air Canada AC880 with TAP Portugal TP1861.
      9:15 PM - 2:20 PM. 10 hr 35 min. 1 stop via LIS.
      C$1,180 per person. Carry-on included. Select.
    </body></html>
    """
    service = SourceResearchService(
        adapters=[
            PlaywrightFlightAdapter(
                fetcher=lambda url, timeout: (html, url, ["fixture Kayak-like flight HTML"])
            ),
            OpenClawResearchAdapter(enabled=False),
            LinkResearchAdapter(),
        ],
        research_dir=tmp_path / "research",
    )
    researched = service.research_state(
        flights,
        adapter_mode="auto",
        option_ids=[candidate.option_id],
    )
    option = next(
        item for item in researched.flight_options if item.option_id == candidate.option_id
    )

    assert option.validation.adapter_used == SourceAdapterCapability.PLAYWRIGHT.value
    assert option.validation.verification_status in {
        VerificationStatus.PARTIAL,
        VerificationStatus.LIVE_VERIFIED,
    }
    assert option.departure_time == "9:15 PM"
    assert option.arrival_time == "2:20 PM"
    assert option.total_travel_duration == "10 hr 35 min"
    assert option.price_band == "C$1,180 per person"
    assert option.layover_airports == ["LIS"]
    assert option.recommendation_rationale
    assert "check-in" in option.timing_implication.lower() or option.stops == 1


def test_user_supplied_flight_candidate_flows_through_same_shortlist_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")

    state = FlightShortlistService(intake_service, planner).add_candidate(
        intake.trip_id,
        link="https://www.google.com/travel/flights/search?tfs=sample",
        name="Air Canada / TAP candidate",
        notes=(
            "Air Canada AC880 and TAP Portugal TP1861, depart 9:15 PM, arrive 2:20 PM, "
            "duration 10h 35m, 1 stop via LIS, layover 2h 20m, CAD 1180 pp, checked bag included."
        ),
    )

    candidate = [
        option for option in state.flight_options if option.option_id.startswith("user-flight-")
    ][0]
    assert candidate.booking_source == "Google Flights"
    assert candidate.departure_time == "9:15 PM"
    assert candidate.arrival_time == "2:20 PM"
    assert candidate.layover_airports == ["LIS"]
    assert candidate.layover_duration == "2h 20m"
    assert candidate.flight_numbers == ["AC880", "TP1861"]
    assert candidate.price_band == "CAD 1180 pp"
    assert candidate.row_status == ShortlistRowStatus.RESEARCHED
    assert candidate.validation.verification_status == VerificationStatus.MANUAL_REQUIRED
    assert candidate.date_viability_signal


def test_selecting_flight_updates_recommendation_and_workspace_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-two-island-balanced")

    state = FlightShortlistService(intake_service, planner).build(intake.trip_id)
    selected = FlightShortlistService(intake_service, planner).select_flight(
        intake.trip_id,
        state.flight_options[1].option_id,
    )

    assert selected.recommended_option_id == state.flight_options[1].option_id
    chosen = next(
        option
        for option in selected.flight_options
        if option.option_id == selected.recommended_option_id
    )
    assert chosen.row_status == ShortlistRowStatus.APPROVED
    assert chosen.recommendation_label.startswith("Selected")

    workspace = TripWorkspaceService(intake_service, planner).prepare(
        intake.trip_id,
        create_google_sheet=False,
    )
    tabs = {tab.name: tab for tab in workspace.tabs}
    overview = tabs["Overview"].rows
    timeline = tabs["Master Timeline"].rows
    assert any(row[0] == "Best Flight Rationale" and row[1] for row in overview)
    assert any(chosen.airline in row[6] for row in timeline)


def test_selected_plan_shapes_research_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "azores-sao-miguel-easy")

    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)
    cars = CarShortlistService(intake_service, planner).build(intake.trip_id)
    activities = ActivityShortlistService(intake_service, planner).build(intake.trip_id)

    assert lodging.lodging_options
    assert cars.car_options
    assert activities.activity_options
    assert all("Sao Miguel" in option.island_or_region for option in lodging.lodging_options)
    assert all("Pico" not in option.pickup_location for option in cars.car_options)
    assert all("Pico" not in option.island_location for option in activities.activity_options)
    assert all("Faial" not in option.island_location for option in activities.activity_options)


def test_trip_party_edge_cases_are_visible() -> None:
    couple = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Couple Trip",
        destination_seeds=["Greece"],
        party=TripParty(party_type=TripPartyType.COUPLE, adults=2, children=0, explicit=True),
    )
    one_parent = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="One Parent Trip",
        destination_seeds=["France"],
        party=TripParty(
            party_type=TripPartyType.SUBSET_FAMILY, adults=1, children=1, explicit=True
        ),
    )
    six = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Six Person Trip",
        destination_seeds=["Canada"],
        party=TripParty(
            party_type=TripPartyType.FAMILY_PLUS_OTHERS,
            adults=3,
            children=3,
            explicit=True,
            privacy_needs="Two bathrooms would materially improve comfort.",
        ),
    )
    unnamed = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Unnamed Four",
        destination_seeds=["Mexico"],
        travelers=4,
    )

    assert couple.party.total_travelers == 2
    assert couple.party.children == 0
    assert one_parent.party.summary().startswith("subset family; 2 traveler")
    assert six.party.total_travelers == 6
    assert "defaulted" not in six.party.summary()
    assert unnamed.party.total_travelers == 4
    assert "defaulted; confirm roster" in unnamed.party.summary()


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
            sleeping_considerations="At least 3 beds; king strongly preferred for adults.",
        ),
        departure_airports=["YYZ"],
        goals=["nature", "food", "relaxed adventure", "family comfort"],
        avoidances=["huge crowds", "overpacked days", "stressful driving"],
        freeform_notes="Golden-path selected destination planning scenario.",
    )
