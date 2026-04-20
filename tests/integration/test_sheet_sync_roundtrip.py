from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from trippy.models.trip import (
    ChecklistItem,
    Segment,
    SegmentType,
    Stay,
    StayType,
    Traveler,
    Trip,
)
from trippy.services.sheet_sync import SheetSyncService
from trippy.services.trip_state import TripStateService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sample_sheets"


class _FakeValues:
    def __init__(self, pulls: dict[str, list[list[str]]]) -> None:
        self._pulls = pulls
        self.batch_updates: list[dict[str, object]] = []

    def get(self, spreadsheetId: str, range: str):  # noqa: N803
        values = self._pulls.get(range, [])

        class _Call:
            def execute(self_nonlocal) -> dict[str, list[list[str]]]:
                return {"values": values}

        return _Call()

    def batchUpdate(self, spreadsheetId: str, body: dict[str, object]):  # noqa: N803
        self.batch_updates.append({"spreadsheetId": spreadsheetId, "body": body})

        class _Call:
            def execute(self_nonlocal) -> dict[str, object]:
                return {"updated": True}

        return _Call()


class _FakeSpreadsheets:
    def __init__(self, values: _FakeValues) -> None:
        self._values = values

    def values(self) -> _FakeValues:
        return self._values


class _FakeSheetsService:
    def __init__(self, values: _FakeValues) -> None:
        self._spreadsheets = _FakeSpreadsheets(values)

    def spreadsheets(self) -> _FakeSpreadsheets:
        return self._spreadsheets


class _FakeAuth:
    def __init__(self, pulls: dict[str, list[list[str]]]) -> None:
        self.values = _FakeValues(pulls)

    def build_service(self, name: str, version: str) -> _FakeSheetsService:  # noqa: ARG002
        return _FakeSheetsService(self.values)


def _seed_trip() -> Trip:
    return Trip(
        trip_id="japan-2027",
        name="Japan 2027",
        destination_summary="Tokyo",
        travelers=[Traveler(name="Ken"), Traveler(name="Sue")],
        segments=[
            Segment(
                segment_id="seg-1",
                segment_type=SegmentType.FLIGHT,
                origin="YYZ",
                destination="NRT",
                carrier="Original Carrier",
                confirmation_code="OLD-CODE",
            )
        ],
        stays=[
            Stay(
                stay_id="stay-1",
                stay_type=StayType.HOTEL,
                property_name="Hotel A",
                city="Tokyo",
                country="Japan",
                confirmation_code="OLD-HOTEL",
            )
        ],
        checklist=[ChecklistItem(item_id="chk-1", category="booking", title="Check passports")],
    )


def _pulls_from_fixture(path: Path) -> dict[str, list[list[str]]]:
    payload = json.loads(path.read_text())

    overview_rows = [["Field", "Value"]] + [[k, v] for k, v in payload.get("overview", {}).items()]

    flight_rows = [
        [
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
    ]
    for row in payload.get("flights", []):
        flight_rows.append(
            [
                row.get("Segment ID", ""),
                row.get("Type", ""),
                row.get("Carrier", ""),
                row.get("Flight #", ""),
                row.get("From", ""),
                row.get("To", ""),
                row.get("Departs", ""),
                row.get("Arrives", ""),
                row.get("Cabin", ""),
                row.get("Cost (CAD)", ""),
                row.get("Confirmation", ""),
                row.get("Notes", ""),
            ]
        )

    hotel_rows = [["Stay ID", "Type", "Property", "City", "Country", "Check-in", "Check-out", "Nights", "Cost (CAD)", "Confirmation", "Notes"]]
    for row in payload.get("hotels", []):
        hotel_rows.append(
            [
                row.get("Stay ID", ""),
                row.get("Type", ""),
                row.get("Property", ""),
                row.get("City", ""),
                row.get("Country", ""),
                row.get("Check-in", ""),
                row.get("Check-out", ""),
                row.get("Nights", ""),
                row.get("Cost (CAD)", ""),
                row.get("Confirmation", ""),
                row.get("Notes", ""),
            ]
        )

    checklist_rows = [["ID", "Category", "Task", "Due", "Assigned", "Done"]]
    for row in payload.get("checklist", []):
        checklist_rows.append(
            [
                row.get("ID", ""),
                row.get("Category", ""),
                row.get("Task", ""),
                row.get("Due", ""),
                row.get("Assigned", ""),
                row.get("Done", ""),
            ]
        )

    return {
        "Overview!A:B": overview_rows,
        "Flights!A:L": flight_rows,
        "Hotels!A:L": hotel_rows,
        "Checklist!A:F": checklist_rows,
        "Budget!A:E": [["Category", "Budgeted", "Booked", "Actual", "Variance"]],
    }


def test_sync_roundtrip_human_edit_propagates_to_json(tmp_path: Path) -> None:
    state = TripStateService(trips_dir=tmp_path)
    trip = _seed_trip()
    trip.sync.google_sheet_id = "sheet-123"
    state.save(trip)

    pulls = _pulls_from_fixture(FIXTURES / "sheet_edit_human_updates.json")
    auth = _FakeAuth(pulls)
    sync = SheetSyncService(auth_manager=auth, state_service=state)

    merged = sync.sync_roundtrip("japan-2027")

    assert merged.name == "Japan 2027 Updated"
    assert merged.destination_summary == "Tokyo, Kyoto"
    assert merged.get_segment("seg-1") is not None
    assert merged.get_segment("seg-1").confirmation_code == "AC-NEW123"  # type: ignore[union-attr]
    assert merged.get_stay("stay-1") is not None
    assert merged.get_stay("stay-1").confirmation_code == "HOTEL-123"  # type: ignore[union-attr]
    assert merged.checklist[0].completed is True

    reloaded = state.load("japan-2027")
    assert reloaded is not None
    assert reloaded.name == "Japan 2027 Updated"
    assert reloaded.sync.last_synced_by == "agent"
    assert auth.values.batch_updates, "Expected normalized push back to sheet"


def test_sync_roundtrip_conflict_is_flagged(tmp_path: Path) -> None:
    state = TripStateService(trips_dir=tmp_path)
    trip = _seed_trip()
    trip.sync.google_sheet_id = "sheet-123"
    trip.sync.last_synced_at = datetime(2026, 3, 1, 0, 0, 0)
    trip.sync.cell_updated_at["flights.seg-1.carrier"] = "2026-03-10T12:00:00"
    state.save(trip)

    pulls = _pulls_from_fixture(FIXTURES / "sheet_edit_conflict.json")
    auth = _FakeAuth(pulls)
    sync = SheetSyncService(auth_manager=auth, state_service=state)

    merged = sync.sync_roundtrip("japan-2027")

    assert merged.get_segment("seg-1") is not None
    assert merged.get_segment("seg-1").carrier == "Original Carrier"  # type: ignore[union-attr]
    assert merged.sync.sync_conflicts
    assert any("flights.seg-1.carrier" in c for c in merged.sync.sync_conflicts)
