"""Build practical map artifacts from a new-trip planning draft."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote_plus

from trippy.models.maps import MapPin, MapPinCategory, MapRoute, MapRouteMode, TripMapArtifact
from trippy.models.trip_planning import TripPlanOption
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class TripMapBuilder:
    """Generate map pins/routes from intake and the selected planning option."""

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)

    def build(self, trip_id: str, *, option_id: str | None = None) -> TripMapArtifact:
        intake = self._intakes.require(trip_id)
        draft = self._planner.require_draft(trip_id)
        option = draft.get_option(option_id)
        if option is None:
            raise ValueError(f"No selected or recommended plan option for trip {trip_id!r}")

        pins = _pins_for_option(option)
        routes = _routes_for_option(option)
        return TripMapArtifact(
            trip_id=trip_id,
            title=f"{intake.trip_name} Planning Map",
            pins=pins,
            routes=routes,
            day_groups=_groups(pins, routes),
            notes=[
                "Map artifacts use Google Maps search/directions links and import-friendly KML/GeoJSON.",
                "Coordinates are not guessed; geocoding/My Maps import should resolve exact pins later.",
                "Use these maps to compare geography, drive load, food clusters, and activity grouping before booking.",
            ],
        )

    def write_artifacts(
        self,
        trip_id: str,
        output_dir: Path,
        *,
        option_id: str | None = None,
    ) -> TripMapArtifact:
        artifact = self.build(trip_id, option_id=option_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{trip_id}-planning-map.json"
        geojson_path = output_dir / f"{trip_id}-planning-map.geojson"
        kml_path = output_dir / f"{trip_id}-planning-map.kml"
        json_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        geojson_path.write_text(json.dumps(artifact.to_geojson(), indent=2), encoding="utf-8")
        kml_path.write_text(_to_kml(artifact), encoding="utf-8")
        artifact.exports = {
            "json": str(json_path),
            "geojson": str(geojson_path),
            "kml": str(kml_path),
        }
        json_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return artifact


def _pins_for_option(option: TripPlanOption) -> list[MapPin]:
    pins: list[MapPin] = []
    for query in _dedupe(_expanded_queries(option)):
        pins.append(
            MapPin(
                pin_id=f"pin-{len(pins) + 1}",
                label=_label(query),
                category=_category(query),
                query=query,
                google_maps_url=_maps_search_url(query),
                notes=_pin_notes(query, option),
            )
        )
    return pins


def _routes_for_option(option: TripPlanOption) -> list[MapRoute]:
    routes: list[MapRoute] = []
    if any("Sao Miguel" in region for region in option.regions):
        routes.append(
            MapRoute(
                route_id="route-1",
                label="PDL airport to Ponta Delgada/Sao Miguel base",
                origin_query="Ponta Delgada airport",
                destination_query="Ponta Delgada family lodging",
                google_maps_url=_directions_url(
                    "Ponta Delgada airport",
                    "Ponta Delgada family lodging",
                    MapRouteMode.DRIVING,
                ),
                mode=MapRouteMode.DRIVING,
                notes="First practical route to validate with luggage and arrival timing.",
            )
        )
        routes.append(
            MapRoute(
                route_id="route-2",
                label="Sao Miguel west/east day drive grouping",
                origin_query="Ponta Delgada",
                destination_query="Sete Cidades and Furnas Azores",
                google_maps_url=_directions_url(
                    "Ponta Delgada",
                    "Sete Cidades and Furnas Azores",
                    MapRouteMode.DRIVING,
                ),
                mode=MapRouteMode.DRIVING,
                notes="Use to sanity-check whether a day is overpacked.",
            )
        )
    if len(option.regions) > 1:
        routes.append(
            MapRoute(
                route_id=f"route-{len(routes) + 1}",
                label="Inter-island movement to validate",
                origin_query=option.regions[0],
                destination_query=option.regions[1],
                google_maps_url=_directions_url(option.regions[0], option.regions[1], MapRouteMode.DRIVING),
                mode=MapRouteMode.DRIVING,
                notes="Placeholder for flight/ferry research; do not treat as a literal drive route.",
            )
        )
    return routes


def _expanded_queries(option: TripPlanOption) -> list[str]:
    queries = list(option.map_seed_queries)
    if any("Sao Miguel" in region for region in option.regions):
        queries.extend(
            [
                "Ponta Delgada airport",
                "Ponta Delgada family lodging",
                "Ponta Delgada restaurants",
                "Furnas Azores hot springs",
                "Sete Cidades viewpoint",
                "Lagoa do Fogo",
                "Sao Miguel whale watching",
                "Gorreana tea plantation",
            ]
        )
    if any("Pico" in region or "Faial" in region for region in option.regions):
        queries.extend(
            [
                "Madalena Pico family lodging",
                "Pico Island wine landscape",
                "Horta Faial marina restaurants",
                "Capelinhos Volcano",
            ]
        )
    if any("Terceira" in region for region in option.regions):
        queries.extend(
            [
                "Angra do Heroismo family lodging",
                "Angra do Heroismo restaurants",
                "Algar do Carvao",
            ]
        )
    return queries


def _category(query: str) -> MapPinCategory:
    lower = query.lower()
    if "airport" in lower:
        return MapPinCategory.AIRPORT
    if "lodging" in lower or "hotel" in lower or "rental" in lower:
        return MapPinCategory.LODGING
    if "restaurant" in lower or "food" in lower:
        return MapPinCategory.FOOD
    if any(word in lower for word in ["whale", "hot springs", "viewpoint", "volcano", "tea", "lagoa", "furnas", "sete"]):
        return MapPinCategory.ACTIVITY
    return MapPinCategory.LOGISTICS


def _pin_notes(query: str, option: TripPlanOption) -> str:
    category = _category(query)
    if category == MapPinCategory.LODGING:
        return option.lodging_strategy
    if category == MapPinCategory.FOOD:
        return option.food_fit
    if category == MapPinCategory.ACTIVITY:
        return "Validate reviews, safety, crowd timing, and whether it fits a balanced day."
    if category == MapPinCategory.AIRPORT:
        return "Validate arrival/departure timing, car pickup, and airport-to-lodging friction."
    return "Planning seed; verify exact location before booking."


def _groups(pins: list[MapPin], routes: list[MapRoute]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "airports": [pin.pin_id for pin in pins if pin.category == MapPinCategory.AIRPORT],
        "lodging": [pin.pin_id for pin in pins if pin.category == MapPinCategory.LODGING],
        "food": [pin.pin_id for pin in pins if pin.category == MapPinCategory.FOOD],
        "activities": [pin.pin_id for pin in pins if pin.category == MapPinCategory.ACTIVITY],
        "routes": [route.route_id for route in routes],
    }
    return {key: value for key, value in groups.items() if value}


def _maps_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def _directions_url(origin: str, destination: str, mode: MapRouteMode) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}"
        f"&destination={quote_plus(destination)}"
        f"&travelmode={mode.value}"
    )


def _to_kml(artifact: TripMapArtifact) -> str:
    placemarks = []
    for pin in artifact.pins:
        placemarks.append(
            "\n".join(
                [
                    "    <Placemark>",
                    f"      <name>{html.escape(pin.label)}</name>",
                    f"      <description>{html.escape(pin.notes or pin.google_maps_url)}</description>",
                    f"      <address>{html.escape(pin.query)}</address>",
                    "    </Placemark>",
                ]
            )
        )
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            "  <Document>",
            f"    <name>{html.escape(artifact.title)}</name>",
            *placemarks,
            "  </Document>",
            "</kml>",
            "",
        ]
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _label(query: str) -> str:
    return query.strip().title()
