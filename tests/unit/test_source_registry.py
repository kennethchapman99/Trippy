"""Tests for deterministic travel source routing."""

from __future__ import annotations

from trippy.models.sources import TravelSourceCategory
from trippy.services.source_registry import TravelSourceRegistry


def test_source_registry_contains_required_platforms() -> None:
    registry = TravelSourceRegistry()
    names = {source.platform_name for source in registry.list_sources()}

    assert {
        "Expedia",
        "Booking.com",
        "Kayak.ca",
        "Google Flights",
        "Airbnb",
        "GetYourGuide",
        "Airbnb Experiences",
        "VRBO",
        "Trivago",
        "Hertz",
        "Flighthub",
        "Travelzoo",
        "Tripadvisor",
    }.issubset(names)


def test_default_routing_matches_booking_priorities() -> None:
    registry = TravelSourceRegistry()

    flights = registry.plan_for(TravelSourceCategory.FLIGHTS)
    cars = registry.plan_for(TravelSourceCategory.CAR_RENTALS)
    tours = registry.plan_for(TravelSourceCategory.TOURS)

    assert [source.platform_name for source in flights.primary] == ["Google Flights"]
    assert flights.primary[0].model_dump()["supports_browser_automation"] is True
    assert "Kayak.ca" in [source.platform_name for source in flights.secondary]
    assert [source.platform_name for source in cars.primary] == ["Booking.com"]
    assert [source.platform_name for source in tours.primary] == ["GetYourGuide"]
