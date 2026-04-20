"""Proactive friction and risk detection for trip plans.

All checks are deterministic and rule-based — no LLM required.
The agent uses this output as context for its reasoning.

Risk severity:
- CRITICAL: trip-blocking (passport expired, no confirmed transport)
- HIGH: likely significant disruption (tight connection for family)
- MEDIUM: friction to resolve (early departure, missing seats)
- LOW: housekeeping / advisory
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from trippy.models.trip import RiskFlag, RiskSeverity, Segment, Trip

if TYPE_CHECKING:
    from trippy.models.preferences import FamilyTravelPreferences

logger = logging.getLogger(__name__)

# Default thresholds (overridden by preferences when provided)
_DEFAULT_MIN_CONNECTION_DOMESTIC = 75  # minutes
_DEFAULT_MIN_CONNECTION_INTL = 110  # minutes
_DEFAULT_PREFERRED_CONNECTION = 120  # minutes
_DEFAULT_MAX_LAYOVER_HOURS = 4.0
_DEFAULT_EARLIEST_DEPARTURE = "07:00"
_DEFAULT_AIRPORT_BUFFER_INTL = 180  # minutes
_DEFAULT_MIN_CHECKIN_HOUR = 15  # 3 PM

# IATA codes for international connections (incomplete but useful heuristic)
_INTL_HUB_CODES = {
    "YYZ",
    "YVR",
    "YUL",
    "ORD",
    "LAX",
    "JFK",
    "EWR",
    "SFO",
    "LHR",
    "CDG",
    "AMS",
    "FRA",
    "DXB",
    "HND",
    "NRT",
    "ICN",
    "SIN",
    "BKK",
    "SYD",
}


def _hm(time_str: str) -> tuple[int, int]:
    h, m = time_str.split(":")
    return int(h), int(m)


def _is_international_connection(origin: str, destination: str) -> bool:
    return origin.upper() in _INTL_HUB_CODES or destination.upper() in _INTL_HUB_CODES


class FrictionDetector:
    """Audits a canonical Trip for timing risks and friction points."""

    def __init__(self, preferences: FamilyTravelPreferences | None = None) -> None:
        self._prefs = preferences

    # ------------------------------------------------------------------
    # Thresholds (from preferences or defaults)
    # ------------------------------------------------------------------

    @property
    def _min_conn_domestic(self) -> int:
        if self._prefs:
            return self._prefs.layover.min_connection_minutes_domestic
        return _DEFAULT_MIN_CONNECTION_DOMESTIC

    @property
    def _min_conn_intl(self) -> int:
        if self._prefs:
            return self._prefs.layover.min_connection_minutes_international
        return _DEFAULT_MIN_CONNECTION_INTL

    @property
    def _preferred_conn(self) -> int:
        if self._prefs:
            return self._prefs.layover.preferred_connection_minutes
        return _DEFAULT_PREFERRED_CONNECTION

    @property
    def _max_layover_hours(self) -> float:
        if self._prefs:
            return self._prefs.layover.max_layover_hours_no_hotel
        return _DEFAULT_MAX_LAYOVER_HOURS

    @property
    def _earliest_departure(self) -> str:
        if self._prefs:
            return self._prefs.departure_time.earliest_acceptable
        return _DEFAULT_EARLIEST_DEPARTURE

    @property
    def _min_checkin_hour(self) -> int:
        if self._prefs:
            return self._prefs.stay.min_checkin_hour
        return _DEFAULT_MIN_CHECKIN_HOUR

    # ------------------------------------------------------------------
    # Main audit
    # ------------------------------------------------------------------

    def audit(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        risks.extend(self._check_departure_times(trip))
        risks.extend(self._check_connection_times(trip))
        risks.extend(self._check_long_layovers(trip))
        risks.extend(self._check_hotel_checkin_alignment(trip))
        risks.extend(self._check_unconfirmed_segments(trip))
        risks.extend(self._check_unconfirmed_stays(trip))
        risks.extend(self._check_passport_expiry(trip))
        risks.extend(self._check_missing_bags(trip))

        logger.info("FrictionDetector: %d risk(s) found for trip %r", len(risks), trip.trip_id)
        return risks

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_departure_times(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        min_h, min_m = _hm(self._earliest_departure)
        for seg in trip.segments:
            if not seg.depart_at:
                continue
            dh, dm = seg.depart_at.hour, seg.depart_at.minute
            if (dh, dm) < (min_h, min_m):
                risks.append(
                    RiskFlag(
                        risk_id=f"early-dep-{seg.segment_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="timing",
                        description=(
                            f"Segment {seg.segment_id} ({seg.origin}→{seg.destination}) "
                            f"departs at {dh:02d}:{dm:02d}, before preferred earliest "
                            f"{self._earliest_departure}. Family of 5 with kids — "
                            "consider later option."
                        ),
                        affected_ids=[seg.segment_id],
                        recommended_fix=f"Look for alternatives departing after {self._earliest_departure}",
                    )
                )
        return risks

    def _check_connection_times(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        segs = sorted(
            [s for s in trip.segments if s.arrive_at and s.depart_at],
            key=lambda s: s.depart_at,  # type: ignore[arg-type, return-value]
        )
        for i in range(len(segs) - 1):
            arrive = segs[i].arrive_at
            depart = segs[i + 1].depart_at
            if arrive is None or depart is None:
                continue
            if depart <= arrive:
                continue

            gap_min = int((depart - arrive).total_seconds() / 60)
            via = segs[i].destination
            is_intl = _is_international_connection(segs[i].destination, segs[i + 1].origin)
            min_req = self._min_conn_intl if is_intl else self._min_conn_domestic

            if gap_min < min_req:
                risks.append(
                    RiskFlag(
                        risk_id=f"tight-conn-{segs[i].segment_id}-{segs[i + 1].segment_id}",
                        severity=RiskSeverity.HIGH,
                        category="layover",
                        description=(
                            f"Connection in {via}: {gap_min} min "
                            f"({'international' if is_intl else 'domestic'}). "
                            f"Minimum for family of 5 with bags: {min_req} min. "
                            f"This connection is {min_req - gap_min} min short."
                        ),
                        affected_ids=[segs[i].segment_id, segs[i + 1].segment_id],
                        recommended_fix=(
                            f"Find an itinerary with ≥{self._preferred_conn} min in {via}, "
                            "or confirm family can make this connection stress-free."
                        ),
                    )
                )
            elif gap_min < self._preferred_conn:
                risks.append(
                    RiskFlag(
                        risk_id=f"short-conn-{segs[i].segment_id}-{segs[i + 1].segment_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="layover",
                        description=(
                            f"Connection in {via}: {gap_min} min (above minimum but below "
                            f"preferred {self._preferred_conn} min for family travel)."
                        ),
                        affected_ids=[segs[i].segment_id, segs[i + 1].segment_id],
                        recommended_fix=f"Acceptable but keep an eye on delays. Preferred: {self._preferred_conn} min.",
                    )
                )
        return risks

    def _check_long_layovers(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        segs = sorted(
            [s for s in trip.segments if s.arrive_at and s.depart_at],
            key=lambda s: s.depart_at,  # type: ignore[arg-type, return-value]
        )
        for i in range(len(segs) - 1):
            arrive = segs[i].arrive_at
            depart = segs[i + 1].depart_at
            if arrive is None or depart is None:
                continue
            gap_h = (depart - arrive).total_seconds() / 3600
            if gap_h > self._max_layover_hours:
                via = segs[i].destination
                risks.append(
                    RiskFlag(
                        risk_id=f"long-layover-{segs[i].segment_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="layover",
                        description=(
                            f"Layover in {via}: {gap_h:.1f}h (>{self._max_layover_hours}h). "
                            "Family of 5 — consider if airport hotel or lounge access is needed."
                        ),
                        affected_ids=[segs[i].segment_id, segs[i + 1].segment_id],
                        recommended_fix="Book airport hotel if > 8h overnight, or confirm lounge access.",
                    )
                )
        return risks

    def _check_hotel_checkin_alignment(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        for stay in trip.stays:
            if not stay.check_in:
                continue
            # Find flight arriving on check-in day
            arrival_seg = self._find_arrival_on_date(trip, stay.check_in)
            if arrival_seg and arrival_seg.arrive_at:
                arrival_hour = arrival_seg.arrive_at.hour
                if arrival_hour >= 23:
                    risks.append(
                        RiskFlag(
                            risk_id=f"late-arrival-{stay.stay_id}",
                            severity=RiskSeverity.HIGH,
                            category="timing",
                            description=(
                                f"Flight arrives at {arrival_hour:02d}:{arrival_seg.arrive_at.minute:02d} "
                                f"but hotel check-in for {stay.property_name} is {stay.check_in}. "
                                "Late arrival — confirm hotel accepts check-in after 23:00."
                            ),
                            affected_ids=[arrival_seg.segment_id, stay.stay_id],
                            recommended_fix="Call hotel to confirm late check-in or book late-check-in guarantee.",
                        )
                    )
                elif arrival_hour < self._min_checkin_hour:
                    risks.append(
                        RiskFlag(
                            risk_id=f"early-arrival-{stay.stay_id}",
                            severity=RiskSeverity.LOW,
                            category="timing",
                            description=(
                                f"Flight arrives at {arrival_hour:02d}:00 but hotel standard "
                                f"check-in is {self._min_checkin_hour:02d}:00. "
                                "Rooms may not be ready — plan for luggage storage or early check-in fee."
                            ),
                            affected_ids=[arrival_seg.segment_id, stay.stay_id],
                            recommended_fix="Request early check-in (often free if room available) or pay for guaranteed early access.",
                        )
                    )
        return risks

    def _check_unconfirmed_segments(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        for seg in trip.unconfirmed_segments:
            if trip.status.value == "booked":
                risks.append(
                    RiskFlag(
                        risk_id=f"unconfirmed-seg-{seg.segment_id}",
                        severity=RiskSeverity.HIGH,
                        category="missing_booking",
                        description=(
                            f"Trip is marked 'booked' but segment {seg.segment_id} "
                            f"({seg.origin}→{seg.destination}) has no confirmation code."
                        ),
                        affected_ids=[seg.segment_id],
                        recommended_fix="Add confirmation code or re-check Gmail for booking email.",
                    )
                )
            elif trip.status.value == "planned":
                risks.append(
                    RiskFlag(
                        risk_id=f"unbooked-seg-{seg.segment_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="missing_booking",
                        description=(
                            f"Segment {seg.segment_id} ({seg.origin}→{seg.destination}) "
                            "not yet booked."
                        ),
                        affected_ids=[seg.segment_id],
                        recommended_fix="Book this flight and add confirmation code.",
                    )
                )
        return risks

    def _check_unconfirmed_stays(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        for stay in trip.unconfirmed_stays:
            if trip.status.value == "booked":
                risks.append(
                    RiskFlag(
                        risk_id=f"unconfirmed-stay-{stay.stay_id}",
                        severity=RiskSeverity.HIGH,
                        category="missing_booking",
                        description=(
                            f"Trip is 'booked' but {stay.property_name} ({stay.city}) "
                            "has no confirmation code."
                        ),
                        affected_ids=[stay.stay_id],
                        recommended_fix="Find and add hotel confirmation code.",
                    )
                )
        return risks

    def _check_passport_expiry(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        if not trip.end_date:
            return risks
        required_expiry = trip.end_date + timedelta(days=180)  # 6-month rule
        for traveler in trip.travelers:
            if not traveler.passport_expiry:
                risks.append(
                    RiskFlag(
                        risk_id=f"no-passport-{traveler.name.lower().replace(' ', '-')}",
                        severity=RiskSeverity.MEDIUM,
                        category="document",
                        description=f"{traveler.name}: no passport expiry date on file.",
                        affected_ids=[],
                        recommended_fix=f"Add {traveler.name}'s passport expiry to profile.",
                    )
                )
            elif traveler.passport_expiry < required_expiry:
                days_short = (required_expiry - traveler.passport_expiry).days
                sev = (
                    RiskSeverity.CRITICAL
                    if traveler.passport_expiry < trip.end_date
                    else RiskSeverity.HIGH
                )
                risks.append(
                    RiskFlag(
                        risk_id=f"passport-expiry-{traveler.name.lower().replace(' ', '-')}",
                        severity=sev,
                        category="document",
                        description=(
                            f"{traveler.name}'s passport expires {traveler.passport_expiry} "
                            f"({days_short} days short of the 6-month rule for trip end {trip.end_date})."
                        ),
                        affected_ids=[],
                        recommended_fix=f"Renew {traveler.name}'s passport before this trip.",
                    )
                )
        return risks

    def _check_missing_bags(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        for seg in trip.segments:
            if seg.baggage_included is None:
                risks.append(
                    RiskFlag(
                        risk_id=f"baggage-unknown-{seg.segment_id}",
                        severity=RiskSeverity.LOW,
                        category="logistics",
                        description=(
                            f"Segment {seg.segment_id} ({seg.origin}→{seg.destination}): "
                            "baggage inclusion not confirmed. Family of 5 needs checked bags."
                        ),
                        affected_ids=[seg.segment_id],
                        recommended_fix="Confirm checked bag allowance and add bags to booking if needed.",
                    )
                )
        return risks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_arrival_on_date(self, trip: Trip, check_date: date) -> Segment | None:
        for seg in trip.segments:
            if seg.arrive_at and seg.arrive_at.date() == check_date:
                return seg
        return None
