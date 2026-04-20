"""Bidirectional sync between canonical trip state and Google Sheets.

Direction 1: trip state → sheet (write current state to sheet)
Direction 2: sheet → trip state (import human edits back to state)

The sheet is the HUMAN-FACING VIEW. Canonical state is the source of truth.
Conflicts are logged and surfaced, not silently overwritten.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from trippy.models.trip import Trip

logger = logging.getLogger(__name__)

# Column layouts for each tab
_OVERVIEW_COLS = ["Field", "Value"]
_FLIGHTS_COLS = [
    "Segment ID",
    "Type",
    "Carrier",
    "Flight #",
    "From",
    "To",
    "Departs",
    "Arrives",
    "Cabin",
    "Cost (CAD)",
    "Confirmation",
    "Notes",
]
_HOTELS_COLS = [
    "Stay ID",
    "Type",
    "Property",
    "City",
    "Country",
    "Check-in",
    "Check-out",
    "Nights",
    "Cost (CAD)",
    "Confirmation",
    "Notes",
]
_CHECKLIST_COLS = ["ID", "Category", "Task", "Due", "Assigned", "Done"]
_BUDGET_COLS = ["Category", "Budgeted", "Booked", "Actual", "Variance"]
_TRANSFERS_COLS = [
    "Transfer ID",
    "Provider",
    "Driver Contact",
    "Pickup Point",
    "Pickup Window",
    "Vehicle Details",
    "Notes",
]


class SheetSyncService:
    """Manages the Trippy trip sheet ↔ canonical state sync."""

    def __init__(self, auth_manager: Any | None = None) -> None:
        self._auth = auth_manager

    def _sheets_service(self) -> Any:
        if self._auth is None:
            from trippy.ingest.google_auth import GoogleAuthManager

            self._auth = GoogleAuthManager()
        return self._auth.build_service("sheets", "v4")

    def _drive_service(self) -> Any:
        if self._auth is None:
            from trippy.ingest.google_auth import GoogleAuthManager

            self._auth = GoogleAuthManager()
        return self._auth.build_service("drive", "v3")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_new_sheet(self, trip: Trip, folder_id: str | None = None) -> dict[str, Any]:
        """Create a new Google Sheet for the trip and populate it."""
        service = self._sheets_service()
        title = f"Trippy — {trip.name}"

        try:
            resp = (
                service.spreadsheets()
                .create(
                    body={
                        "properties": {"title": title},
                        "sheets": [
                            {"properties": {"title": tab}}
                            for tab in [
                                "Overview",
                                "Flights",
                                "Hotels",
                                "Transfers",
                                "Checklist",
                                "Budget",
                            ]
                        ],
                    }
                )
                .execute()
            )
            sid = resp["spreadsheetId"]
            url = resp.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sid}")

            if folder_id:
                drive = self._drive_service()
                meta = drive.files().get(fileId=sid, fields="parents").execute()
                prev = ",".join(meta.get("parents", []))
                drive.files().update(
                    fileId=sid, addParents=folder_id, removeParents=prev, fields="id,parents"
                ).execute()

            self.push_trip_to_sheet(trip, sid)
            return {"spreadsheet_id": sid, "url": url}
        except Exception as exc:
            logger.error("create_new_sheet failed: %s", exc)
            return {"error": str(exc)}

    def create_from_template(
        self,
        trip: Trip,
        template_id: str,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy a template sheet and populate it with trip data."""
        drive = self._drive_service()
        title = f"Trippy — {trip.name}"
        try:
            copy = drive.files().copy(fileId=template_id, body={"name": title}).execute()
            new_id = copy["id"]
            url = f"https://docs.google.com/spreadsheets/d/{new_id}"

            if folder_id:
                meta = drive.files().get(fileId=new_id, fields="parents").execute()
                prev = ",".join(meta.get("parents", []))
                drive.files().update(
                    fileId=new_id, addParents=folder_id, removeParents=prev, fields="id,parents"
                ).execute()

            self.push_trip_to_sheet(trip, new_id)
            return {"spreadsheet_id": new_id, "url": url}
        except Exception as exc:
            logger.error("create_from_template failed: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Push: trip state → sheet
    # ------------------------------------------------------------------

    def push_trip_to_sheet(self, trip: Trip, sheet_id: str) -> None:
        """Write canonical trip state to the Google Sheet."""
        service = self._sheets_service()

        updates = []
        updates.extend(self._build_overview_update(trip))
        updates.extend(self._build_flights_update(trip))
        updates.extend(self._build_hotels_update(trip))
        updates.extend(self._build_transfers_update(trip))
        updates.extend(self._build_checklist_update(trip))
        updates.extend(self._build_budget_update(trip))

        if not updates:
            return

        try:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": updates},
            ).execute()
            logger.info("Pushed trip %r to sheet %s", trip.trip_id, sheet_id)
        except Exception as exc:
            logger.error("push_trip_to_sheet failed for %s: %s", sheet_id, exc)

    def _build_overview_update(self, trip: Trip) -> list[dict[str, Any]]:
        rows: list[list[Any]] = [
            _OVERVIEW_COLS,
            ["Trip Name", trip.name],
            ["Status", trip.status.value],
            ["Destinations", trip.destination_summary],
            ["Start Date", str(trip.start_date or "")],
            ["End Date", str(trip.end_date or "")],
            ["Travelers", ", ".join(t.name for t in trip.travelers)],
            ["Num Travelers", len(trip.travelers)],
            ["Last Updated", str(datetime.utcnow().date())],
            ["Trip ID", trip.trip_id],
        ]
        if trip.sync.google_sheet_url:
            rows.append(["Sheet URL", trip.sync.google_sheet_url])
        return [{"range": "Overview!A1", "values": rows}]

    def _build_flights_update(self, trip: Trip) -> list[dict[str, Any]]:
        rows: list[list[Any]] = [_FLIGHTS_COLS]
        for seg in trip.segments:
            rows.append(
                [
                    seg.segment_id,
                    seg.segment_type.value,
                    seg.carrier or "",
                    seg.flight_number or "",
                    seg.origin,
                    seg.destination,
                    str(seg.depart_at or ""),
                    str(seg.arrive_at or ""),
                    seg.cabin_class or "",
                    seg.cost_cad or "",
                    seg.confirmation_code or "UNCONFIRMED",
                    seg.notes or "",
                ]
            )
        if len(rows) > 1:
            return [{"range": "Flights!A1", "values": rows}]
        return []

    def _build_hotels_update(self, trip: Trip) -> list[dict[str, Any]]:
        rows: list[list[Any]] = [_HOTELS_COLS]
        for stay in trip.stays:
            rows.append(
                [
                    stay.stay_id,
                    stay.stay_type.value,
                    stay.property_name,
                    stay.city,
                    stay.country,
                    str(stay.check_in or ""),
                    str(stay.check_out or ""),
                    stay.nights or "",
                    stay.cost_cad or "",
                    stay.confirmation_code or "UNCONFIRMED",
                    stay.notes or "",
                ]
            )
        if len(rows) > 1:
            return [{"range": "Hotels!A1", "values": rows}]
        return []

    def _build_checklist_update(self, trip: Trip) -> list[dict[str, Any]]:
        rows: list[list[Any]] = [_CHECKLIST_COLS]
        for item in trip.checklist:
            rows.append(
                [
                    item.item_id,
                    item.category,
                    item.title,
                    str(item.due_by or ""),
                    item.assigned_to or "",
                    "Yes" if item.completed else "No",
                ]
            )
        if len(rows) > 1:
            return [{"range": "Checklist!A1", "values": rows}]
        return []

    def _build_transfers_update(self, trip: Trip) -> list[dict[str, Any]]:
        rows: list[list[Any]] = [_TRANSFERS_COLS]
        for transfer in trip.transfers:
            rows.append(
                [
                    transfer.transfer_id,
                    transfer.provider or "",
                    transfer.driver_contact or "",
                    transfer.pickup_point or "",
                    transfer.pickup_window or "",
                    transfer.vehicle_details or "",
                    transfer.notes or "",
                ]
            )
        if len(rows) > 1:
            return [{"range": "Transfers!A1", "values": rows}]
        return []

    def _build_budget_update(self, trip: Trip) -> list[dict[str, Any]]:
        rows: list[list[Any]] = [_BUDGET_COLS]
        for b in trip.budgets:
            rows.append(
                [
                    b.category,
                    b.budgeted_cad or "",
                    b.booked_cad or "",
                    b.actual_cad or "",
                    b.variance_cad or "",
                ]
            )
        if len(rows) > 1:
            return [{"range": "Budget!A1", "values": rows}]
        return []
