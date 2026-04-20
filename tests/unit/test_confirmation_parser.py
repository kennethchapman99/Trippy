"""Unit tests for ConfirmationParser — all Claude calls mocked."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trippy.ingest.parser import ConfirmationParser, ParsedConfirmation, ParserResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
EMAILS_DIR = FIXTURES_DIR / "emails"
CLAUDE_RESPONSES = FIXTURES_DIR / "claude_responses"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(fixture_name: str) -> MagicMock:
    raw = json.loads((CLAUDE_RESPONSES / f"{fixture_name}.json").read_text())

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "extract_confirmation"
    tool_block.input = raw

    message = MagicMock()
    message.content = [tool_block]

    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _parse(fixture_name: str) -> ParserResult:
    email_path = EMAILS_DIR / f"{fixture_name}.txt"
    body = email_path.read_text()
    parser = ConfirmationParser(anthropic_client=_make_mock_client(fixture_name))
    return parser.parse(body_text=body)


# ---------------------------------------------------------------------------
# Per-vendor tests
# ---------------------------------------------------------------------------


class TestAirCanadaFlight:
    def test_ok(self) -> None:
        result = _parse("aircanada_flight")
        assert result.ok
        assert result.confirmation is not None

    def test_confirmation_code(self) -> None:
        r = _parse("aircanada_flight")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_code == "ABC123"

    def test_origin_destination(self) -> None:
        r = _parse("aircanada_flight")
        assert r.confirmation is not None
        assert r.confirmation.origin == "YYZ"
        assert r.confirmation.destination == "NRT"

    def test_flight_number(self) -> None:
        r = _parse("aircanada_flight")
        assert r.confirmation is not None
        assert r.confirmation.flight_number == "AC003"

    def test_cost_cad(self) -> None:
        r = _parse("aircanada_flight")
        assert r.confirmation is not None
        assert r.confirmation.cost_cad == pytest.approx(8500.0)

    def test_five_travelers(self) -> None:
        r = _parse("aircanada_flight")
        assert r.confirmation is not None
        assert len(r.confirmation.traveler_names) == 5


class TestUnitedFlight:
    def test_ok(self) -> None:
        assert _parse("united_flight").ok

    def test_confirmation_code(self) -> None:
        r = _parse("united_flight")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_code == "XY7890"

    def test_type_is_flight(self) -> None:
        r = _parse("united_flight")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_type == "flight"


class TestDeltaFlight:
    def test_ok(self) -> None:
        assert _parse("delta_flight").ok

    def test_confirmation_code(self) -> None:
        r = _parse("delta_flight")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_code == "DL4422PQ"

    def test_origin_destination(self) -> None:
        r = _parse("delta_flight")
        assert r.confirmation is not None
        assert r.confirmation.origin == "ATL"
        assert r.confirmation.destination == "CDG"


class TestBookingHotel:
    def test_ok(self) -> None:
        assert _parse("booking_hotel").ok

    def test_type_is_hotel(self) -> None:
        r = _parse("booking_hotel")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_type == "hotel"

    def test_property_name(self) -> None:
        r = _parse("booking_hotel")
        assert r.confirmation is not None
        assert "Granbell" in (r.confirmation.property_name or "")

    def test_check_in(self) -> None:
        r = _parse("booking_hotel")
        assert r.confirmation is not None
        assert r.confirmation.check_in == "2026-03-16"

    def test_city_tokyo(self) -> None:
        r = _parse("booking_hotel")
        assert r.confirmation is not None
        assert r.confirmation.city == "Tokyo"


class TestAirbnbStay:
    def test_ok(self) -> None:
        assert _parse("airbnb_stay").ok

    def test_confirmation_code(self) -> None:
        r = _parse("airbnb_stay")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_code == "HMXK234567"

    def test_cost_cad(self) -> None:
        r = _parse("airbnb_stay")
        assert r.confirmation is not None
        assert r.confirmation.cost_cad == pytest.approx(1890.0)


class TestMarriottHotel:
    def test_ok(self) -> None:
        assert _parse("marriott_hotel").ok

    def test_confirmation_code(self) -> None:
        r = _parse("marriott_hotel")
        assert r.confirmation is not None
        assert r.confirmation.confirmation_code == "MRRT-20260316-00451"

    def test_high_confidence(self) -> None:
        r = _parse("marriott_hotel")
        assert r.confirmation is not None
        assert r.confirmation.confidence >= 0.9


class TestVrboStay:
    def test_ok(self) -> None:
        assert _parse("vrbo_stay").ok

    def test_city_reykjavik(self) -> None:
        r = _parse("vrbo_stay")
        assert r.confirmation is not None
        assert r.confirmation.city == "Reykjavik"

    def test_check_in_out(self) -> None:
        r = _parse("vrbo_stay")
        assert r.confirmation is not None
        assert r.confirmation.check_in == "2026-07-10"
        assert r.confirmation.check_out == "2026-07-17"


# ---------------------------------------------------------------------------
# Empty content
# ---------------------------------------------------------------------------


class TestEmptyContent:
    def test_empty_body_returns_error(self) -> None:
        parser = ConfirmationParser(anthropic_client=_make_mock_client("aircanada_flight"))
        result = parser.parse(body_text="", body_html="")
        assert not result.ok
        assert result.error is not None

    def test_error_result_has_no_confirmation(self) -> None:
        parser = ConfirmationParser(anthropic_client=_make_mock_client("aircanada_flight"))
        result = parser.parse(body_text="", body_html="")
        assert result.confirmation is None


# ---------------------------------------------------------------------------
# ParsedConfirmation model
# ---------------------------------------------------------------------------


class TestParsedConfirmation:
    def test_defaults_empty_traveler_names(self) -> None:
        c = ParsedConfirmation(
            confirmation_type="flight",
            confirmation_code="X1",
            vendor="TestAir",
        )
        assert c.traveler_names == []

    def test_default_confidence_is_one(self) -> None:
        c = ParsedConfirmation(
            confirmation_type="hotel",
            confirmation_code="H1",
            vendor="TestHotel",
        )
        assert c.confidence == pytest.approx(1.0)
