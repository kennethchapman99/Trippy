"""Connector-safe destination profile data for planning and live-source research."""

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
    text = " ".join([intake.trip_name, *intake.destination_seeds, intake.freeform_notes or ""])
    lower_text = text.lower()
    if "azores" in lower_text:
        return _AZORES
    if _looks_like_chile(lower_text):
        return _chile_profile(intake)
    if _looks_like_grand_cayman(lower_text):
        return _GRAND_CAYMAN
    return _generic_profile(intake)


def _generic_profile(intake: TripIntake) -> DestinationProfile:
    """Build a profile from canonical geography without inventing airport codes."""
    geography = intake.geography
    destination = (
        geography.primary_destination_name
        if geography and geography.primary_destination_name
        else ", ".join(intake.destination_seeds) or intake.trip_name
    )
    gateway = geography.primary_gateway_iata() if geography else None
    gateway_airports = [gateway] if gateway else []
    regions = (
        geography.region_names()
        if geography and geography.region_names()
        else _dedupe_strings([*intake.destination_seeds, destination])
    )
    lodging_locations = (
        geography.lodging_locations()
        if geography and geography.lodging_locations()
        else regions or [destination]
    )
    car_locations = (
        geography.car_locations()
        if geography and geography.car_locations()
        else regions or [destination]
    )
    activity_locations = (
        geography.activity_locations()
        if geography and geography.activity_locations()
        else regions or [destination]
    )
    notes = ["Generic profile: validate gateway airport, seasonal service, and same-ticket routing."]
    if geography and geography.warnings:
        notes.extend(geography.warnings)
    if not gateway_airports:
        notes.append(
            "No destination airport resolved; live flight providers must fail closed until a valid IATA destination is selected."
        )
    return DestinationProfile(
        key="generic",
        title=destination,
        country=(geography.country or "") if geography else "",
        gateway_airports=gateway_airports,
        island_or_region_terms=[],
        flight_notes=notes,
        lodging_search_targets=[
            {
                "name": f"{location} family lodging search",
                "location_area": location,
                "island_or_region": _first_matching_region(location, regions, destination),
                "lodging_type": "family lodging",
                "query": f"{location} family lodging 3 beds parking",
            }
            for location in lodging_locations[:6]
        ],
        car_search_targets=[
            {
                "name": f"{location} family SUV or minivan",
                "pickup": _car_pickup_label(location),
                "dropoff": _car_pickup_label(location),
                "vehicle_class": "SUV or minivan",
                "query": f"{location} car rental SUV minivan family luggage",
            }
            for location in car_locations[:6]
        ],
        activity_search_targets=_generic_activity_search_targets(
            intake,
            destination,
            activity_locations,
        ),
    )


def _looks_like_chile(text: str) -> bool:
    return any(
        term in text
        for term in [
            "chile",
            "santiago",
            "providencia",
            "bellavista",
            "barrio italia",
            "barrio-italia",
            "maipo",
            "atacama",
            "patagonia",
            "torres del paine",
        ]
    )


def _looks_like_grand_cayman(text: str) -> bool:
    return any(
        term in text
        for term in [
            "cayman",
            "seven mile beach",
            "west bay",
            "stingray city",
            "rum point",
            "grand cayman",
        ]
    )


def _chile_profile(intake: TripIntake) -> DestinationProfile:
    geography = intake.geography
    gateway = geography.primary_gateway_iata() if geography else "SCL"
    regions = geography.region_names() if geography else ["Santiago"]
    lodging_locations = (
        geography.lodging_locations()
        if geography
        else ["Providencia, Santiago, Chile", "Barrio Italia, Santiago, Chile", "Santiago, Chile"]
    )
    car_locations = (
        geography.car_locations()
        if geography
        else ["SCL", "Santiago, Chile", "Maipo Valley, Chile"]
    )
    activity_locations = (
        geography.activity_locations()
        if geography
        else ["Santiago", "Providencia", "Bellavista", "Barrio Italia", "Maipo Valley"]
    )
    return DestinationProfile(
        key="chile",
        title="Santiago, Chile",
        country="Chile",
        gateway_airports=[gateway or "SCL"],
        island_or_region_terms=[],
        flight_notes=[
            "SCL is the canonical international gateway for Santiago/central Chile trips.",
            "Santiago neighborhoods, Barrio Italia, Bellavista, Providencia, and Maipo Valley are map/activity/lodging areas only; never pass them as flight route codes.",
            "If Atacama or Patagonia are selected, use CJC/PUQ as in-trip domestic airports only after the international gateway is set.",
            *(geography.warnings if geography else []),
            *(f"Planning region: {region}" for region in regions[:4]),
        ],
        lodging_search_targets=[
            {
                "name": f"{location} family lodging search",
                "location_area": location,
                "island_or_region": _region_for_chile_location(location),
                "lodging_type": "family hotel or apartment",
                "query": f"{location} family hotel apartment 3 beds safe neighborhood parking",
            }
            for location in lodging_locations[:6]
        ],
        car_search_targets=[
            {
                "name": f"{location} family SUV or minivan",
                "pickup": _car_pickup_label(location),
                "dropoff": _car_pickup_label(location),
                "vehicle_class": "SUV or minivan",
                "query": f"{location} car rental automatic SUV minivan family luggage",
            }
            for location in car_locations[:6]
        ],
        activity_search_targets=[
            {
                "name": f"{location} family-friendly activity search",
                "location": location,
                "query": _chile_activity_query(location),
            }
            for location in activity_locations[:8]
        ],
    )


def _region_for_chile_location(location: str) -> str:
    lower = location.lower()
    if "atacama" in lower:
        return "Atacama"
    if "patagonia" in lower or "natales" in lower or "torres" in lower:
        return "Patagonia"
    if "maipo" in lower:
        return "Maipo Valley"
    return "Santiago"


def _car_pickup_label(location: str) -> str:
    if location.upper() in {"SCL", "CJC", "PUQ", "PDL", "PIX", "HOR", "TER", "GCM"}:
        return f"{location.upper()} airport"
    return location


def _chile_activity_query(location: str) -> str:
    lower = location.lower()
    if "maipo" in lower:
        return "Maipo Valley small group family wine food day trip from Santiago"
    if "bellavista" in lower:
        return "Bellavista Santiago family culture food walking tour"
    if "barrio italia" in lower:
        return "Barrio Italia Santiago food design walking tour family"
    if "providencia" in lower:
        return "Providencia Santiago family-friendly neighborhood restaurants parks"
    if "atacama" in lower:
        return "San Pedro de Atacama family small group desert tour"
    if "patagonia" in lower or "torres" in lower:
        return "Torres del Paine family day tour small group"
    return f"{location} Santiago Chile family friendly guided activity small group"


def _generic_activity_search_targets(
    intake: TripIntake,
    destination: str,
    locations: list[str] | None = None,
) -> list[dict[str, str]]:
    seeds = [seed.strip() for seed in (locations or intake.destination_seeds) if seed.strip()]
    seeds = seeds or [destination]
    targets: list[dict[str, str]] = []
    for seed in seeds[:5]:
        lower = seed.lower()
        if "stingray" in lower:
            name = f"{seed} family stingray and sandbar tour"
            query = f"{seed} small group family stingray sandbar tour"
        elif "rum point" in lower:
            name = f"{seed} family boat and beach day"
            query = f"{seed} small group family boat beach tour"
        elif any(term in lower for term in ["beach", "bay", "island", "coast"]):
            name = f"{seed} family snorkeling or beach activity"
            query = f"{seed} family snorkeling beach activity small group"
        else:
            name = f"{seed} family-friendly guided activity"
            query = f"{seed} family friendly guided activity small group"
        targets.append({"name": name, "location": seed, "query": query})
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


def _first_matching_region(location: str, regions: list[str], fallback: str) -> str:
    location_lower = location.lower()
    for region in regions:
        if region.lower() in location_lower or location_lower in region.lower():
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


_AZORES = DestinationProfile(
    key="azores",
    title="Azores, Portugal",
    country="Portugal",
    gateway_airports=["PDL", "PIX", "HOR", "TER"],
    island_or_region_terms=["Sao Miguel", "Pico", "Faial", "Terceira"],
    flight_notes=[
        "PDL is the natural first gateway for the current Azores golden path.",
        "Inter-island movement needs schedule/weather buffers before booking.",
        "Flight numbers and fare precision must be live-verified on source sites.",
    ],
    lodging_search_targets=[
        {
            "name": "Octant Ponta Delgada",
            "location_area": "Ponta Delgada waterfront",
            "island_or_region": "Sao Miguel",
            "lodging_type": "boutique hotel",
            "query": "Octant Ponta Delgada family room 3 beds parking",
        },
        {
            "name": "Senhora da Rosa Tradition & Nature Hotel",
            "location_area": "Ponta Delgada / Sao Roque area",
            "island_or_region": "Sao Miguel",
            "lodging_type": "small hotel",
            "query": "Senhora da Rosa Tradition Nature Hotel family room parking",
        },
        {
            "name": "Terra Nostra Garden Hotel",
            "location_area": "Furnas",
            "island_or_region": "Sao Miguel",
            "lodging_type": "hotel",
            "query": "Terra Nostra Garden Hotel family room parking",
        },
        {
            "name": "Pico or Faial 3-bedroom private rental",
            "location_area": "Madalena or Horta practical base",
            "island_or_region": "Pico or Faial",
            "lodging_type": "private rental",
            "query": "Pico Faial 3 bedroom vacation rental family parking",
        },
    ],
    car_search_targets=[
        {
            "name": "PDL airport automatic SUV",
            "pickup": "Ponta Delgada airport",
            "dropoff": "Ponta Delgada airport",
            "vehicle_class": "automatic SUV",
            "query": "Ponta Delgada airport car rental automatic SUV family luggage",
        },
        {
            "name": "PDL airport 7-seat van",
            "pickup": "Ponta Delgada airport",
            "dropoff": "Ponta Delgada airport",
            "vehicle_class": "7-seat van",
            "query": "Ponta Delgada airport 7 seat van rental",
        },
        {
            "name": "Pico/Faial island compact SUV",
            "pickup": "Pico or Horta airport/ferry terminal",
            "dropoff": "same-island airport/ferry terminal",
            "vehicle_class": "compact SUV",
            "query": "Pico Faial car rental compact SUV family luggage",
        },
    ],
    activity_search_targets=[
        {
            "name": "Sao Miguel whale watching small-group search",
            "location": "Ponta Delgada / Sao Miguel",
            "query": "Sao Miguel whale watching small group family",
        },
        {
            "name": "Furnas hot springs and geothermal food day",
            "location": "Furnas / Sao Miguel",
            "query": "Furnas hot springs geothermal food tour small group",
        },
        {
            "name": "Sete Cidades and Lagoa do Fogo private day tour",
            "location": "Sao Miguel",
            "query": "Sete Cidades Lagoa do Fogo private day tour family",
        },
        {
            "name": "Pico wine landscape or Faial volcano outing",
            "location": "Pico or Faial",
            "query": "Pico wine landscape Faial Capelinhos volcano small group tour",
        },
    ],
)


_GRAND_CAYMAN = DestinationProfile(
    key="grand-cayman",
    title="Grand Cayman, Cayman Islands",
    country="Cayman Islands",
    gateway_airports=["GCM"],
    island_or_region_terms=["Seven Mile Beach", "West Bay", "Rum Point", "George Town"],
    flight_notes=[
        "GCM is the main gateway for Grand Cayman trips.",
        "Toronto nonstop service can be seasonal or day-specific; compare nonstop against one-stop same-ticket options.",
        "For a 7-day family trip, avoid routings that add avoidable connection or baggage friction.",
    ],
    lodging_search_targets=[
        {
            "name": "Seven Mile Beach family condo or resort",
            "location_area": "Seven Mile Beach",
            "island_or_region": "Grand Cayman",
            "lodging_type": "family condo or resort",
            "query": "Seven Mile Beach Grand Cayman family condo 3 beds parking",
        },
        {
            "name": "West Bay family rental",
            "location_area": "West Bay",
            "island_or_region": "Grand Cayman",
            "lodging_type": "family rental",
            "query": "West Bay Grand Cayman family rental 3 bedrooms parking",
        },
        {
            "name": "Rum Point quiet family rental",
            "location_area": "Rum Point",
            "island_or_region": "Grand Cayman",
            "lodging_type": "quiet family rental",
            "query": "Rum Point Grand Cayman family rental 3 bedrooms",
        },
    ],
    car_search_targets=[
        {
            "name": "GCM airport family SUV or minivan",
            "pickup": "GCM airport",
            "dropoff": "GCM airport",
            "vehicle_class": "SUV or minivan",
            "query": "GCM airport Grand Cayman SUV minivan rental family luggage",
        },
        {
            "name": "Seven Mile Beach car rental",
            "pickup": "Seven Mile Beach or GCM airport",
            "dropoff": "Seven Mile Beach or GCM airport",
            "vehicle_class": "comfortable SUV",
            "query": "Seven Mile Beach Grand Cayman car rental SUV family",
        },
    ],
    activity_search_targets=[
        {
            "name": "Stingray City small-group family tour",
            "location": "Grand Cayman",
            "query": "Grand Cayman Stingray City small group family tour",
        },
        {
            "name": "Seven Mile Beach snorkeling family outing",
            "location": "Seven Mile Beach",
            "query": "Seven Mile Beach Grand Cayman family snorkeling tour",
        },
        {
            "name": "West Bay turtle and reef day",
            "location": "West Bay",
            "query": "West Bay Grand Cayman family turtle reef tour",
        },
        {
            "name": "Rum Point private boat or beach day",
            "location": "Rum Point",
            "query": "Rum Point Grand Cayman private boat family beach day",
        },
    ],
)
