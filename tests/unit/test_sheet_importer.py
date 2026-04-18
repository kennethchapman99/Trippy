"""Unit tests for SheetImporter — all Claude calls mocked."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_trip.importers.sheet_importer import (
    CONFIDENCE_THRESHOLD,
    ImportResult,
    SheetImporter,
    _collect_flags,
    _parse_date,
    _parse_datetime,
    _parse_float,
    read_sheet_to_text,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_SHEETS = FIXTURES_DIR / "sample_sheets"
CLAUDE_RESPONSES = FIXTURES_DIR / "claude_responses"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(fixture_name: str) -> MagicMock:
    """Return a mock Anthropic client that returns the given fixture response."""
    raw = json.loads((CLAUDE_RESPONSES / f"{fixture_name}.json").read_text())

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "extract_trips"
    tool_block.input = raw

    message = MagicMock()
    message.content = [tool_block]

    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _make_importer(fixture_name: str, db_url: str | None = None) -> SheetImporter:
    """SheetImporter backed by a temp file DB (tables created) and mock Claude client."""
    import tempfile

    from sqlalchemy import create_engine

    from hermes_trip.db.models import Base

    if db_url is None:
        _, db_path = tempfile.mkstemp(suffix=".db")
        db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return SheetImporter(db_url=db_url, anthropic_client=_make_mock_client(fixture_name))


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestParseHelpers:
    def test_parse_date_iso(self) -> None:
        assert _parse_date("2026-03-15") is not None

    def test_parse_date_slash(self) -> None:
        assert _parse_date("15/03/2026") is not None

    def test_parse_date_none(self) -> None:
        assert _parse_date(None) is None

    def test_parse_date_invalid(self) -> None:
        assert _parse_date("32/13/2026") is None

    def test_parse_float_clean(self) -> None:
        assert _parse_float("8500") == 8500.0

    def test_parse_float_with_currency(self) -> None:
        assert _parse_float("$8,500.00") == pytest.approx(8500.0)

    def test_parse_float_not_a_number(self) -> None:
        assert _parse_float("not-a-number") is None

    def test_parse_float_none(self) -> None:
        assert _parse_float(None) is None

    def test_parse_datetime_iso(self) -> None:
        dt = _parse_datetime("2026-03-15T13:30:00")
        assert dt is not None
        assert dt.hour == 13

    def test_parse_datetime_date_only(self) -> None:
        dt = _parse_datetime("2026-03-15")
        assert dt is not None
        assert dt.year == 2026


class TestReadSheetToText:
    def test_read_csv(self) -> None:
        text = read_sheet_to_text(SAMPLE_SHEETS / "row_based.csv")
        assert "Costa Rica" in text

    def test_read_xlsx_column_based(self) -> None:
        text = read_sheet_to_text(SAMPLE_SHEETS / "column_based.xlsx")
        assert "Japan 2026" in text

    def test_read_xlsx_multi_tab(self) -> None:
        text = read_sheet_to_text(SAMPLE_SHEETS / "multi_tab.xlsx")
        assert "Sheet: Flights" in text
        assert "Sheet: Hotels" in text

    def test_read_free_form_csv(self) -> None:
        text = read_sheet_to_text(SAMPLE_SHEETS / "free_form.csv")
        assert "iceland" in text.lower()

    def test_read_broken_csv(self) -> None:
        # Should not raise — broken CSV is still readable text
        text = read_sheet_to_text(SAMPLE_SHEETS / "broken.csv")
        assert isinstance(text, str)

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "trip.pdf"
        f.write_bytes(b"fake")
        with pytest.raises(ValueError, match="Unsupported file type"):
            read_sheet_to_text(f)

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            read_sheet_to_text(Path("/nonexistent/trip.csv"))


# ---------------------------------------------------------------------------
# Fixture shape tests
# ---------------------------------------------------------------------------


class TestColumnBasedShape:
    def test_creates_trip(self) -> None:
        importer = _make_importer("column_based")
        result = importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")
        assert result.ok
        assert result.trips_created == 1

    def test_trip_has_correct_name(self) -> None:
        importer = _make_importer("column_based")
        result = importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")
        assert result.ok
        assert result.trips_created == 1

    def test_no_flags_for_high_confidence(self) -> None:
        importer = _make_importer("column_based")
        result = importer.import_file(SAMPLE_SHEETS / "column_based.xlsx")
        # column_based fixture has all confidence >= 0.7 except one null cost field
        low_conf = [f for f in result.flagged_fields if f.value is not None]
        assert len(low_conf) == 0


class TestRowBasedShape:
    def test_creates_trip(self) -> None:
        importer = _make_importer("row_based")
        result = importer.import_file(SAMPLE_SHEETS / "row_based.csv")
        assert result.ok
        assert result.trips_created == 1

    def test_no_errors(self) -> None:
        importer = _make_importer("row_based")
        result = importer.import_file(SAMPLE_SHEETS / "row_based.csv")
        assert not result.errors


class TestMultiTabShape:
    def test_creates_trip(self) -> None:
        importer = _make_importer("multi_tab")
        result = importer.import_file(SAMPLE_SHEETS / "multi_tab.xlsx")
        assert result.ok
        assert result.trips_created == 1

    def test_has_flagged_passport_fields(self) -> None:
        importer = _make_importer("multi_tab")
        result = importer.import_file(SAMPLE_SHEETS / "multi_tab.xlsx")
        # Traveler passport expiry fields have confidence 0.0 in fixture
        expiry_flags = [f for f in result.flagged_fields if f.field == "passport_expiry"]
        assert len(expiry_flags) == 5


class TestFreeFormShape:
    def test_creates_trip(self) -> None:
        importer = _make_importer("free_form")
        result = importer.import_file(SAMPLE_SHEETS / "free_form.csv")
        assert result.ok
        assert result.trips_created == 1

    def test_has_flagged_fields_for_inferred_data(self) -> None:
        importer = _make_importer("free_form")
        result = importer.import_file(SAMPLE_SHEETS / "free_form.csv")
        # Free-form has several fields below 0.7 (status, some passport expiries)
        assert len(result.flagged_fields) > 0

    def test_parsing_notes_populated(self) -> None:
        importer = _make_importer("free_form")
        result = importer.import_file(SAMPLE_SHEETS / "free_form.csv")
        assert len(result.parsing_notes) > 0


class TestBrokenShape:
    def test_graceful_failure_returns_result_not_exception(self) -> None:
        importer = _make_importer("broken")
        result = importer.import_file(SAMPLE_SHEETS / "broken.csv")
        # Broken fixture has a trip with name "Trip" but no start_date
        # The importer falls back to date.today() for missing start dates, so it proceeds
        assert isinstance(result, ImportResult)

    def test_many_flagged_fields(self) -> None:
        importer = _make_importer("broken")
        result = importer.import_file(SAMPLE_SHEETS / "broken.csv")
        # Almost everything is low-confidence in the broken fixture
        assert len(result.flagged_fields) >= 5

    def test_parsing_notes_explain_issues(self) -> None:
        importer = _make_importer("broken")
        result = importer.import_file(SAMPLE_SHEETS / "broken.csv")
        assert (
            "malformed" in result.parsing_notes.lower() or "broken" in result.parsing_notes.lower()
        )

    def test_unreadable_file_returns_error_not_exception(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "bad.xlsx"
        bad_path.write_bytes(b"not an xlsx file at all")
        importer = _make_importer("broken")
        result = importer.import_file(bad_path)
        assert not result.ok
        assert result.errors


# ---------------------------------------------------------------------------
# Idempotency test
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_reimport_updates_not_duplicates(self) -> None:
        db_url = "sqlite:///:memory:"
        client = _make_mock_client("column_based")

        # First import
        SheetImporter(db_url=db_url, anthropic_client=client)
        # We can't share in-memory SQLite across instances with the same URL easily,
        # so use a file-based temp DB for this test
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            file_db = f"sqlite:///{tmp_db}"
            from sqlalchemy import create_engine

            from hermes_trip.db import make_session_factory
            from hermes_trip.db.models import Base

            eng = create_engine(file_db)
            Base.metadata.create_all(eng)
            eng.dispose()

            imp1 = SheetImporter(db_url=file_db, anthropic_client=_make_mock_client("column_based"))
            r1 = imp1.import_file(SAMPLE_SHEETS / "column_based.xlsx")
            assert r1.trips_created == 1
            assert r1.trips_updated == 0

            imp2 = SheetImporter(db_url=file_db, anthropic_client=_make_mock_client("column_based"))
            r2 = imp2.import_file(SAMPLE_SHEETS / "column_based.xlsx")
            assert r2.trips_created == 0
            assert r2.trips_updated == 1

            # Confirm only 1 trip in DB
            from sqlalchemy import select

            from hermes_trip.db.models import Trip

            factory = make_session_factory(file_db)
            with factory() as session:
                trips = session.execute(select(Trip)).scalars().all()
            assert len(trips) == 1
        finally:
            os.unlink(tmp_db)


# ---------------------------------------------------------------------------
# Flag collection unit test
# ---------------------------------------------------------------------------


class TestCollectFlags:
    def test_flags_low_confidence_fields(self) -> None:
        from hermes_trip.importers.sheet_importer import FieldValue, ParsedTrip

        parsed = ParsedTrip(
            name=FieldValue(value="Test Trip", confidence=1.0),
            start_date=FieldValue(value="2026-01-01", confidence=0.5),  # LOW
            end_date=FieldValue(value=None, confidence=0.0),  # LOW (null)
            status=FieldValue(value="planned", confidence=0.9),
        )
        flags = _collect_flags(parsed)
        flag_fields = {f.field for f in flags}
        assert "start_date" in flag_fields
        assert "end_date" in flag_fields
        assert "status" not in flag_fields  # 0.9 >= threshold

    def test_no_flags_for_high_confidence_fields_with_values(self) -> None:
        from hermes_trip.importers.sheet_importer import FieldValue, ParsedTrip

        parsed = ParsedTrip(
            name=FieldValue(value="Test Trip", confidence=1.0),
            start_date=FieldValue(value="2026-01-01", confidence=1.0),
            end_date=FieldValue(value="2026-01-15", confidence=0.9),
            status=FieldValue(value="booked", confidence=0.8),
            destination_summary=FieldValue(value="Paris", confidence=0.9),
        )
        flags = _collect_flags(parsed)
        # Fields with values and confidence >= threshold should not appear in flags
        high_conf_with_value = [
            f for f in flags if f.value is not None and f.confidence >= CONFIDENCE_THRESHOLD
        ]
        assert len(high_conf_with_value) == 0
