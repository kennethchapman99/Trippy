"""Build practical map artifacts from a new-trip planning draft."""

from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path
from urllib.parse import quote_plus

from trippy.models.maps import MapPin, MapPinCategory, MapRoute, MapRouteMode, TripMapArtifact
from trippy.models.shortlists import ResearchShortlistState, ShortlistCategory, ShortlistRowStatus
from trippy.models.trip_planning import TripPlanOption
from trippy.services.shortlist_store import ShortlistStore
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

        shortlists = {state.category: state for state in ShortlistStore().load_all(trip_id)}
        pins = _ordered_pins([*_pins_for_shortlists(shortlists), *_pins_for_option(option)])
        primary_route = _primary_route_for_pins(pins)
        routes = (
            [primary_route, *_routes_for_option(option)]
            if primary_route
            else _routes_for_option(option)
        )
        return TripMapArtifact(
            trip_id=trip_id,
            title=f"{intake.trip_name} Planning Map",
            primary_google_maps_url=primary_route.google_maps_url if primary_route else None,
            pins=pins,
            routes=routes,
            day_groups=_groups(pins, routes),
            notes=[
                "The primary Google Maps route is the single ordered map preview for this trip.",
                "The KML/CSV exports are Google My Maps-compatible and keep every pin numbered in planning order.",
                "Coordinates are not guessed; Google My Maps should resolve exact pins during import.",
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
        csv_path = output_dir / f"{trip_id}-planning-map.csv"
        json_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        geojson_path.write_text(json.dumps(artifact.to_geojson(), indent=2), encoding="utf-8")
        kml_path.write_text(_to_kml(artifact), encoding="utf-8")
        csv_path.write_text(_to_csv(artifact), encoding="utf-8")
        artifact.exports = {
            "json": str(json_path),
            "geojson": str(geojson_path),
            "kml": str(kml_path),
            "csv": str(csv_path),
            "google_maps_route": artifact.primary_google_maps_url or "",
            "google_my_maps": artifact.google_my_maps_url,
        }
        json_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return artifact


def _pins_for_option(option: TripPlanOption) -> list[MapPin]:
    pins: list[MapPin] = []
    for query in _dedupe(_expanded_queries(option)):
        pins.append(
            MapPin(
                pin_id="",
                label=_label(query),
                category=_category(query),
                query=query,
                google_maps_url=_maps_search_url(query),
                notes=_pin_notes(query, option),
            )
        )
    return pins


def _pins_for_shortlists(
    shortlists: dict[ShortlistCategory, ResearchShortlistState],
) -> list[MapPin]:
    pins: list[MapPin] = []
    flights = shortlists.get(ShortlistCategory.FLIGHTS)
    flight = _chosen_option(getattr(flights, "flight_options", []), flights)
    if flight is not None:
        departure = str(getattr(flight, "departure_airport", "")).strip()
        arrival = str(getattr(flight, "arrival_airport", "")).strip()
        if departure:
            pins.append(
                _pin(
                    label=f"Depart {departure}",
                    category=MapPinCategory.AIRPORT,
                    query=_airport_query(departure),
                    source_id=str(getattr(flight, "option_id", "")) or None,
                    notes="Selected or recommended departure airport.",
                    day_index=1,
                )
            )
        if arrival:
            pins.append(
                _pin(
                    label=f"Arrive {arrival}",
                    category=MapPinCategory.AIRPORT,
                    query=_airport_query(arrival),
                    source_id=str(getattr(flight, "option_id", "")) or None,
                    notes="Selected or recommended arrival airport.",
                    day_index=1,
                )
            )

    lodging = shortlists.get(ShortlistCategory.LODGING)
    for option in _map_options(getattr(lodging, "lodging_options", []), lodging, limit=6):
        query = ", ".join(
            part
            for part in [
                str(getattr(option, "name", "")).strip(),
                str(getattr(option, "location_area", "")).strip(),
                str(getattr(option, "island_or_region", "")).strip(),
            ]
            if part
        )
        if not query:
            continue
        pins.append(
            _pin(
                label=f"Stay: {getattr(option, 'name', 'Lodging')}",
                category=MapPinCategory.LODGING,
                query=query,
                source_id=str(getattr(option, "option_id", "")) or None,
                notes=str(getattr(option, "comfort_fit", "") or getattr(option, "price_band", "")),
                day_index=1,
            )
        )

    cars = shortlists.get(ShortlistCategory.CARS)
    car = _chosen_option(getattr(cars, "car_options", []), cars)
    if car is not None:
        for label, query in (
            ("Car pickup", str(getattr(car, "pickup_location", "")).strip()),
            ("Car dropoff", str(getattr(car, "dropoff_location", "")).strip()),
        ):
            if query:
                pins.append(
                    _pin(
                        label=label,
                        category=MapPinCategory.TRANSFER,
                        query=query,
                        source_id=str(getattr(car, "option_id", "")) or None,
                        notes=str(getattr(car, "vehicle_class", "") or "Car rental logistics."),
                        day_index=1 if "pickup" in label.lower() else None,
                    )
                )

    activities = shortlists.get(ShortlistCategory.ACTIVITIES)
    for option in _map_options(getattr(activities, "activity_options", []), activities, limit=12):
        name = str(getattr(option, "activity_name", "")).strip()
        location = str(getattr(option, "island_location", "")).strip()
        query = ", ".join(part for part in [name, location] if part)
        if not query:
            continue
        pins.append(
            _pin(
                label=f"Activity: {name}",
                category=MapPinCategory.ACTIVITY,
                query=query,
                source_id=str(getattr(option, "option_id", "")) or None,
                notes=str(
                    getattr(option, "scheduling_rationale", "")
                    or getattr(option, "review_safety_signal", "")
                    or "Activity candidate."
                ),
                day_index=getattr(option, "scheduled_day", None)
                or getattr(option, "suggested_day", None),
            )
        )
    return pins


def _routes_for_option(option: TripPlanOption) -> list[MapRoute]:
    routes: list[MapRoute] = []
    if len(option.regions) > 1:
        routes.append(
            MapRoute(
                route_id=f"route-{len(routes) + 1}",
                label="Inter-region movement to validate",
                origin_query=option.regions[0],
                destination_query=option.regions[1],
                google_maps_url=_directions_url(
                    option.regions[0], option.regions[1], MapRouteMode.DRIVING
                ),
                mode=MapRouteMode.DRIVING,
                notes="Placeholder for route research; do not treat as a validated drive route.",
            )
        )
    return routes


def _pin(
    *,
    label: str,
    category: MapPinCategory,
    query: str,
    notes: str,
    source_id: str | None = None,
    day_index: int | None = None,
) -> MapPin:
    return MapPin(
        pin_id="",
        label=label,
        category=category,
        query=query,
        google_maps_url=_maps_search_url(query),
        source_id=source_id,
        notes=notes,
        day_index=day_index,
    )


def _chosen_option(options: list[object], state: ResearchShortlistState | None) -> object | None:
    if not options:
        return None
    approved = [
        option
        for option in options
        if getattr(option, "row_status", None) == ShortlistRowStatus.APPROVED
    ]
    if approved:
        return sorted(approved, key=lambda option: int(getattr(option, "rank", 999)))[0]
    recommended_id = getattr(state, "recommended_option_id", None)
    if recommended_id:
        for option in options:
            if getattr(option, "option_id", None) == recommended_id:
                return option
    return sorted(options, key=lambda option: int(getattr(option, "rank", 999)))[0]


def _map_options(
    options: list[object],
    state: ResearchShortlistState | None,
    *,
    limit: int,
) -> list[object]:
    if not options:
        return []
    recommended_id = getattr(state, "recommended_option_id", None)

    def sort_key(option: object) -> tuple[int, int]:
        status = getattr(option, "row_status", None)
        option_id = getattr(option, "option_id", None)
        if status == ShortlistRowStatus.APPROVED:
            priority = 0
        elif recommended_id and option_id == recommended_id:
            priority = 1
        else:
            priority = 2
        return (priority, int(getattr(option, "rank", 999)))

    filtered = [
        option
        for option in options
        if getattr(option, "row_status", None) != ShortlistRowStatus.REJECTED
    ]
    return sorted(filtered, key=sort_key)[:limit]


def _ordered_pins(pins: list[MapPin]) -> list[MapPin]:
    deduped: list[MapPin] = []
    seen: set[str] = set()
    for pin in pins:
        key = " ".join(pin.query.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(pin)

    ordered = sorted(
        enumerate(deduped),
        key=lambda item: (
            item[1].day_index if item[1].day_index is not None else 999,
            _category_order(item[1].category),
            item[0],
        ),
    )
    numbered: list[MapPin] = []
    for index, (_, pin) in enumerate(ordered, start=1):
        numbered.append(
            pin.model_copy(
                update={
                    "pin_id": f"pin-{index:02d}",
                    "label": f"{index:02d} · {_strip_order_prefix(pin.label)}",
                }
            )
        )
    return numbered


def _category_order(category: MapPinCategory) -> int:
    order = {
        MapPinCategory.AIRPORT: 10,
        MapPinCategory.LODGING: 20,
        MapPinCategory.TRANSFER: 30,
        MapPinCategory.ACTIVITY: 40,
        MapPinCategory.FOOD: 50,
        MapPinCategory.LOGISTICS: 60,
        MapPinCategory.OTHER: 70,
    }
    return order.get(category, 99)


def _strip_order_prefix(label: str) -> str:
    parts = label.split(" · ", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return label


def _primary_route_for_pins(pins: list[MapPin]) -> MapRoute | None:
    route_pins = [
        pin
        for pin in pins
        if pin.category
        in {
            MapPinCategory.AIRPORT,
            MapPinCategory.LODGING,
            MapPinCategory.TRANSFER,
            MapPinCategory.ACTIVITY,
            MapPinCategory.FOOD,
            MapPinCategory.LOGISTICS,
        }
    ]
    if len(route_pins) < 2:
        return None
    route_pins = route_pins[:10]
    origin = route_pins[0].query
    destination = route_pins[-1].query
    waypoints = [pin.query for pin in route_pins[1:-1]]
    return MapRoute(
        route_id="route-primary",
        label="Single ordered Google Map",
        origin_query=origin,
        destination_query=destination,
        google_maps_url=_directions_url(origin, destination, MapRouteMode.DRIVING, waypoints),
        mode=MapRouteMode.DRIVING,
        notes=(
            "Opens the current trip points in planning order. "
            "Use the KML/CSV export for a full Google My Maps import with every numbered pin."
        ),
    )


def _expanded_queries(option: TripPlanOption) -> list[str]:
    return list(option.map_seed_queries)


def _category(query: str) -> MapPinCategory:
    lower = query.lower()
    if "airport" in lower:
        return MapPinCategory.AIRPORT
    if "lodging" in lower or "hotel" in lower or "rental" in lower:
        return MapPinCategory.LODGING
    if "restaurant" in lower or "food" in lower:
        return MapPinCategory.FOOD
    if any(
        word in lower
        for word in [
            "whale",
            "hot springs",
            "viewpoint",
            "volcano",
            "tea",
        ]
    ):
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


def _airport_query(code_or_city: str) -> str:
    value = code_or_city.strip()
    if len(value) == 3 and value.isalpha():
        return f"{value.upper()} airport"
    return value


def _directions_url(
    origin: str,
    destination: str,
    mode: MapRouteMode,
    waypoints: list[str] | None = None,
) -> str:
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}"
        f"&destination={quote_plus(destination)}"
        f"&travelmode={mode.value}"
    )
    if waypoints:
        url += f"&waypoints={quote_plus('|'.join(waypoints))}"
    return url


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


def _to_csv(artifact: TripMapArtifact) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Sequence",
            "Label",
            "Category",
            "Day",
            "Search Query",
            "Notes",
            "Google Maps URL",
        ]
    )
    for index, pin in enumerate(artifact.pins, start=1):
        writer.writerow(
            [
                f"{index:02d}",
                _strip_order_prefix(pin.label),
                pin.category.value,
                pin.day_index or "",
                pin.address or pin.query,
                pin.notes or "",
                pin.google_maps_url,
            ]
        )
    return output.getvalue()


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
