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
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from trippy.models.trip import RiskFlag, RiskSeverity, Segment, SegmentType, Stay, StayType, Trip

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
        risks.extend(self._check_family_sleeping_fit(trip))
        risks.extend(self._check_lodging_context(trip))
        risks.extend(self._check_driving_and_parking_friction(trip))
        risks.extend(self._check_pacing(trip))
        risks.extend(self._check_destination_readiness(trip))
        risks.extend(self._check_country_priors(trip))
        risks.extend(self._check_tour_quality_signals(trip))
        risks.extend(self._check_too_many_moves(trip))

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

    def _check_family_sleeping_fit(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        if len(trip.travelers) < 5:
            return risks
        min_beds = self._prefs.stay.min_beds_for_family if self._prefs else 3
        for stay in trip.stays:
            text = _stay_text(stay)
            bed_count = _bed_count(text)
            if bed_count is None:
                risks.append(
                    RiskFlag(
                        risk_id=f"bed-fit-unknown-{stay.stay_id}",
                        severity=RiskSeverity.HIGH,
                        category="lodging",
                        description=(
                            f"{stay.property_name} does not clearly document bed count. "
                            f"Family of 5 needs an explicit sleeping setup with at least {min_beds} beds."
                        ),
                        affected_ids=[stay.stay_id],
                        recommended_fix=(
                            "Confirm exact bed layout before booking; reject options that cannot verify "
                            f"{min_beds}+ beds."
                        ),
                    )
                )
            elif bed_count < min_beds:
                risks.append(
                    RiskFlag(
                        risk_id=f"bed-fit-short-{stay.stay_id}",
                        severity=RiskSeverity.HIGH,
                        category="lodging",
                        description=(
                            f"{stay.property_name} appears to have {bed_count} bed(s), below the "
                            f"family minimum of {min_beds}."
                        ),
                        affected_ids=[stay.stay_id],
                        recommended_fix=f"Find a property with at least {min_beds} beds or book two rooms.",
                    )
                )

            if (
                (self._prefs is None or self._prefs.stay.queen_requires_compelling_upside)
                and "queen" in text
                and "king" not in text
                and not _has_compelling_lodging_upside(text)
            ):
                risks.append(
                    RiskFlag(
                        risk_id=f"queen-compromise-{stay.stay_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="lodging",
                        description=(
                            f"{stay.property_name} appears to rely on queen bed(s) without a clear "
                            "offsetting benefit. King bed is strongly preferred for the primary adults."
                        ),
                        affected_ids=[stay.stay_id],
                        recommended_fix="Prefer a king-bed option unless this property has exceptional location, space, or value.",
                    )
                )
        return risks

    def _check_lodging_context(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        for stay in trip.stays:
            text = _stay_text(stay)
            if _looks_like_city_stay(stay):
                if any(
                    term in text for term in ("suburb", "outside city", "airport hotel", "remote")
                ):
                    risks.append(
                        RiskFlag(
                            risk_id=f"non-central-city-lodging-{stay.stay_id}",
                            severity=RiskSeverity.MEDIUM,
                            category="lodging",
                            description=(
                                f"{stay.property_name} has non-central location signals. "
                                "For city stays, the family strongly prefers walkable urban-core lodging."
                            ),
                            affected_ids=[stay.stay_id],
                            recommended_fix="Compare against central boutique hotels before accepting transit burden.",
                        )
                    )
                if stay.stay_type in {
                    StayType.AIRBNB,
                    StayType.VRBO,
                    StayType.HOUSE,
                } and not _has_compelling_lodging_upside(text):
                    risks.append(
                        RiskFlag(
                            risk_id=f"city-rental-fit-{stay.stay_id}",
                            severity=RiskSeverity.MEDIUM,
                            category="lodging",
                            description=(
                                f"{stay.property_name} is a city rental without clear upside. "
                                "In cities, boutique hotels usually fit the family's walkability and service needs better."
                            ),
                            affected_ids=[stay.stay_id],
                            recommended_fix="Require exceptional space/location/safety value or prefer a central boutique hotel.",
                        )
                    )
            if stay.stay_type in {StayType.AIRBNB, StayType.VRBO, StayType.HOUSE}:
                missing_signals = []
                if "safe" not in text and "well-reviewed" not in text:
                    missing_signals.append("safety/review confidence")
                if "parking" not in text and "walkable" not in text and "transit" not in text:
                    missing_signals.append("access/parking practicality")
                if missing_signals:
                    risks.append(
                        RiskFlag(
                            risk_id=f"rental-access-confidence-{stay.stay_id}",
                            severity=RiskSeverity.LOW,
                            category="lodging",
                            description=(
                                f"{stay.property_name} is a private rental missing explicit "
                                f"{', '.join(missing_signals)}."
                            ),
                            affected_ids=[stay.stay_id],
                            recommended_fix="Verify location safety, parking/access, and review quality before shortlisting.",
                        )
                    )
        return risks

    def _check_driving_and_parking_friction(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        friction_terms = (
            "narrow road",
            "cramped road",
            "difficult parking",
            "no parking",
            "limited parking",
        )
        for seg in trip.segments:
            if seg.segment_type != SegmentType.CAR:
                continue
            text = (seg.notes or "").lower()
            if any(term in text for term in friction_terms):
                risks.append(
                    RiskFlag(
                        risk_id=f"driving-friction-{seg.segment_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="transfer",
                        description=(
                            f"Driving segment {seg.segment_id} has cramped-road or parking friction signals. "
                            "The family is comfortable driving generally, but dislikes stressful roads and parking."
                        ),
                        affected_ids=[seg.segment_id],
                        recommended_fix="Confirm route/parking practicality or use train/private transfer instead.",
                    )
                )
        for stay in trip.stays:
            text = _stay_text(stay)
            if any(term in text for term in friction_terms):
                risks.append(
                    RiskFlag(
                        risk_id=f"parking-friction-{stay.stay_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="lodging",
                        description=f"{stay.property_name} has parking or road-access friction signals.",
                        affected_ids=[stay.stay_id],
                        recommended_fix="Verify parking details and arrival route before booking.",
                    )
                )
        return risks

    def _check_pacing(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        for stay in trip.stays:
            if stay.nights == 1:
                risks.append(
                    RiskFlag(
                        risk_id=f"one-night-stop-{stay.stay_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="pacing",
                        description=(
                            f"{stay.property_name} is a one-night stop. The family dislikes frequent "
                            "hotel changes and overcompressed pacing."
                        ),
                        affected_ids=[stay.stay_id],
                        recommended_fix="Combine stops or extend to at least 2 nights unless this is a necessary transit stop.",
                    )
                )
        if trip.start_date and trip.end_date and trip.stays:
            trip_days = max(1, (trip.end_date - trip.start_date).days + 1)
            max_destinations = max(
                1,
                int(
                    (trip_days / 7) * (self._prefs.max_destinations_per_week if self._prefs else 3)
                ),
            )
            distinct_stops = len({(stay.city.lower(), stay.country.lower()) for stay in trip.stays})
            if distinct_stops > max_destinations:
                risks.append(
                    RiskFlag(
                        risk_id="overcompressed-itinerary",
                        severity=RiskSeverity.MEDIUM,
                        category="pacing",
                        description=(
                            f"{distinct_stops} lodging stops across {trip_days} days is likely overcompressed "
                            "for a family trip."
                        ),
                        affected_ids=[stay.stay_id for stay in trip.stays],
                        recommended_fix="Reduce destinations or add downtime between transitions.",
                    )
                )
        return risks

    def _check_destination_readiness(self, trip: Trip) -> list[RiskFlag]:
        checklist_text = " ".join(
            f"{item.category} {item.title} {item.notes or ''}" for item in trip.checklist
        ).lower()
        required = {
            "cash-currency-guidance": ("cash", "currency"),
            "entry-requirements": ("visa", "entry", "eta", "passport"),
            "health-precautions": ("health", "vaccine", "vaccination", "medical"),
        }
        risks: list[RiskFlag] = []
        for risk_key, terms in required.items():
            if not any(term in checklist_text for term in terms):
                risks.append(
                    RiskFlag(
                        risk_id=f"missing-{risk_key}",
                        severity=RiskSeverity.LOW,
                        category="readiness",
                        description=(
                            f"Trip is missing explicit {risk_key.replace('-', ' ')}. "
                            "Trippy should surface this before final recommendations or booking."
                        ),
                        affected_ids=[],
                        recommended_fix="Add researched destination guidance to the planning sheet checklist.",
                    )
                )
        return risks

    def _check_country_priors(self, trip: Trip) -> list[RiskFlag]:
        from trippy.models.country_priors import CountryPriorBand
        from trippy.services.country_priors import CountryPriorService

        service = CountryPriorService()
        risks: list[RiskFlag] = []
        for country in _countries_for_trip(trip):
            fit = service.fit_for_country(country)
            if fit is None or not fit.caution_signals:
                continue
            severity = (
                RiskSeverity.MEDIUM if fit.band == CountryPriorBand.CAUTION else RiskSeverity.LOW
            )
            risks.append(
                RiskFlag(
                    risk_id=f"country-prior-{_risk_slug(fit.country)}",
                    severity=severity,
                    category="country_prior",
                    description=(
                        f"{fit.country} has historical country-level caution signals: "
                        f"{', '.join(fit.caution_signals[:5])}. These are directional priors, "
                        "not a reason to reject the trip automatically."
                    ),
                    affected_ids=[],
                    recommended_fix=(
                        "Explain why this exact sub-region, season, logistics plan, and trip style "
                        "still fit before recommending."
                    ),
                )
            )
        return risks

    def _check_tour_quality_signals(self, trip: Trip) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        tour_terms = ("tour", "excursion", "outing", "adventure")
        bad_terms = ("large group", "mass market", "crowded", "weak review", "safety unknown")
        for item in trip.checklist:
            text = f"{item.category} {item.title} {item.notes or ''}".lower()
            if any(term in text for term in tour_terms) and any(term in text for term in bad_terms):
                risks.append(
                    RiskFlag(
                        risk_id=f"tour-quality-{item.item_id}",
                        severity=RiskSeverity.MEDIUM,
                        category="activity",
                        description=(
                            f"Activity '{item.title}' has crowd, review, or safety confidence warnings. "
                            "The family prefers safe, well-reviewed, smaller-group outings."
                        ),
                        affected_ids=[item.item_id],
                        recommended_fix="Find a smaller-group, strongly reviewed operator with clear safety signals.",
                    )
                )
        return risks

    def _check_too_many_moves(self, trip: Trip) -> list[RiskFlag]:
        """Flag trips where the number of lodging transitions is high relative to trip length."""
        if not trip.stays or not trip.start_date or not trip.end_date:
            return []
        trip_days = max(1, (trip.end_date - trip.start_date).days + 1)
        moves = len(trip.stays) - 1
        if moves <= 0:
            return []

        if trip_days <= 5 and moves >= 2:
            severity = RiskSeverity.HIGH
            description = (
                f"{moves} lodging move(s) across a {trip_days}-day trip is too compressed "
                "for a family of 5 with kids — packing, unpacking, parking, and check-in "
                "friction stack up fast on a short trip."
            )
            fix = "Consolidate to one base or reduce moves to at most one for a trip this short."
        elif trip_days <= 7 and moves >= 2:
            severity = RiskSeverity.MEDIUM
            description = (
                f"{moves} lodging move(s) in a {trip_days}-day trip is borderline for a family. "
                "Each move adds check-in, luggage, and parking friction."
            )
            fix = "Keep moves to one unless the second base has a clear activity or logistics win."
        elif trip_days <= 10 and moves >= 3:
            severity = RiskSeverity.MEDIUM
            description = (
                f"{moves} lodging move(s) across {trip_days} days is on the high side — "
                "confirm each transition has a clear upside (not just routing convenience)."
            )
            fix = "Reduce to 2 moves max unless each base is meaningfully distinct."
        else:
            return []

        return [
            RiskFlag(
                risk_id="too-many-moves",
                severity=severity,
                category="pacing",
                description=description,
                affected_ids=[stay.stay_id for stay in trip.stays],
                recommended_fix=fix,
            )
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_arrival_on_date(self, trip: Trip, check_date: date) -> Segment | None:
        for seg in trip.segments:
            if seg.arrive_at and seg.arrive_at.date() == check_date:
                return seg
        return None


def _stay_text(stay: Stay) -> str:
    return " ".join(
        str(value or "")
        for value in (
            stay.property_name,
            stay.city,
            stay.country,
            stay.address,
            stay.room_type,
            stay.parking_instructions,
            stay.check_in_instructions,
            stay.notes,
        )
    ).lower()


def _bed_count(text: str) -> int | None:
    if not text.strip():
        return None
    if "2 rooms" in text or "two rooms" in text:
        return 3
    explicit = re.search(r"(\d+)\s+(?:beds?|sleeping surfaces?)", text)
    if explicit:
        return int(explicit.group(1))
    count = 0
    for word in ("king", "queen", "double", "twin", "sofa bed", "bunk"):
        if word in text:
            multiplier = 1
            match = re.search(rf"(\d+)\s+{re.escape(word)}", text)
            if match:
                multiplier = int(match.group(1))
            count += multiplier
    return count or None


def _has_compelling_lodging_upside(text: str) -> bool:
    return any(
        term in text
        for term in (
            "central",
            "walkable",
            "suite",
            "exceptional",
            "spacious",
            "safe",
            "parking",
            "near transit",
            "urban core",
        )
    )


def _looks_like_city_stay(stay: Stay) -> bool:
    text = _stay_text(stay)
    return bool(stay.city) and not any(term in text for term in ("countryside", "rural", "villa"))


def _countries_for_trip(trip: Trip) -> list[str]:
    countries = []
    seen = set()
    for stay in trip.stays:
        if stay.country and stay.country.lower() not in seen:
            countries.append(stay.country)
            seen.add(stay.country.lower())
    return countries


def _risk_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
