"""Tests for the two-step flight selection envelope contract."""

from __future__ import annotations

import pytest

from trippy.models.shortlists import (
    FlightOption,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
)
from trippy.services.flight_trip_envelope import (
    FlightEnvelopeError,
    assert_trip_envelope_locked,
    derive_trip_envelope,
    downstream_status_for_category,
    is_iata_code,
    select_flight_for_envelope,
    split_options_by_phase,
)


def test_return_selection_is_blocked_until_departure_is_selected() -> None:
    state = _flight_state()

    with pytest.raises(FlightEnvelopeError, match="departure flight"):
        select_flight_for_envelope(state, "return-1", selection_kind="return")

    assert derive_trip_envelope(state) is None


def test_trip_envelope_only_locks_after_both_flights_are_selected() -> None:
    state = _flight_state()

    state = select_flight_for_envelope(state, "outbound-1", selection_kind="departure")
    assert derive_trip_envelope(state) is None
    assert state.artifacts["two_step_flight_flow"]["phase"] == "return_required"
    assert downstream_status_for_category(state, "lodging") == "blocked"

    state = select_flight_for_envelope(state, "return-1", selection_kind="return")
    envelope = assert_trip_envelope_locked(state)

    assert envelope["status"] == "locked"
    assert envelope["trip_start_datetime"] == "2027-06-16T07:10"
    assert envelope["trip_end_datetime"] == "2027-06-22T10:00"
    assert envelope["home_return_datetime"] == "2027-06-22T14:20"
    assert envelope["origin_airport"] == "YYZ"
    assert envelope["destination_airport"] == "PDL"
    assert envelope["trip_nights"] == 6
    assert state.artifacts["flight_selection"]["trip_envelope_locked"] is True
    assert downstream_status_for_category(state, "lodging") == "ready"
    assert downstream_status_for_category(state, "cars") == "ready"
    assert downstream_status_for_category(state, "activities") == "ready"
    assert downstream_status_for_category(state, "timeline") == "ready"


def test_return_options_are_route_filtered_from_selected_departure() -> None:
    state = _flight_state()
    state = select_flight_for_envelope(state, "outbound-1", selection_kind="outbound")

    phase = split_options_by_phase(state)

    assert phase["phase"] == "return_required"
    assert phase["route"] == {
        "origin_airport": "PDL",
        "destination_airport": "YYZ",
        "based_on_selected_outbound_option_id": "outbound-1",
    }
    assert [option.option_id for option in phase["return_options"]] == ["return-1"]


def test_freeform_destination_strings_are_not_iata_codes() -> None:
    assert is_iata_code("YYZ") is True
    assert is_iata_code("PDL") is True
    assert is_iata_code("SANTIAGO-PROVIDENCIA-SANTIAGO-BELLAVISTA") is False
    assert is_iata_code("Chile") is False


def test_envelope_lock_requires_normalized_airport_codes() -> None:
    state = _flight_state(
        outbound_arrival_airport="SANTIAGO-PROVIDENCIA-SANTIAGO-BELLAVISTA",
    )
    state = select_flight_for_envelope(state, "outbound-1", selection_kind="outbound")

    with pytest.raises(FlightEnvelopeError, match="IATA"):
        select_flight_for_envelope(state, "return-1", selection_kind="return")


def _flight_state(outbound_arrival_airport: str = "PDL") -> ResearchShortlistState:
    return ResearchShortlistState(
        trip_id="azores-family-2027",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[
            _option(
                option_id="outbound-1",
                departure_airport="YYZ",
                arrival_airport=outbound_arrival_airport,
                departure_date="2027-06-15",
                arrival_date="2027-06-16",
                departure_time="9:15 PM",
                arrival_time="7:10 AM",
            ),
            _option(
                option_id="return-1",
                departure_airport="PDL",
                arrival_airport="YYZ",
                departure_date="2027-06-22",
                arrival_date="2027-06-22",
                departure_time="10:00 AM",
                arrival_time="2:20 PM",
            ),
            _option(
                option_id="wrong-return-route",
                departure_airport="LIS",
                arrival_airport="YYZ",
                departure_date="2027-06-22",
                arrival_date="2027-06-22",
                departure_time="12:00 PM",
                arrival_time="4:20 PM",
            ),
        ],
    )


def _option(
    *,
    option_id: str,
    departure_airport: str,
    arrival_airport: str,
    departure_date: str,
    arrival_date: str,
    departure_time: str,
    arrival_time: str,
) -> FlightOption:
    return FlightOption(
        option_id=option_id,
        rank=1,
        airline="Azores Airlines",
        flight_numbers=["S4332"],
        departure_date=departure_date,
        arrival_date=arrival_date,
        departure_airport=departure_airport,
        arrival_airport=arrival_airport,
        departure_time=departure_time,
        arrival_time=arrival_time,
        stops=0,
        total_travel_duration="5h 55m",
        fare_estimate_cad="CAD 1,180 total; CAD 236 per person",
        price_band="CAD 1,180 total; CAD 236 per person",
        baggage_cabin_notes="verify bags",
        booking_source="Duffel",
        deep_link="https://www.google.com/travel/flights/search",
        traveler_count=5,
        friction_score=10,
        family_comfort_score=90,
        recommendation_grade=RecommendationGrade.STRONG,
    )
