"""trippy-preference-extractor skill runner."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PreferenceExtractorRunner:
    skill_name = "trippy-preference-extractor"

    def __init__(
        self,
        memory_store: Any | None = None,
        trips_dir: Path | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._trips_dir = trips_dir

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from trippy import config
        from trippy.memory.preference_writer import PreferenceWriter
        from trippy.memory.profile_manager import ProfileManager
        from trippy.memory.store import MemoryStore
        from trippy.services.trip_state import TripStateService

        memory = self._memory_store or MemoryStore(config.MEMORY_PATH)
        trips_dir = self._trips_dir or config.TRIPS_PATH
        state_svc = TripStateService(trips_dir=trips_dir)

        # Load trips to analyse
        trip_ids: list[str] | None = inputs.get("trip_ids")
        min_evidence = inputs.get("min_evidence_trips", 2)

        if trip_ids:
            trips = [t for tid in trip_ids if (t := state_svc.load(tid)) is not None]
        else:
            trips = state_svc.load_all()

        if not trips:
            return {"skip_reason": "No trips found to analyse", "preferences_written": {}}

        writer = PreferenceWriter(memory=memory)
        written = writer.extract_and_write(trips, min_trips=min_evidence)

        # Update family profile from traveler data
        profile_mgr = ProfileManager(memory=memory)
        profile_updates: list[str] = []
        for trip in trips:
            if trip.travelers:
                before = len(profile_mgr.load().travelers)
                profile_mgr.update_from_trip_travelers(trip.travelers)
                after = len(profile_mgr.load().travelers)
                if after > before:
                    profile_updates.append(
                        f"Added {after - before} new traveler(s) from {trip.trip_id}"
                    )

        logger.info(
            "PreferenceExtractor: wrote %d preferences, %d profile updates",
            len(written),
            len(profile_updates),
        )

        return {
            "trips_analysed": len(trips),
            "lived_trips": len([t for t in trips if t.status.value == "lived"]),
            "preferences_written": written,
            "profile_updates": profile_updates,
            "skip_reason": None,
        }
