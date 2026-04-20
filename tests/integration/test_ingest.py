"""Integration test — mock Gmail → confirmation parsed → linked to trip."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

from trippy.db.models import Base, Confirmation, Leg, Stay, Trip
from trippy.models.trip import Segment, SegmentType, SyncMetadata

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


class TestGmailReconcilerCanonicalSync:
    def test_runner_updates_canonical_and_pushes_sheet(
        self, file_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_trip(file_db)

        from trippy import config
        from trippy.ingest.gmail_watcher import EmailContent
        from trippy.models.trip import Trip as CanonicalTrip
        from trippy.models.trip import TripStatus
        from trippy.services.trip_state import TripStateService
        from trippy.skills.runners.gmail_reconciler import GmailReconcilerRunner

        trips_dir = tmp_path / "trips"
        vault_dir = tmp_path / "vault"
        monkeypatch.setattr(config, "DATABASE_URL", file_db)
        monkeypatch.setattr(config, "TRIPS_PATH", trips_dir)
        monkeypatch.setattr(config, "VAULT_PATH", vault_dir)

        trip_state = TripStateService(trips_dir=trips_dir)
        canonical_trip = CanonicalTrip(
            trip_id="japan-2026",
            name="Japan 2026",
            status=TripStatus.BOOKED,
            sync=SyncMetadata(google_sheet_id="sheet-abc-123"),
            segments=[
                Segment(
                    segment_id="leg-1",
                    segment_type=SegmentType.FLIGHT,
                    carrier="Air Canada",
                    flight_number="AC003",
                    origin="YYZ",
                    destination="NRT",
                )
            ],
        )
        trip_state.save(canonical_trip)

        email_text = (EMAILS_DIR / "aircanada_flight.txt").read_text()
        fixture_email = EmailContent(
            message_id="m-1",
            sender="bookings@aircanada.com",
            subject="Your Air Canada booking confirmation",
            date=canonical_trip.created_at,
            body_text=email_text,
            body_html="",
            attachments=[],
            raw_bytes=b"raw-email",
        )

        class FakeWatcher:
            def __init__(self, auth_manager: object | None = None) -> None:
                self._auth_manager = auth_manager

            def authenticate(self) -> None:
                return None

            def fetch_new_messages(self, max_results: int = 50) -> list[EmailContent]:
                return [fixture_email]

            def save_to_vault(self, email_content: EmailContent, vault_path: Path) -> Path:
                vault_path.mkdir(parents=True, exist_ok=True)
                p = vault_path / "email-1.eml"
                p.write_bytes(email_content.raw_bytes)
                return p

        pushes: list[tuple[str, str]] = []

        class FakeSheetSyncService:
            def __init__(self, auth_manager: object | None = None) -> None:
                self._auth_manager = auth_manager

            def push_trip_to_sheet(self, trip: CanonicalTrip, sheet_id: str) -> None:
                pushes.append((trip.trip_id, sheet_id))

        class FakeAuthManager:
            pass

        from trippy.ingest import gmail_watcher as watcher_mod
        from trippy.ingest import google_auth as google_auth_mod
        from trippy.services import sheet_sync as sheet_sync_mod

        monkeypatch.setattr(watcher_mod, "GmailWatcher", FakeWatcher)
        monkeypatch.setattr(google_auth_mod, "GoogleAuthManager", FakeAuthManager)
        monkeypatch.setattr(sheet_sync_mod, "SheetSyncService", FakeSheetSyncService)

        runner = GmailReconcilerRunner(
            trips_dir=trips_dir,
            anthropic_client=_make_parser_client("aircanada_flight"),
        )
        result = runner.run({"max_emails": 5})

        updated = trip_state.load("japan-2026")
        assert updated is not None
        assert result["confirmations_linked"] == 1
        assert result["confirmations_unlinked"] == 0
        assert len(updated.confirmations) == 1
        assert updated.confirmations[0].confirmation_code == "ABC123"
        assert updated.confirmations[0].linked_segment_id == "leg-1"
        assert updated.segments[0].confirmation_code == "ABC123"
        assert pushes == [("japan-2026", "sheet-abc-123")]
        assert result["ambiguities"] == []
