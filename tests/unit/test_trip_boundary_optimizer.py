"""Tests for destination-agnostic stay-boundary optimization."""

from __future__ import annotations

from trippy.models.trip_calendar import StaySegment, TripCalendarState, TripEnvelope
from trippy.services.trip_boundary_optimizer import BoundaryOptimizerService, TransferEvidence


def test_boundary_optimizer_prefers_split_with_transfer_evidence() -> None:
    calendar = _calendar_with_two_stays(3, 5)
    candidates = BoundaryOptimizerService().suggest_splits(
        calendar,
        transfer_evidence=[
            TransferEvidence(date="2027-06-19", cost_cad=900, friction_score=70),
            TransferEvidence(date="2027-06-20", cost_cad=250, friction_score=25),
        ],
        max_shift_nights=1,
    )

    assert candidates
    best = candidates[0]

    assert best.nights_by_region == {"Region A": 4, "Region B": 4}
    assert best.transfer_dates == ["2027-06-20"]
    assert best.total_known_transfer_cost_cad == 250
    assert best.recommendation in {"good", "strong"}


def test_boundary_optimizer_requires_locked_envelope() -> None:
    calendar = TripCalendarState(trip_id="trip")

    candidates = BoundaryOptimizerService().suggest_splits(calendar)

    assert candidates == []


def test_boundary_optimizer_marks_missing_evidence_as_research_required() -> None:
    calendar = _calendar_with_two_stays(3, 5)

    candidates = BoundaryOptimizerService().suggest_splits(calendar, transfer_evidence=[])

    assert candidates
    assert candidates[0].recommendation == "research_required"
    assert candidates[0].missing_evidence_dates


def _calendar_with_two_stays(first_nights: int, second_nights: int) -> TripCalendarState:
    calendar = TripCalendarState(
        trip_id="trip",
        trip_envelope=TripEnvelope(
            locked=True,
            trip_start_date="2027-06-16",
            trip_end_date="2027-06-24",
            trip_nights=8,
        ),
        stay_segments=[
            StaySegment(
                segment_id="stay-1",
                sequence=1,
                region="Region A",
                start_date="2027-06-16",
                end_date="2027-06-19",
                nights=first_nights,
            ),
            StaySegment(
                segment_id="stay-2",
                sequence=2,
                region="Region B",
                start_date="2027-06-19",
                end_date="2027-06-24",
                nights=second_nights,
            ),
        ],
    )
    calendar.integrity.booking_safe = True
    return calendar
