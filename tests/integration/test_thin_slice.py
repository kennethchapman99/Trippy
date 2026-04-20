"""
Thin-slice acceptance test — exercises the full pipeline.
Phases 0-2: stubs only. Becomes live from Phase 3 onward.
"""

from __future__ import annotations

import pytest


def test_import_sheet_creates_trip() -> None:
    """Phase 1: Import fixture sheet → trip created in DB."""
    import json
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock

    from sqlalchemy import create_engine, select

    from trippy.db import make_session_factory
    from trippy.db.models import Base, Trip
    from trippy.importers.sheet_importer import SheetImporter

    fixtures = Path(__file__).parent.parent / "fixtures"
    raw = json.loads((fixtures / "claude_responses" / "column_based.json").read_text())
    block = MagicMock()
    block.type = "tool_use"
    block.name = "extract_trips"
    block.input = raw
    msg = MagicMock()
    msg.content = [block]
    client = MagicMock()
    client.messages.create.return_value = msg

    with tempfile.TemporaryDirectory() as tmp:
        db_url = f"sqlite:///{tmp}/thin.db"
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        engine.dispose()

        importer = SheetImporter(db_url=db_url, anthropic_client=client)
        result = importer.import_file(fixtures / "sample_sheets" / "column_based.xlsx")

        assert result.ok, result.errors
        assert result.trips_created == 1

        factory = make_session_factory(db_url)
        with factory() as session:
            trip = session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
        assert str(trip.start_date) == "2026-03-15"


def test_confirmation_email_links_to_leg() -> None:
    """Phase 2: Feed mock confirmation email → leg linked."""
    import json
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock

    from sqlalchemy import create_engine

    from trippy.db import make_session_factory
    from trippy.db.models import Base, Leg, Trip
    from trippy.ingest.linker import ingest_email
    from trippy.ingest.parser import ConfirmationParser

    fixtures = Path(__file__).parent.parent / "fixtures"

    # --- set up DB with Japan 2026 trip + leg ---
    with tempfile.TemporaryDirectory() as tmp:
        db_url = f"sqlite:///{tmp}/thin2.db"
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        engine.dispose()

        from datetime import date, datetime

        factory = make_session_factory(db_url)
        with factory() as session:
            trip = Trip(
                name="Japan 2026",
                start_date=date(2026, 3, 15),
                end_date=date(2026, 3, 29),
                status="booked",
            )
            session.add(trip)
            session.flush()
            leg = Leg(
                trip_id=trip.id,
                leg_type="flight",
                carrier="Air Canada",
                flight_number="AC003",
                origin="YYZ",
                destination="NRT",
                depart_at=datetime(2026, 3, 15, 13, 30),
                arrive_at=datetime(2026, 3, 16, 17, 45),
            )
            session.add(leg)
            session.commit()
            trip_id = trip.id

        # --- mock parser ---
        raw = json.loads((fixtures / "claude_responses" / "aircanada_flight.json").read_text())
        block = MagicMock()
        block.type = "tool_use"
        block.name = "extract_confirmation"
        block.input = raw
        msg = MagicMock()
        msg.content = [block]
        client = MagicMock()
        client.messages.create.return_value = msg

        email_text = (fixtures / "emails" / "aircanada_flight.txt").read_text()
        parser = ConfirmationParser(anthropic_client=client)
        result = parser.parse(body_text=email_text)
        assert result.ok and result.confirmation is not None

        with factory() as session:
            link = ingest_email(result.confirmation, session)

        assert link.linked
        assert link.trip_id == trip_id


@pytest.mark.skip(reason="Phase 3 not yet implemented")
def test_trip_hub_show_japan() -> None:
    """Phase 3: Query trip hub 'show Japan' → structured summary."""


@pytest.mark.skip(reason="Phase 4 not yet implemented")
def test_visa_check_returns_expected_flags() -> None:
    """Phase 4: Run visa check → expected flags returned."""


@pytest.mark.skip(reason="Phase 5 not yet implemented")
def test_retro_extracts_preference() -> None:
    """Phase 5: Submit mock retro → preference extracted."""


@pytest.mark.skip(reason="Phase 6 not yet implemented")
def test_flight_search_respects_preference() -> None:
    """Phase 6: Flight search → results respect preference."""


@pytest.mark.skip(reason="Phase 7 not yet implemented")
def test_timeline_export_contains_trip() -> None:
    """Phase 7: Export timeline → HTML contains the trip."""
