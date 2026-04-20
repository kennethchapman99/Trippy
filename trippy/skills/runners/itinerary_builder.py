"""trippy-family-itinerary-builder skill runner."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ItineraryBuilderRunner:
    skill_name = "trippy-family-itinerary-builder"

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
        from trippy.services.trip_state import TripStateService

        trip_id: str = inputs["trip_id"]
        destinations: list[str] = inputs.get("destinations", [])
        total_days: int = inputs.get("total_days", 14)

        memory = self._memory_store or MemoryStore(config.MEMORY_PATH)
        trips_dir = self._trips_dir or config.TRIPS_PATH
        state_svc = TripStateService(trips_dir=trips_dir)

        trip = state_svc.load(trip_id)
        if trip is None:
            return {"error": f"Trip {trip_id!r} not found"}

        # Load preferences
        raw = memory.get_value("pref:preferences_object")
        prefs = FamilyTravelPreferences.model_validate(raw) if raw else FamilyTravelPreferences()

        # Use trip destinations if not provided
        if not destinations and trip.destination_summary:
            destinations = [d.strip() for d in trip.destination_summary.split(",")]

        start = trip.start_date or date.today()
        itinerary = self._build_itinerary(destinations, total_days, start, prefs)
        city_summary = self._city_summary(destinations, total_days, start)
        warnings = self._check_warnings(itinerary, prefs)

        # Update trip notes
        trip.notes = (trip.notes or "") + "\n\n" + _itinerary_to_text(itinerary)
        state_svc.save(trip)

        return {
            "trip_id": trip_id,
            "total_days": total_days,
            "itinerary": itinerary,
            "city_summary": city_summary,
            "warnings": warnings,
        }

    def _build_itinerary(
        self,
        destinations: list[str],
        total_days: int,
        start: date,
        prefs: FamilyTravelPreferences,
    ) -> list[dict[str, Any]]:
        if not destinations:
            return []

        # Distribute days across destinations
        # Reserve day 1 (arrival) and last day (departure)
        usable_days = total_days - 2
        days_per_dest = max(2, usable_days // max(len(destinations), 1))

        itinerary: list[dict[str, Any]] = []
        current_day = 1
        current_date = start

        # Day 1: arrival
        itinerary.append({
            "day": current_day,
            "date": str(current_date),
            "city": destinations[0] if destinations else "Arrival city",
            "type": "arrival",
            "notes": "Arrive, check in, easy first evening. Jet lag day — no packed schedule.",
        })
        current_day += 1
        current_date += timedelta(days=1)

        # Main itinerary days
        for i, dest in enumerate(destinations):
            nights = days_per_dest
            if i == 0:
                nights -= 1  # day 1 already consumed as arrival
            nights = max(prefs.stay.min_nights_per_destination, nights)

            for day_in_dest in range(nights):
                is_transit_day = (day_in_dest == nights - 1 and i < len(destinations) - 1)
                notes = f"{dest}: "
                if day_in_dest == 0 and i > 0:
                    notes += f"Arrive from {destinations[i-1]}. "
                if is_transit_day:
                    notes += f"Check out, transfer to {destinations[i+1]}."
                else:
                    notes += f"Explore {dest}."

                itinerary.append({
                    "day": current_day,
                    "date": str(current_date),
                    "city": dest,
                    "type": "transit" if is_transit_day else "regular",
                    "notes": notes,
                })
                current_day += 1
                current_date += timedelta(days=1)

                if current_day >= total_days:
                    break
            if current_day >= total_days:
                break

        # Last day: departure
        itinerary.append({
            "day": total_days,
            "date": str(start + timedelta(days=total_days - 1)),
            "city": destinations[-1] if destinations else "Departure",
            "type": "departure",
            "notes": "Pack, check out, depart. No activities — buffer for airport.",
        })

        return itinerary

    def _city_summary(
        self,
        destinations: list[str],
        total_days: int,
        start: date,
    ) -> dict[str, str]:
        summary: dict[str, str] = {}
        usable = total_days - 2
        per_dest = max(2, usable // max(len(destinations), 1))
        current = start + timedelta(days=1)
        for dest in destinations:
            end = current + timedelta(days=per_dest - 1)
            summary[dest] = f"{per_dest} nights ({current} – {end})"
            current = end + timedelta(days=1)
        return summary

    def _check_warnings(
        self,
        itinerary: list[dict[str, Any]],
        prefs: FamilyTravelPreferences,
    ) -> list[str]:
        warnings: list[str] = []
        for item in itinerary:
            if item.get("type") == "transit":
                warnings.append(
                    f"Day {item['day']}: city transit day — confirm transfer booking"
                )
        return warnings


def _itinerary_to_text(itinerary: list[dict[str, Any]]) -> str:
    lines = ["### Draft Itinerary"]
    for item in itinerary:
        lines.append(f"**Day {item['day']} ({item['date']}) — {item['city']}**")
        lines.append(item["notes"])
    return "\n".join(lines)
