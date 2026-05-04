"""Tests for the backend-owned flight flow state machine."""

from __future__ import annotations

import pytest

from trippy.models.shortlists import (
    FlightOption,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
)
from trippy.services.flight_flow import FlightFlowService
from trippy.services.flight_trip_envelope import FlightEnvelopeError


class _FakeStore:
    def __init__(self, state: ResearchShortlistState | None) -> None:
        self.state = state

    def load(
        self,
        trip_id: str,
        category: ShortlistCategory,
    ) -> ResearchShortlistState | None:
        return self.state

    def save(self, state: ResearchShortlistState) -> ResearchShortlistState:
        self.state = state
        return state


def test_flight_flow_repairs_orphan_return_selection() -> None:
    state = ResearchShortlistState(
        trip_id="azores-family-2026",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[
            _option("departure-1", "departure", "YYZ", "PDL"),
            _option("return-1", "return", "PDL", "YYZ"),
        ],
        artifacts={
            "flight_selection": {
                "selected_return_option_id": "return-1",
                "trip_envelope_locked": True,
            },
            "return_search": {"origin_airport": "PDL", "destination_airport": "YYZ"},
            "trip_envelope": {"status": "locked"},
        },
    )

    service = FlightFlowService(store=_FakeStore(state))
    response = service.get_state("azores-family-2026")
    flow = response["flight_flow"]
    repaired = response["shortlist"]

    assert flow["phase"] == "departure_required"
    assert flow["selected_departure"] is None
    assert flow["selected_return"] is None
    assert flow["return_options"] == []
    assert [option["option_id"] for option in flow["departure_options"]] == ["departure-1"]
    assert repaired["artifacts"]["flight_selection"]["trip_envelope_locked"] is False
    assert "selected_return_option_id" not in repaired["artifacts"]["flight_selection"]
    assert "return_search" not in repaired["artifacts"]
    assert [option["option_id"] for option in repaired["flight_options"]] == ["departure-1"]


def test_inter_location_search_creates_scanner_handoff_without_fake_flight_data() -> None:
    state = ResearchShortlistState(
        trip_id="azores-family-2026",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[
            _option(
                "departure-1",
                "departure",
                "YYZ",
                "PDL",
                row_status=ShortlistRowStatus.APPROVED,
            ),
        ],
        artifacts={"flight_selection": {"selected_outbound_option_id": "departure-1"}},
    )

    service = FlightFlowService(store=_FakeStore(state))
    response = service.search_inter_location(
        "azores-family-2026",
        origin_airport="PDL",
        destination_airport="LIS",
        departure_date="2026-08-27",
    )
    transfer_options = response["flight_flow"]["inter_location_options"]

    assert len(transfer_options) == 1
    row = transfer_options[0]
    assert row["option_id"] == "scanner-inter_location-PDL-LIS"
    assert row["flight_phase"] == "inter_location"
    assert row["departure_airport"] == "PDL"
    assert row["arrival_airport"] == "LIS"
    assert row["airline"] == "Flight scanner handoff — exact evidence required"
    assert row["flight_numbers"] == []
    assert row["fare_estimate_cad"] == "source evidence required"
    assert row["total_travel_duration"] == "source evidence required"
    assert row["validation"]["verification_status"] == "manual_required"
    assert "flight_numbers" in row["validation"]["missing_fields"]


def test_scanner_handoff_rows_are_not_selectable() -> None:
    service = FlightFlowService(store=_FakeStore(None))
    scanner_row = service._scanner_handoff_option(  # noqa: SLF001 - explicit contract regression
        "azores-family-2026",
        phase="departure",
        origin="YYZ",
        destination="PDL",
        departure_date="2026-08-24",
        rank=1,
    )
    state = ResearchShortlistState(
        trip_id="azores-family-2026",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[scanner_row],
    )
    service = FlightFlowService(store=_FakeStore(state))

    with pytest.raises(FlightEnvelopeError, match="scanner handoff"):
        service.select_departure("azores-family-2026", scanner_row.option_id)


def _option(
    option_id: str,
    phase: str,
    origin: str,
    destination: str,
    *,
    row_status: ShortlistRowStatus = ShortlistRowStatus.RESEARCHED,
) -> FlightOption:
    return FlightOption(
        option_id=option_id,
        rank=1,
        airline="WestJet",
        flight_numbers=["WS1"],
        flight_phase=phase,
        departure_date="2026-08-24",
        arrival_date="2026-08-24",
        departure_airport=origin,
        arrival_airport=destination,
        departure_time="8:00 AM",
        arrival_time="12:10 PM",
        stops=0,
        total_travel_duration="5h 10m",
        fare_estimate_cad="CAD 1,200 total; CAD 240 per person",
        price_band="CAD 1,200 total; CAD 240 per person",
        baggage_cabin_notes="verify bags",
        booking_source="Duffel",
        deep_link="https://www.google.com/travel/flights/search",
        traveler_count=5,
        friction_score=10,
        family_comfort_score=90,
        recommendation_grade=RecommendationGrade.STRONG,
        row_status=row_status,
    )
