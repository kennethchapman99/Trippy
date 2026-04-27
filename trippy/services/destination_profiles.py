"""Destination profile data used by generic planning/research services."""

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
    if "azores" in text.lower():
        return _AZORES
    destination = ", ".join(intake.destination_seeds) or intake.trip_name
    return DestinationProfile(
        key="generic",
        title=destination,
        country="",
        gateway_airports=[],
        island_or_region_terms=list(intake.destination_seeds),
        flight_notes=[
            "Generic profile: validate gateway airport, seasonal service, and same-ticket routing."
        ],
        lodging_search_targets=[
            {
                "name": f"{destination} family lodging search",
                "location_area": destination,
                "island_or_region": destination,
                "lodging_type": "family lodging",
                "query": f"{destination} family lodging 3 beds parking",
            }
        ],
        car_search_targets=[
            {
                "name": f"{destination} airport family SUV or minivan",
                "pickup": destination,
                "dropoff": destination,
                "vehicle_class": "SUV or minivan",
                "query": f"{destination} car rental SUV minivan family luggage",
            }
        ],
        activity_search_targets=_generic_activity_search_targets(intake, destination),
    )


def _generic_activity_search_targets(
    intake: TripIntake,
    destination: str,
) -> list[dict[str, str]]:
    seeds = [seed.strip() for seed in intake.destination_seeds if seed.strip()] or [destination]
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
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for target in targets:
        key = target["query"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(target)
    return deduped[:8]


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
