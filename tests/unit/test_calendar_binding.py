"""Tests for binding shortlist rows to the canonical calendar."""

from __future__ import annotations

from trippy.models.shortlists import (
    LodgingOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    VerificationStatus,
)
from trippy.models.trip_calendar import StaySegment, TripCalendarState, TripEnvelope
from trippy.services.calendar_binding import CalendarBindingService


def test_lodging_is_provisional_when_envelope_is_not_locked() -> None:
    calendar = TripCalendarState(trip_id="trip")
    state = ResearchShortlistState(
        trip_id="trip",
        category=ShortlistCategory.LODGING,
        lodging_options=[_lodging_option()],
    )

    bound = CalendarBindingService().bind_state(calendar, state)
    option = bound.lodging_options[0]

    assert option.booking_safe is False
    assert option.dependency_status == "provisional_no_envelope"
    assert "Trip envelope is not locked" in option.booking_blockers[0]


def test_live_lodging_matching_current_segment_can_be_booking_safe() -> None:
    calendar = _locked_calendar()
    option = _lodging_option()
    option.live_data_status = LiveDataStatus.LIVE_VERIFIED
    option.validation.verification_status = VerificationStatus.LIVE_VERIFIED
    state = ResearchShortlistState(
        trip_id="trip",
        category=ShortlistCategory.LODGING,
        lodging_options=[option],
    )

    bound = CalendarBindingService().bind_state(calendar, state)
    option = bound.lodging_options[0]

    assert option.booking_safe is True
    assert option.dependency_status == "current"
    assert option.calendar_version == calendar.calendar_version
    assert option.date_dependency_hash == calendar.date_dependency_hash
    assert option.valid_for_start_date == "2027-06-16"
    assert option.valid_for_end_date == "2027-06-22"
    assert option.valid_for_segment_id == "stay-1"


def test_stale_hash_blocks_booking_safe() -> None:
    calendar = _locked_calendar()
    option = _lodging_option()
    option.live_data_status = LiveDataStatus.LIVE_VERIFIED
    option.validation.verification_status = VerificationStatus.LIVE_VERIFIED
    option.date_dependency_hash = "old-hash"
    state = ResearchShortlistState(
        trip_id="trip",
        category=ShortlistCategory.LODGING,
        lodging_options=[option],
    )

    bound = CalendarBindingService().bind_state(calendar, state)
    option = bound.lodging_options[0]

    assert option.booking_safe is False
    assert option.dependency_status == "stale_calendar_changed"
    assert "stale calendar" in " ".join(option.booking_blockers).lower()


def _locked_calendar() -> TripCalendarState:
    calendar = TripCalendarState(
        trip_id="trip",
        calendar_version=3,
        date_dependency_hash="calendar-hash",
        trip_envelope=TripEnvelope(
            locked=True,
            trip_start_date="2027-06-16",
            trip_end_date="2027-06-22",
            trip_nights=6,
        ),
        stay_segments=[
            StaySegment(
                segment_id="stay-1",
                sequence=1,
                region="Ponta Delgada",
                start_date="2027-06-16",
                end_date="2027-06-22",
                nights=6,
            )
        ],
    )
    calendar.integrity.booking_safe = True
    return calendar


def _lodging_option() -> LodgingOption:
    return LodgingOption(
        option_id="lodging-1",
        rank=1,
        source="manual-test-source",
        name="Ponta Delgada stay",
        location_area="Ponta Delgada",
        island_or_region="Ponta Delgada",
        lodging_type="hotel",
        bed_layout="3 beds confirmed",
        min_three_beds_satisfied=True,
        king_bed_preference_satisfied=True,
        family_of_five_fit=True,
        parking_practicality="good",
        driving_practicality="good",
        walkability="good",
        cancellation_notes="verify",
        price_band="CAD 2,000 total",
        deep_link="manual-test-link",
        friction_score=10,
        family_comfort_score=90,
        recommendation_grade=RecommendationGrade.STRONG,
        live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
    )
