"""Tests for canonical trip calendar integrity."""

from __future__ import annotations

from datetime import date

from trippy.models.shortlists import (
    FlightOption,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
)
from trippy.models.trip_calendar import TripCalendarStatus
from trippy.models.trip_planning import (
    TravelWindow,
    TripIntake,
    TripPlanOption,
)
from trippy.services.flight_trip_envelope import select_flight_for_envelope
from trippy.services.trip_calendar import TripCalendarService


def test_intake_only_calendar_is_provisional_target_window(tmp_path) -> None:
    intake = _intake()
    service = TripCalendarService(calendars_dir=tmp_path)

    calendar = service.from_intake(intake)

    assert calendar.status == TripCalendarStatus.TARGET_WINDOW
    assert calendar.rough_window.start_date == "2027-06-15"
    assert calendar.rough_window.end_date == "2027-06-23"
    assert calendar.rough_window.duration_days == 8
    assert calendar.trip_envelope.locked is False
    assert calendar.integrity.booking_safe is False
    assert "Trip envelope is provisional" in calendar.integrity.warnings[0]


def test_outbound_selection_does_not_lock_end_date(tmp_path) -> None:
    service = TripCalendarService(calendars_dir=tmp_path)
    calendar = service.from_intake(_intake())
    flight_state = _flight_state()
    flight_state = select_flight_for_envelope(
        flight_state,
        "outbound-1",
        selection_kind="departure",
    )

    calendar = service.apply_flight_state(calendar, flight_state)

    assert calendar.status == TripCalendarStatus.OUTBOUND_SELECTED
    assert calendar.trip_envelope.locked is False
    assert calendar.trip_envelope.outbound_flight_option_id == "outbound-1"
    assert calendar.trip_envelope.trip_end_date == ""
    assert calendar.integrity.booking_safe is False


def test_selected_departure_and_return_lock_envelope_and_stay_segments(tmp_path) -> None:
    service = TripCalendarService(calendars_dir=tmp_path)
    calendar = service.from_intake(_intake())
    flight_state = _flight_state()
    flight_state = select_flight_for_envelope(
        flight_state,
        "outbound-1",
        selection_kind="departure",
    )
    flight_state = select_flight_for_envelope(
        flight_state,
        "return-1",
        selection_kind="return",
    )

    calendar = service.apply_flight_state(calendar, flight_state)
    calendar = service.apply_plan_option(calendar, _two_region_option())

    assert calendar.trip_envelope.locked is True
    assert calendar.trip_envelope.trip_start_date == "2027-06-16"
    assert calendar.trip_envelope.trip_end_date == "2027-06-22"
    assert calendar.trip_envelope.trip_nights == 6
    assert calendar.stay_nights_total() == 6
    assert sum(segment.nights for segment in calendar.stay_segments) == calendar.trip_envelope.trip_nights
    assert calendar.stay_segments[0].start_date == "2027-06-16"
    assert calendar.stay_segments[-1].end_date == "2027-06-22"
    assert calendar.transfer_segments[0].date == calendar.stay_segments[0].end_date
    assert calendar.integrity.blocking_issues == []


def test_stay_segments_must_sum_to_locked_trip_nights(tmp_path) -> None:
    service = TripCalendarService(calendars_dir=tmp_path)
    calendar = service.from_intake(_intake())
    flight_state = _flight_state()
    flight_state = select_flight_for_envelope(
        select_flight_for_envelope(flight_state, "outbound-1", selection_kind="departure"),
        "return-1",
        selection_kind="return",
    )
    calendar = service.apply_flight_state(calendar, flight_state)
    calendar.stay_segments = []
    calendar = service.apply_plan_option(calendar, _two_region_option())

    calendar.stay_segments[0].nights = 1
    saved = service.save(calendar)

    assert saved.integrity.invariant_results["stay_nights_match_trip_nights"] is False
    assert "Stay segments total" in saved.integrity.blocking_issues[0]


def test_manual_stay_split_bumps_calendar_version_and_creates_boundaries(tmp_path) -> None:
    intake = _intake()
    service = TripCalendarService(calendars_dir=tmp_path)
    calendar = service.from_intake(intake)
    service.save(calendar)

    updated = service.update_stay_segments(
        intake.trip_id,
        [
            {"region": "Ponta Delgada", "nights": 4},
            {"region": "Furnas", "nights": 3},
        ],
    )

    assert updated.calendar_version == 2
    assert updated.stay_nights_total() == 7
    assert len(updated.transfer_segments) == 1
    assert updated.transfer_segments[0].from_region == "Ponta Delgada"
    assert updated.transfer_segments[0].to_region == "Furnas"


def _intake() -> TripIntake:
    return TripIntake(
        trip_id="azores-family-2027",
        trip_name="Azores family 2027",
        destination_seeds=["Azores"],
        travel_window=TravelWindow(
            start_date=date(2027, 6, 15),
            end_date=date(2027, 6, 23),
        ),
        duration_days=8,
        departure_airports=["YYZ"],
    )


def _two_region_option() -> TripPlanOption:
    return TripPlanOption(
        option_id="two-region-balanced",
        title="Ponta Delgada + Furnas",
        summary="Two-region split",
        duration_days=8,
        regions=["Ponta Delgada", "Furnas"],
        nights_by_region={"Ponta Delgada": 4, "Furnas": 3},
        travel_burden="moderate",
        island_region_movement_friction="one transfer",
        family_comfort_score=80,
        food_fit="good",
        driving_fit="verify roads",
        crowd_fit="good",
        recommendation_strength=82,
        lodging_strategy="split stay if transfer works",
        car_strategy="validate",
    )


def _flight_state() -> ResearchShortlistState:
    return ResearchShortlistState(
        trip_id="azores-family-2027",
        category=ShortlistCategory.FLIGHTS,
        flight_options=[
            _option(
                option_id="outbound-1",
                departure_airport="YYZ",
                arrival_airport="PDL",
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
