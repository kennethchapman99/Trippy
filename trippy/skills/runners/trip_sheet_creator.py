"""trippy-trip-sheet-creator skill runner."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Trippy standard sheet tab names
_SHEET_TABS = ["Overview", "Flights", "Hotels", "Transfers", "Checklist", "Budget"]

# Standard checklist items (pre-populated)
_BASE_CHECKLIST = [
    ("booking", "Book outbound flights"),
    ("booking", "Book return flights"),
    ("booking", "Book all hotels/stays"),
    ("booking", "Book airport transfers"),
    ("document", "Check all passport expiry dates (6mo beyond trip end)"),
    ("document", "Check visa requirements for all travelers"),
    ("logistics", "Arrange pet/house care"),
    ("logistics", "Notify bank/credit cards of travel"),
    ("logistics", "Get travel insurance"),
    ("logistics", "Purchase foreign currency or confirm card fees"),
    ("packing", "Check airline baggage allowance"),
]


class TripSheetCreatorRunner:
    skill_name = "trippy-trip-sheet-creator"

    def __init__(
        self,
        trips_dir: Path | None = None,
        auth_manager: Any | None = None,
        memory_store: Any | None = None,
    ) -> None:
        self._trips_dir = trips_dir
        self._auth_manager = auth_manager
        self._memory_store = memory_store

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from trippy import config
        from trippy.memory.profile_manager import ProfileManager
        from trippy.memory.store import MemoryStore
        from trippy.models.trip import ChecklistItem, Trip, TripStatus
        from trippy.services.sheet_sync import SheetSyncService
        from trippy.services.trip_state import TripStateService

        trip_idea: str = inputs.get("trip_idea", "")
        folder_id: str | None = inputs.get("folder_id")
        template_id: str | None = inputs.get("template_sheet_id") or config.SHEET_TEMPLATE_ID

        memory = self._memory_store or MemoryStore(config.MEMORY_PATH)
        profile_mgr = ProfileManager(memory=memory)
        profile = profile_mgr.load()
        trips_dir = self._trips_dir or config.TRIPS_PATH
        state_svc = TripStateService(trips_dir=trips_dir)

        # Parse the trip idea
        trip_name, destinations, start_date, end_date = _parse_trip_idea(trip_idea)
        trip_id_slug = trip_name.lower().replace(" ", "-")

        # Build canonical trip record
        from trippy.models.trip import Traveler

        travelers = [
            Traveler(
                name=t.name,
                passport_country=t.passport_country,
                passport_expiry=t.passport_expiry,
                is_minor=t.is_minor,
            )
            for t in profile.travelers
        ]

        # Build checklist
        checklist = [
            ChecklistItem(
                item_id=f"chk-{i + 1:02d}",
                category=cat,
                title=title,
            )
            for i, (cat, title) in enumerate(_BASE_CHECKLIST)
        ]

        trip = Trip(
            trip_id=trip_id_slug,
            name=trip_name,
            status=TripStatus.PLANNED,
            destination_summary=", ".join(destinations),
            start_date=start_date,
            end_date=end_date,
            travelers=travelers,
            checklist=checklist,
        )

        # Save canonical trip record
        state_svc.save(trip)

        # Create Google Sheet
        sheet_result: dict[str, Any] = {}
        flags: list[str] = []

        auth = self._auth_manager
        if auth is None:
            try:
                from trippy.ingest.google_auth import GoogleAuthManager

                auth = GoogleAuthManager()
            except Exception:
                logger.warning("Google auth unavailable — skipping sheet creation")

        if auth is not None:
            sync = SheetSyncService(auth_manager=auth)
            if template_id:
                sheet_result = sync.create_from_template(
                    trip=trip, template_id=template_id, folder_id=folder_id
                )
            else:
                sheet_result = sync.create_new_sheet(trip=trip, folder_id=folder_id)

            if sheet_result.get("spreadsheet_id"):
                trip.sync.google_sheet_id = sheet_result["spreadsheet_id"]
                trip.sync.google_sheet_url = sheet_result.get("url", "")
                state_svc.save(trip)

        # Destination-specific flags
        dest_lower = " ".join(d.lower() for d in destinations)
        if "japan" in dest_lower:
            flags.append("Add JR Pass to checklist (if rail travel planned)")
            flags.append("Check Japan ETA requirement for Canadian passports")
        if "us" in dest_lower or "united states" in dest_lower:
            flags.append("Check eTA/ESTA requirement")
        if "europe" in dest_lower:
            flags.append("Check ETIAS requirement (effective 2025)")

        return {
            "trip_id": trip.trip_id,
            "trip_name": trip.name,
            "sheet_id": sheet_result.get("spreadsheet_id", ""),
            "sheet_url": sheet_result.get("url", ""),
            "suggestion_summary": _suggest_structure(destinations),
            "flags": flags,
        }


def _parse_trip_idea(
    idea: str,
) -> tuple[str, list[str], date | None, date | None]:
    """Very simple trip idea parser — LLM-assisted version is in agent.py."""
    import re
    from datetime import datetime

    destinations = []
    start_date = None
    end_date = None

    # Extract year
    year_match = re.search(r"\b(202[5-9]|203\d)\b", idea)
    year = int(year_match.group()) if year_match else datetime.utcnow().year + 1

    # Extract month
    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month_match = re.search(r"\b(" + "|".join(months.keys()) + r")\b", idea.lower())
    month = months.get(month_match.group(), 3) if month_match else 3

    # Extract duration
    dur_match = re.search(r"(\d+)\s*(?:day|night|week)", idea.lower())
    duration_days = (
        int(dur_match.group(1)) * 7
        if "week" in (idea.lower())
        else (int(dur_match.group(1)) if dur_match else 14)
    )
    if "week" in idea.lower() and dur_match:
        duration_days = int(dur_match.group(1)) * 7

    start_date = date(year, month, 10)
    from datetime import timedelta

    end_date = start_date + timedelta(days=duration_days)

    # Extract destination(s)
    clean = re.sub(r"\b(trip|travel|next|in|for|days|nights|weeks?|months?)\b", " ", idea.lower())
    clean = re.sub(
        r"\b(20\d\d|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)\b",
        " ",
        clean,
    )
    clean = re.sub(r"\d+", " ", clean)
    words = [w.strip().capitalize() for w in clean.split() if len(w.strip()) > 2]
    destinations = words[:3] if words else ["Unknown"]

    name = f"{destinations[0]} {year}"
    return name, destinations, start_date, end_date


def _suggest_structure(destinations: list[str]) -> str:
    if not destinations:
        return "No destinations specified"
    if len(destinations) == 1:
        return f"{destinations[0]}: suggest 7-10 nights, explore different neighbourhoods"
    days_per = 14 // len(destinations)
    return " → ".join(f"{d} {days_per}n" for d in destinations)
