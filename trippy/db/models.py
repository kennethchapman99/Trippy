"""SQLAlchemy 2.x ORM models for Hermes Trip Agent."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TripStatus(enum.StrEnum):
    dream = "dream"
    planned = "planned"
    booked = "booked"
    lived = "lived"
    cancelled = "cancelled"


class LegType(enum.StrEnum):
    flight = "flight"
    train = "train"
    ferry = "ferry"
    bus = "bus"
    car = "car"
    other = "other"


class StayType(enum.StrEnum):
    hotel = "hotel"
    airbnb = "airbnb"
    vrbo = "vrbo"
    hostel = "hostel"
    house = "house"
    other = "other"


class ConfirmationType(enum.StrEnum):
    flight = "flight"
    hotel = "hotel"
    rental = "rental"
    tour = "tour"
    transfer = "transfer"
    other = "other"


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (UniqueConstraint("name", "start_date", name="uq_trip_name_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus), default=TripStatus.planned, nullable=False
    )
    destination_summary: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    travelers: Mapped[list[Traveler]] = relationship(
        "Traveler", back_populates="trip", cascade="all, delete-orphan"
    )
    legs: Mapped[list[Leg]] = relationship(
        "Leg", back_populates="trip", cascade="all, delete-orphan"
    )
    stays: Mapped[list[Stay]] = relationship(
        "Stay", back_populates="trip", cascade="all, delete-orphan"
    )
    confirmations: Mapped[list[Confirmation]] = relationship(
        "Confirmation", back_populates="trip", cascade="all, delete-orphan"
    )
    visa_checks: Mapped[list[VisaCheck]] = relationship(
        "VisaCheck", back_populates="trip", cascade="all, delete-orphan"
    )


class Traveler(Base):
    __tablename__ = "travelers"
    __table_args__ = (UniqueConstraint("trip_id", "name", name="uq_traveler_trip_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(Integer, ForeignKey("trips.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    passport_country: Mapped[str | None] = mapped_column(String(3))  # ISO 3166-1 alpha-3
    passport_expiry: Mapped[date | None] = mapped_column(Date)
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    trip: Mapped[Trip] = relationship("Trip", back_populates="travelers")
    visa_checks: Mapped[list[VisaCheck]] = relationship(
        "VisaCheck", back_populates="traveler", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        "Document", back_populates="traveler", cascade="all, delete-orphan"
    )


class Leg(Base):
    __tablename__ = "legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(Integer, ForeignKey("trips.id"), nullable=False)
    leg_type: Mapped[LegType] = mapped_column(Enum(LegType), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(100))
    flight_number: Mapped[str | None] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(10), nullable=False)  # IATA or city
    destination: Mapped[str] = mapped_column(String(10), nullable=False)
    depart_at: Mapped[datetime | None] = mapped_column(DateTime)
    arrive_at: Mapped[datetime | None] = mapped_column(DateTime)
    cabin_class: Mapped[str | None] = mapped_column(String(50))
    cost_cad: Mapped[float | None] = mapped_column(Float)
    confirmation_code: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    trip: Mapped[Trip] = relationship("Trip", back_populates="legs")
    confirmation: Mapped[Confirmation | None] = relationship(
        "Confirmation",
        primaryjoin="and_(Leg.confirmation_code == foreign(Confirmation.confirmation_code),"
        " Leg.trip_id == foreign(Confirmation.trip_id))",
        viewonly=True,
        uselist=False,
    )


class Stay(Base):
    __tablename__ = "stays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(Integer, ForeignKey("trips.id"), nullable=False)
    stay_type: Mapped[StayType] = mapped_column(Enum(StayType), nullable=False)
    property_name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    check_in: Mapped[date | None] = mapped_column(Date)
    check_out: Mapped[date | None] = mapped_column(Date)
    cost_cad: Mapped[float | None] = mapped_column(Float)
    confirmation_code: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    trip: Mapped[Trip] = relationship("Trip", back_populates="stays")


class Confirmation(Base):
    __tablename__ = "confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("trips.id"), nullable=True)
    confirmation_type: Mapped[ConfirmationType] = mapped_column(
        Enum(ConfirmationType), nullable=False
    )
    confirmation_code: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(200))
    raw_email_path: Mapped[str | None] = mapped_column(String(500))
    extracted_data: Mapped[str | None] = mapped_column(Text)  # JSON blob
    linked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    trip: Mapped[Trip | None] = relationship("Trip", back_populates="confirmations")


class Preference(Base):
    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # seat, hotel, food, etc.
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_trip_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("trips.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class VisaCheck(Base):
    __tablename__ = "visa_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(Integer, ForeignKey("trips.id"), nullable=False)
    traveler_id: Mapped[int] = mapped_column(Integer, ForeignKey("travelers.id"), nullable=False)
    destination_country: Mapped[str] = mapped_column(String(3), nullable=False)  # ISO alpha-3
    passport_country: Mapped[str] = mapped_column(String(3), nullable=False)
    visa_required: Mapped[bool | None] = mapped_column(nullable=True)
    visa_type: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    data_source: Mapped[str] = mapped_column(String(50), default="static")

    trip: Mapped[Trip] = relationship("Trip", back_populates="visa_checks")
    traveler: Mapped[Traveler] = relationship("Traveler", back_populates="visa_checks")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    traveler_id: Mapped[int] = mapped_column(Integer, ForeignKey("travelers.id"), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)  # passport, visa, etc.
    file_path: Mapped[str | None] = mapped_column(String(500))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    traveler: Mapped[Traveler] = relationship("Traveler", back_populates="documents")
