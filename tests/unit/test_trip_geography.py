"""Regression tests for canonical trip geography and connector-safe locations."""

from __future__ import annotations

from trippy.models.trip_planning import TripIntake, TripIntakeMode
from trippy.services.destination_profiles import profile_for_intake


def test_chile_geography_separates_flight_airport_from_neighborhoods() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Chile family trip",
        destination_seeds=[
            "Santiago-Providencia-Santiago-Bellavista-Santiago-Barrio-Italia-Maipo-Valley"
        ],
        departure_airports=["YYZ"],
        duration_days=8,
    )

    assert intake.geography is not None
    assert intake.geography.primary_origin_iata() == "YYZ"
    assert intake.geography.primary_gateway_iata() == "SCL"
    assert [airport.iata_code for airport in intake.geography.destination_airports] == ["SCL"]
    assert "SANTIAGO-PROVIDENCIA" not in intake.geography.all_airport_codes()

    map_queries = intake.geography.map_seed_queries()
    assert any("Providencia" in query for query in map_queries)
    assert any("Bellavista" in query for query in map_queries)
    assert any("Barrio Italia" in query for query in map_queries)
    assert any("Maipo Valley" in query for query in map_queries)


def test_chile_destination_profile_feeds_each_connector_the_right_location_type() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Chile",
        destination_seeds=["Santiago, Providencia, Bellavista, Barrio Italia, Maipo Valley"],
        departure_airports=["YYZ"],
    )

    profile = profile_for_intake(intake)

    assert profile.key == "chile"
    assert profile.gateway_airports == ["SCL"]
    assert all(len(code) == 3 and code.isupper() for code in profile.gateway_airports)
    assert any("SCL is the canonical" in note for note in profile.flight_notes)

    lodging_text = " ".join(str(target) for target in profile.lodging_search_targets)
    car_text = " ".join(str(target) for target in profile.car_search_targets)
    activity_text = " ".join(str(target) for target in profile.activity_search_targets)

    assert "Providencia" in lodging_text
    assert "Barrio Italia" in lodging_text
    assert "SCL" in car_text
    assert "Maipo Valley" in activity_text
    assert "SANTIAGO-PROVIDENCIA-SANTIAGO-BELLAVISTA" not in car_text
