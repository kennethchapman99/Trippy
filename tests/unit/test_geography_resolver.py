from trippy.models.trip_planning import TripIntake, TripIntakeMode
from trippy.services.geography_resolver import resolve_trip_geography


def test_resolver_keeps_flight_codes_clean() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Family trip",
        destination_seeds=["Santiago, Providencia, Bellavista, Barrio Italia, Maipo Valley"],
        departure_airports=["YYZ"],
    )
    geography = resolve_trip_geography(intake)
    assert geography.primary_origin_iata() == "YYZ"
    assert geography.primary_destination_iata() == "SCL"
    assert geography.connector_inputs()["flights"]["to"] == "SCL"
    assert "Providencia" in " ".join(geography.map_locations)


def test_unknown_destination_requires_airport_resolution() -> None:
    intake = TripIntake(
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Mystery surf region",
        destination_seeds=["Cool Beach Zone, Old Town, Sunset Valley"],
        departure_airports=["YYZ"],
    )
    geography = resolve_trip_geography(intake)
    assert geography.primary_destination_iata() == ""
    assert geography.connector_inputs()["flights"]["status"] == "airport_required"
