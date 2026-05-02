"""Architecture tests for JSON-first trip geography."""

from __future__ import annotations

from trippy.models.trip_planning import (
    TravelAirportRef,
    TripGeography,
    TripIntake,
    TripIntakeMode,
    TripMapLocation,
)
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


def test_brain_dump_creates_unresolved_places_not_inferred_airports() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Chile family trip",
        destination_seeds=["Santiago, Providencia, Bellavista, Barrio Italia, Maipo Valley"],
        departure_airports=["YYZ"],
    )

    assert intake.geography is not None
    assert intake.geography.destination_airports == []
    assert intake.geography.primary_origin_iata() == "YYZ"

    place_names = [location.name for location in intake.geography.map_locations]
    assert place_names == [
        "Santiago",
        "Providencia",
        "Bellavista",
        "Barrio Italia",
        "Maipo Valley",
    ]

    profile = profile_for_intake(intake)
    assert profile.gateway_airports == []
    assert any("fail closed" in note.lower() for note in profile.flight_notes)
    assert any("Santiago" in str(target) for target in profile.lodging_search_targets)
    assert any("Maipo Valley" in str(target) for target in profile.activity_search_targets)


def test_explicit_iata_destination_code_is_accepted_without_invented_place_facts() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Resolved destination",
        destination_seeds=["SCL"],
        departure_airports=["YYZ"],
    )

    assert intake.geography is not None
    assert [airport.iata_code for airport in intake.geography.destination_airports] == ["SCL"]
    assert intake.geography.destination_airports[0].city is None
    assert intake.geography.destination_airports[0].country is None
    assert intake.geography.map_locations == []

    profile = profile_for_intake(intake)
    assert profile.gateway_airports == ["SCL"]


def test_curated_azores_gateway_hint_restores_live_flight_route() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Azores 2026",
        destination_seeds=["Azores"],
        departure_airports=["YYZ"],
    )

    assert intake.geography is not None
    assert [airport.iata_code for airport in intake.geography.destination_airports] == ["PDL"]
    assert intake.geography.destination_airports[0].source == "curated_gateway_hint"
    assert intake.geography.destination_airports[0].requires_user_confirmation is True

    profile = profile_for_intake(intake)
    assert profile.gateway_airports == ["PDL"]
    assert all("fail closed" not in note.lower() for note in profile.flight_notes)


def test_pre_enriched_trip_json_drives_connector_targets() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Resolved JSON trip",
        destination_seeds=["Somewhere"],
        departure_airports=["YYZ"],
        geography=TripGeography(
            primary_destination_name="Somewhere",
            destination_airports=[
                TravelAirportRef(
                    iata_code="ABC",
                    city="User Supplied City",
                    country="User Supplied Country",
                    source="test_fixture",
                )
            ],
            map_locations=[
                TripMapLocation(
                    name="User Supplied District",
                    city="User Supplied City",
                    use_for=["lodging", "activity"],
                )
            ],
            lodging_search_locations=["User Supplied District"],
            activity_search_locations=["User Supplied Activity Area"],
            car_search_locations=["ABC"],
        ),
    )

    profile = profile_for_intake(intake)

    assert profile.gateway_airports == ["ABC"]
    assert any("User Supplied District" in str(target) for target in profile.lodging_search_targets)
    assert any(
        "User Supplied Activity Area" in str(target)
        for target in profile.activity_search_targets
    )
    assert any("ABC" in str(target) for target in profile.car_search_targets)


def test_raw_concatenated_destination_cannot_become_route_code() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Concatenated destination",
        destination_seeds=[
            "Santiago-Providencia-Santiago-Bellavista-Santiago-Barrio-Italia-Maipo-Valley"
        ],
        departure_airports=["YYZ"],
    )

    assert intake.geography is not None
    assert intake.geography.destination_airports == []
    assert intake.geography.all_airport_codes() == ["YYZ"]
    assert [
        location.name for location in intake.geography.map_locations
    ] == ["Santiago-Providencia-Santiago-Bellavista-Santiago-Barrio-Italia-Maipo-Valley"]

    profile = profile_for_intake(intake)
    assert profile.gateway_airports == []


def test_provider_failure_does_not_create_fake_bookable_flight_rows(
    tmp_path, monkeypatch
) -> None:
    from trippy import config

    monkeypatch.setattr(config, "INTAKES_PATH", tmp_path / "intakes")
    monkeypatch.setattr(config, "PLANS_PATH", tmp_path / "plans")
    monkeypatch.setattr(config, "SHORTLISTS_PATH", tmp_path / "shortlists")

    intake_service = TripIntakeService()
    intake = intake_service.create(
        TripIntake(
            mode=TripIntakeMode.SELECTED_DESTINATION,
            trip_name="Resolved gateway",
            destination_seeds=["SCL"],
            departure_airports=["YYZ"],
        )
    )
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)

    flights = FlightShortlistService(intake_service, planner).build(intake.trip_id)

    assert flights.flight_options == []
    assert flights.recommended_option_id is None
    assert any("failed closed" in warning for warning in flights.warnings)
    assert not any("CAD" in warning for warning in flights.warnings)


def test_user_flight_candidate_without_destination_iata_gets_no_route_links(
    tmp_path, monkeypatch
) -> None:
    from trippy import config

    monkeypatch.setattr(config, "INTAKES_PATH", tmp_path / "intakes")
    monkeypatch.setattr(config, "PLANS_PATH", tmp_path / "plans")
    monkeypatch.setattr(config, "SHORTLISTS_PATH", tmp_path / "shortlists")

    intake_service = TripIntakeService()
    intake = intake_service.create(
        TripIntake(
            mode=TripIntakeMode.SELECTED_DESTINATION,
            trip_name="Chile family trip",
            destination_seeds=[
                "Santiago-Providencia-Santiago-Bellavista-Santiago-Barrio-Italia-Maipo-Valley"
            ],
            departure_airports=["YYZ"],
        )
    )
    planner = TripPlannerService(intake_service)
    planner.draft(intake.trip_id)

    flights = FlightShortlistService(intake_service, planner).add_candidate(
        intake.trip_id,
        link="",
        notes="raw destination text only; no destination airport supplied",
    )
    candidate = flights.flight_options[0]

    assert candidate.arrival_airport == "DESTINATION_AIRPORT_REQUIRED"
    assert candidate.comparison_links == {}
    assert "Santiago-Providencia" not in candidate.deep_link
