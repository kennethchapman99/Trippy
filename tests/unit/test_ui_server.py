"""Tests for the local Trippy browser UI service."""

from __future__ import annotations

from pathlib import Path

import pytest

from trippy.services.learning import ProposalStatus
from trippy.ui.server import STATIC_DIR, TrippyUIService


def test_ui_service_runs_planning_and_feedback_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()

    intake_result = service.create_intake(
        {
            "trip_name": "Azores UI 2027",
            "destinations": "Azores",
            "travel_window": "June 2027 flexible",
            "duration": "6 to 8 days",
            "party_type": "whole_family",
            "adults": 2,
            "children": 3,
            "child_ages": "16, 14, 11",
            "roster": "Ken|adult, Jenn|adult, Child 1|16, Child 2|14, Child 3|11",
            "departure_airports": "YYZ",
            "goals": "food, whale watching, hot springs",
            "avoidances": "overpacked island hopping, tight transitions",
        }
    )
    trip_id = intake_result["intake"]["trip_id"]

    draft_result = service.draft_plan(trip_id)
    option_id = draft_result["draft"]["recommended_option_id"]
    service.select_plan(trip_id, option_id)
    flights = service.build_shortlist(trip_id, "flights")
    workspace = service.build_workspace(trip_id, create_google_sheet=False)
    snapshot = service.trip_state(trip_id)

    assert snapshot["intake"]["party"]["total_travelers"] == 5
    assert snapshot["draft"]["selected_option_id"] == option_id
    assert flights["shortlist"]["recommended_option_id"]
    assert workspace["workspace"]["status"] == "prepared_local"
    assert snapshot["shortlists"]

    feedback_result = service.add_feedback(
        {
            "workflow_id": flights["workflow_id"],
            "rating": "needs-work",
            "notes": "Prefer lower-friction direct routings even if they cost more.",
            "future_learning": True,
        }
    )

    assert feedback_result["learning_proposals"]
    proposals = service._learning.list_proposals(ProposalStatus.PENDING)
    assert any(
        proposal.source_feedback_id == feedback_result["feedback"]["id"] for proposal in proposals
    )

    logs = service.logs(trip_id=trip_id)
    event_types = {event["event_type"] for event in logs["events"]}
    assert logs["events_path"].endswith("events.jsonl")
    assert "workflow_outcome" in event_types
    assert "user_feedback" in event_types
    assert "learning_proposal" in event_types
    assert logs["pending_proposals"]


def test_ui_logs_capture_backend_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()

    service.record_ui_error(
        path="/api/shortlist",
        message="trip_id is required",
        payload={"category": "flights"},
    )

    logs = service.logs()
    assert logs["events"][-1]["event_type"] == "ui_error"
    assert logs["events"][-1]["severity"] == "error"
    assert logs["events"][-1]["summary"] == "trip_id is required"

    trip_logs = service.logs(trip_id="azores-2027")
    assert trip_logs["events"][-1]["event_type"] == "ui_error"


def test_ui_suggest_ideas_returns_concepts_and_records_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()

    result = service.suggest_ideas(
        {
            "party_type": "couple",
            "travelers": 2,
            "adults": 2,
            "children": 0,
            "time_of_year": "fall shoulder season",
            "duration_days": 9,
            "budget_cad": 18000,
            "max_flight_hours": 8,
            "activity_level": "balanced",
            "goals": "great food, walkable cities, culture",
            "avoidances": "huge crowds, stressful driving",
            "direct_flight_preferred": True,
        }
    )

    comparison = result["comparison"]
    assert result["workflow_id"]
    assert len(comparison["concepts"]) == 3
    assert comparison["request"]["travelers"] == 2
    assert comparison["request"]["duration_days"] == 9
    assert comparison["request"]["goals"] == ["great food", "walkable cities", "culture"]
    assert comparison["request"]["avoid"] == ["huge crowds", "stressful driving"]

    logs = service.logs()
    assert any(event["title"] == "ui-trip-ideas-suggest" for event in logs["events"])
    suggest_events = [
        event for event in logs["events"] if event["title"] == "ui-trip-ideas-suggest"
    ]
    assert suggest_events[-1]["metrics"]["concepts"] == 3


def test_ui_lodging_candidate_is_evaluated_in_shortlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    service.build_shortlist(trip_id, "lodging")

    result = service.add_lodging_candidate(
        {
            "trip_id": trip_id,
            "name": "Hotel do Test",
            "link": "https://www.booking.com/hotel/pt/hotel-do-test.html",
            "notes": "Ponta Delgada. CAD 420/night. 3 bedroom suite, king bed, parking, refundable cancellation.",
        }
    )

    candidates = [
        option
        for option in result["shortlist"]["lodging_options"]
        if option["option_id"].startswith("user-lodging-")
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source"] == "Booking.com"
    assert candidate["name"] == "Hotel do Test"
    assert candidate["min_three_beds_satisfied"] is True
    assert candidate["king_bed_preference_satisfied"] is True
    assert candidate["current_price_signal"] == "CAD 420/night"
    assert candidate["deep_link"].startswith("https://www.booking.com/")

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-lodging-candidate" for event in logs["events"])


def test_ui_flight_candidate_is_evaluated_in_shortlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    service.build_shortlist(trip_id, "flights")

    result = service.add_flight_candidate(
        {
            "trip_id": trip_id,
            "name": "Air Canada / TAP candidate",
            "link": "https://www.google.com/travel/flights/search?tfs=test",
            "notes": (
                "Air Canada AC880 and TAP Portugal TP1861, depart 9:15 PM, arrive 2:20 PM, "
                "duration 10h 35m, 1 stop via LIS, layover 2h 20m, CAD 1180 pp, checked bag included."
            ),
        }
    )

    candidates = [
        option
        for option in result["shortlist"]["flight_options"]
        if option["option_id"].startswith("user-flight-")
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["booking_source"] == "Google Flights"
    assert candidate["departure_time"] == "9:15 PM"
    assert candidate["arrival_time"] == "2:20 PM"
    assert candidate["layover_airports"] == ["LIS"]
    assert candidate["price_band"] == "CAD 1180 pp"

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-flight-candidate" for event in logs["events"])


def test_ui_select_flight_updates_canonical_shortlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    flights = service.build_shortlist(trip_id, "flights")
    option_id = flights["shortlist"]["flight_options"][1]["option_id"]

    result = service.select_flight({"trip_id": trip_id, "option_id": option_id})

    assert result["shortlist"]["recommended_option_id"] == option_id
    chosen = [
        option
        for option in result["shortlist"]["flight_options"]
        if option["option_id"] == option_id
    ][0]
    assert chosen["row_status"] == "approved"
    assert chosen["recommendation_label"].startswith("Selected")
    assert chosen["date_viability_signal"]
    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-flight-select" for event in logs["events"])


def test_ui_lodging_candidate_can_run_deep_source_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    fixture = tmp_path / "lodging-fixture.html"
    fixture.write_text(
        """
        <html><body>
          Casa Family. CAD 610/night. Available. 3 bedrooms, king bed, parking.
          Free cancellation. Ponta Delgada.
        </body></html>
        """,
        encoding="utf-8",
    )

    result = service.add_lodging_candidate(
        {
            "trip_id": trip_id,
            "name": "Casa Family",
            "link": str(fixture),
            "notes": "Candidate from local fixture.",
            "deep_research": True,
            "adapter": "playwright",
        }
    )

    candidate = [
        option
        for option in result["shortlist"]["lodging_options"]
        if option["option_id"].startswith("user-lodging-")
    ][0]
    assert candidate["validation"]["adapter_used"] == "playwright"
    assert candidate["current_price_signal"] == "CAD 610/night"
    assert candidate["min_three_beds_satisfied"] is True
    assert candidate["validation"]["evidence_artifacts"]


def test_ui_delete_trip_removes_local_planning_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    service.build_shortlist(trip_id, "lodging")
    service.build_workspace(trip_id, create_google_sheet=False)
    service.build_map(trip_id)

    from trippy import config

    assert service.trip_state(trip_id)["intake"]["trip_id"] == trip_id
    assert list(config.EXPORT_PATH.rglob(f"*{trip_id}*"))

    result = service.delete_trip(trip_id)

    assert result["deletion"]["deleted_count"] >= 5
    snapshot = service.trip_state(trip_id)
    assert snapshot["intake"] is None
    assert snapshot["draft"] is None
    assert snapshot["workspace"] is None
    assert snapshot["shortlists"] == []
    assert snapshot["map_artifact"] is None
    assert all(intake["trip_id"] != trip_id for intake in service.app_state()["intakes"])

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-delete" for event in logs["events"])


def test_ui_static_logo_is_available() -> None:
    assert (STATIC_DIR / "trippy-logo.png").exists()
    assert (STATIC_DIR / "app.css").exists()
    assert (STATIC_DIR / "app.js").exists()


def _create_selected_trip(service: TrippyUIService) -> str:
    intake_result = service.create_intake(
        {
            "trip_name": "Azores UI 2027",
            "destinations": "Azores",
            "travel_window": "June 2027 flexible",
            "duration": "6 to 8 days",
            "party_type": "whole_family",
            "adults": 2,
            "children": 3,
            "child_ages": "16, 14, 11",
            "roster": "Ken|adult, Jenn|adult, Child 1|16, Child 2|14, Child 3|11",
            "departure_airports": "YYZ",
            "goals": "food, whale watching, hot springs",
            "avoidances": "overpacked island hopping, tight transitions",
        }
    )
    trip_id = intake_result["intake"]["trip_id"]
    draft_result = service.draft_plan(trip_id)
    service.select_plan(trip_id, draft_result["draft"]["recommended_option_id"])
    return str(trip_id)


def _patch_ui_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
