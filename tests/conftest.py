"""Shared pytest fixtures."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from hermes_trip.db.models import (
    Base,
    Leg,
    LegType,
    Stay,
    StayType,
    Traveler,
    Trip,
    TripStatus,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    """In-memory SQLite engine with all tables created."""
    e = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def session(engine):  # type: ignore[no-untyped-def]
    """Session bound to in-memory DB."""
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as s:
        yield s


@pytest.fixture
def seeded_session(session: Session) -> Session:
    """Session pre-populated with seed.json data."""
    seed_path = FIXTURES_DIR / "seed.json"
    data = json.loads(seed_path.read_text())

    for trip_data in data["trips"]:
        trip = Trip(
            name=trip_data["name"],
            start_date=date.fromisoformat(trip_data["start_date"]),
            end_date=date.fromisoformat(trip_data["end_date"])
            if trip_data.get("end_date")
            else None,
            status=TripStatus(trip_data.get("status", "planned")),
            destination_summary=trip_data.get("destination_summary"),
        )
        session.add(trip)
        session.flush()

        for t in trip_data.get("travelers", []):
            traveler = Traveler(
                trip_id=trip.id,
                name=t["name"],
                passport_country=t.get("passport_country"),
                passport_expiry=date.fromisoformat(t["passport_expiry"])
                if t.get("passport_expiry")
                else None,
            )
            session.add(traveler)

        for leg_data in trip_data.get("legs", []):
            from datetime import datetime

            leg = Leg(
                trip_id=trip.id,
                leg_type=LegType(leg_data["leg_type"]),
                carrier=leg_data.get("carrier"),
                flight_number=leg_data.get("flight_number"),
                origin=leg_data["origin"],
                destination=leg_data["destination"],
                depart_at=datetime.fromisoformat(leg_data["depart_at"])
                if leg_data.get("depart_at")
                else None,
                arrive_at=datetime.fromisoformat(leg_data["arrive_at"])
                if leg_data.get("arrive_at")
                else None,
                cabin_class=leg_data.get("cabin_class"),
                cost_cad=leg_data.get("cost_cad"),
                confirmation_code=leg_data.get("confirmation_code"),
            )
            session.add(leg)

        for stay_data in trip_data.get("stays", []):
            stay = Stay(
                trip_id=trip.id,
                stay_type=StayType(stay_data["stay_type"]),
                property_name=stay_data["property_name"],
                city=stay_data.get("city"),
                country=stay_data.get("country"),
                check_in=date.fromisoformat(stay_data["check_in"])
                if stay_data.get("check_in")
                else None,
                check_out=date.fromisoformat(stay_data["check_out"])
                if stay_data.get("check_out")
                else None,
                cost_cad=stay_data.get("cost_cad"),
                confirmation_code=stay_data.get("confirmation_code"),
            )
            session.add(stay)

    session.commit()
    return session
