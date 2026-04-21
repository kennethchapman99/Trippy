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
    assert flights.flight_options[0].validation.verification_status == VerificationStatus.MANUAL_REQUIRED
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

    validator = LiveValidationService(fetcher=lambda _url, _timeout: (True, 200, "fake live source OK"))
    validated = validator.validate_state(flights, attempt_network=True)
    first = validated.flight_options[0]

    assert first.row_status == ShortlistRowStatus.VERIFIED_LIVE
    assert first.validation.verification_status == VerificationStatus.LINK_VALIDATED
    assert first.validation.freshness_status == FreshnessStatus.CURRENT
    assert "exact_fare" in first.validation.missing_fields
    assert any("exact inventory" in note for note in first.validation.notes)


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
        party=TripParty(party_type=TripPartyType.SUBSET_FAMILY, adults=1, children=1, explicit=True),
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
