"""Unit tests for SQLAlchemy models."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trippy.db.models import (
    Confirmation,
    ConfirmationType,
    Document,
    Leg,
    LegType,
    Stay,
    StayType,
    Traveler,
    Trip,
    TripStatus,
    VisaCheck,
)


def make_trip(session: Session, name: str = "Test Trip", start: str = "2026-06-01") -> Trip:
    trip = Trip(name=name, start_date=date.fromisoformat(start), status=TripStatus.planned)
    session.add(trip)
    session.flush()
    return trip


class TestTripModel:
    def test_create_minimal(self, session: Session) -> None:
        trip = make_trip(session)
        assert trip.id is not None
        assert trip.status == TripStatus.planned

    def test_natural_key_unique(self, session: Session) -> None:
        make_trip(session, name="Dupe", start="2026-01-01")
        session.commit()
        with pytest.raises(IntegrityError):
            make_trip(session, name="Dupe", start="2026-01-01")
            session.commit()

    def test_different_start_date_allowed(self, session: Session) -> None:
        make_trip(session, name="Same Name", start="2026-01-01")
        make_trip(session, name="Same Name", start="2027-01-01")
        session.commit()
        result = session.execute(select(Trip).where(Trip.name == "Same Name")).scalars().all()
        assert len(result) == 2

    def test_cascade_delete_travelers(self, session: Session) -> None:
        trip = make_trip(session)
        t = Traveler(trip_id=trip.id, name="Alice", passport_country="CAN")
        session.add(t)
        session.commit()
        session.delete(trip)
        session.commit()
        assert session.get(Traveler, t.id) is None

    def test_cascade_delete_legs(self, session: Session) -> None:
        trip = make_trip(session)
        leg = Leg(trip_id=trip.id, leg_type=LegType.flight, origin="YYZ", destination="NRT")
        session.add(leg)
        session.commit()
        session.delete(trip)
        session.commit()
        assert session.get(Leg, leg.id) is None

    def test_cascade_delete_stays(self, session: Session) -> None:
        trip = make_trip(session)
        stay = Stay(
            trip_id=trip.id,
            stay_type=StayType.hotel,
            property_name="Grand Hotel",
            city="Tokyo",
        )
        session.add(stay)
        session.commit()
        session.delete(trip)
        session.commit()
        assert session.get(Stay, stay.id) is None

    def test_cascade_delete_confirmations(self, session: Session) -> None:
        trip = make_trip(session)
        conf = Confirmation(
            trip_id=trip.id,
            confirmation_type=ConfirmationType.flight,
            confirmation_code="ABC123",
        )
        session.add(conf)
        session.commit()
        session.delete(trip)
        session.commit()
        assert session.get(Confirmation, conf.id) is None


class TestTravelerModel:
    def test_unique_name_within_trip(self, session: Session) -> None:
        trip = make_trip(session)
        session.add(Traveler(trip_id=trip.id, name="Ken", passport_country="CAN"))
        session.commit()
        with pytest.raises(IntegrityError):
            session.add(Traveler(trip_id=trip.id, name="Ken", passport_country="CAN"))
            session.commit()

    def test_same_name_different_trip_ok(self, session: Session) -> None:
        trip1 = make_trip(session, name="Trip A", start="2026-01-01")
        trip2 = make_trip(session, name="Trip B", start="2026-06-01")
        session.add(Traveler(trip_id=trip1.id, name="Ken"))
        session.add(Traveler(trip_id=trip2.id, name="Ken"))
        session.commit()

    def test_cascade_delete_documents(self, session: Session) -> None:
        trip = make_trip(session)
        traveler = Traveler(trip_id=trip.id, name="Ken")
        session.add(traveler)
        session.flush()
        doc = Document(traveler_id=traveler.id, doc_type="passport")
        session.add(doc)
        session.commit()
        session.delete(traveler)
        session.commit()
        assert session.get(Document, doc.id) is None


class TestRelationships:
    def test_trip_travelers_relationship(self, session: Session) -> None:
        trip = make_trip(session)
        for name in ["Ken", "Sarah", "Emma", "Liam", "Olivia"]:
            session.add(Traveler(trip_id=trip.id, name=name))
        session.commit()
        session.refresh(trip)
        assert len(trip.travelers) == 5

    def test_trip_legs_and_stays(self, session: Session) -> None:
        trip = make_trip(session)
        session.add(Leg(trip_id=trip.id, leg_type=LegType.flight, origin="YYZ", destination="CDG"))
        session.add(Stay(trip_id=trip.id, stay_type=StayType.hotel, property_name="Hotel Paris"))
        session.commit()
        session.refresh(trip)
        assert len(trip.legs) == 1
        assert len(trip.stays) == 1

    def test_traveler_visa_checks(self, session: Session) -> None:
        trip = make_trip(session)
        traveler = Traveler(trip_id=trip.id, name="Ken", passport_country="CAN")
        session.add(traveler)
        session.flush()
        vc = VisaCheck(
            trip_id=trip.id,
            traveler_id=traveler.id,
            destination_country="JPN",
            passport_country="CAN",
        )
        session.add(vc)
        session.commit()
        session.refresh(traveler)
        assert len(traveler.visa_checks) == 1


class TestSeedData:
    def test_seeded_session_has_two_trips(self, seeded_session: Session) -> None:
        trips = seeded_session.execute(select(Trip)).scalars().all()
        assert len(trips) == 2

    def test_japan_trip_has_five_travelers(self, seeded_session: Session) -> None:
        trip = seeded_session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
        assert len(trip.travelers) == 5

    def test_japan_trip_has_leg_and_stay(self, seeded_session: Session) -> None:
        trip = seeded_session.execute(select(Trip).where(Trip.name == "Japan 2026")).scalar_one()
        assert len(trip.legs) == 1
        assert trip.legs[0].origin == "YYZ"
        assert len(trip.stays) == 1
