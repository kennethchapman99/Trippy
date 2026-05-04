"""Tests for the backend-owned flight flow state machine."""

from __future__ import annotations

from trippy.models.shortlists import (
    FlightOption,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
)
from trippy.services.flight_flow import FlightFlowService


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


def _option(
    option_id: str,
    phase: str,
    origin: str,
    destination: str,
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
    )
