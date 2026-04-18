"""Integration test — import fixture sheet → verify DB materialization."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

from hermes_trip.db import make_session_factory
from hermes_trip.db.models import Base, Leg, Stay, Traveler, Trip, TripStatus
from hermes_trip.importers.sheet_importer import SheetImporter

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_SHEETS = FIXTURES_DIR / "sample_sheets"
CLAUDE_RESPONSES = FIXTURES_DIR / "claude_responses"


@pytest.fixture
def file_db(tmp_path: Path) -> str:
    """Temp file-based SQLite DB with schema applied."""
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


def _mock_client(fixture_name: str) -> MagicMock:
    raw = json.loads((CLAUDE_RESPONSES / f"{fixture_name}.json").read_text())
    block = MagicMock()
    block.type = "tool_use"
    block.name = "extract_trips"
    block.input = raw
    msg = MagicMock()
    msg.content = [block]
    client = MagicMock()
    client.messages.create.return_value = msg
    return client


class TestColumnBasedIntegration:
    """Full import → DB query for the column-based fixture."""

    def test_trip_created_with_correct_fields(self, file_db: str) -> None:
        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("column_based"))
        result = importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")

        assert result.ok, result.errors
        assert result.trips_created == 1

        factory = make_session_factory(file_db)
        with factory() as session:
            trip = session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()

        assert str(trip.start_date) == "2026-03-15"
        assert str(trip.end_date) == "2026-03-29"
        assert trip.status == TripStatus.booked
        assert trip.destination_summary is not None
        assert "Tokyo" in trip.destination_summary

    def test_five_travelers_created(self, file_db: str) -> None:
        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("column_based"))
        importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")

        factory = make_session_factory(file_db)
        with factory() as session:
            trip = session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
            travelers = (
                session.execute(select(Traveler).where(Traveler.trip_id == trip.id)).scalars().all()
            )

        assert len(travelers) == 5
        names = {t.name for t in travelers}
        assert "Ken Chapman" in names
        assert "Sarah Chapman" in names

    def test_two_legs_created(self, file_db: str) -> None:
        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("column_based"))
        importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")

        factory = make_session_factory(file_db)
        with factory() as session:
            trip = session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
            legs = session.execute(select(Leg).where(Leg.trip_id == trip.id)).scalars().all()

        assert len(legs) == 2
        outbound = next(leg for leg in legs if leg.origin == "YYZ")
        assert outbound.destination == "NRT"
        assert outbound.confirmation_code == "ACJPN26"
        assert outbound.cost_cad == pytest.approx(8500.0)

    def test_two_stays_created(self, file_db: str) -> None:
        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("column_based"))
        importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")

        factory = make_session_factory(file_db)
        with factory() as session:
            trip = session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
            stays = session.execute(select(Stay).where(Stay.trip_id == trip.id)).scalars().all()

        assert len(stays) == 2
        tokyo = next(s for s in stays if s.city == "Tokyo")
        assert tokyo.property_name == "Shinjuku Granbell Hotel"
        assert str(tokyo.check_in) == "2026-03-16"

    def test_reimport_idempotent(self, file_db: str) -> None:
        for _ in range(2):
            importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("column_based"))
            importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")

        factory = make_session_factory(file_db)
        with factory() as session:
            trips = session.execute(select(Trip)).scalars().all()
            legs = session.execute(select(Leg)).scalars().all()

        assert len(trips) == 1
        assert len(legs) == 2  # not 4

    def test_confirmations_present(self, file_db: str) -> None:
        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("column_based"))
        importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")

        factory = make_session_factory(file_db)
        with factory() as session:
            trip = session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
            legs = session.execute(select(Leg).where(Leg.trip_id == trip.id)).scalars().all()
        conf_codes = {leg.confirmation_code for leg in legs if leg.confirmation_code}
        assert "ACJPN26" in conf_codes


class TestBrokenSheetIntegration:
    """Broken sheet must not raise and must return flagged report."""

    def test_returns_result_with_flags(self, file_db: str) -> None:
        from hermes_trip.importers.sheet_importer import ImportResult

        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("broken"))
        result = importer.import_file(SAMPLE_SHEETS / "broken.csv")
        assert isinstance(result, ImportResult)
        assert len(result.flagged_fields) > 0

    def test_does_not_create_leg_without_destination(self, file_db: str) -> None:
        importer = SheetImporter(db_url=file_db, anthropic_client=_mock_client("broken"))
        importer.import_file(SAMPLE_SHEETS / "broken.csv")

        factory = make_session_factory(file_db)
        with factory() as session:
            legs = session.execute(select(Leg)).scalars().all()
        # Broken fixture leg has no destination — _upsert skips it
        assert all(leg.destination for leg in legs)
