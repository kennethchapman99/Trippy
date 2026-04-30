"""Tests for the new-trip intake -> plan -> workspace -> map pipeline."""

from __future__ import annotations

import json
from datetime import date
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
from trippy.models.trip import Trip
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
    WorkspaceStatus,
    WorkspaceTab,
)
from trippy.models.web_research import WebResearchResult
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
    PlaywrightActivityAdapter,
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
    assert draft.recommended_option_id == "two-region-balanced"
    balanced = draft.get_option(draft.recommended_option_id)
    assert balanced is not None
    assert "Ponta Delgada, Portugal" in balanced.regions
    assert "Furnas, Portugal" in balanced.regions
    assert balanced.recommendation_strength >= 80
    assert balanced.country_prior_signals

    selected = planner.select_option(intake.trip_id, "two-region-balanced")
    assert selected.selected_option_id == "two-region-balanced"

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
    assert tabs["Flights"].rows[0][1] in {"seeded", "researched", "verified_live"}
    assert tabs["Flights"].rows[0][2] == ""
    assert tabs["Lodging"].rows[0][1] in {"recommended", "researched"}
    assert tabs["Cars"].rows[0][8] >= 5
    timeline = tabs["Master Timeline"].rows
    assert any(row[5] == "activity" for row in timeline)
    assert [int(row[0]) for row in timeline] == sorted(int(row[0]) for row in timeline)
    assert all(row[1] for row in timeline)
    assert all("summer 2027" in row[1] for row in timeline)
    assert any("Traveler Roster" in row for row in tabs["Overview"].rows)

    canonical = TripStateService().load(intake.trip_id)
    assert canonical is not None
    assert canonical.status.value == "planned"
    assert canonical.stays

    artifact = TripMapBuilder(intake_service, planner).write_artifacts(
        intake.trip_id,
        tmp_path / "export" / "maps",
    )
    assert artifact.pins
    assert any(pin.category == MapPinCategory.ACTIVITY for pin in artifact.pins)
    assert Path(artifact.exports["json"]).exists()

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)
    cars = CarShortlistService(intake_service, planner).build(intake.trip_id)
    activities = ActivityShortlistService(intake_service, planner).build(intake.trip_id)

    assert flights.category == ShortlistCategory.FLIGHTS
    assert flights.recommended_option_id is None
    assert flights.flight_options == []
    assert any("failed closed" in warning for warning in flights.warnings)
    assert lodging.lodging_options
    assert lodging.recommended_option_id is not None
    assert cars.car_options[0].booking_source == "Booking.com"
    assert "cars" in cars.car_options[0].deep_link
    assert "Flights-Search" not in cars.car_options[1].deep_link
    assert all("/flights/" not in option.deep_link for option in cars.car_options)
    assert activities.activity_options[0].source == "GetYourGuide"
    activity_links = [
        link
        for option in activities.activity_options
        for link in [option.deep_link, *option.validation_links.values()]
    ]
    assert all("airbnb.ca" not in link for link in activity_links)
    assert all(
        "Airbnb Experiences" not in option.validation_links
        for option in activities.activity_options
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
    assert planned.shortlist_status["flights"].startswith("0 option")
    assert planned.planning_completeness < 100


def test_google_workspace_updates_existing_sheet_instead_of_creating_new() -> None:
    class _Request:
        def __init__(self, response: dict[str, object]) -> None:
            self.response = response

        def execute(self) -> dict[str, object]:
            return self.response

    class _Values:
        def __init__(self) -> None:
            self.batch_clears: list[dict[str, object]] = []
            self.batch_updates: list[dict[str, object]] = []

        def batchClear(self, spreadsheetId: str, body: dict[str, object]) -> _Request:  # noqa: N803
            self.batch_clears.append({"spreadsheetId": spreadsheetId, "body": body})
            return _Request({})

        def batchUpdate(self, spreadsheetId: str, body: dict[str, object]) -> _Request:  # noqa: N803
            self.batch_updates.append({"spreadsheetId": spreadsheetId, "body": body})
            return _Request({})

    class _Spreadsheets:
        def __init__(self) -> None:
            self.created: list[dict[str, object]] = []
            self.batch_updates: list[dict[str, object]] = []
            self.values_api = _Values()

        def create(self, body: dict[str, object]) -> _Request:
            self.created.append(body)
            return _Request({"spreadsheetId": "new-sheet", "spreadsheetUrl": "new-url"})

        def get(self, spreadsheetId: str, fields: str) -> _Request:  # noqa: N803
            return _Request(
                {
                    "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet-123",
                    "sheets": [
                        {"properties": {"sheetId": 1, "title": "Overview"}},
                        {"properties": {"sheetId": 2, "title": "Flights"}},
                    ],
                }
            )

        def batchUpdate(self, spreadsheetId: str, body: dict[str, object]) -> _Request:  # noqa: N803
            self.batch_updates.append({"spreadsheetId": spreadsheetId, "body": body})
            return _Request({})

        def values(self) -> _Values:
            return self.values_api

    class _SheetsService:
        def __init__(self) -> None:
            self.spreadsheets_api = _Spreadsheets()

        def spreadsheets(self) -> _Spreadsheets:
            return self.spreadsheets_api

    class _Auth:
        def __init__(self) -> None:
            self.service = _SheetsService()

        def build_service(self, name: str, version: str) -> _SheetsService:
            assert (name, version) == ("sheets", "v4")
            return self.service

    auth = _Auth()
    workspace = TripWorkspaceService(auth_manager=auth)
    result = workspace._try_create_google_sheet(
        Trip(trip_id="azores-2027", name="Azores 2027"),
        [
            WorkspaceTab(name="Overview", headers=["Field", "Value"], rows=[["Trip", "Azores"]]),
            WorkspaceTab(name="Flights", headers=["Airline"], rows=[["TAP"]]),
        ],
        folder_id=None,
        existing_sheet_id="sheet-123",
        existing_sheet_url="https://docs.google.com/spreadsheets/d/sheet-123",
    )

    sheets = auth.service.spreadsheets_api
    assert result["spreadsheet_id"] == "sheet-123"
    assert result["operation"] == "updated"
    assert sheets.created == []
    assert sheets.values_api.batch_clears[0]["spreadsheetId"] == "sheet-123"
    assert sheets.values_api.batch_updates[0]["spreadsheetId"] == "sheet-123"


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
            "PDL, Ponta Delgada, Furnas",
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
    assert option_id == "two-region-balanced"

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
    assert workspace_tabs["Flights"]["rows"][0][1] in {"seeded", "researched", "verified_live"}
    assert workspace_tabs["Flights"]["rows"][0][2] in {"", "yes"}

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
    assert map_payload["map"]["pins"][0]["label"].startswith("01 ·")
    assert "google.com/maps/dir" in map_payload["map"]["primary_google_maps_url"]
    assert Path(map_payload["map"]["exports"]["kml"]).exists()
    assert Path(map_payload["map"]["exports"]["csv"]).exists()
    assert "01," in Path(map_payload["map"]["exports"]["csv"]).read_text(encoding="utf-8")
    assert map_payload["workflow_id"].startswith("wf-")

    for command in ("flights", "lodging", "cars", "activities"):
        result = runner.invoke(
            app,
            ["trip-plan", command, "--trip-id", trip_id, "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["shortlist"]["trip_id"] == trip_id
        if command == "flights":
            assert payload["shortlist"]["recommended_option_id"] is None
            assert payload["shortlist"]["flight_options"] == []
        else:
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
    planner.select_option(intake.trip_id, "two-region-balanced")

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
    assert result["recommended_option_id"] is None
    assert result["flight_options"] == []


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
    planner.select_option(intake.trip_id, "two-region-balanced")
    service = FlightShortlistService(intake_service, planner)
    flights = service.add_candidate(
        intake.trip_id,
        link="https://www.google.com/travel/flights/search",
        notes="YYZ to PDL nonstop candidate; provider evidence pending.",
    )

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
    planner.select_option(intake.trip_id, "two-region-balanced")
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
    planner.select_option(intake.trip_id, "two-region-balanced")
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
    planner.select_option(intake.trip_id, "two-region-balanced")
    service_builder = FlightShortlistService(intake_service, planner)
    flights = service_builder.add_candidate(
        intake.trip_id,
        link="https://www.google.com/travel/flights/search",
        notes="YYZ to PDL nonstop candidate; provider evidence pending.",
    )

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


def test_flight_shortlist_uses_duffel_live_offers_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("trippy.config.DUFFEL_ACCESS_TOKEN", "test-token")

    def fake_duffel_request(token: str, payload: dict[str, object]) -> dict[str, object]:
        assert token == "test-token"
        data = payload["data"]
        assert isinstance(data, dict)
        slices = data["slices"]
        assert isinstance(slices, list)
        assert slices[0]["origin"] == "YYZ"
        assert slices[0]["destination"] == "PDL"
        return {
            "data": {
                "offers": [
                    {
                        "id": "off_live_1",
                        "total_amount": "1180.00",
                        "total_currency": "CAD",
                        "owner": {"name": "Azores Airlines"},
                        "slices": [
                            {
                                "duration": "PT5H55M",
                                "segments": [
                                    {
                                        "departing_at": "2027-06-15T21:15:00-04:00",
                                        "arriving_at": "2027-06-16T07:10:00+00:00",
                                        "origin": {"iata_code": "YYZ"},
                                        "destination": {"iata_code": "PDL"},
                                        "marketing_carrier": {
                                            "iata_code": "S4",
                                            "name": "Azores Airlines",
                                        },
                                        "operating_carrier": {"name": "Azores Airlines"},
                                        "marketing_carrier_flight_number": "332",
                                    }
                                ],
                            },
                            {
                                "duration": "PT6H20M",
                                "segments": [
                                    {
                                        "departing_at": "2027-06-22T10:00:00+00:00",
                                        "arriving_at": "2027-06-22T14:20:00-04:00",
                                        "origin": {"iata_code": "PDL"},
                                        "destination": {"iata_code": "YYZ"},
                                        "marketing_carrier": {
                                            "iata_code": "S4",
                                            "name": "Azores Airlines",
                                        },
                                        "operating_carrier": {"name": "Azores Airlines"},
                                        "marketing_carrier_flight_number": "331",
                                    }
                                ],
                            },
                        ],
                    }
                ]
            }
        }

    monkeypatch.setattr(
        "trippy.services.flight_shortlist._post_duffel_offer_request",
        fake_duffel_request,
    )
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)
    option = flights.flight_options[0]

    assert option.option_id == "duffel-flight-1"
    assert option.booking_source == "Duffel"
    assert option.flight_numbers == ["S4332"]
    assert option.departure_date == "2027-06-15"
    assert option.departure_time == "9:15 PM"
    assert option.arrival_date == "2027-06-16"
    assert option.arrival_time == "7:10 AM"
    assert option.total_travel_duration == "5h 55m"
    assert option.price_band == "CAD 1,180 total; CAD 236 per person"
    assert option.deep_link.startswith("https://www.google.com/travel/flights/search?")
    assert option.row_status == ShortlistRowStatus.VERIFIED_LIVE
    assert option.validation.adapter_used == "duffel"
    assert "Duffel returned 1 exact offer row" in " ".join(flights.warnings)


def test_flight_shortlist_ignores_duffel_sandbox_airways_offers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("trippy.config.DUFFEL_ACCESS_TOKEN", "test-token")

    def fake_duffel_request(token: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "data": {
                "offers": [
                    {
                        "id": "off_test_1",
                        "total_amount": "369.66",
                        "total_currency": "CAD",
                        "owner": {"name": "Duffel Airways"},
                        "slices": [
                            {
                                "duration": "PT6H35M",
                                "segments": [
                                    {
                                        "departing_at": "2026-08-24T17:48:00-04:00",
                                        "arriving_at": "2026-08-25T04:23:00+00:00",
                                        "origin": {"iata_code": "YYZ"},
                                        "destination": {"iata_code": "PDL"},
                                        "marketing_carrier": {
                                            "iata_code": "ZZ",
                                            "name": "Duffel Airways",
                                        },
                                        "operating_carrier": {"name": "Duffel Airways"},
                                        "marketing_carrier_flight_number": "7753",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }

    monkeypatch.setattr(
        "trippy.services.flight_shortlist._post_duffel_offer_request",
        fake_duffel_request,
    )
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)

    assert all("Duffel Airways" not in option.airline for option in flights.flight_options)
    assert all("ZZ7753" not in option.flight_numbers for option in flights.flight_options)
    assert "Ignored 1 Duffel sandbox/test offer" in " ".join(flights.warnings)


def test_flight_shortlist_ignores_duffel_offers_with_impossible_date_spans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("trippy.config.DUFFEL_ACCESS_TOKEN", "test-token")

    def fake_duffel_request(token: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "data": {
                "offers": [
                    {
                        "id": "off_bad_span",
                        "total_amount": "1299.80",
                        "total_currency": "USD",
                        "owner": {"name": "TAP Air Portugal"},
                        "slices": [
                            {
                                "duration": "PT17H",
                                "segments": [
                                    {
                                        "departing_at": "2026-08-24T17:45:00-04:00",
                                        "arriving_at": "2026-08-25T05:45:00+00:00",
                                        "origin": {"iata_code": "YYZ"},
                                        "destination": {"iata_code": "LIS"},
                                        "marketing_carrier": {
                                            "iata_code": "TP",
                                            "name": "TAP Air Portugal",
                                        },
                                        "operating_carrier": {"name": "TAP Air Portugal"},
                                        "marketing_carrier_flight_number": "258",
                                    },
                                    {
                                        "departing_at": "2026-08-31T12:30:00+00:00",
                                        "arriving_at": "2026-08-31T14:45:00+00:00",
                                        "origin": {"iata_code": "LIS"},
                                        "destination": {"iata_code": "PDL"},
                                        "marketing_carrier": {
                                            "iata_code": "TP",
                                            "name": "TAP Air Portugal",
                                        },
                                        "operating_carrier": {"name": "TAP Air Portugal"},
                                        "marketing_carrier_flight_number": "1861",
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        }

    monkeypatch.setattr(
        "trippy.services.flight_shortlist._post_duffel_offer_request",
        fake_duffel_request,
    )
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)

    assert all(option.booking_source != "Duffel" for option in flights.flight_options)
    assert all(option.arrival_date != "2026-08-31" for option in flights.flight_options)
    assert "Ignored 1 Duffel offer row" in " ".join(flights.warnings)


def test_flight_deep_research_handles_partial_secondary_source_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")
    flight_service = FlightShortlistService(intake_service, planner)
    flights = flight_service.add_candidate(
        intake.trip_id,
        link="https://www.ca.kayak.com/flights/YYZ-PDL/2027-06-15/2027-06-25/5adults",
        notes="YYZ to PDL one stop via LIS; secondary source evidence pending.",
    )
    flights = flight_service.add_candidate(
        intake.trip_id,
        link="https://www.ca.kayak.com/flights/YYZ-PDL/2027-06-15/2027-06-25/5adults",
        notes="YYZ to PDL one stop via LIS; partial secondary source text.",
    )
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
    planner.select_option(intake.trip_id, "two-region-balanced")

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
    assert candidate.price_band == "CAD 1,180 total; CAD 236 per person"
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
    planner.select_option(intake.trip_id, "two-region-balanced")

    flight_service = FlightShortlistService(intake_service, planner)
    state = flight_service.add_candidate(
        intake.trip_id,
        link="https://www.google.com/travel/flights/search",
        notes="YYZ to PDL nonstop candidate; provider evidence pending.",
    )
    state = flight_service.add_candidate(
        intake.trip_id,
        link="https://www.google.com/travel/flights/search",
        notes="YYZ to PDL one stop candidate; provider evidence pending.",
    )
    state = flight_service.add_candidate(
        intake.trip_id,
        link="https://www.google.com/travel/flights/search",
        notes="PDL to YYZ return candidate; provider evidence pending.",
    )
    selected = flight_service.select_flight(
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
    assert chosen.recommendation_label.startswith("Departure selected")
    assert selected.artifacts["flight_selection"]["selected_outbound_option_id"] == chosen.option_id

    return_selected = flight_service.select_flight(
        intake.trip_id,
        state.flight_options[2].option_id,
        selection_kind="return",
    )
    assert (
        return_selected.artifacts["flight_selection"]["selected_return_option_id"]
        == state.flight_options[2].option_id
    )
    assert return_selected.artifacts["flight_selection"]["constraint_status"] == "complete"

    workspace = TripWorkspaceService(intake_service, planner).prepare(
        intake.trip_id,
        create_google_sheet=False,
    )
    tabs = {tab.name: tab for tab in workspace.tabs}
    overview = tabs["Overview"].rows
    timeline = tabs["Master Timeline"].rows
    assert any(row[0] == "Best Flight Rationale" and row[1] for row in overview)
    assert any(chosen.airline in row[6] for row in timeline)


def test_selecting_lodging_and_manual_split_drives_workspace_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    lodging_service = LodgingShortlistService(intake_service, planner)
    lodging = lodging_service.build(intake.trip_id)
    option_id = lodging.lodging_options[0].option_id
    selected = lodging_service.select_lodging(intake.trip_id, option_id)
    assert selected.recommended_option_id == option_id
    assert selected.lodging_options[0].row_status == ShortlistRowStatus.APPROVED

    updated = lodging_service.update_stay_structure(
        intake.trip_id,
        strategy="split_stay",
        night_plan=[
            {
                "region": "Ponta Delgada",
                "nights": 4,
                "lodging_option_id": option_id,
                "notes": "central first base",
            },
            {
                "region": "Furnas",
                "nights": 3,
                "notes": "second base to reduce backtracking",
            },
        ],
        notes="Manual same-island split test.",
    )
    structure = updated.artifacts["lodging_structure"]
    assert structure["strategy"] == "split_stay"
    assert structure["data_status"] == "manual_override"

    workspace = TripWorkspaceService(intake_service, planner).prepare(
        intake.trip_id,
        create_google_sheet=False,
    )
    tabs = {tab.name: tab for tab in workspace.tabs}
    stay_plan = tabs["Stay Plan"].rows
    timeline = tabs["Master Timeline"].rows
    assert any(row[1] == "Furnas" and row[2] == 3 for row in stay_plan)
    assert any(row[6] == "Check in: Furnas" for row in timeline)
    assert any("second base" in row[18] for row in timeline)


def test_selecting_multiple_lodging_options_preserves_split_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    lodging_service = LodgingShortlistService(intake_service, planner)
    lodging = lodging_service.build(intake.trip_id)
    first_id = lodging.lodging_options[0].option_id
    second_id = lodging.lodging_options[1].option_id

    lodging_service.select_lodging(intake.trip_id, first_id)
    selected = lodging_service.select_lodging(intake.trip_id, second_id)

    approved = {
        option.option_id
        for option in selected.lodging_options
        if option.row_status == ShortlistRowStatus.APPROVED
    }
    structure = selected.artifacts["lodging_structure"]
    assert approved == {first_id, second_id}
    assert structure["selected_lodging_option_ids"] == [first_id, second_id]
    assert structure["selected_lodging_option_id"] == second_id


def test_deselecting_lodging_removes_it_from_split_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "two-region-balanced")

    lodging_service = LodgingShortlistService(intake_service, planner)
    lodging = lodging_service.build(intake.trip_id)
    first_id = lodging.lodging_options[0].option_id
    second_id = lodging.lodging_options[1].option_id

    lodging_service.select_lodging(intake.trip_id, first_id)
    lodging_service.select_lodging(intake.trip_id, second_id)
    updated = lodging_service.deselect_lodging(intake.trip_id, first_id)

    statuses = {option.option_id: option.row_status for option in updated.lodging_options}
    structure = updated.artifacts["lodging_structure"]
    assert statuses[first_id] == ShortlistRowStatus.RESEARCHED
    assert statuses[second_id] == ShortlistRowStatus.APPROVED
    assert structure["selected_lodging_option_ids"] == [second_id]
    assert structure["selected_lodging_option_id"] == second_id


def test_lodging_service_suggests_editable_split_stay_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    lodging_service = LodgingShortlistService(intake_service, planner)
    lodging_service.build(intake.trip_id)
    updated = lodging_service.suggest_stay_structures(intake.trip_id, use_llm=False)

    structure = updated.artifacts["lodging_structure"]
    options = structure["options"]
    assert len(options) == 3
    assert {option["strategy"] for option in options} == {"single_stay", "split_stay"}
    assert all(option["night_plan"] for option in options)
    assert any(
        any("activity side" in stay["region"] for stay in option["night_plan"])
        for option in options
    )
    assert len({option["thumbnail_variant"] for option in options}) >= 2


def test_lodging_split_seeds_options_for_each_saved_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    lodging_service = LodgingShortlistService(intake_service, planner)
    lodging_service.build(intake.trip_id)
    updated = lodging_service.update_stay_structure(
        intake.trip_id,
        strategy="split_stay",
        night_plan=[
            {"region": "Ponta Delgada / south coast", "nights": 4},
            {"region": "Ribeira Grande / north coast", "nights": 2},
        ],
        notes="Testing a north-coast second base.",
    )

    regions = [option.location_area for option in updated.lodging_options]
    assert any("Ponta Delgada" in region for region in regions)
    assert any("Ribeira Grande" in region for region in regions)
    ribeira = next(
        option for option in updated.lodging_options if "Ribeira Grande" in option.location_area
    )
    assert ribeira.option_id.startswith("stay-region-lodging-ribeira-grande")
    assert any("location-specific search seed" in flag for flag in ribeira.friction_flags)


def test_selected_plan_shapes_research_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)
    cars = CarShortlistService(intake_service, planner).build(intake.trip_id)
    activities = ActivityShortlistService(intake_service, planner).build(intake.trip_id)

    assert lodging.lodging_options
    assert cars.car_options
    assert activities.activity_options
    assert any("Ponta Delgada" in option.island_or_region for option in lodging.lodging_options)
    assert any("Furnas" in option.island_or_region for option in lodging.lodging_options)
    lodging_sources = {option.source for option in lodging.lodging_options}
    assert {"Airbnb", "VRBO", "Google Search"} <= lodging_sources
    assert any(
        "best boutique hotels" in option.name.lower()
        for option in lodging.lodging_options
    )
    lodging_links = [
        link
        for option in lodging.lodging_options
        for link in [option.deep_link, *option.validation_links.values()]
    ]
    assert any("airbnb.ca" in link for link in lodging_links)
    assert any("vrbo.com" in link for link in lodging_links)
    assert all("Pico" not in option.pickup_location for option in cars.car_options)
    assert all("Pico" not in option.island_location for option in activities.activity_options)
    assert all("Faial" not in option.island_location for option in activities.activity_options)


def test_lodging_deep_research_promotes_reviewed_exact_property_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)

    class _Availability:
        available = True
        reason = ""

    class _FakeFirecrawl:
        def availability(self) -> _Availability:
            return _Availability()

        def research(self, query: str, *, limit: int | None = None) -> list[WebResearchResult]:
            return [
                WebResearchResult(
                    id="fake-lodging-result",
                    query=query,
                    source_url="https://www.airbnb.ca/rooms/casa-atlantica",
                    source_title="Casa Atlantica Family Villa",
                    source_domain="airbnb.ca",
                    raw_markdown_excerpt=(
                        "Casa Atlantica Family Villa. Available for 2027-06-15 to 2027-06-25. "
                        "3 bedrooms, king bed, parking, free cancellation. CAD 4,800 total."
                    ),
                    confidence=0.84,
                )
            ]

    monkeypatch.setattr("trippy.services.lodging_shortlist.FirecrawlService", _FakeFirecrawl)
    intake_service = TripIntakeService()
    intake_payload = _azores_intake()
    intake_payload.travel_window = TravelWindow(
        start_date=date(2027, 6, 15),
        end_date=date(2027, 6, 25),
    )
    intake = intake_service.create(intake_payload)
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    lodging = LodgingShortlistService(intake_service, planner).build(
        intake.trip_id,
        deep_research=True,
        adapter_mode="link",
    )

    reviewed = [
        option
        for option in lodging.lodging_options
        if option.option_id.startswith("reviewed-lodging-")
    ]
    assert reviewed
    candidate = reviewed[0]
    assert candidate.name == "Casa Atlantica Family Villa"
    assert candidate.min_three_beds_satisfied is True
    assert candidate.current_price_signal == "CAD 4,800 total"
    assert "2027-06-15 to 2027-06-25" in candidate.current_availability_signal
    assert candidate.recommendation_grade.value == "good"
    assert candidate.validation.adapter_used == "firecrawl/lodging-discovery-review"
    assert lodging.recommended_option_id == candidate.option_id
    review = lodging.artifacts["lodging_discovery_review"]
    assert review["status"] == "completed"
    assert review["accepted_candidates"]


def test_generic_activity_shortlist_offers_multiple_specific_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(
        TripIntake(
            mode=TripIntakeMode.SELECTED_DESTINATION,
            trip_name="Grand Cayman",
            destination_seeds=[
                "Seven Mile Beach",
                "West Bay",
                "Stingray City or Rum Point",
            ],
            duration_days=7,
            party=TripParty(
                party_type=TripPartyType.WHOLE_FAMILY,
                adults=2,
                children=3,
                explicit=True,
            ),
        )
    )
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    activities = ActivityShortlistService(intake_service, planner).build(intake.trip_id)

    assert len(activities.activity_options) >= 1
    names = " ".join(option.activity_name for option in activities.activity_options)
    assert "Seven Mile Beach" in names
    assert "West Bay" in names
    assert "Stingray" in names
    assert all(option.price_band == "source price required" for option in activities.activity_options)
    assert all(
        option.duration == "source schedule required" for option in activities.activity_options
    )
    assert all(not option.suggested_start_time for option in activities.activity_options)
    assert all("airbnb.ca" not in option.deep_link for option in activities.activity_options)


def test_grand_cayman_flight_shortlist_uses_gcm_not_generic_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(
        TripIntake(
            mode=TripIntakeMode.SELECTED_DESTINATION,
            trip_name="Cayman Reef + Food Easy Week",
            destination_seeds=[
                "Seven Mile Beach",
                "West Bay",
                "Stingray City or Rum Point",
            ],
            duration_days=7,
            party=TripParty(
                party_type=TripPartyType.WHOLE_FAMILY,
                adults=2,
                children=3,
                explicit=True,
            ),
            departure_airports=["YYZ"],
        )
    )
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)

    assert flights.flight_options == []
    assert flights.recommended_option_id is None
    assert any("fail closed" in warning.lower() for warning in flights.warnings)


def test_activity_deep_research_extracts_cost_time_and_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)

    def fake_fetcher(url: str, timeout: float) -> tuple[str, str, list[str]]:
        return (
            """
            <html><body>
            <h1>Stingray Sandbar small-group tour</h1>
            <p>From C$89 per person. Check availability. Free cancellation.</p>
            <p>Starts at 9:30 AM and ends at 12:30 PM. Duration 3 hours.</p>
            <p>Small group limited to 10. Rated 4.8 out of 5.</p>
            </body></html>
            """,
            url,
            ["fixture activity page"],
        )

    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_intake())
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)
    planner.select_option(intake.trip_id, "single-base-easy")
    activities = ActivityShortlistService(intake_service, planner).build(intake.trip_id)

    researched = SourceResearchService(
        adapters=[PlaywrightActivityAdapter(fetcher=fake_fetcher)],
        research_dir=tmp_path / "research",
    ).research_state(activities, adapter_mode="playwright")
    option = researched.activity_options[0]

    assert option.price_band == "C$89 per person"
    assert option.duration in {"3 hours", "3 h"}
    assert option.suggested_start_time == "9:30 AM"
    assert option.suggested_end_time == "12:30 PM"
    assert "availability_signal" in option.validation.extracted_fields
    assert option.validation.price_status.value == "live_signal"
    assert option.validation.availability_status.value == "availability_signal"


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


def test_generic_single_base_plan_uses_one_lodging_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(
        TripIntake(
            mode=TripIntakeMode.SELECTED_DESTINATION,
            trip_name="Grand Cayman",
            destination_seeds=[
                "Seven Mile Beach",
                "West Bay",
                "Stingray City or Rum Point",
            ],
            duration_days=7,
            party=TripParty(
                party_type=TripPartyType.WHOLE_FAMILY,
                adults=2,
                children=3,
                explicit=True,
            ),
        )
    )

    planner = TripPlannerService(intake_service)
    draft = planner.draft(intake.trip_id)
    assert len(draft.options) == 3

    single_base = draft.get_option("single-base-easy")
    assert single_base is not None
    assert single_base.title == "Seven Mile Beach Single-Base Easy Version"
    assert single_base.regions == ["Seven Mile Beach"]
    assert single_base.nights_by_region == {"Seven Mile Beach": 6}

    balanced = draft.get_option("two-region-balanced")
    assert balanced is not None
    assert balanced.regions == ["Seven Mile Beach", "West Bay"]
    assert set(balanced.nights_by_region) == {"Seven Mile Beach", "West Bay"}

    fuller = draft.get_option("multi-spot-fuller-version")
    assert fuller is not None
    assert fuller.regions == ["Seven Mile Beach", "West Bay", "Stingray City or Rum Point"]
    assert set(fuller.nights_by_region) == {
        "Seven Mile Beach",
        "West Bay",
        "Stingray City or Rum Point",
    }

    stale = draft.model_dump(mode="json")
    for option in stale["options"]:
        if option["option_id"] == "single-base-easy":
            option["title"] = (
                "Seven Mile Beach, West Bay, Stingray City or Rum Point Single-Base Easy Version"
            )
            option["regions"] = [
                "Seven Mile Beach",
                "West Bay",
                "Stingray City or Rum Point",
            ]
            option["nights_by_region"] = {
                "Seven Mile Beach": 2,
                "West Bay": 2,
                "Stingray City or Rum Point": 2,
            }
        if option["option_id"] == "two-region-balanced":
            option["regions"] = [
                "Seven Mile Beach",
                "West Bay",
                "Stingray City or Rum Point",
            ]
            option["nights_by_region"] = {
                "Seven Mile Beach": 3,
                "West Bay": 3,
            }
    planner.path_for(intake.trip_id).write_text(json.dumps(stale), encoding="utf-8")

    loaded = planner.load_draft(intake.trip_id)
    assert loaded is not None
    loaded_single = loaded.get_option("single-base-easy")
    assert loaded_single is not None
    assert loaded_single.title == "Seven Mile Beach Single-Base Easy Version"
    assert loaded_single.regions == ["Seven Mile Beach"]
    assert loaded_single.nights_by_region == {"Seven Mile Beach": 6}
    loaded_balanced = loaded.get_option("two-region-balanced")
    assert loaded_balanced is not None
    assert loaded_balanced.regions == ["Seven Mile Beach", "West Bay"]


def test_picked_trip_idea_drafts_shapes_inside_selected_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(
        TripIntake(
            mode=TripIntakeMode.IDEA,
            trip_name="Cayman Reef + Food Easy Week",
            destination_seeds=[
                "Seven Mile Beach",
                "West Bay",
                "Stingray City or Rum Point",
            ],
            duration_days=7,
            party=TripParty(
                party_type=TripPartyType.WHOLE_FAMILY,
                adults=2,
                children=3,
                explicit=True,
            ),
        )
    )

    draft = TripPlannerService(intake_service).draft(intake.trip_id)

    assert {option.option_id for option in draft.options} == {
        "single-base-easy",
        "two-region-balanced",
        "multi-spot-fuller-version",
    }
    assert all(
        set(option.regions)
        <= {"Seven Mile Beach", "West Bay", "Stingray City or Rum Point"}
        for option in draft.options
    )
    assert not any(
        destination in option.title or destination in option.summary
        for option in draft.options
        for destination in ("Mexico", "Belize")
    )


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
        goals=["nature", "food", "relaxed adventure", "family comfort"],
        avoidances=["huge crowds", "overpacked days", "stressful driving"],
        freeform_notes="Golden-path selected destination planning scenario.",
    )
