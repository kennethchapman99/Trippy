"""Build practical Google Maps artifacts from canonical trip state."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote_plus

from trippy.models.maps import MapPin, MapPinCategory, MapRoute, MapRouteMode, TripMapArtifact
from trippy.models.trip import Segment, SegmentType, Stay, Trip


class MapOutputService:
    """Create linkable map artifacts for a trip."""

    def build_trip_map(self, trip: Trip) -> TripMapArtifact:
        pins = self._pins_for_trip(trip)
        routes = self._routes_for_trip(trip)
        artifact = TripMapArtifact(
            trip_id=trip.trip_id,
            title=f"{trip.name} Map",
            pins=pins,
            routes=routes,
            day_groups=_day_groups(pins, routes),
            notes=[
                "Coordinates are intentionally not guessed. Google Maps links use address/search queries.",
                "GeoJSON uses null geometry until a geocoder or My Maps import resolves coordinates.",
            ],
        )
        return artifact

    def write_artifacts(self, trip: Trip, output_dir: Path) -> TripMapArtifact:
        artifact = self.build_trip_map(trip)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{trip.trip_id}-map.json"
        geojson_path = output_dir / f"{trip.trip_id}-map.geojson"
        kml_path = output_dir / f"{trip.trip_id}-map.kml"

        json_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        geojson_path.write_text(json.dumps(artifact.to_geojson(), indent=2), encoding="utf-8")
        kml_path.write_text(self.to_kml(artifact), encoding="utf-8")

        artifact.exports = {
            "json": str(json_path),
            "geojson": str(geojson_path),
            "kml": str(kml_path),
        }
        json_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return artifact

    def to_kml(self, artifact: TripMapArtifact) -> str:
        placemarks = []
        for pin in artifact.pins:
            description = html.escape(pin.notes or pin.google_maps_url)
            placemarks.append(
                "\n".join(
                    [
                        "    <Placemark>",
                        f"      <name>{html.escape(pin.label)}</name>",
                        f"      <description>{description}</description>",
                        f"      <address>{html.escape(pin.address or pin.query)}</address>",
                        "    </Placemark>",
                    ]
                )
            )
        body = "\n".join(placemarks)
        return "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<kml xmlns="http://www.opengis.net/kml/2.2">',
                "  <Document>",
                f"    <name>{html.escape(artifact.title)}</name>",
                body,
                "  </Document>",
                "</kml>",
                "",
            ]
        )

    def _pins_for_trip(self, trip: Trip) -> list[MapPin]:
        pins: list[MapPin] = []
        seen: set[tuple[MapPinCategory, str]] = set()

        for segment in trip.segments:
            if segment.segment_type == SegmentType.FLIGHT:
                origin_query = _airport_query(segment.origin)
                destination_query = _airport_query(segment.destination)
                for label, query, source_id in (
                    (f"Depart {segment.origin}", origin_query, f"{segment.segment_id}:origin"),
                    (
                        f"Arrive {segment.destination}",
                        destination_query,
                        f"{segment.segment_id}:destination",
                    ),
                ):
                    key = (MapPinCategory.AIRPORT, query)
                    if key in seen:
                        continue
                    seen.add(key)
                    pins.append(
                        MapPin(
                            pin_id=f"pin-{len(pins) + 1}",
                            label=label,
                            category=MapPinCategory.AIRPORT,
                            query=query,
                            google_maps_url=_maps_search_url(query),
                            source_id=source_id,
                            notes="Airport pin generated from flight segment.",
                        )
                    )

        for stay in trip.stays:
            query = _stay_query(stay)
            pins.append(
                MapPin(
                    pin_id=f"pin-{len(pins) + 1}",
                    label=stay.property_name,
                    category=MapPinCategory.LODGING,
                    query=query,
                    address=stay.address,
                    google_maps_url=_maps_search_url(query),
                    source_id=stay.stay_id,
                    day_index=_day_index(trip, stay.check_in),
                    notes=_stay_notes(stay),
                )
            )

        for transfer in trip.transfers:
            if not transfer.pickup_point:
                continue
            query = transfer.pickup_point
            pins.append(
                MapPin(
                    pin_id=f"pin-{len(pins) + 1}",
                    label=transfer.provider or "Transfer pickup",
                    category=MapPinCategory.TRANSFER,
                    query=query,
                    google_maps_url=_maps_search_url(query),
                    source_id=transfer.transfer_id,
                    notes=transfer.notes or transfer.pickup_window,
                )
            )

        return pins

    def _routes_for_trip(self, trip: Trip) -> list[MapRoute]:
        routes: list[MapRoute] = []
        arrival_segments = [
            segment
            for segment in trip.segments
            if segment.segment_type == SegmentType.FLIGHT and segment.destination
        ]
        for stay in trip.stays:
            arrival = _best_arrival_for_stay(stay, arrival_segments)
            if arrival is None:
                continue
            origin = _airport_query(arrival.destination)
            destination = _stay_query(stay)
            routes.append(
                MapRoute(
                    route_id=f"route-{len(routes) + 1}",
                    label=f"{arrival.destination} to {stay.property_name}",
                    origin_query=origin,
                    destination_query=destination,
                    google_maps_url=_directions_url(origin, destination, MapRouteMode.DRIVING),
                    mode=MapRouteMode.DRIVING,
                    day_index=_day_index(trip, stay.check_in),
                    notes="Airport-to-lodging route; verify drive/transit mode for the destination.",
                )
            )

        for previous, current in zip(trip.stays, trip.stays[1:], strict=False):
            origin = _stay_query(previous)
            destination = _stay_query(current)
            routes.append(
                MapRoute(
                    route_id=f"route-{len(routes) + 1}",
                    label=f"{previous.property_name} to {current.property_name}",
                    origin_query=origin,
                    destination_query=destination,
                    google_maps_url=_directions_url(origin, destination, MapRouteMode.DRIVING),
                    mode=MapRouteMode.DRIVING,
                    day_index=_day_index(trip, current.check_in),
                    notes="Stay-to-stay transition; check luggage load and buffers.",
                )
            )
        return routes


def _maps_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def _directions_url(origin: str, destination: str, mode: MapRouteMode) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}"
        f"&destination={quote_plus(destination)}"
        f"&travelmode={mode.value}"
    )


def _airport_query(code_or_city: str) -> str:
    value = code_or_city.strip()
    if len(value) == 3 and value.isalpha():
        return f"{value.upper()} airport"
    return value


def _stay_query(stay: Stay) -> str:
    if stay.address:
        return stay.address
    return ", ".join(part for part in [stay.property_name, stay.city, stay.country] if part)


def _stay_notes(stay: Stay) -> str:
    notes = []
    if stay.check_in:
        notes.append(f"Check-in {stay.check_in}")
    if stay.check_in_time:
        notes.append(f"after {stay.check_in_time}")
    if stay.room_type:
        notes.append(stay.room_type)
    if stay.notes:
        notes.append(stay.notes)
    return "; ".join(notes)


def _day_index(trip: Trip, value: object) -> int | None:
    if trip.start_date is None or value is None or not hasattr(value, "toordinal"):
        return None
    return max(1, int(value.toordinal() - trip.start_date.toordinal()) + 1)


def _best_arrival_for_stay(stay: Stay, segments: list[Segment]) -> Segment | None:
    if not segments:
        return None
    if stay.check_in is None:
        return segments[0]
    candidates = []
    for segment in segments:
        arrive_at = segment.arrive_at
        if arrive_at is not None and arrive_at.date() <= stay.check_in:
            candidates.append(segment)
    if candidates:
        return sorted(
            candidates,
            key=lambda segment: segment.arrive_at.timestamp() if segment.arrive_at else 0.0,
        )[-1]
    return segments[0]


def _day_groups(pins: list[MapPin], routes: list[MapRoute]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for pin in pins:
        if pin.day_index is None:
            continue
        groups.setdefault(f"day-{pin.day_index}", []).append(pin.pin_id)
    for route in routes:
        if route.day_index is None:
            continue
        groups.setdefault(f"day-{route.day_index}", []).append(route.route_id)
    return groups
