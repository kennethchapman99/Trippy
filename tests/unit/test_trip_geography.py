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


def test_pre_enriched_trip_json_drives_connector_targets() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Resolved trip",
        destination_seeds=["Santiago, Chile"],
        departure_airports=["YYZ"],
        geography=TripGeography(
            primary_destination_name="Santiago, Chile",
            country="Chile",
            destination_airports=[
                TravelAirportRef(
                    iata_code="SCL",
                    city="Santiago",
                    country="Chile",
                    source="test_fixture",
                )
            ],
            map_locations=[
                TripMapLocation(
                    name="Providencia",
                    city="Santiago",
                    country="Chile",
                    use_for=["lodging", "activity"],
                )
            ],
            lodging_search_locations=["Providencia, Santiago, Chile"],
            activity_search_locations=["Maipo Valley, Chile"],
            car_search_locations=["SCL"],
        ),
    )

    profile = profile_for_intake(intake)

    assert profile.gateway_airports == ["SCL"]
    assert any("Providencia" in str(target) for target in profile.lodging_search_targets)
    assert any("Maipo Valley" in str(target) for target in profile.activity_search_targets)
    assert any("SCL" in str(target) for target in profile.car_search_targets)


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
