"""Tests for Google Maps output artifacts."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from trippy.models.maps import MapPinCategory
from trippy.models.trip import Segment, SegmentType, Stay, StayType, Trip, TripStatus
from trippy.services.map_outputs import MapOutputService


def test_map_artifact_builds_pins_routes_and_links() -> None:
    trip = _map_trip()
    artifact = MapOutputService().build_trip_map(trip)

    assert artifact.trip_id == "lisbon-2027"
    assert any(pin.category == MapPinCategory.LODGING for pin in artifact.pins)
    assert any("google.com/maps/search" in pin.google_maps_url for pin in artifact.pins)
    assert artifact.routes
    assert "google.com/maps/dir" in artifact.routes[0].google_maps_url
    assert artifact.to_geojson()["features"][0]["geometry"] is None


def test_map_artifact_writes_json_geojson_and_kml(tmp_path: Path) -> None:
    trip = _map_trip()
    artifact = MapOutputService().write_artifacts(trip, tmp_path)

    json_path = Path(artifact.exports["json"])
    geojson_path = Path(artifact.exports["geojson"])
    kml_path = Path(artifact.exports["kml"])

    assert json_path.exists()
    assert geojson_path.exists()
    assert kml_path.exists()
    assert json.loads(geojson_path.read_text(encoding="utf-8"))["type"] == "FeatureCollection"
    assert "<address>Rua Central 1, Lisbon, Portugal</address>" in kml_path.read_text(
        encoding="utf-8"
    )


def _map_trip() -> Trip:
    start = date(2027, 3, 10)
    depart = datetime(2027, 3, 10, 9, 30)
    return Trip(
        trip_id="lisbon-2027",
        name="Lisbon 2027",
        status=TripStatus.PLANNED,
        destination_summary="Lisbon, Portugal",
        start_date=start,
        end_date=start + timedelta(days=7),
        segments=[
            Segment(
                segment_id="seg-1",
                segment_type=SegmentType.FLIGHT,
                origin="YYZ",
                destination="LIS",
                depart_at=depart,
                arrive_at=depart + timedelta(hours=7),
            )
        ],
        stays=[
            Stay(
                stay_id="stay-1",
                stay_type=StayType.HOTEL,
                property_name="Central Lisbon Hotel",
                city="Lisbon",
                country="Portugal",
                address="Rua Central 1, Lisbon, Portugal",
                check_in=start,
                check_out=start + timedelta(days=4),
                room_type="king plus two twins",
            )
        ],
    )
