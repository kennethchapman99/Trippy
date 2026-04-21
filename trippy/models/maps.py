"""Map output models for trip planning and concierge use."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MapPinCategory(StrEnum):
    AIRPORT = "airport"
    LODGING = "lodging"
    TRANSFER = "transfer"
    FOOD = "food"
    ACTIVITY = "activity"
    LOGISTICS = "logistics"
    OTHER = "other"


class MapRouteMode(StrEnum):
    DRIVING = "driving"
    WALKING = "walking"
    TRANSIT = "transit"


class MapPin(BaseModel):
    pin_id: str
    label: str
    category: MapPinCategory
    query: str
    google_maps_url: str
    address: str | None = None
    day_index: int | None = None
    source_id: str | None = None
    notes: str | None = None


class MapRoute(BaseModel):
    route_id: str
    label: str
    origin_query: str
    destination_query: str
    google_maps_url: str
    mode: MapRouteMode = MapRouteMode.DRIVING
    day_index: int | None = None
    notes: str | None = None


class TripMapArtifact(BaseModel):
    trip_id: str
    title: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    pins: list[MapPin] = Field(default_factory=list)
    routes: list[MapRoute] = Field(default_factory=list)
    day_groups: dict[str, list[str]] = Field(default_factory=dict)
    exports: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": pin.model_dump(mode="json"),
                }
                for pin in self.pins
            ],
        }
