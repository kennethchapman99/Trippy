"""Integration test — mock Gmail → confirmation parsed → linked to trip."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

from trippy.db.models import Base, Confirmation, Leg, Stay, Trip

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
EMAILS_DIR = FIXTURES_DIR / "emails"
CLAUDE_RESPONSES = FIXTURES_DIR / "claude_responses"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def file_db(tmp_path: Path) -> str:
    db_path = tmp_path / "ingest_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return f"sqlite:///{db_path}"


def _seed_trip(db_url: str) -> None:
    """Insert Japan 2026 trip with one leg (AC003 YYZ→NRT) and one stay."""
    from trippy.db import make_session_factory

    factory = make_session_factory(db_url)
    with factory() as session:
        from datetime import date, datetime

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
            confirmation_code="ACJPN26",
        )
        stay = Stay(
            trip_id=trip.id,
            stay_type="hotel",
            property_name="Shinjuku Granbell Hotel",
            city="Tokyo",
            country="Japan",
            check_in=date(2026, 3, 16),
            check_out=date(2026, 3, 23),
        )
        session.add(leg)
        session.add(stay)
        session.commit()


def _make_parser_client(fixture_name: str) -> MagicMock:
    raw = json.loads((CLAUDE_RESPONSES / f"{fixture_name}.json").read_text())
    block = MagicMock()
    block.type = "tool_use"
    block.name = "extract_confirmation"
    block.input = raw
    message = MagicMock()
    message.content = [block]
    client = MagicMock()
    client.messages.create.return_value = message
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlightIngestion:
    def test_air_canada_confirmation_links_to_japan_trip(self, file_db: str) -> None:
        _seed_trip(file_db)

        from trippy.db import make_session_factory
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ConfirmationParser

        email_text = (EMAILS_DIR / "aircanada_flight.txt").read_text()
        parser = ConfirmationParser(anthropic_client=_make_parser_client("aircanada_flight"))
        result = parser.parse(body_text=email_text)
        assert result.ok
        assert result.confirmation is not None

        factory = make_session_factory(file_db)
        with factory() as session:
            link = ingest_email(result.confirmation, session)

        assert link.linked
        assert link.trip_id is not None

    def test_confirmation_row_persisted(self, file_db: str) -> None:
        _seed_trip(file_db)

        from trippy.db import make_session_factory
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ConfirmationParser

        email_text = (EMAILS_DIR / "aircanada_flight.txt").read_text()
        parser = ConfirmationParser(anthropic_client=_make_parser_client("aircanada_flight"))
        result = parser.parse(body_text=email_text)
        assert result.ok and result.confirmation is not None

        factory = make_session_factory(file_db)
        with factory() as session:
            ingest_email(result.confirmation, session)

        engine = create_engine(file_db)
        with engine.connect() as conn:
            rows = conn.execute(select(Confirmation)).fetchall()
        engine.dispose()
        assert len(rows) == 1

    def test_link_method_is_date_airport_or_flight_code(self, file_db: str) -> None:
        _seed_trip(file_db)

        from trippy.db import make_session_factory
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ConfirmationParser

        email_text = (EMAILS_DIR / "aircanada_flight.txt").read_text()
        parser = ConfirmationParser(anthropic_client=_make_parser_client("aircanada_flight"))
        result = parser.parse(body_text=email_text)
        assert result.ok and result.confirmation is not None

        factory = make_session_factory(file_db)
        with factory() as session:
            link = ingest_email(result.confirmation, session)

        assert link.method in ("date_airport", "trip_window", "flight_code")


class TestHotelIngestion:
    def test_booking_hotel_links_to_japan_trip(self, file_db: str) -> None:
        _seed_trip(file_db)

        from trippy.db import make_session_factory
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ConfirmationParser

        email_text = (EMAILS_DIR / "booking_hotel.txt").read_text()
        parser = ConfirmationParser(anthropic_client=_make_parser_client("booking_hotel"))
        result = parser.parse(body_text=email_text)
        assert result.ok and result.confirmation is not None

        factory = make_session_factory(file_db)
        with factory() as session:
            link = ingest_email(result.confirmation, session)

        assert link.linked


class TestUnlinkedConfirmation:
    def test_unknown_dates_stored_unlinked(self, file_db: str) -> None:
        """A confirmation with no matching trip is stored with trip_id=None."""
        _seed_trip(file_db)

        from trippy.db import make_session_factory
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ParsedConfirmation

        # VRBO Iceland — no matching trip in DB
        parsed = ParsedConfirmation(
            confirmation_type="hotel",
            confirmation_code="VRBO-8812345",
            vendor="VRBO",
            city="Reykjavik",
            country="Iceland",
            check_in="2026-07-10",
            check_out="2026-07-17",
            cost_cad=2875.0,
        )

        factory = make_session_factory(file_db)
        with factory() as session:
            link = ingest_email(parsed, session)

        assert not link.linked
        assert link.trip_id is None
        assert link.method == "unlinked"

    def test_unlinked_confirmation_persisted_in_db(self, file_db: str) -> None:
        from trippy.db import make_session_factory
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ParsedConfirmation

        parsed = ParsedConfirmation(
            confirmation_type="hotel",
            confirmation_code="VRBO-NO-TRIP",
            vendor="VRBO",
            city="Reykjavik",
            country="Iceland",
            check_in="2030-07-10",
        )

        factory = make_session_factory(file_db)
        with factory() as session:
            ingest_email(parsed, session)

        engine = create_engine(file_db)
        with engine.connect() as conn:
            rows = conn.execute(
                select(Confirmation).where(Confirmation.trip_id.is_(None))
            ).fetchall()
        engine.dispose()
        assert len(rows) >= 1
