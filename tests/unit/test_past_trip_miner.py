from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trippy.db.models import TripStatus
from trippy.importers.sheet_importer import ImportResult
from trippy.skills.runners.past_trip_miner import PastTripMinerRunner


def _fake_db_trip(name: str) -> SimpleNamespace:
    now = datetime(2026, 1, 1, 12, 0, 0)
    return SimpleNamespace(
        name=name,
        status=TripStatus.planned,
        destination_summary="",
        start_date=date(2026, 3, 10),
        end_date=date(2026, 3, 20),
        travelers=[],
        legs=[],
        stays=[],
        notes=None,
        created_at=now,
        updated_at=now,
    )


def test_import_sheet_persists_canonical_json_and_returns_trip_ids(tmp_path) -> None:
    runner = PastTripMinerRunner(
        trips_dir=tmp_path, auth_manager=MagicMock(), anthropic_client=MagicMock()
    )

    import_result = ImportResult(source="sheet-id")
    import_result.trips_created = 2
    import_result.db_trip_ids = [101, 202]

    db_trips = {
        101: _fake_db_trip("Japan 2026"),
        202: _fake_db_trip("Costa Rica 2027"),
    }

    session = MagicMock()
    session.get.side_effect = lambda _model, trip_id: db_trips.get(trip_id)

    @contextmanager
    def _factory_ctx():
        yield session

    def _factory():
        return _factory_ctx()

    with (
        patch(
            "trippy.importers.sheet_importer.SheetImporter.import_file", return_value=import_result
        ),
        patch("trippy.db.make_session_factory", return_value=_factory),
    ):
        result = runner._import_sheet({"id": "sheet-123", "name": "Ignored Name"})

    assert result["ok"] is True
    assert result["trip_ids"] == ["japan-2026", "costa-rica-2027"]

    saved_files = sorted(p.name for p in tmp_path.glob("*.json"))
    assert saved_files == ["costa-rica-2027.json", "japan-2026.json"]
