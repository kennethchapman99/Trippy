"""TripLinker — fuzzy-matches parsed confirmations to existing trips/legs/stays."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from hermes_trip.db.models import Confirmation, ConfirmationType, Leg, Stay, Trip
from hermes_trip.ingest.parser import ParsedConfirmation

logger = logging.getLogger(__name__)

_DATE_WINDOW_DAYS = 3  # how many days off a date match can be
_FUZZY_THRESHOLD = 70  # rapidfuzz score (0–100)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    # Try ISO date prefix first, then full datetime
    date_part = val[:10]  # "YYYY-MM-DD"
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError:
        return None


def _dates_close(a: date | None, b: date | None) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).days) <= _DATE_WINDOW_DAYS


def _airport_match(conf_val: str | None, leg_val: str | None) -> bool:
    if not conf_val or not leg_val:
        return False
    return conf_val.upper().strip() == leg_val.upper().strip()


def _fuzzy_city_match(conf_val: str | None, db_val: str | None) -> bool:
    if not conf_val or not db_val:
        return False
    score = fuzz.token_set_ratio(conf_val.lower(), db_val.lower())
    return score >= _FUZZY_THRESHOLD


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class LinkResult:
    confirmation_id: int
    trip_id: int | None
    linked: bool
    method: str  # "flight_code" | "date_airport" | "date_city" | "unlinked"


# ---------------------------------------------------------------------------
# TripLinker
# ---------------------------------------------------------------------------


class TripLinker:
    """Match a ParsedConfirmation against trips in the DB and persist a Confirmation row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def link(
        self,
        parsed: ParsedConfirmation,
        raw_email_path: str | None = None,
    ) -> LinkResult:
        """Persist the confirmation and attempt to link it to a trip.

        Returns a LinkResult describing what happened.
        """
        trip_id, method = self._find_trip(parsed)

        conf = Confirmation(
            trip_id=trip_id,
            confirmation_type=ConfirmationType(parsed.confirmation_type),
            confirmation_code=parsed.confirmation_code,
            vendor=parsed.vendor,
            raw_email_path=raw_email_path,
            extracted_data=json.dumps(parsed.model_dump()),
            linked_at=datetime.utcnow() if trip_id is not None else None,
        )
        self._session.add(conf)
        self._session.flush()  # get the PK

        linked = trip_id is not None
        logger.info(
            "Confirmation %s → trip_id=%s (%s)", parsed.confirmation_code, trip_id, method
        )
        return LinkResult(
            confirmation_id=conf.id,
            trip_id=trip_id,
            linked=linked,
            method=method,
        )

    # ------------------------------------------------------------------
    # Private matching logic
    # ------------------------------------------------------------------

    def _find_trip(self, parsed: ParsedConfirmation) -> tuple[int | None, str]:
        trips: list[Trip] = self._session.query(Trip).all()
        if not trips:
            return None, "unlinked"

        # 1. Exact confirmation code match on legs/stays
        if parsed.confirmation_type == "flight":
            trip_id = self._match_by_flight_code(parsed, trips)
            if trip_id:
                return trip_id, "flight_code"

            trip_id = self._match_flight_by_dates_airports(parsed, trips)
            if trip_id:
                return trip_id, "date_airport"

        elif parsed.confirmation_type in ("hotel", "rental"):
            trip_id = self._match_stay_by_dates_city(parsed, trips)
            if trip_id:
                return trip_id, "date_city"

        # 2. Generic: does the confirmation date fall inside any trip window?
        trip_id = self._match_by_trip_window(parsed, trips)
        if trip_id:
            return trip_id, "trip_window"

        return None, "unlinked"

    def _match_by_flight_code(
        self, parsed: ParsedConfirmation, trips: list[Trip]
    ) -> int | None:
        code = parsed.confirmation_code.upper()
        for trip in trips:
            legs: list[Leg] = self._session.query(Leg).filter_by(trip_id=trip.id).all()
            for leg in legs:
                if leg.confirmation_code and leg.confirmation_code.upper() == code:
                    return trip.id
        return None

    def _match_flight_by_dates_airports(
        self, parsed: ParsedConfirmation, trips: list[Trip]
    ) -> int | None:
        depart = _parse_date(parsed.depart_at)
        if not depart:
            return None
        for trip in trips:
            legs = self._session.query(Leg).filter_by(trip_id=trip.id).all()
            for leg in legs:
                leg_depart = leg.depart_at.date() if leg.depart_at else None
                if not _dates_close(depart, leg_depart):
                    continue
                if _airport_match(parsed.origin, leg.origin) and _airport_match(
                    parsed.destination, leg.destination
                ):
                    return trip.id
        return None

    def _match_stay_by_dates_city(
        self, parsed: ParsedConfirmation, trips: list[Trip]
    ) -> int | None:
        check_in = _parse_date(parsed.check_in)
        if not check_in:
            return None
        for trip in trips:
            stays: list[Stay] = self._session.query(Stay).filter_by(trip_id=trip.id).all()
            for stay in stays:
                if not _dates_close(check_in, stay.check_in):
                    continue
                if _fuzzy_city_match(parsed.city, stay.city) or _fuzzy_city_match(
                    parsed.property_name, stay.property_name
                ):
                    return trip.id
        return None

    def _match_by_trip_window(
        self, parsed: ParsedConfirmation, trips: list[Trip]
    ) -> int | None:
        """Fall back: confirmation date within trip start–end window."""
        ref_date = _parse_date(parsed.depart_at or parsed.check_in)
        if not ref_date:
            return None
        for trip in trips:
            end = trip.end_date or trip.start_date
            if trip.start_date <= ref_date <= end:
                return trip.id
        return None


# ---------------------------------------------------------------------------
# Convenience function used by the CLI
# ---------------------------------------------------------------------------


def ingest_email(
    parsed: ParsedConfirmation,
    session: Session,
    raw_email_path: str | None = None,
) -> LinkResult:
    linker = TripLinker(session)
    result = linker.link(parsed, raw_email_path=raw_email_path)
    session.commit()
    return result


def load_confirmation_data(confirmation: Confirmation) -> dict[str, Any]:
    """Deserialize the extracted_data JSON blob."""
    if confirmation.extracted_data:
        return json.loads(confirmation.extracted_data)  # type: ignore[no-any-return]
    return {}
