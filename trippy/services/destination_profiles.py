"""Destination profile data used by generic planning/research services.

This module must stay destination-agnostic. It converts resolved trip geography
into connector-ready search targets; it should not hardwire country, city, hotel,
activity, or trip-specific recommendations.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from trippy.models.geography import TripGeography
from trippy.models.trip_planning import TripIntake
from trippy.services.geography_resolver import resolve_trip_geography


class DestinationProfile(BaseModel):
    key: str
    title: str
    country: str
    gateway_airports: list[str] = Field(default_factory=list)
    island_or_region_terms: list[str] = Field(default_factory=list)
    flight_notes: list[str] = Field(default_factory=list)
    lodging_search_targets: list[dict[str, str]] = Field(default_factory=list)
    car_search_targets: list[dict[str, str]] = Field(default_factory=list)
    activity_search_targets: list[dict[str, str]] = Field(default_factory=list)


def profile_for_intake(intake: TripIntake) -> DestinationProfile:
    """Build a connector-safe destination profile from user input.

    The profile is generated from the geography resolver so Trippy can support any
    user-requested country, city, region, or trip shape without hardwired destination
    branches in this service.
    """
    return _profile_from_geography(intake, resolve_trip_geography(intake))


def _profile_from_geography(intake: TripIntake, geography: TripGeography) -> DestinationProfile:
    destination = geography.primary_destination_name or ", ".join(intake.destination_seeds) or intake.trip_name
    country = _country_for_geography(geography)
    gateway_airports = [airport.iata_code for airport in geography.destination_airports[:1]]
    regions = geography.planning_regions or geography.map_locations or list(intake.destination_seeds) or [destination]
    lodging_locations = geography.lodging_search_locations or regions or [destination]
    car_locations = geography.car_search_locations or [destination]
    activity_locations = geography.activity_search_locations or regions or [destination]
    notes = [
        "Generated from user trip input and resolved geography; validate gateway airport, seasonal service, and same-ticket routing before booking.",
        *geography.warnings,
        *geography.evidence,
    ]
    return DestinationProfile(
        key=_profile_key(destination),
        title=destination,
        country=country,
        gateway_airports=gateway_airports,
        # Keep empty by design. Filtering by static known region terms can incorrectly
        # remove valid user-requested neighborhoods, side-trip regions, or activity clusters.
        island_or_region_terms=[],
        flight_notes=_dedupe_strings(notes),
        lodging_search_targets=_lodging_targets(lodging_locations, destination),
        car_search_targets=_car_targets(car_locations, destination),
        activity_search_targets=_activity_targets(activity_locations, destination),
    )


def _lodging_targets(locations: list[str], destination: str) -> list[dict[str, str]]:
    return [
        {
            "name": f"{location} family lodging search",
            "location_area": location,
            "island_or_region": location,
            "lodging_type": "family lodging",
            "query": f"{location} family lodging hotel apartment rental 3 beds safe location parking",
        }
        for location in _dedupe_strings(locations or [destination])[:8]
    ]


def _car_targets(locations: list[str], destination: str) -> list[dict[str, str]]:
    return [
        {
            "name": f"{location} family vehicle search",
            "pickup": _car_pickup_label(location),
            "dropoff": _car_pickup_label(location),
            "vehicle_class": "SUV or minivan",
            "query": f"{location} car rental automatic SUV minivan family luggage",
        }
        for location in _dedupe_strings(locations or [destination])[:8]
    ]


def _activity_targets(locations: list[str], destination: str) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for location in _dedupe_strings(locations or [destination])[:8]:
        query = _activity_query(location)
        targets.append(
            {
                "name": f"{location} family-friendly activity search",
                "location": location,
                "query": query,
            }
        )
    if len(targets) < 5:
        targets.extend(
            [
                {
                    "name": f"{destination} private family highlights tour",
                    "location": destination,
                    "query": f"{destination} private family highlights tour",
                },
                {
                    "name": f"{destination} family food or culture experience",
                    "location": destination,
                    "query": f"{destination} family food culture experience",
                },
            ]
        )
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for target in targets:
        key = target["query"].casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(target)
    return deduped[:8]


def _activity_query(location: str) -> str:
    lower = location.lower()
    if any(term in lower for term in ["wine", "valley", "vineyard"]):
        return f"{location} small group family food culture day trip"
    if any(term in lower for term in ["beach", "bay", "island", "coast", "reef", "snorkel"]):
        return f"{location} family snorkeling beach activity small group"
    if any(term in lower for term in ["park", "gorge", "falls", "mount", "volcano", "desert", "trail"]):
        return f"{location} family nature guided activity small group"
    if any(term in lower for term in ["barrio", "district", "neighborhood", "neighbourhood", "quarter"]):
        return f"{location} family culture food walking tour"
    return f"{location} family friendly guided activity small group"


def _car_pickup_label(location: str) -> str:
    cleaned = location.strip().upper()
    if len(cleaned) == 3 and cleaned.isalpha():
        return f"{cleaned} airport"
    return location


def _country_for_geography(geography: TripGeography) -> str:
    if geography.destination_airports:
        return geography.destination_airports[0].country
    for place in geography.places:
        if place.country:
            return place.country
    return ""


def _profile_key(destination: str) -> str:
    key = "-".join(destination.lower().replace(",", " ").split())
    return key or "generic"


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = " ".join(str(value).strip().split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
