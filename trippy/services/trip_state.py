"""Canonical trip state management — JSON persistence + query helpers.

The canonical trip state is stored as JSON files at:
    ~/.trippy/trips/{trip_id}.json

This service provides CRUD operations over those files.
SQLite (via db/models.py) is used for query, linking, and index operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from trippy.models.trip import Trip, TripStatus

logger = logging.getLogger(__name__)


class TripStateService:
    """Load, save, and query canonical trip JSON files."""

    def __init__(self, trips_dir: Path | None = None) -> None:
        from trippy import config

        self._dir = trips_dir or config.TRIPS_PATH

    def _path(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.json"

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, trip: Trip) -> Path:
        """Persist a canonical trip to JSON. Creates or overwrites."""
        self._ensure_dir()
        trip.updated_at = datetime.utcnow()
        path = self._path(trip.trip_id)
        path.write_text(trip.model_dump_json(indent=2), encoding="utf-8")
        logger.debug("Saved trip %r to %s", trip.trip_id, path)
        return path

    def load(self, trip_id: str) -> Trip | None:
        """Load a canonical trip from JSON. Returns None if not found."""
        path = self._path(trip_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Trip.model_validate(data)
        except Exception as exc:
            logger.error("Failed to load trip %r: %s", trip_id, exc)
            return None

    def load_all(self) -> list[Trip]:
        """Load all canonical trips from the trips directory."""
        self._ensure_dir()
        trips: list[Trip] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                trips.append(Trip.model_validate(data))
            except Exception as exc:
                logger.warning("Failed to load %s: %s", path, exc)
        return trips

    def delete(self, trip_id: str) -> bool:
        path = self._path(trip_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, trip_id: str) -> bool:
        return self._path(trip_id).exists()

    def load_or_create(self, trip_id: str, name: str | None = None) -> Trip:
        """Load existing trip or create a minimal new one."""
        existing = self.load(trip_id)
        if existing is not None:
            return existing
        trip = Trip(trip_id=trip_id, name=name or trip_id)
        self.save(trip)
        return trip

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def find_by_status(self, status: TripStatus) -> list[Trip]:
        return [t for t in self.load_all() if t.status == status]

    def find_active(self) -> list[Trip]:
        """Return planned and booked trips."""
        return [t for t in self.load_all() if t.status in (TripStatus.PLANNED, TripStatus.BOOKED)]

    def find_lived(self) -> list[Trip]:
        return [t for t in self.load_all() if t.status == TripStatus.LIVED]

    def summary_context(self, max_trips: int = 5) -> str:
        """Return a compact multi-trip summary for agent context injection."""
        trips = sorted(
            self.find_active(),
            key=lambda t: t.start_date or datetime.max.date(),  # type: ignore[arg-type]
        )
        if not trips:
            return "No active trips found."

        lines = ["## Active Trips"]
        for t in trips[:max_trips]:
            lines.append(f"- {t.summary()}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Merge helpers (for importing from SQLAlchemy DB)
    # ------------------------------------------------------------------

    def from_db_trip(self, db_trip: Any) -> Trip:
        """Convert a SQLAlchemy Trip ORM object to a canonical Pydantic Trip."""
        from trippy.models.trip import (
            Segment,
            SegmentType,
            Stay,
            StayType,
            Traveler,
            TripStatus,
        )

        travelers = [
            Traveler(
                name=tv.name,
                passport_country=tv.passport_country,
                passport_expiry=tv.passport_expiry,
                date_of_birth=tv.date_of_birth,
            )
            for tv in getattr(db_trip, "travelers", [])
        ]

        segments = [
            Segment(
                segment_id=f"leg-{i + 1}",
                segment_type=SegmentType(leg.leg_type.value),
                carrier=leg.carrier,
                flight_number=leg.flight_number,
                origin=leg.origin,
                destination=leg.destination,
                depart_at=leg.depart_at,
                arrive_at=leg.arrive_at,
                cabin_class=leg.cabin_class,
                cost_cad=leg.cost_cad,
                confirmation_code=leg.confirmation_code,
                notes=leg.notes,
            )
            for i, leg in enumerate(getattr(db_trip, "legs", []))
        ]

        stays = [
            Stay(
                stay_id=f"stay-{i + 1}",
                stay_type=StayType(stay.stay_type.value),
                property_name=stay.property_name,
                city=stay.city or "",
                country=stay.country or "",
                check_in=stay.check_in,
                check_out=stay.check_out,
                cost_cad=stay.cost_cad,
                confirmation_code=stay.confirmation_code,
                notes=stay.notes,
            )
            for i, stay in enumerate(getattr(db_trip, "stays", []))
        ]

        return Trip(
            trip_id=db_trip.name.lower().replace(" ", "-"),
            name=db_trip.name,
            status=TripStatus(db_trip.status.value),
            destination_summary=db_trip.destination_summary or "",
            start_date=db_trip.start_date,
            end_date=db_trip.end_date,
            travelers=travelers,
            segments=segments,
            stays=stays,
            notes=db_trip.notes,
            created_at=db_trip.created_at,
            updated_at=db_trip.updated_at,
        )
