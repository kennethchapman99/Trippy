"""Tests for canonical Pydantic trip models."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from trippy.models.preferences import (
    DepartureTimePreference,
    FamilyTravelPreferences,
    LayoverPreference,
)
from trippy.models.profile import FamilyProfile, TravelerProfile
from trippy.models.trip import (
    Budget,
    RiskFlag,
    RiskSeverity,
    Segment,
    SegmentType,
    Stay,
    Traveler,
    Trip,
    TripStatus,
)

# ---------------------------------------------------------------------------
# Trip model
# ---------------------------------------------------------------------------


class TestTripModel:
    def test_auto_trip_id(self) -> None:
        trip = Trip(name="Japan 2026")
        assert trip.trip_id == "japan-2026"

    def test_auto_trip_id_with_spaces(self) -> None:
        trip = Trip(name="Costa Rica 2025 Family")
        assert trip.trip_id == "costa-rica-2025-family"

    def test_explicit_trip_id(self) -> None:
        trip = Trip(trip_id="my-custom-id", name="Japan 2026")
        assert trip.trip_id == "my-custom-id"

    def test_default_status(self) -> None:
        trip = Trip(name="Test Trip")
        assert trip.status == TripStatus.DREAM

    def test_summary_no_dates(self) -> None:
        trip = Trip(name="Japan 2026", status=TripStatus.PLANNED)
        assert "Japan 2026" in trip.summary()
        assert "planned" in trip.summary()

    def test_summary_with_dates(self) -> None:
        trip = Trip(
            name="Japan 2026",
            status=TripStatus.BOOKED,
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 24),
        )
        s = trip.summary()
        assert "2026-03-10" in s
        assert "booked" in s

    def test_summary_with_high_risks(self) -> None:
        trip = Trip(
            name="Japan 2026",
            risk_flags=[
                RiskFlag(
                    risk_id="r1",
                    severity=RiskSeverity.HIGH,
                    category="layover",
                    description="Tight connection",
                )
            ],
        )
        assert "high risks" in trip.summary()

    def test_unconfirmed_segments(self) -> None:
        trip = Trip(
            name="Test",
            segments=[
                Segment(segment_id="s1", origin="YYZ", destination="NRT", confirmation_code="ABC"),
                Segment(segment_id="s2", origin="NRT", destination="KIX"),
            ],
        )
        assert len(trip.unconfirmed_segments) == 1
        assert trip.unconfirmed_segments[0].segment_id == "s2"

    def test_confirmed_segment_unknown_code(self) -> None:
        seg = Segment(segment_id="s1", origin="YYZ", destination="NRT", confirmation_code="UNKNOWN")
        assert not seg.is_confirmed

    def test_total_booked_cad(self) -> None:
        trip = Trip(
            name="Test",
            budgets=[
                Budget(category="flights", booked_cad=2500.0),
                Budget(category="hotels", booked_cad=3000.0),
            ],
        )
        assert trip.total_booked_cad == 5500.0

    def test_json_round_trip(self) -> None:
        trip = Trip(
            name="Japan 2026",
            status=TripStatus.BOOKED,
            start_date=date(2026, 3, 10),
            travelers=[Traveler(name="Ken", passport_country="CAN")],
            segments=[
                Segment(
                    segment_id="s1",
                    segment_type=SegmentType.FLIGHT,
                    origin="YYZ",
                    destination="NRT",
                    depart_at=datetime(2026, 3, 10, 9, 0),
                )
            ],
        )
        json_str = trip.model_dump_json()
        restored = Trip.model_validate_json(json_str)
        assert restored.trip_id == trip.trip_id
        assert restored.travelers[0].name == "Ken"
        assert restored.segments[0].segment_type == SegmentType.FLIGHT


class TestSegment:
    def test_duration_minutes(self) -> None:
        seg = Segment(
            segment_id="s1",
            origin="YYZ",
            destination="YVR",
            depart_at=datetime(2026, 3, 10, 9, 0),
            arrive_at=datetime(2026, 3, 10, 11, 30),
        )
        assert seg.duration_minutes == 150

    def test_is_confirmed_true(self) -> None:
        seg = Segment(segment_id="s1", origin="YYZ", destination="NRT", confirmation_code="ABC123")
        assert seg.is_confirmed

    def test_is_confirmed_false_empty(self) -> None:
        seg = Segment(segment_id="s1", origin="YYZ", destination="NRT")
        assert not seg.is_confirmed


class TestStay:
    def test_nights(self) -> None:
        stay = Stay(
            stay_id="stay-1",
            property_name="Test Hotel",
            city="Tokyo",
            country="Japan",
            check_in=date(2026, 3, 11),
            check_out=date(2026, 3, 15),
        )
        assert stay.nights == 4

    def test_is_confirmed(self) -> None:
        stay = Stay(
            stay_id="stay-1",
            property_name="Test Hotel",
            city="Tokyo",
            country="Japan",
            confirmation_code="HT-12345",
        )
        assert stay.is_confirmed


class TestBudget:
    def test_variance_positive(self) -> None:
        b = Budget(category="flights", budgeted_cad=2000.0, booked_cad=2400.0)
        assert b.variance_cad == pytest.approx(400.0)

    def test_variance_none_when_missing(self) -> None:
        b = Budget(category="flights", budgeted_cad=2000.0)
        assert b.variance_cad is None


# ---------------------------------------------------------------------------
# Preferences model
# ---------------------------------------------------------------------------


class TestFamilyTravelPreferences:
    def test_defaults(self) -> None:
        prefs = FamilyTravelPreferences()
        assert prefs.departure_time.earliest_acceptable == "07:00"
        assert prefs.layover.min_connection_minutes_international == 110
        assert prefs.stay.min_checkin_hour == 15

    def test_context_string(self) -> None:
        prefs = FamilyTravelPreferences()
        ctx = prefs.to_context_string()
        assert "07:00" in ctx
        assert "110" in ctx
        assert "comfort" in ctx.lower()

    def test_departure_acceptable(self) -> None:
        pref = DepartureTimePreference(earliest_acceptable="07:00")
        assert pref.is_acceptable("09:00")
        assert not pref.is_acceptable("06:30")

    def test_connection_safe_international(self) -> None:
        layover = LayoverPreference(min_connection_minutes_international=110)
        assert layover.is_connection_safe(120, is_international=True)
        assert not layover.is_connection_safe(90, is_international=True)


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------


class TestFamilyProfile:
    def test_num_travelers(self) -> None:
        profile = FamilyProfile(
            travelers=[
                TravelerProfile(name="Ken"),
                TravelerProfile(name="Sue"),
                TravelerProfile(name="Kid1", is_minor=True),
            ]
        )
        assert profile.num_travelers == 3
        assert len(profile.adults) == 2
        assert len(profile.minors) == 1

    def test_passport_valid_for_trip(self) -> None:
        t = TravelerProfile(name="Ken", passport_expiry=date(2030, 12, 31))
        assert t.passport_valid_for_trip(date(2027, 3, 24))

    def test_passport_invalid_six_month_rule(self) -> None:
        # Passport expires 3 months after trip end — fails 6-month rule
        t = TravelerProfile(name="Ken", passport_expiry=date(2027, 6, 1))
        assert not t.passport_valid_for_trip(date(2027, 3, 24), buffer_months=6)

    def test_passports_expiring_before(self) -> None:
        profile = FamilyProfile(
            travelers=[
                TravelerProfile(name="Ken", passport_expiry=date(2026, 6, 1)),
                TravelerProfile(name="Sue", passport_expiry=date(2030, 1, 1)),
            ]
        )
        expiring = profile.passports_expiring_before(date(2027, 1, 1))
        assert len(expiring) == 1
        assert expiring[0].name == "Ken"

    def test_context_string(self) -> None:
        profile = FamilyProfile(
            travelers=[
                TravelerProfile(name="Ken", passport_expiry=date(2030, 5, 15)),
                TravelerProfile(name="Sue"),
            ]
        )
        ctx = profile.to_context_string()
        assert "Ken" in ctx
        assert "2030-05-15" in ctx
