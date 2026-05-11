"""Tests for calendar binding during shortlist persistence."""

from __future__ import annotations

from trippy import config
from trippy.models.shortlists import (
    LodgingOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    VerificationStatus,
)
from trippy.models.trip_calendar import (
    StaySegment,
    TripCalendarState,
    TripEnvelope,
)
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.trip_calendar import TripCalendarService


def test_shortlist_store_binds_lodging_to_existing_calendar(tmp_path, monkeypatch) -> None:
    trip_id = "calendar-bound-trip"
    calendar_dir = tmp_path / "calendars"
    shortlist_dir = tmp_path / "shortlists"
    monkeypatch.setattr(config, "CALENDARS_PATH", calendar_dir, raising=False)

    calendar = TripCalendarState(
        trip_id=trip_id,
        calendar_version=4,
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
    TripCalendarService(calendars_dir=calendar_dir).save(calendar)

    store = ShortlistStore(shortlists_dir=shortlist_dir)
    state = ResearchShortlistState(
        trip_id=trip_id,
        category=ShortlistCategory.LODGING,
        lodging_options=[_live_lodging_option()],
    )

    saved = store.save(state)
    option = saved.lodging_options[0]

    assert option.calendar_version == 4
    assert option.date_dependency_hash == calendar.date_dependency_hash
    assert option.valid_for_segment_id == "stay-1"
    assert option.valid_for_start_date == "2027-06-16"
    assert option.valid_for_end_date == "2027-06-22"


def _live_lodging_option() -> LodgingOption:
    option = LodgingOption(
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
        live_data_status=LiveDataStatus.LIVE_VERIFIED,
    )
    option.validation.verification_status = VerificationStatus.LIVE_VERIFIED
    return option
