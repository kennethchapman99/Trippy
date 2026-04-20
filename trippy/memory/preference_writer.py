"""Write durable family travel preferences to memory, backed by evidence.

Design principles:
- Only write preferences that are evidenced by ≥2 trips (configurable)
- Confidence scales with number of corroborating trips
- Distinguish durable preference from one-off exception
- Never write trip-specific facts to memory
"""

from __future__ import annotations

import logging
from collections import Counter

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
    ) -> dict[str, str]:
        """Analyse trips and write any new or updated durable preferences.

        Returns a dict of {preference_key: reason_string} for logging/display.
        """
        if not trips:
            return {}

        lived_trips = [t for t in trips if t.status.value == "lived"]
        if not lived_trips:
            logger.info("No 'lived' trips to extract preferences from")
            return {}

        trip_ids = [t.trip_id for t in lived_trips]
        written: dict[str, str] = {}

        # -------------------------------------------------------
        # Departure time analysis
        # -------------------------------------------------------
        early_departures = self._find_early_departures(lived_trips)
        if early_departures["avoided_count"] >= min_trips:
            conf = _calc_confidence(early_departures["avoided_count"], min_trips)
            self._memory.set(
                key="pref:departure_time_earliest_acceptable",
                value={
                    "time": "07:00",
                    "evidence": f"avoided early departures in {early_departures['avoided_count']} trips",
                },
                category="preference",
                confidence=conf,
                source=f"extracted from {len(lived_trips)} trips",
            )
            written["departure_time"] = (
                f"Earliest acceptable 07:00 (avoided early in "
                f"{early_departures['avoided_count']} trips, conf={conf:.0%})"
            )

        # -------------------------------------------------------
        # Connection time analysis
        # -------------------------------------------------------
        connections = self._analyse_connections(lived_trips)
        if connections["sample_count"] >= min_trips:
            min_seen = connections.get("min_minutes_seen")
            if min_seen and min_seen > 60:
                conf = _calc_confidence(connections["sample_count"], min_trips)
                self._memory.set(
                    key="pref:min_connection_international",
                    value={
                        "minutes": max(110, min_seen),
                        "evidence": f"min observed: {min_seen} min across {connections['sample_count']} connections",
                    },
                    category="preference",
                    confidence=conf,
                    source=f"extracted from trips: {', '.join(trip_ids)}",
                )
                written["min_connection"] = (
                    f"Min international connection {max(110, min_seen)} min"
                    f" (conf={conf:.0%})"
                )

        # -------------------------------------------------------
        # Stay preferences from lived trips
        # -------------------------------------------------------
        stay_prefs = self._analyse_stays(lived_trips)
        if stay_prefs["sample_count"] >= min_trips:
            conf = _calc_confidence(stay_prefs["sample_count"], min_trips)
            if stay_prefs.get("avg_nights_per_dest"):
                self._memory.set(
                    key="pref:min_nights_per_destination",
                    value={
                        "nights": max(2, int(stay_prefs["avg_nights_per_dest"])),
                        "evidence": f"avg {stay_prefs['avg_nights_per_dest']:.1f} nights/dest",
                    },
                    category="preference",
                    confidence=conf,
                    source=f"extracted from trips: {', '.join(trip_ids)}",
                )
                written["nights_per_dest"] = (
                    f"Min {max(2, int(stay_prefs['avg_nights_per_dest']))} nights/destination"
                )

        # -------------------------------------------------------
        # Source trip metadata in memory
        # -------------------------------------------------------
        existing_prefs = FamilyTravelPreferences(source_trips=trip_ids)
        existing_prefs.confidence = min(0.9, len(lived_trips) * 0.15)
        self._memory.set(
            key="pref:preference_source_trips",
            value={"trip_ids": trip_ids, "count": len(lived_trips)},
            category="preference",
            confidence=existing_prefs.confidence,
            source="preference_writer",
        )

        logger.info(
            "PreferenceWriter wrote %d preferences from %d lived trips",
            len(written), len(lived_trips)
        )
        return written

    # ------------------------------------------------------------------

    def _find_early_departures(self, trips: list[Trip]) -> dict[str, int]:
        avoided = 0
        for trip in trips:
            for seg in trip.segments:
                if seg.depart_at:
                    hour = seg.depart_at.hour
                    minute = seg.depart_at.minute
                    if hour >= 8:
                        avoided += 1  # acceptable departure; family chose not-early
        return {"avoided_count": avoided}

    def _analyse_connections(self, trips: list[Trip]) -> dict[str, object]:
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

    def _analyse_stays(self, trips: list[Trip]) -> dict[str, object]:
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
    ) -> None:
        """Write an agent-discovered planning pattern to memory."""
        self._memory.set(
            key=f"hint:{key}",
            value=hint,
            category="skill_hint",
            confidence=confidence,
            source=source,
        )
