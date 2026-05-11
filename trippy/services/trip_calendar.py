"""Canonical trip calendar service.

This service owns date integrity for a trip. It deliberately separates:
- rough intake timing
- selected flight envelope timing
- stay segments inside the envelope
- transfer boundaries between stays
- booking-safety validation

Downstream shortlists should read this state instead of independently inferring
booking dates from intake duration, plan options, or stale artifacts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from trippy.models.shortlists import ResearchShortlistState, ShortlistCategory
from trippy.models.trip_calendar import (
    CalendarIntegrity,
    CalendarInvalidation,
    CalendarRoughWindow,
    StaySegment,
    TransferSegment,
    TripCalendarState,
    TripCalendarStatus,
    TripEnvelope,
)
from trippy.models.trip_planning import TripIntake, TripPlanOption
from trippy.services.flight_trip_envelope import derive_trip_envelope
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class TripCalendarError(ValueError):
    """Raised when the canonical trip calendar would enter an invalid state."""


class TripCalendarService:
    """Build, persist, and validate canonical trip calendars."""

    def __init__(
        self,
        *,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        calendars_dir: Path | None = None,
    ) -> None:
        from trippy import config

        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._dir = calendars_dir or getattr(
            config,
            "CALENDARS_PATH",
            config.TRIPS_PATH.parent / "calendars",
        )

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.calendar.json"

    def load(self, trip_id: str) -> TripCalendarState | None:
        path = self.path_for(trip_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        calendar = TripCalendarState.model_validate(data)
        return self._finalize(calendar, bump_version=False)

    def save(self, calendar: TripCalendarState) -> TripCalendarState:
        self._ensure_dir()
        calendar.updated_at = datetime.utcnow()
        calendar = self._finalize(calendar, bump_version=False)
        self.path_for(calendar.trip_id).write_text(
            calendar.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return calendar

    def require(self, trip_id: str) -> TripCalendarState:
        calendar = self.load(trip_id)
        if calendar is not None:
            return calendar
        intake = self._intakes.require(trip_id)
        return self.save(self.from_intake(intake))

    def from_intake(self, intake: TripIntake) -> TripCalendarState:
        """Create the provisional calendar from rough intake timing."""
        window = intake.travel_window
        rough = CalendarRoughWindow(
            label=window.label,
            season=window.season,
            start_date=window.start_date.isoformat() if window.start_date else "",
            end_date=window.end_date.isoformat() if window.end_date else "",
            duration_days=intake.duration_days,
            duration_min_days=intake.duration_min_days,
            duration_max_days=intake.duration_max_days,
            confidence=0.55 if window.start_date or window.end_date else 0.3,
            source="intake",
        )
        calendar = TripCalendarState(
            trip_id=intake.trip_id,
            status=TripCalendarStatus.TARGET_WINDOW
            if rough.start_date or rough.end_date or rough.duration_days
            else TripCalendarStatus.IDEA_WINDOW,
            rough_window=rough,
            source_summary=[
                "Calendar initialized from intake. Dates are provisional until selected departure and return flights lock the envelope."
            ],
        )
        return self._finalize(calendar, bump_version=False)

    def rebuild_from_current_state(self, trip_id: str) -> TripCalendarState:
        """Rebuild from intake plus any existing selected flight envelope."""
        intake = self._intakes.require(trip_id)
        calendar = self.from_intake(intake)
        flight_state = self._load_flight_state(trip_id)
        if flight_state is not None:
            calendar = self.apply_flight_state(calendar, flight_state)
        option = self._selected_plan_option(trip_id)
        if option is not None:
            calendar = self.apply_plan_option(calendar, option)
        return self.save(calendar)

    def apply_flight_state(
        self,
        calendar: TripCalendarState,
        flight_state: ResearchShortlistState,
    ) -> TripCalendarState:
        """Update the canonical calendar from selected departure/return flights."""
        if flight_state.category != ShortlistCategory.FLIGHTS:
            raise TripCalendarError("apply_flight_state requires a flights shortlist state")

        previous_hash = calendar.date_dependency_hash
        envelope_payload = derive_trip_envelope(flight_state)
        selection = flight_state.artifacts.get("flight_selection") or {}
        selected_outbound = str(selection.get("selected_outbound_option_id") or "") if isinstance(selection, dict) else ""

        if envelope_payload is None:
            if selected_outbound:
                calendar.status = TripCalendarStatus.OUTBOUND_SELECTED
                calendar.trip_envelope = TripEnvelope(
                    locked=False,
                    outbound_flight_option_id=selected_outbound,
                    source="selected_departure_without_return",
                )
                calendar.source_summary = _dedupe(
                    [
                        *calendar.source_summary,
                        "Departure selected. Return flight is still required before the trip end date is authoritative.",
                    ]
                )
            return self._maybe_bump(calendar, previous_hash, "flight_selection_changed")

        calendar.trip_envelope = _envelope_from_payload(envelope_payload)
        calendar.status = TripCalendarStatus.ENVELOPE_LOCKED
        calendar.source_summary = _dedupe(
            [
                *calendar.source_summary,
                "Selected departure and return flights now define the authoritative trip envelope.",
            ]
        )
        if calendar.stay_segments:
            calendar = self._normalize_stay_dates(calendar)
        return self._maybe_bump(calendar, previous_hash, "trip_envelope_locked_or_changed")

    def apply_plan_option(
        self,
        calendar: TripCalendarState,
        option: TripPlanOption,
    ) -> TripCalendarState:
        """Create or refresh stay segments from the selected plan option."""
        previous_hash = calendar.date_dependency_hash
        if not option.regions:
            return self._finalize(calendar, bump_version=False)

        nights_by_region = _normalized_nights_by_region(option, calendar)
        calendar.stay_segments = _segments_from_nights(calendar, nights_by_region)
        calendar.transfer_segments = _transfer_segments_from_stays(calendar.stay_segments)
        if calendar.envelope_locked:
            calendar.status = TripCalendarStatus.STAY_PLAN_PROPOSED
        calendar.source_summary = _dedupe(
            [
                *calendar.source_summary,
                "Stay segments generated from the selected plan option. Segment nights are normalized against locked trip_nights when available.",
            ]
        )
        return self._maybe_bump(calendar, previous_hash, "stay_plan_changed")

    def update_stay_segments(
        self,
        trip_id: str,
        night_plan: list[dict[str, Any]],
        *,
        reason: str = "manual_stay_split_changed",
    ) -> TripCalendarState:
        """Persist a manual stay split and invalidate dependent downstream options."""
        calendar = self.require(trip_id)
        previous_hash = calendar.date_dependency_hash
        normalized = _normalize_manual_night_plan(night_plan)
        if not normalized:
            raise TripCalendarError("Stay split requires at least one region/night row")
        calendar.stay_segments = _segments_from_nights(calendar, normalized)
        calendar.transfer_segments = _transfer_segments_from_stays(calendar.stay_segments)
        calendar.status = (
            TripCalendarStatus.STAY_PLAN_PROPOSED
            if calendar.envelope_locked
            else TripCalendarStatus.TARGET_WINDOW
        )
        return self.save(self._maybe_bump(calendar, previous_hash, reason))

    def validate(self, trip_id: str) -> CalendarIntegrity:
        calendar = self.require(trip_id)
        return calendar.integrity

    def ui_payload(self, trip_id: str) -> dict[str, Any]:
        calendar = self.require(trip_id)
        return {
            "trip_id": trip_id,
            "calendar": calendar.model_dump(mode="json"),
            "summary": {
                "status": calendar.status.value,
                "calendar_version": calendar.calendar_version,
                "date_dependency_hash": calendar.date_dependency_hash,
                "envelope_locked": calendar.envelope_locked,
                "trip_start_date": calendar.trip_envelope.trip_start_date,
                "trip_end_date": calendar.trip_envelope.trip_end_date,
                "trip_nights": calendar.trip_envelope.trip_nights,
                "stay_nights_total": calendar.stay_nights_total(),
                "booking_safe": calendar.integrity.booking_safe,
                "blocking_issues": calendar.integrity.blocking_issues,
                "warnings": calendar.integrity.warnings,
            },
        }

    def _load_flight_state(self, trip_id: str) -> ResearchShortlistState | None:
        from trippy.services.shortlist_store import ShortlistStore

        return ShortlistStore().load(trip_id, ShortlistCategory.FLIGHTS)

    def _selected_plan_option(self, trip_id: str) -> TripPlanOption | None:
        draft = self._planner.load_draft(trip_id)
        return draft.get_option() if draft is not None else None

    def _maybe_bump(
        self,
        calendar: TripCalendarState,
        previous_hash: str,
        reason: str,
    ) -> TripCalendarState:
        finalized = self._finalize(calendar, bump_version=False)
        if previous_hash and finalized.date_dependency_hash != previous_hash:
            finalized.invalidations.append(
                CalendarInvalidation(
                    reason=reason,
                    previous_calendar_version=finalized.calendar_version,
                    invalidated_categories=["lodging", "cars", "activities", "timeline", "transfers"],
                )
            )
            finalized.calendar_version += 1
            finalized.integrity.stale_option_ids = _dedupe(finalized.integrity.stale_option_ids)
            finalized = self._finalize(finalized, bump_version=False)
        return finalized

    def _finalize(
        self,
        calendar: TripCalendarState,
        *,
        bump_version: bool,
    ) -> TripCalendarState:
        if bump_version:
            calendar.calendar_version += 1
        calendar.updated_at = datetime.utcnow()
        calendar.date_dependency_hash = _calendar_hash(calendar)
        calendar.integrity = _integrity(calendar)
        return calendar

    def _normalize_stay_dates(self, calendar: TripCalendarState) -> TripCalendarState:
        if not calendar.stay_segments:
            return calendar
        nights_by_region = {
            segment.region: segment.nights for segment in calendar.stay_segments
        }
        if calendar.trip_envelope.trip_nights is not None:
            nights_by_region = _rebalance_nights(
                nights_by_region,
                calendar.trip_envelope.trip_nights,
            )
        calendar.stay_segments = _segments_from_nights(calendar, nights_by_region)
        calendar.transfer_segments = _transfer_segments_from_stays(calendar.stay_segments)
        return calendar


def _envelope_from_payload(payload: dict[str, object]) -> TripEnvelope:
    start_date = _date_part(str(payload.get("trip_start_datetime") or ""))
    end_date = _date_part(str(payload.get("trip_end_datetime") or ""))
    nights = _int_or_none(payload.get("trip_nights"))
    days = nights + 1 if nights is not None else None
    return TripEnvelope(
        locked=True,
        outbound_flight_option_id=str(payload.get("selected_outbound_option_id") or ""),
        return_flight_option_id=str(payload.get("selected_return_option_id") or ""),
        trip_start_datetime=str(payload.get("trip_start_datetime") or ""),
        trip_start_date=start_date,
        trip_end_datetime=str(payload.get("trip_end_datetime") or ""),
        trip_end_date=end_date,
        home_return_datetime=str(payload.get("home_return_datetime") or ""),
        origin_airport=str(payload.get("origin_airport") or ""),
        destination_airport=str(payload.get("destination_airport") or ""),
        return_airport=str(payload.get("return_airport") or ""),
        home_arrival_airport=str(payload.get("home_arrival_airport") or ""),
        trip_days=days,
        trip_nights=nights,
        timezone_notes=[
            "Envelope dates use flight-local source timestamps; timezone normalization should be handled before final booking."
        ],
    )


def _normalized_nights_by_region(
    option: TripPlanOption,
    calendar: TripCalendarState,
) -> dict[str, int]:
    raw = {region: int(option.nights_by_region.get(region, 0)) for region in option.regions}
    raw = {region: nights for region, nights in raw.items() if region and nights > 0}
    if not raw:
        target_nights = _target_nights(calendar, option.duration_days)
        return _even_nights(option.regions, target_nights)
    target = calendar.trip_envelope.trip_nights
    if target is None:
        return raw
    return _rebalance_nights(raw, target)


def _normalize_manual_night_plan(night_plan: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, row in enumerate(night_plan, start=1):
        region = str(row.get("region") or row.get("location") or row.get("name") or f"Region {index}").strip()
        nights = _int_or_none(row.get("nights"))
        if not region or nights is None or nights < 0:
            continue
        result[region] = nights
    return result


def _segments_from_nights(
    calendar: TripCalendarState,
    nights_by_region: dict[str, int],
) -> list[StaySegment]:
    if not nights_by_region:
        return []
    start = _parse_date(calendar.trip_envelope.trip_start_date)
    segments: list[StaySegment] = []
    cursor = start
    for index, (region, nights) in enumerate(nights_by_region.items(), start=1):
        segment_start = cursor.isoformat() if cursor else ""
        segment_end = ""
        if cursor is not None:
            segment_end_date = cursor + timedelta(days=nights)
            segment_end = segment_end_date.isoformat()
            cursor = segment_end_date
        segments.append(
            StaySegment(
                segment_id=f"stay-{index}",
                sequence=index,
                region=region,
                location_label=region,
                start_date=segment_start,
                end_date=segment_end,
                nights=nights,
                check_in_status="date_locked" if segment_start else "date_required",
                check_out_status="date_locked" if segment_end else "date_required",
            )
        )
    return segments


def _transfer_segments_from_stays(stays: list[StaySegment]) -> list[TransferSegment]:
    transfers: list[TransferSegment] = []
    for index in range(1, len(stays)):
        previous = stays[index - 1]
        current = stays[index]
        transfers.append(
            TransferSegment(
                transfer_id=f"transfer-{index}",
                sequence=index,
                from_region=previous.region,
                to_region=current.region,
                date=previous.end_date,
                warnings=[
                    "Transfer boundary created from stay split; price and timing evidence required before booking."
                ],
            )
        )
    return transfers


def _integrity(calendar: TripCalendarState) -> CalendarIntegrity:
    results: dict[str, bool] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    envelope = calendar.trip_envelope
    results["envelope_locked"] = envelope.locked
    if envelope.locked:
        results["trip_start_date_exists"] = bool(envelope.trip_start_date)
        results["trip_end_date_exists"] = bool(envelope.trip_end_date)
        results["trip_nights_exists"] = envelope.trip_nights is not None
        if not results["trip_start_date_exists"]:
            blockers.append("Locked envelope is missing trip_start_date")
        if not results["trip_end_date_exists"]:
            blockers.append("Locked envelope is missing trip_end_date")
        if not results["trip_nights_exists"]:
            blockers.append("Locked envelope is missing trip_nights")
    else:
        warnings.append("Trip envelope is provisional until both departure and return flights are selected.")

    if calendar.stay_segments:
        total_nights = calendar.stay_nights_total()
        expected = envelope.trip_nights if envelope.locked else None
        results["stay_nights_match_trip_nights"] = expected is None or total_nights == expected
        if expected is not None and total_nights != expected:
            blockers.append(
                f"Stay segments total {total_nights} nights, but locked envelope requires {expected} nights."
            )
        results["stay_segments_contiguous"] = _stays_are_contiguous(calendar.stay_segments)
        if not results["stay_segments_contiguous"]:
            blockers.append("Stay segments have a gap or overlap.")
        if envelope.locked:
            first = calendar.stay_segments[0]
            last = calendar.stay_segments[-1]
            results["first_stay_starts_on_trip_start"] = first.start_date == envelope.trip_start_date
            results["last_stay_ends_on_trip_end"] = last.end_date == envelope.trip_end_date
            if not results["first_stay_starts_on_trip_start"]:
                blockers.append("First stay does not start on the locked trip start date.")
            if not results["last_stay_ends_on_trip_end"]:
                blockers.append("Last stay does not end on the locked trip end date.")

    if calendar.transfer_segments:
        valid_boundary_dates = {segment.end_date for segment in calendar.stay_segments[:-1]}
        results["transfer_dates_match_stay_boundaries"] = all(
            transfer.date in valid_boundary_dates for transfer in calendar.transfer_segments
        )
        if not results["transfer_dates_match_stay_boundaries"]:
            blockers.append("One or more transfer dates do not match a stay-segment boundary.")

    booking_safe = envelope.locked and bool(calendar.stay_segments) and not blockers
    return CalendarIntegrity(
        invariant_results=results,
        booking_safe=booking_safe,
        blocking_issues=_dedupe(blockers),
        warnings=_dedupe(warnings),
    )


def _calendar_hash(calendar: TripCalendarState) -> str:
    payload = {
        "status": calendar.status.value,
        "rough_window": calendar.rough_window.model_dump(mode="json"),
        "trip_envelope": calendar.trip_envelope.model_dump(mode="json"),
        "stay_segments": [segment.model_dump(mode="json") for segment in calendar.stay_segments],
        "transfer_segments": [segment.model_dump(mode="json") for segment in calendar.transfer_segments],
        "constraints": calendar.constraints.model_dump(mode="json"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _target_nights(calendar: TripCalendarState, duration_days: int | None) -> int:
    if calendar.trip_envelope.trip_nights is not None:
        return calendar.trip_envelope.trip_nights
    duration = duration_days or calendar.rough_window.duration_days or 1
    return max(0, duration - 1)


def _even_nights(regions: list[str], target_nights: int) -> dict[str, int]:
    if not regions:
        return {}
    base = target_nights // len(regions)
    extra = target_nights % len(regions)
    return {
        region: base + (1 if index < extra else 0)
        for index, region in enumerate(regions)
    }


def _rebalance_nights(raw: dict[str, int], target: int) -> dict[str, int]:
    if not raw:
        return raw
    current = sum(raw.values())
    if current == target:
        return raw
    keys = list(raw)
    result = dict(raw)
    if current < target:
        for index in range(target - current):
            result[keys[index % len(keys)]] += 1
        return result
    overage = current - target
    for key in reversed(keys):
        if overage <= 0:
            break
        removable = min(overage, result[key])
        result[key] -= removable
        overage -= removable
    return {key: value for key, value in result.items() if value > 0}


def _stays_are_contiguous(stays: list[StaySegment]) -> bool:
    if len(stays) < 2:
        return True
    return all(left.end_date == right.start_date for left, right in zip(stays, stays[1:]))


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _date_part(value: str) -> str:
    return value.split("T", 1)[0] if value else ""


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
