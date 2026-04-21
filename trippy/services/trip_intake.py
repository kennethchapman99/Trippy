"""Persistence and helpers for new-trip intake."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from trippy.models.trip_planning import TripIntake, make_trip_slug


class TripIntakeService:
    """Save, load, and query canonical new-trip intake JSON files."""

    def __init__(self, intakes_dir: Path | None = None) -> None:
        from trippy import config

        self._dir = intakes_dir or config.INTAKES_PATH

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.json"

    def create(self, intake: TripIntake, *, overwrite: bool = False) -> TripIntake:
        """Persist a new intake, assigning a unique slug if needed."""
        self._ensure_dir()
        if not intake.trip_id:
            intake.trip_id = make_trip_slug(intake.trip_name)
        if not overwrite:
            intake.trip_id = self._available_trip_id(intake.trip_id)
        return self.save(intake)

    def save(self, intake: TripIntake) -> TripIntake:
        self._ensure_dir()
        intake.updated_at = datetime.utcnow()
        self._path(intake.trip_id).write_text(intake.model_dump_json(indent=2), encoding="utf-8")
        return intake

    def load(self, trip_id: str) -> TripIntake | None:
        path = self._path(trip_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return TripIntake.model_validate(data)

    def require(self, trip_id: str) -> TripIntake:
        intake = self.load(trip_id)
        if intake is None:
            raise FileNotFoundError(f"No trip intake found for {trip_id!r}")
        return intake

    def list_intakes(self) -> list[TripIntake]:
        self._ensure_dir()
        intakes: list[TripIntake] = []
        for path in sorted(self._dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            intakes.append(TripIntake.model_validate(data))
        return intakes

    def path_for(self, trip_id: str) -> Path:
        return self._path(trip_id)

    def _available_trip_id(self, base: str) -> str:
        candidate = base
        suffix = 2
        while self._path(candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
