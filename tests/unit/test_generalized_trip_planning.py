"""Regression tests that keep Trippy's planning pipeline destination-agnostic."""

from __future__ import annotations

from pathlib import Path

from trippy.models.trip_planning import TripIntake, TripIntakeMode
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.geography_resolver import resolve_trip_geography
from trippy.services.trip_planner import TripPlannerService


GENERIC_PLAN_IDS = {
    "single-base-easy",
    "two-region-balanced",
    "multi-spot-fuller-version",
}


def test_trip_planner_does_not_ship_destination_specific_branches() -> None:
    source = Path("trippy/services/trip_planner.py").read_text(encoding="utf-8")

    forbidden = [
        "_is_azores",
        "_build_azores_draft",
        "_azores_easy_option",
        "_azores_balanced_option",
        "_azores_ambitious_option",
        "azores-two-island-balanced",
        "azores-sao-miguel-easy",
    ]
    for token in forbidden:
        assert token not in source


def test_destination_profiles_are_resolver_driven_not_static_destination_apps() -> None:
    source = Path("trippy/services/destination_profiles.py").read_text(encoding="utf-8")

    forbidden = [
        "_AZORES",
        "_GRAND_CAYMAN",
        "_chile_profile",
        "_looks_like_chile",
        "_looks_like_grand_cayman",
        "if \"azores\" in lower_text",
    ]
    for token in forbidden:
        assert token not in source


def test_selected_destination_planner_uses_generic_shapes_for_any_destination() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Chile family trip",
        destination_seeds=[
            "Santiago-Providencia-Santiago-Bellavista-Santiago-Barrio-Italia-Maipo-Valley"
        ],
        departure_airports=["YYZ"],
        duration_days=8,
    )

    draft = TripPlannerService()._build_draft(intake)

    assert {option.option_id for option in draft.options} == GENERIC_PLAN_IDS
    assert draft.recommended_option_id in GENERIC_PLAN_IDS
    assert all(not option.option_id.startswith("chile") for option in draft.options)
    assert all(not option.option_id.startswith("azores") for option in draft.options)
    assert any("not a hardcoded destination profile" in note for note in draft.assumptions)


def test_resolved_geography_separates_flight_codes_from_place_search_targets() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Chile family trip",
        destination_seeds=[
            "Santiago-Providencia-Santiago-Bellavista-Santiago-Barrio-Italia-Maipo-Valley"
        ],
        departure_airports=["YYZ"],
    )

    geography = resolve_trip_geography(intake)
    profile = profile_for_intake(intake)

    assert geography.connector_inputs()["flights"] == {
        "from": "YYZ",
        "to": "SCL",
        "status": "ready",
    }
    assert profile.gateway_airports == ["SCL"]
    assert all(len(code) == 3 and code.isupper() for code in profile.gateway_airports)

    non_flight_text = " ".join(
        [
            str(profile.lodging_search_targets),
            str(profile.car_search_targets),
            str(profile.activity_search_targets),
        ]
    )
    assert "Providencia" in non_flight_text
    assert "Bellavista" in non_flight_text
    assert "Maipo" in non_flight_text
    assert "SANTIAGO-PROVIDENCIA-SANTIAGO-BELLAVISTA" not in str(profile.gateway_airports)
