"""trippy-flight-friction-audit skill runner."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FrictionAuditRunner:
    skill_name = "trippy-flight-friction-audit"

    def __init__(
        self,
        trips_dir: Path | None = None,
        memory_store: Any | None = None,
    ) -> None:
        self._trips_dir = trips_dir
        self._memory_store = memory_store

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from trippy import config
        from trippy.memory.store import MemoryStore
        from trippy.models.preferences import FamilyTravelPreferences
        from trippy.services.friction_detector import FrictionDetector
        from trippy.services.trip_state import TripStateService

        trip_id: str = inputs["trip_id"]
        use_prefs: bool = inputs.get("check_preferences", True)

        memory = self._memory_store or MemoryStore(config.MEMORY_PATH)
        trips_dir = self._trips_dir or config.TRIPS_PATH
        state_svc = TripStateService(trips_dir=trips_dir)

        trip = state_svc.load(trip_id)
        if trip is None:
            return {"error": f"Trip {trip_id!r} not found"}

        # Load preferences if requested
        prefs: FamilyTravelPreferences | None = None
        if use_prefs:
            raw = memory.get_value("pref:preferences_object")
            if raw:
                try:
                    prefs = FamilyTravelPreferences.model_validate(raw)
                except Exception:
                    prefs = FamilyTravelPreferences()
            else:
                prefs = FamilyTravelPreferences()

        detector = FrictionDetector(preferences=prefs)
        risks = detector.audit(trip)

        # Persist risks back to trip state
        trip.risk_flags = [r for r in trip.risk_flags if r.resolved]  # keep resolved
        trip.risk_flags.extend(risks)
        state_svc.save(trip)

        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in risks:
            by_severity[r.severity.value] = by_severity.get(r.severity.value, 0) + 1

        return {
            "trip_id": trip_id,
            "total_risks": len(risks),
            "critical": by_severity["critical"],
            "high": by_severity["high"],
            "medium": by_severity["medium"],
            "low": by_severity["low"],
            "risks": [
                {
                    "risk_id": r.risk_id,
                    "severity": r.severity.value,
                    "category": r.category,
                    "description": r.description,
                    "affected": r.affected_ids,
                    "fix": r.recommended_fix,
                }
                for r in risks
            ],
        }
