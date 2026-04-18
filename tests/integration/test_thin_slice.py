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

    from hermes_trip.db import make_session_factory
    from hermes_trip.db.models import Base, Trip
    from hermes_trip.importers.sheet_importer import SheetImporter

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


@pytest.mark.skip(reason="Phase 2 not yet implemented")
def test_confirmation_email_links_to_leg() -> None:
    """Phase 2: Feed mock confirmation email → leg linked."""


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
