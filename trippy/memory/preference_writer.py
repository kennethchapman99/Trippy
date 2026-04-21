"""Write durable family travel preferences to memory, backed by evidence.

Design principles:
- Only write preferences that are evidenced by ≥2 trips (configurable)
- Confidence scales with number of corroborating trips
- Distinguish durable preference from one-off exception
- Never write trip-specific facts to memory
"""

from __future__ import annotations

import logging
from typing import Any

from trippy.memory.store import MemoryStore
from trippy.models.preferences import FamilyTravelPreferences
from trippy.models.trip import Trip

logger = logging.getLogger(__name__)

_MIN_TRIPS_FOR_PREFERENCE = 2
_CONFIDENCE_PER_TRIP = 0.15  # Each additional trip adds this to confidence


def _calc_confidence(evidence_count: int, min_trips: int = _MIN_TRIPS_FOR_PREFERENCE) -> float:
    if evidence_count < min_trips:
        return 0.0
    base = 0.5
    extra = (evidence_count - min_trips) * _CONFIDENCE_PER_TRIP
    return min(0.95, base + extra)


class PreferenceWriter:
    """Derives and persists durable preferences from a set of canonical trips."""

    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory

    def extract_and_write(
        self,
        trips: list[Trip],
        min_trips: int = _MIN_TRIPS_FOR_PREFERENCE,
        *,
        approved_by_human: bool = False,
    ) -> dict[str, str]:
        """Analyse trips and write approved durable preferences.

        Returns a dict of {preference_key: reason_string} for logging/display.
        """
        if not approved_by_human:
            raise PermissionError(
                "Preference writes require review approval. Use extract_candidates() "
                "and the learning proposal flow instead."
            )
        candidates = self.extract_candidates(trips, min_trips=min_trips)
        written: dict[str, str] = {}
        for name, candidate in candidates.items():
            self._memory.set(
                key=str(candidate["key"]),
                value=candidate["value"],
                category=str(candidate["category"]),
                confidence=float(candidate["confidence"]),
                source=str(candidate["source"]),
                notes=str(candidate["notes"]) if candidate.get("notes") else None,
            )
            written[name] = str(candidate["reason"])

        logger.info("PreferenceWriter wrote %d preferences", len(written))
        return written

    def extract_candidates(
        self,
        trips: list[Trip],
        min_trips: int = _MIN_TRIPS_FOR_PREFERENCE,
    ) -> dict[str, dict[str, Any]]:
        """Analyse trips and return memory-write candidates without mutating memory."""
        if not trips:
            return {}

        lived_trips = [t for t in trips if t.status.value == "lived"]
        if not lived_trips:
            logger.info("No 'lived' trips to extract preferences from")
            return {}

        trip_ids = [t.trip_id for t in lived_trips]
        candidates: dict[str, dict[str, Any]] = {}

        # -------------------------------------------------------
        # Departure time analysis
        # -------------------------------------------------------
        early_departures = self._find_early_departures(lived_trips)
        if early_departures["avoided_count"] >= min_trips:
            conf = _calc_confidence(early_departures["avoided_count"], min_trips)
            reason = (
                f"Earliest acceptable 07:00 (avoided early in "
                f"{early_departures['avoided_count']} trips, conf={conf:.0%})"
            )
            candidates["departure_time"] = {
                "key": "pref:departure_time_earliest_acceptable",
                "value": {
                    "time": "07:00",
                    "evidence": f"avoided early departures in {early_departures['avoided_count']} trips",
                },
                "category": "preference",
                "confidence": conf,
                "source": f"extracted from {len(lived_trips)} trips",
                "notes": reason,
                "reason": reason,
            }

        # -------------------------------------------------------
        # Connection time analysis
        # -------------------------------------------------------
        connections = self._analyse_connections(lived_trips)
        if connections["sample_count"] >= min_trips:
            min_seen = connections.get("min_minutes_seen")
            if min_seen and min_seen > 60:
                conf = _calc_confidence(connections["sample_count"], min_trips)
                reason = f"Min international connection {max(110, min_seen)} min (conf={conf:.0%})"
                candidates["min_connection"] = {
                    "key": "pref:min_connection_international",
                    "value": {
                        "minutes": max(110, min_seen),
                        "evidence": f"min observed: {min_seen} min across {connections['sample_count']} connections",
                    },
                    "category": "preference",
                    "confidence": conf,
                    "source": f"extracted from trips: {', '.join(trip_ids)}",
                    "notes": reason,
                    "reason": reason,
                }

        # -------------------------------------------------------
        # Stay preferences from lived trips
        # -------------------------------------------------------
        stay_prefs = self._analyse_stays(lived_trips)
        if stay_prefs["sample_count"] >= min_trips:
            conf = _calc_confidence(stay_prefs["sample_count"], min_trips)
            if stay_prefs.get("avg_nights_per_dest"):
                nights = max(2, int(stay_prefs["avg_nights_per_dest"]))
                reason = f"Min {nights} nights/destination"
                candidates["nights_per_dest"] = {
                    "key": "pref:min_nights_per_destination",
                    "value": {
                        "nights": max(2, int(stay_prefs["avg_nights_per_dest"])),
                        "evidence": f"avg {stay_prefs['avg_nights_per_dest']:.1f} nights/dest",
                    },
                    "category": "preference",
                    "confidence": conf,
                    "source": f"extracted from trips: {', '.join(trip_ids)}",
                    "notes": reason,
                    "reason": reason,
                }

        # -------------------------------------------------------
        # Source trip metadata in memory
        # -------------------------------------------------------
        existing_prefs = FamilyTravelPreferences(source_trips=trip_ids)
        existing_prefs.confidence = min(0.9, len(lived_trips) * 0.15)
        candidates["preference_source_trips"] = {
            "key": "pref:preference_source_trips",
            "value": {"trip_ids": trip_ids, "count": len(lived_trips)},
            "category": "preference",
            "confidence": existing_prefs.confidence,
            "source": "preference_writer",
            "notes": "Tracks the lived trips used as preference evidence.",
            "reason": f"Preference evidence covers {len(lived_trips)} lived trip(s)",
        }

        logger.info(
            "PreferenceWriter found %d preference candidates from %d lived trips",
            len(candidates),
            len(lived_trips),
        )
        return candidates

    # ------------------------------------------------------------------

    def _find_early_departures(self, trips: list[Trip]) -> dict[str, int]:
        avoided = 0
        for trip in trips:
            for seg in trip.segments:
                if seg.depart_at:
                    hour = seg.depart_at.hour
                    if hour >= 8:
                        avoided += 1  # acceptable departure; family chose not-early
        return {"avoided_count": avoided}

    def _analyse_connections(self, trips: list[Trip]) -> dict[str, Any]:
        connection_minutes: list[int] = []
        for trip in trips:
            segs = sorted(
                [s for s in trip.segments if s.arrive_at and s.depart_at],
                key=lambda s: s.depart_at,  # type: ignore[arg-type, return-value]
            )
            for i in range(len(segs) - 1):
                arrive = segs[i].arrive_at
                depart = segs[i + 1].depart_at
                if arrive and depart and depart > arrive:
                    gap = int((depart - arrive).total_seconds() / 60)
                    if 30 < gap < 300:  # plausible connection
                        connection_minutes.append(gap)

        if not connection_minutes:
            return {"sample_count": 0}

        return {
            "sample_count": len(connection_minutes),
            "min_minutes_seen": min(connection_minutes),
            "avg_minutes": sum(connection_minutes) / len(connection_minutes),
        }

    def _analyse_stays(self, trips: list[Trip]) -> dict[str, Any]:
        nights_per_dest: list[float] = []
        for trip in trips:
            for stay in trip.stays:
                n = stay.nights
                if n and n > 0:
                    nights_per_dest.append(float(n))

        if not nights_per_dest:
            return {"sample_count": 0}

        avg = sum(nights_per_dest) / len(nights_per_dest)
        return {
            "sample_count": len(nights_per_dest),
            "avg_nights_per_dest": avg,
        }

    # ------------------------------------------------------------------
    # Skill-hint writing
    # ------------------------------------------------------------------

    def write_skill_hint(
        self,
        key: str,
        hint: str,
        source: str,
        confidence: float = 0.7,
        *,
        approved_by_human: bool = False,
    ) -> None:
        """Write an agent-discovered planning pattern to memory."""
        if not approved_by_human:
            raise PermissionError(
                "Skill-hint writes require review approval. Use the learning proposal flow instead."
            )
        self._memory.set(
            key=f"hint:{key}",
            value=hint,
            category="skill_hint",
            confidence=confidence,
            source=source,
        )
