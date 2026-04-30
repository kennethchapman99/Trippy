"""Connector-safe destination profiles generated from canonical trip geography.

This module must stay destination-agnostic. It converts already-resolved geography
into connector-specific search targets. Flight connectors receive only IATA airport
codes. Lodging, cars, activities, and maps receive human-readable places, regions,
neighborhoods, or airport pickup labels as appropriate.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from trippy.models.trip_planning import TripIntake


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
    """Return connector-ready search targets without destination-specific branching."""

    geography = intake.geography
    destination = (
        geography.primary_destination_name
        if geography and geography.primary_destination_name
        else ", ".join(intake.destination_seeds) or intake.trip_name
    )
    gateway = geography.primary_gateway_iata() if geography else None
    gateway_airports = [gateway] if gateway else []
    country = geography.country or "" if geography else ""
    regions = geography.region_names() if geography else _dedupe_strings(intake.destination_seeds)
    lodging_locations = geography.lodging_locations() if geography else regions or [destination]
    car_locations = geography.car_locations() if geography else regions or [destination]
    activity_locations = geography.activity_locations() if geography else regions or [destination]

    notes = [
        "Destination profile generated from canonical geography; flight providers receive only resolved IATA gateway codes.",
    ]
    if geography and geography.warnings:
        notes.extend(geography.warnings)
    if not gateway_airports:
        notes.append(
            "No destination gateway airport is resolved yet; live flight adapters must fail closed instead of using raw destination text."
        )

    return DestinationProfile(
        key="resolved-geography" if geography else "unresolved-geography",
        title=destination,
        country=country,
        gateway_airports=gateway_airports,
        island_or_region_terms=[],
        flight_notes=notes,
        lodging_search_targets=_lodging_targets(lodging_locations, regions, destination),
        car_search_targets=_car_targets(car_locations),
        activity_search_targets=_activity_targets(intake, destination, activity_locations),
    )


def _lodging_targets(
    locations: list[str],
    regions: list[str],
    destination: str,
) -> list[dict[str, str]]:
    return [
        {
            "name": f"{location} family lodging search",
            "location_area": location,
            "island_or_region": _first_matching_region(location, regions, destination),
            "lodging_type": "family lodging",
            "query": f"{location} family lodging 3 beds parking safe location",
        }
        for location in _dedupe_strings(locations)[:6]
    ]


def _car_targets(locations: list[str]) -> list[dict[str, str]]:
    return [
        {
            "name": f"{location} family SUV or minivan",
            "pickup": _car_pickup_label(location),
            "dropoff": _car_pickup_label(location),
            "vehicle_class": "SUV or minivan",
            "query": f"{location} car rental automatic SUV minivan family luggage",
        }
        for location in _dedupe_strings(locations)[:6]
    ]


def _activity_targets(
    intake: TripIntake,
    destination: str,
    locations: list[str] | None = None,
) -> list[dict[str, str]]:
    seeds = [seed.strip() for seed in (locations or intake.destination_seeds) if seed.strip()]
    seeds = seeds or [destination]
    targets: list[dict[str, str]] = []
    for seed in _dedupe_strings(seeds)[:8]:
        lower = seed.lower()
        if "beach" in lower or "bay" in lower or "coast" in lower:
            query = f"{seed} family beach activity small group"
        elif "valley" in lower:
            query = f"{seed} small group family food culture day trip"
        elif "park" in lower or "mount" in lower or "volcano" in lower:
            query = f"{seed} family guided nature day tour small group"
        else:
            query = f"{seed} family friendly guided activity small group"
        targets.append(
            {
                "name": f"{seed} family-friendly activity search",
                "location": seed,
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
    return _dedupe_targets(targets)[:8]


def _car_pickup_label(location: str) -> str:
    cleaned = location.strip().upper()
    if len(cleaned) == 3 and cleaned.isalpha():
        return f"{cleaned} airport"
    return location


def _first_matching_region(location: str, regions: list[str], fallback: str) -> str:
    location_lower = location.lower()
    for region in regions:
        region_lower = region.lower()
        if region_lower in location_lower or location_lower in region_lower:
            return region
    return regions[0] if regions else fallback


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


def _dedupe_targets(values: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for target in values:
        key = target["query"].casefold()
        if key not in seen:
            seen.add(key)
            result.append(target)
    return result
