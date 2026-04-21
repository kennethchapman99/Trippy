from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, cast

from trippy.models.trip import ChecklistItem, Segment, Stay, Trip
from trippy.services.trip_state import TripStateService

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

    def __init__(
        self, auth_manager: Any | None = None, state_service: TripStateService | None = None
    ) -> None:
        self._auth = auth_manager
        self._state = state_service or TripStateService()

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

    # ------------------------------------------------------------------
    # Pull: sheet → trip state
    # ------------------------------------------------------------------

    def pull_overview(self, sheet_id: str) -> dict[str, str]:
        rows = self._pull_range(sheet_id, "Overview!A:B")
        out: dict[str, str] = {}
        for row in rows[1:]:
            if len(row) >= 2 and str(row[0]).strip():
                out[str(row[0]).strip()] = str(row[1]).strip()
        return out

    def pull_flights(self, sheet_id: str) -> list[dict[str, str]]:
        rows = self._pull_range(sheet_id, "Flights!A:L")
        return self._rows_to_dicts(rows, _FLIGHTS_COLS)

    def pull_hotels(self, sheet_id: str) -> list[dict[str, str]]:
        rows = self._pull_range(sheet_id, "Hotels!A:L")
        return self._rows_to_dicts(rows, _HOTELS_COLS)

    def pull_checklist(self, sheet_id: str) -> list[dict[str, str]]:
        rows = self._pull_range(sheet_id, "Checklist!A:F")
        return self._rows_to_dicts(rows, _CHECKLIST_COLS)

    def pull_budget(self, sheet_id: str) -> list[dict[str, str]]:
        rows = self._pull_range(sheet_id, "Budget!A:E")
        return self._rows_to_dicts(rows, _BUDGET_COLS)

    def pull_sheet_edits(self, sheet_id: str) -> dict[str, Any]:
        return {
            "overview": self.pull_overview(sheet_id),
            "flights": self.pull_flights(sheet_id),
            "hotels": self.pull_hotels(sheet_id),
            "checklist": self.pull_checklist(sheet_id),
            "budget": self.pull_budget(sheet_id),
        }

    def _pull_range(self, sheet_id: str, range_name: str) -> list[list[str]]:
        service = self._sheets_service()
        try:
            resp = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=sheet_id, range=range_name)
                .execute()
            )
            return cast(list[list[str]], resp.get("values", []))
        except Exception as exc:
            logger.warning("pull range failed sheet=%s range=%s err=%s", sheet_id, range_name, exc)
            return []

    def _rows_to_dicts(self, rows: list[list[str]], cols: list[str]) -> list[dict[str, str]]:
        data: list[dict[str, str]] = []
        for row in rows[1:]:
            if not row:
                continue
            mapped = {
                col: str(row[idx]).strip() if idx < len(row) else "" for idx, col in enumerate(cols)
            }
            if any(mapped.values()):
                data.append(mapped)
        return data

    # ------------------------------------------------------------------
    # Merge + roundtrip
    # ------------------------------------------------------------------

    def merge_sheet_edits(
        self,
        trip: Trip,
        pulled: dict[str, Any],
        pulled_at: datetime | None = None,
    ) -> Trip:
        ts = pulled_at or datetime.utcnow()

        overview = pulled.get("overview", {})
        if isinstance(overview, dict):
            self._merge_trip_field(trip, "overview.name", "name", overview.get("Trip Name"), ts)
            self._merge_trip_field(
                trip,
                "overview.destination_summary",
                "destination_summary",
                overview.get("Destinations"),
                ts,
            )
            self._merge_trip_field(
                trip,
                "overview.start_date",
                "start_date",
                _parse_date(overview.get("Start Date")),
                ts,
            )
            self._merge_trip_field(
                trip,
                "overview.end_date",
                "end_date",
                _parse_date(overview.get("End Date")),
                ts,
            )
            sheet_trip_id = (overview.get("Trip ID") or "").strip()
            if sheet_trip_id and sheet_trip_id != trip.trip_id:
                self._record_conflict(
                    trip,
                    "overview.trip_id",
                    sheet_trip_id,
                    trip.trip_id,
                    ts,
                    "Trip ID is immutable; canonical ID preserved.",
                )

        by_segment_id = {seg.segment_id: seg for seg in trip.segments}
        for row in pulled.get("flights", []):
            seg_id = (row.get("Segment ID") or "").strip()
            if not seg_id:
                continue
            seg = by_segment_id.get(seg_id)
            if seg is None:
                self._record_conflict(
                    trip,
                    f"flights.{seg_id}",
                    "new row",
                    "missing segment",
                    ts,
                    "Segment ID not found in canonical trip; row ignored.",
                )
                continue
            self._merge_model_field(
                trip, seg, f"flights.{seg_id}.carrier", "carrier", row.get("Carrier"), ts
            )
            self._merge_model_field(
                trip,
                seg,
                f"flights.{seg_id}.confirmation_code",
                "confirmation_code",
                row.get("Confirmation"),
                ts,
            )
            self._merge_model_field(
                trip, seg, f"flights.{seg_id}.notes", "notes", row.get("Notes"), ts
            )

        by_stay_id = {stay.stay_id: stay for stay in trip.stays}
        for row in pulled.get("hotels", []):
            stay_id = (row.get("Stay ID") or "").strip()
            if not stay_id:
                continue
            stay = by_stay_id.get(stay_id)
            if stay is None:
                self._record_conflict(
                    trip,
                    f"hotels.{stay_id}",
                    "new row",
                    "missing stay",
                    ts,
                    "Stay ID not found in canonical trip; row ignored.",
                )
                continue
            self._merge_model_field(
                trip,
                stay,
                f"hotels.{stay_id}.confirmation_code",
                "confirmation_code",
                row.get("Confirmation"),
                ts,
            )
            self._merge_model_field(
                trip,
                stay,
                f"hotels.{stay_id}.notes",
                "notes",
                row.get("Notes"),
                ts,
            )

        by_item_id = {item.item_id: item for item in trip.checklist}
        for row in pulled.get("checklist", []):
            item_id = (row.get("ID") or "").strip()
            if not item_id:
                continue
            item = by_item_id.get(item_id)
            if item is None:
                self._record_conflict(
                    trip,
                    f"checklist.{item_id}",
                    "new row",
                    "missing item",
                    ts,
                    "Checklist ID not found in canonical trip; row ignored.",
                )
                continue
            done_raw = (row.get("Done") or "").strip().lower()
            self._merge_model_field(
                trip,
                item,
                f"checklist.{item_id}.completed",
                "completed",
                done_raw in {"yes", "true", "1", "done"},
                ts,
            )

        return trip

    def sync_roundtrip(self, trip_id: str) -> Trip:
        trip = self._state.load(trip_id)
        if trip is None:
            raise ValueError(f"Trip {trip_id!r} not found")
        if not trip.sync.google_sheet_id:
            raise ValueError(f"Trip {trip_id!r} has no google_sheet_id configured")

        pulled_at = datetime.utcnow()
        pulled = self.pull_sheet_edits(trip.sync.google_sheet_id)
        merged = self.merge_sheet_edits(trip, pulled, pulled_at=pulled_at)
        self._state.save(merged)

        self.push_trip_to_sheet(merged, trip.sync.google_sheet_id)
        merged.sync.last_synced_at = datetime.utcnow()
        merged.sync.last_synced_by = "agent"
        self._state.save(merged)
        return merged

    def _merge_trip_field(
        self,
        trip: Trip,
        field_key: str,
        attr: str,
        incoming: Any,
        incoming_ts: datetime,
    ) -> None:
        if incoming in (None, ""):
            return
        canonical = getattr(trip, attr)
        self._merge_with_timestamp(
            trip=trip,
            field_key=field_key,
            canonical_value=canonical,
            incoming_value=incoming,
            incoming_ts=incoming_ts,
            apply=lambda value: setattr(trip, attr, value),
        )

    def _merge_model_field(
        self,
        trip: Trip,
        obj: Segment | Stay | ChecklistItem,
        field_key: str,
        attr: str,
        incoming: Any,
        incoming_ts: datetime,
    ) -> None:
        if incoming in (None, ""):
            return
        canonical = getattr(obj, attr)
        self._merge_with_timestamp(
            trip=trip,
            field_key=field_key,
            canonical_value=canonical,
            incoming_value=incoming,
            incoming_ts=incoming_ts,
            apply=lambda value: setattr(obj, attr, value),
        )

    def _merge_with_timestamp(
        self,
        trip: Trip,
        field_key: str,
        canonical_value: Any,
        incoming_value: Any,
        incoming_ts: datetime,
        apply: Any,
    ) -> None:
        if canonical_value == incoming_value:
            return

        cell_map = trip.sync.cell_updated_at
        field_ts_raw = cell_map.get(field_key)
        field_ts = _parse_datetime(field_ts_raw)

        if field_ts is not None and field_ts > incoming_ts:
            self._record_conflict(
                trip,
                field_key,
                incoming_value,
                canonical_value,
                incoming_ts,
                "Canonical field is newer than sheet edit; keeping canonical value.",
            )
            return

        last_sync = trip.sync.last_synced_at
        if field_ts is not None and last_sync is not None and field_ts > last_sync:
            self._record_conflict(
                trip,
                field_key,
                incoming_value,
                canonical_value,
                incoming_ts,
                "Field changed since last sync; edit requires review.",
            )
            return

        apply(incoming_value)
        cell_map[field_key] = incoming_ts.isoformat()

    def _record_conflict(
        self,
        trip: Trip,
        field_key: str,
        sheet_value: Any,
        canonical_value: Any,
        ts: datetime,
        reason: str,
    ) -> None:
        trip.sync.sync_conflicts.append(
            f"{ts.isoformat()} field={field_key} sheet={sheet_value!r} "
            f"canonical={canonical_value!r} reason={reason}"
        )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
