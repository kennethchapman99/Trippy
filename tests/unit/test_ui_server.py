"""Tests for the local Trippy browser UI service."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
            "destinations": "PDL, Ponta Delgada, Furnas",
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
    assert flights["shortlist"]["recommended_option_id"] is None
    assert flights["shortlist"]["flight_options"] == []
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


def test_ui_can_export_and_import_enriched_trip_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)

    exported = service.export_trip_json(trip_id)
    assert exported["schema"] == "trippy.trip_intake.v1"
    assert exported["resolver_evidence"]["destination_airports"]

    intake_json = exported["intake"]
    intake_json["trip_id"] = "imported-json-trip"
    intake_json["trip_name"] = "Imported JSON Trip"
    intake_json["geography"]["destination_airports"] = [
        {
            "iata_code": "ABC",
            "city": "User Supplied City",
            "country": "User Supplied Country",
            "source": "ui_test",
        }
    ]
    intake_json["geography"]["lodging_search_locations"] = ["User Supplied District"]

    imported = service.import_trip_json({"intake": intake_json, "overwrite": True})

    assert imported["intake"]["trip_id"] == "imported-json-trip"
    assert imported["resolver_evidence"]["destination_airports"][0]["iata_code"] == "ABC"
    assert service.export_trip_json("imported-json-trip")["intake"]["geography"][
        "lodging_search_locations"
    ] == ["User Supplied District"]


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


def test_ui_suggest_ideas_respects_six_day_prompt_and_can_capture_idea_feedback(
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
            "time_of_year": "late summer",
            "duration_days": 6,
            "max_flight_hours": 8,
            "goals": "great food, nature, low friction",
            "avoidances": "huge crowds, stressful transfers",
        }
    )

    comparison = result["comparison"]
    assert len(comparison["concepts"]) == 3
    assert all(concept["recommended_duration_days"] <= 6 for concept in comparison["concepts"])

    too_long_feedback = service.add_feedback(
        {
            "workflow_id": result["workflow_id"],
            "rating": "needs-work",
            "notes": "One of the generated ideas ignored the 6-day constraint.",
            "correction": "Respect the requested duration before ranking generated ideas.",
            "future_learning": True,
        }
    )

    assert too_long_feedback["learning_proposals"]
    logs = service.logs()
    assert any(event["title"] == "ui-trip-ideas-suggest" for event in logs["events"])
    assert any(event["event_type"] == "user_feedback" for event in logs["events"])


def test_ui_suggest_ideas_does_not_convert_region_words_to_destination_catalog(
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
            "time_of_year": "winter",
            "duration_days": 6,
            "max_flight_hours": 8,
            "goals": "Caribbean, beach, great food",
            "avoidances": "huge crowds, stressful transfers",
        }
    )

    concepts = result["comparison"]["concepts"]
    assert len(concepts) == 3
    output_text = " ".join(
        [
            *(concept["title"] for concept in concepts),
            *(slot for concept in concepts for slot in concept["destinations"]),
            *result["comparison"]["scoring_notes"],
        ]
    ).lower()
    assert "caribbean" not in output_text
    assert all(not concept["country_prior_signals"] for concept in concepts)


def test_ui_suggest_ideas_respects_snorkeling_requirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()

    result = service.suggest_ideas(
        {
            "party_type": "whole_family",
            "travelers": 5,
            "adults": 2,
            "children": 3,
            "child_ages": "16, 14, 11",
            "time_of_year": "march break",
            "duration_days": 7,
            "max_flight_hours": 5,
            "goals": "great food, low friction, memorable snorkling",
            "avoidances": "huge crowds, stressful transfers",
        }
    )

    concepts = result["comparison"]["concepts"]
    assert len(concepts) == 3
    output_text = " ".join(
        [
            *(concept["title"] for concept in concepts),
            *(slot for concept in concepts for slot in concept["destinations"]),
        ]
    ).lower()
    assert "cayman" not in output_text
    assert "belize" not in output_text
    assert all(
        any("snorkeling" in item for item in concept["rationale"]) for concept in concepts
    )


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
    structure = result["shortlist"]["artifacts"]["lodging_structure"]
    assert structure["strategy"] in {"single_stay", "split_stay"}
    assert structure["data_status"] == "inferred_from_selected_plan"
    assert structure["night_plan"]
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


def test_ui_can_select_lodging_and_override_stay_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    lodging = service.build_shortlist(trip_id, "lodging")
    option_id = lodging["shortlist"]["lodging_options"][0]["option_id"]

    selected = service.select_lodging({"trip_id": trip_id, "option_id": option_id})
    assert selected["shortlist"]["recommended_option_id"] == option_id
    chosen = next(
        option
        for option in selected["shortlist"]["lodging_options"]
        if option["option_id"] == option_id
    )
    assert chosen["row_status"] == "approved"

    deselected = service.deselect_lodging({"trip_id": trip_id, "option_id": option_id})
    removed = next(
        option
        for option in deselected["shortlist"]["lodging_options"]
        if option["option_id"] == option_id
    )
    assert removed["row_status"] == "researched"
    assert deselected["shortlist"]["artifacts"]["lodging_structure"]["selected_lodging_option_ids"] == []

    selected = service.select_lodging({"trip_id": trip_id, "option_id": option_id})
    assert selected["shortlist"]["recommended_option_id"] == option_id

    updated = service.update_lodging_structure(
        {
            "trip_id": trip_id,
            "strategy": "split_stay",
            "night_plan": [
                {
                    "region": "Ponta Delgada",
                    "nights": 4,
                    "lodging_option_id": option_id,
                    "notes": "central first base",
                },
                {
                    "region": "Furnas",
                    "nights": 3,
                    "notes": "hot springs side of the island",
                },
            ],
            "notes": "Testing whether a same-island split reduces backtracking.",
        }
    )

    structure = updated["shortlist"]["artifacts"]["lodging_structure"]
    assert structure["strategy"] == "split_stay"
    assert structure["data_status"] == "manual_override"
    assert structure["night_plan"][0]["region"] == "Ponta Delgada"
    assert structure["night_plan"][1]["nights"] == 3
    assert structure["selected_lodging_option_id"] == option_id

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-lodging-select" for event in logs["events"])
    assert any(event["title"] == "ui-trip-plan-lodging-structure" for event in logs["events"])


def test_ui_can_generate_stay_structure_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    service.build_shortlist(trip_id, "lodging")

    result = service.suggest_lodging_structures({"trip_id": trip_id, "use_llm": False})
    structure = result["shortlist"]["artifacts"]["lodging_structure"]
    options = structure["options"]

    assert result["option_count"] == 3
    assert len(options) == 3
    assert any(option["strategy"] == "split_stay" for option in options)
    assert any(
        any("activity side" in stay["region"] for stay in option["night_plan"])
        for option in options
    )
    assert any(
        event["title"] == "ui-trip-plan-lodging-structure-suggest"
        for event in service.logs(trip_id=trip_id)["events"]
    )


def test_ui_lodging_for_couple_does_not_force_family_bed_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    intake_result = service.create_intake(
        {
            "trip_name": "Azores Couple 2027",
            "destinations": "PDL, Ponta Delgada, Furnas",
            "travel_window": "September 2027 flexible",
            "duration": "6 to 8 days",
            "party_type": "couple",
            "travelers": 2,
            "adults": 2,
            "children": 0,
            "roster": "Ken|adult, Sue|adult",
            "departure_airports": "YYZ",
            "goals": "food, scenery, low friction",
            "avoidances": "huge crowds, stressful transfers",
        }
    )
    trip_id = intake_result["intake"]["trip_id"]
    draft = service.draft_plan(trip_id)
    service.select_plan(trip_id, draft["draft"]["recommended_option_id"])

    result = service.build_shortlist(trip_id, "lodging")

    first = result["shortlist"]["lodging_options"][0]
    assert first["bed_layout"] == "bed layout not confirmed yet"
    assert "family+room+3+beds" not in first["deep_link"]
    assert "king+bed" in first["deep_link"]


def test_ui_booking_lodging_links_include_trip_dates_and_party(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    intake_result = service.create_intake(
        {
            "trip_name": "Cayman Family 2027",
            "destinations": "GCM, Seven Mile Beach, West Bay",
            "start_date": "2027-03-13",
            "end_date": "2027-03-19",
            "duration": "7 days",
            "party_type": "whole_family",
            "adults": 2,
            "children": 3,
            "child_ages": "16, 14, 11",
            "roster": "Ken|adult, Jenn|adult, Child 1|16, Child 2|14, Child 3|11",
            "departure_airports": "YYZ",
        }
    )
    trip_id = intake_result["intake"]["trip_id"]
    draft = service.draft_plan(trip_id)
    service.select_plan(trip_id, draft["draft"]["recommended_option_id"])

    result = service.build_shortlist(trip_id, "lodging")

    first = result["shortlist"]["lodging_options"][0]
    params = parse_qs(urlparse(first["deep_link"]).query)
    assert params["checkin"] == ["2027-03-13"]
    assert params["checkout"] == ["2027-03-19"]
    assert params["group_adults"] == ["2"]
    assert params["group_children"] == ["3"]
    assert params["age"] == ["16", "14", "11"]
    assert params["no_rooms"] == ["1"]

    user = service.add_lodging_candidate(
        {
            "trip_id": trip_id,
            "name": "Oceanfront Seven Mile Beach 2 BR",
            "link": "https://www.booking.com/hotel/ky/oceanfront-seven-mile.html",
            "notes": "West Bay. CAD 900/night. 2 bedrooms, parking.",
        }
    )
    candidate = next(
        option
        for option in user["shortlist"]["lodging_options"]
        if option["option_id"].startswith("user-lodging-")
    )
    candidate_params = parse_qs(urlparse(candidate["deep_link"]).query)
    assert candidate_params["checkin"] == ["2027-03-13"]
    assert candidate_params["checkout"] == ["2027-03-19"]
    assert candidate_params["group_adults"] == ["2"]
    assert candidate_params["group_children"] == ["3"]
    assert candidate_params["age"] == ["16", "14", "11"]


def test_ui_can_approve_and_schedule_activity_for_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    activities = service.build_shortlist(trip_id, "activities")
    option_id = activities["shortlist"]["activity_options"][0]["option_id"]

    approved = service.select_activity({"trip_id": trip_id, "option_id": option_id})
    chosen = next(
        option
        for option in approved["shortlist"]["activity_options"]
        if option["option_id"] == option_id
    )
    assert chosen["row_status"] == "approved"
    assert chosen["scheduled_day"] == chosen["suggested_day"]
    assert approved["shortlist"]["artifacts"]["activity_schedule"]["entries"]

    scheduled = service.schedule_activity(
        {
            "trip_id": trip_id,
            "option_id": option_id,
            "day": 4,
            "date": "2027-06-18",
            "start_time": "10:15",
            "end_time": "13:00",
            "fixed": True,
            "notes": "Manual move after reviewing lodging base.",
        }
    )
    moved = next(
        option
        for option in scheduled["shortlist"]["activity_options"]
        if option["option_id"] == option_id
    )
    assert moved["scheduled_day"] == 4
    assert moved["scheduled_start_time"] == "10:15"
    assert moved["scheduled_flexibility"] == "fixed"

    workspace = service.build_workspace(trip_id, create_google_sheet=False)
    timeline = next(
        tab for tab in workspace["workspace"]["tabs"] if tab["name"] == "Master Timeline"
    )["rows"]
    assert any(row[5] == "activity" and row[2] == "10:15" for row in timeline)
    assert any("Manual move" in row[18] for row in timeline)

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-activity-select" for event in logs["events"])
    assert any(event["title"] == "ui-trip-plan-activity-schedule" for event in logs["events"])


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
            "flight_numbers": "AC880, TP1861",
            "departure_date": "2026-08-24",
            "departure_time": "9:15 PM",
            "arrival_date": "2026-08-25",
            "arrival_time": "2:20 PM",
            "total_duration": "10h 35m",
            "layover_airports": "LIS",
            "layover_duration": "2h 20m",
            "price_band": "CAD 1180 pp",
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
    assert candidate["flight_numbers"] == ["AC880", "TP1861"]
    assert candidate["departure_date"] == "2026-08-24"
    assert candidate["departure_time"] == "9:15 PM"
    assert candidate["arrival_date"] == "2026-08-25"
    assert candidate["arrival_time"] == "2:20 PM"
    assert candidate["layover_airports"] == ["LIS"]
    assert candidate["price_band"] == "CAD 1,180 total; CAD 236 per person"

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-flight-candidate" for event in logs["events"])


def test_ui_select_flight_updates_canonical_shortlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    flights = _add_ui_flight_candidates(service, trip_id)
    option_id = flights["shortlist"]["flight_options"][1]["option_id"]

    result = service.select_flight({"trip_id": trip_id, "option_id": option_id})

    assert result["shortlist"]["recommended_option_id"] == option_id
    chosen = [
        option
        for option in result["shortlist"]["flight_options"]
        if option["option_id"] == option_id
    ][0]
    assert chosen["row_status"] == "approved"
    assert chosen["recommendation_label"].startswith("Departure selected")
    assert chosen["date_viability_signal"]

    return_id = flights["shortlist"]["flight_options"][2]["option_id"]
    returned = service.select_flight(
        {"trip_id": trip_id, "option_id": return_id, "selection_kind": "return"}
    )
    selection = returned["shortlist"]["artifacts"]["flight_selection"]
    assert selection["selected_outbound_option_id"] == option_id
    assert selection["selected_return_option_id"] == return_id
    assert selection["constraint_status"] == "complete"
    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-flight-select" for event in logs["events"])


def test_ui_can_confirm_core_bookings_and_hydrate_trip_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    flights = _add_ui_flight_candidates(service, trip_id)
    lodging = service.build_shortlist(trip_id, "lodging")
    flight_id = flights["shortlist"]["flight_options"][0]["option_id"]
    lodging_id = lodging["shortlist"]["lodging_options"][0]["option_id"]
    service.select_flight({"trip_id": trip_id, "option_id": flight_id})
    service.select_lodging({"trip_id": trip_id, "option_id": lodging_id})

    flight_packet = service.update_trip_packet_item(
        {
            "trip_id": trip_id,
            "category": "flight",
            "option_id": flight_id,
            "status": "confirmed",
            "provider": "Azores Airlines",
            "confirmation_code": "S4-ABC123",
            "booking_link": "https://www.google.com/travel/flights",
            "date": "2027-06-12",
            "start_time": "21:15",
            "end_time": "08:30",
            "notes": "Seats still need assignment.",
        }
    )
    lodging_packet = service.update_trip_packet_item(
        {
            "trip_id": trip_id,
            "category": "lodging",
            "option_id": lodging_id,
            "status": "confirmed",
            "provider": "Booking.com",
            "confirmation_code": "BK-98765",
            "booking_link": "https://www.booking.com/",
            "address": "Ponta Delgada, Azores",
            "date": "2027-06-13",
            "notes": "Check-in after 15:00.",
        }
    )

    assert flight_packet["trip_packet"]["readiness_percent"] < 100
    assert lodging_packet["trip_packet"]["readiness_percent"] == 100
    assert lodging_packet["trip_packet"]["status_label"] == "trip packet confirmed"

    snapshot = service.trip_state(trip_id)
    flight_state = next(
        shortlist for shortlist in snapshot["shortlists"] if shortlist["category"] == "flights"
    )
    lodging_state = next(
        shortlist for shortlist in snapshot["shortlists"] if shortlist["category"] == "lodging"
    )
    assert flight_state["flight_options"][0]["row_status"] == "confirmed"
    assert lodging_state["lodging_options"][0]["row_status"] == "confirmed"

    workspace = service.build_workspace(trip_id, create_google_sheet=False)
    tabs = {tab["name"]: tab for tab in workspace["workspace"]["tabs"]}
    packet_rows = tabs["Trip Packet"]["rows"]
    timeline = tabs["Master Timeline"]["rows"]
    assert any(row[4] == "S4-ABC123" for row in packet_rows)
    assert any(row[4] == "BK-98765" for row in packet_rows)
    assert any("S4-ABC123" in row[10] for row in timeline)
    assert any("BK-98765" in row[10] for row in timeline)

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-packet-update" for event in logs["events"])


def test_ui_can_select_car_for_local_movement_planning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ui_paths(tmp_path, monkeypatch)
    service = TrippyUIService()
    trip_id = _create_selected_trip(service)
    cars = service.build_shortlist(trip_id, "cars")
    option_id = cars["shortlist"]["car_options"][1]["option_id"]

    result = service.select_car({"trip_id": trip_id, "option_id": option_id})

    assert result["shortlist"]["recommended_option_id"] == option_id
    chosen = [
        option for option in result["shortlist"]["car_options"] if option["option_id"] == option_id
    ][0]
    assert chosen["row_status"] == "approved"
    assert chosen["price_band"]
    assert chosen["comparison_links"]["Expedia"].startswith("https://www.expedia.ca/Cars-Search")
    assert result["shortlist"]["artifacts"]["selected_car_option_id"] == option_id

    workspace = service.build_workspace(trip_id, create_google_sheet=False)
    cars_tab = next(tab for tab in workspace["workspace"]["tabs"] if tab["name"] == "Cars")
    assert any(row[1] == "approved" for row in cars_tab["rows"])

    logs = service.logs(trip_id=trip_id)
    assert any(event["title"] == "ui-trip-plan-car-select" for event in logs["events"])


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
            "destinations": "PDL, Ponta Delgada, Furnas",
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


def _add_ui_flight_candidates(service: TrippyUIService, trip_id: str) -> dict[str, object]:
    service.build_shortlist(trip_id, "flights")
    state: dict[str, object] = {}
    for notes in [
        "YYZ to PDL nonstop candidate; provider evidence pending.",
        "YYZ to PDL one stop candidate; provider evidence pending.",
        "PDL to YYZ return candidate; provider evidence pending.",
    ]:
        state = service.add_flight_candidate(
            {
                "trip_id": trip_id,
                "link": "https://www.google.com/travel/flights/search",
                "notes": notes,
            }
        )
    return state


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
