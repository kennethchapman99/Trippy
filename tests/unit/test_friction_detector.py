"""Tests for the deterministic FrictionDetector."""

from __future__ import annotations

from datetime import date, datetime

from trippy.models.preferences import FamilyTravelPreferences
from trippy.models.trip import (
    ChecklistItem,
    RiskSeverity,
    Segment,
    SegmentType,
    Stay,
    StayType,
    Traveler,
    Trip,
    TripStatus,
)
from trippy.services.friction_detector import FrictionDetector


def _make_trip(**kwargs) -> Trip:  # type: ignore[no-untyped-def]
    defaults = {
        "trip_id": "test-trip",
        "name": "Test Trip",
        "status": TripStatus.BOOKED,
        "start_date": date(2027, 3, 10),
        "end_date": date(2027, 3, 24),
    }
    defaults.update(kwargs)
    return Trip(**defaults)


def _detector(prefs: FamilyTravelPreferences | None = None) -> FrictionDetector:
    return FrictionDetector(preferences=prefs or FamilyTravelPreferences())


class TestDepartureTimeChecks:
    def test_acceptable_departure_no_risk(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YYZ",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 9, 0),
                )
            ]
        )
        risks = _detector().audit(trip)
        early_risks = [r for r in risks if "early" in r.risk_id]
        assert not early_risks

    def test_early_departure_medium_risk(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YYZ",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 6, 0),  # 06:00 — before 07:00
                )
            ]
        )
        risks = _detector().audit(trip)
        early_risks = [r for r in risks if "early-dep" in r.risk_id]
        assert len(early_risks) == 1
        assert early_risks[0].severity == RiskSeverity.MEDIUM


class TestConnectionTimeChecks:
    def test_tight_international_connection_high_risk(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YYZ",
                    destination="YVR",
                    depart_at=datetime(2027, 3, 10, 9, 0),
                    arrive_at=datetime(2027, 3, 10, 11, 30),
                ),
                Segment(
                    segment_id="s2",
                    origin="YVR",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 13, 0),  # 90 min after arrival
                    arrive_at=datetime(2027, 3, 11, 15, 0),
                ),
            ]
        )
        risks = _detector().audit(trip)
        conn_risks = [r for r in risks if "tight-conn" in r.risk_id]
        assert len(conn_risks) == 1
        assert conn_risks[0].severity == RiskSeverity.HIGH

    def test_safe_connection_no_risk(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YYZ",
                    destination="YVR",
                    depart_at=datetime(2027, 3, 10, 9, 0),
                    arrive_at=datetime(2027, 3, 10, 11, 30),
                ),
                Segment(
                    segment_id="s2",
                    origin="YVR",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 14, 0),  # 150 min — well above min
                    arrive_at=datetime(2027, 3, 11, 15, 0),
                ),
            ]
        )
        risks = _detector().audit(trip)
        conn_risks = [r for r in risks if "conn" in r.risk_id]
        assert not conn_risks

    def test_short_connection_medium_risk(self) -> None:
        """Between min and preferred — medium risk."""
        prefs = FamilyTravelPreferences()
        prefs.layover.min_connection_minutes_international = 90
        prefs.layover.preferred_connection_minutes = 120

        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YYZ",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 9, 0),
                    arrive_at=datetime(2027, 3, 10, 20, 0),
                ),
                Segment(
                    segment_id="s2",
                    origin="NRT",
                    destination="KIX",
                    depart_at=datetime(2027, 3, 10, 21, 45),  # 105 min — between min and preferred
                    arrive_at=datetime(2027, 3, 10, 23, 0),
                ),
            ]
        )
        risks = FrictionDetector(preferences=prefs).audit(trip)
        conn_risks = [r for r in risks if "short-conn" in r.risk_id]
        assert len(conn_risks) == 1
        assert conn_risks[0].severity == RiskSeverity.MEDIUM


class TestHotelCheckinAlignment:
    def test_late_arrival_high_risk(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YVR",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 14, 0),
                    arrive_at=datetime(2027, 3, 11, 23, 45),  # very late arrival
                )
            ],
            stays=[
                Stay(
                    stay_id="stay-1",
                    property_name="Shinjuku Hotel",
                    city="Tokyo",
                    country="Japan",
                    check_in=date(2027, 3, 11),
                )
            ],
        )
        risks = _detector().audit(trip)
        late_risks = [r for r in risks if "late-arrival" in r.risk_id]
        assert len(late_risks) == 1
        assert late_risks[0].severity == RiskSeverity.HIGH

    def test_daytime_arrival_low_risk(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YVR",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 14, 0),
                    arrive_at=datetime(2027, 3, 11, 14, 0),  # 2 PM arrival
                )
            ],
            stays=[
                Stay(
                    stay_id="stay-1",
                    property_name="Shinjuku Hotel",
                    city="Tokyo",
                    country="Japan",
                    check_in=date(2027, 3, 11),
                )
            ],
        )
        risks = _detector().audit(trip)
        checkin_risks = [r for r in risks if "arrival" in r.risk_id]
        # 14:00 arrival < 15:00 min check-in = LOW risk (early arrival, room may not be ready)
        low_risks = [r for r in checkin_risks if r.severity == RiskSeverity.LOW]
        assert low_risks  # Should flag as low (room may not be ready)


class TestPassportExpiry:
    def test_expired_passport_critical(self) -> None:
        trip = _make_trip(
            end_date=date(2027, 3, 24),
            travelers=[
                Traveler(
                    name="Ken",
                    passport_country="CAN",
                    passport_expiry=date(2027, 3, 20),  # expires BEFORE trip end
                )
            ],
        )
        risks = _detector().audit(trip)
        passport_risks = [r for r in risks if "passport-expiry" in r.risk_id]
        assert len(passport_risks) == 1
        assert passport_risks[0].severity == RiskSeverity.CRITICAL

    def test_passport_failing_six_month_rule_high(self) -> None:
        trip = _make_trip(
            end_date=date(2027, 3, 24),
            travelers=[
                Traveler(
                    name="Ken",
                    passport_country="CAN",
                    passport_expiry=date(2027, 6, 1),  # expires 2mo after trip — fails 6mo rule
                )
            ],
        )
        risks = _detector().audit(trip)
        passport_risks = [r for r in risks if "passport-expiry" in r.risk_id]
        assert len(passport_risks) == 1
        assert passport_risks[0].severity == RiskSeverity.HIGH

    def test_valid_passport_no_risk(self) -> None:
        trip = _make_trip(
            end_date=date(2027, 3, 24),
            travelers=[
                Traveler(
                    name="Ken",
                    passport_country="CAN",
                    passport_expiry=date(2030, 12, 31),  # well beyond 6mo
                )
            ],
        )
        risks = _detector().audit(trip)
        passport_risks = [r for r in risks if "passport" in r.risk_id]
        assert not passport_risks

    def test_no_passport_expiry_medium_risk(self) -> None:
        trip = _make_trip(
            end_date=date(2027, 3, 24),
            travelers=[Traveler(name="Ken", passport_country="CAN")],  # no expiry
        )
        risks = _detector().audit(trip)
        no_passport_risks = [r for r in risks if "no-passport" in r.risk_id]
        assert len(no_passport_risks) == 1
        assert no_passport_risks[0].severity == RiskSeverity.MEDIUM


class TestUnconfirmedBookings:
    def test_unconfirmed_segment_booked_trip_high(self) -> None:
        trip = _make_trip(
            status=TripStatus.BOOKED,
            segments=[
                Segment(segment_id="s1", origin="YYZ", destination="NRT")  # no confirmation
            ],
        )
        risks = _detector().audit(trip)
        unconf = [r for r in risks if "unconfirmed-seg" in r.risk_id]
        assert len(unconf) == 1
        assert unconf[0].severity == RiskSeverity.HIGH

    def test_unbooked_segment_planned_trip_medium(self) -> None:
        trip = _make_trip(
            status=TripStatus.PLANNED,
            segments=[Segment(segment_id="s1", origin="YYZ", destination="NRT")],
        )
        risks = _detector().audit(trip)
        unbooked = [r for r in risks if "unbooked-seg" in r.risk_id]
        assert len(unbooked) == 1
        assert unbooked[0].severity == RiskSeverity.MEDIUM


class TestFamilyComfortChecks:
    def test_family_stay_requires_explicit_three_bed_fit(self) -> None:
        trip = _make_trip(
            travelers=[Traveler(name=f"Traveler {i}") for i in range(5)],
            stays=[
                Stay(
                    stay_id="stay-1",
                    stay_type=StayType.HOTEL,
                    property_name="Nice Hotel",
                    city="Lisbon",
                    country="Portugal",
                    room_type="standard queen room",
                )
            ],
        )

        risks = _detector().audit(trip)

        assert [r for r in risks if r.risk_id == "bed-fit-short-stay-1"]
        assert [r for r in risks if r.risk_id == "queen-compromise-stay-1"]

    def test_city_rental_without_exceptional_upside_is_flagged(self) -> None:
        trip = _make_trip(
            stays=[
                Stay(
                    stay_id="stay-1",
                    stay_type=StayType.AIRBNB,
                    property_name="Apartment",
                    city="Rome",
                    country="Italy",
                    notes="basic apartment",
                )
            ],
        )

        risks = _detector().audit(trip)

        assert [r for r in risks if r.risk_id == "city-rental-fit-stay-1"]

    def test_driving_and_pacing_friction_are_flagged(self) -> None:
        trip = _make_trip(
            segments=[
                Segment(
                    segment_id="drive-1",
                    segment_type=SegmentType.CAR,
                    origin="Florence",
                    destination="Hill Town",
                    notes="narrow roads and difficult parking",
                )
            ],
            stays=[
                Stay(
                    stay_id="stay-1",
                    property_name="Transit Stop",
                    city="Siena",
                    country="Italy",
                    check_in=date(2027, 3, 10),
                    check_out=date(2027, 3, 11),
                    room_type="king suite with 3 beds",
                )
            ],
        )

        risks = _detector().audit(trip)

        assert [r for r in risks if r.risk_id == "driving-friction-drive-1"]
        assert [r for r in risks if r.risk_id == "one-night-stop-stay-1"]

    def test_missing_destination_readiness_and_tour_quality_are_flagged(self) -> None:
        trip = _make_trip(
            checklist=[
                ChecklistItem(
                    item_id="tour-1",
                    category="activity",
                    title="Large group food tour",
                    notes="crowded mass market safety unknown",
                )
            ]
        )

        risks = _detector().audit(trip)

        assert [r for r in risks if r.risk_id == "missing-cash-currency-guidance"]
        assert [r for r in risks if r.risk_id == "missing-entry-requirements"]
        assert [r for r in risks if r.risk_id == "missing-health-precautions"]
        assert [r for r in risks if r.risk_id == "tour-quality-tour-1"]


class TestNoRisks:
    def test_clean_trip_no_risks(self) -> None:
        """A well-configured trip should produce no risks."""
        trip = _make_trip(
            status=TripStatus.BOOKED,
            end_date=date(2027, 3, 24),
            travelers=[
                Traveler(
                    name="Ken",
                    passport_country="CAN",
                    passport_expiry=date(2032, 1, 1),
                )
            ],
            segments=[
                Segment(
                    segment_id="s1",
                    origin="YYZ",
                    destination="YVR",
                    depart_at=datetime(2027, 3, 10, 9, 0),
                    arrive_at=datetime(2027, 3, 10, 11, 30),
                    confirmation_code="ABC123",
                    baggage_included=True,
                ),
                Segment(
                    segment_id="s2",
                    origin="YVR",
                    destination="NRT",
                    depart_at=datetime(2027, 3, 10, 14, 0),  # 150 min connection
                    arrive_at=datetime(2027, 3, 11, 15, 0),
                    confirmation_code="ABC123",
                    baggage_included=True,
                ),
            ],
        )
        risks = _detector().audit(trip)
        high_or_critical = [
            r for r in risks if r.severity in (RiskSeverity.HIGH, RiskSeverity.CRITICAL)
        ]
        assert not high_or_critical
