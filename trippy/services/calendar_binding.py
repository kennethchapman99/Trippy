"""Bind shortlist rows to the canonical trip calendar.

This module is intentionally deterministic. It does not make booking decisions from
LLM prose. It marks rows as current/stale/provisional against the calendar version
and prevents rows from becoming booking-safe unless the calendar and row dates are
compatible.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from trippy.models.shortlists import (
    CalendarDependencyStatus,
    LiveDataStatus,
    ResearchShortlistState,
    ShortlistCategory,
    VerificationStatus,
)
from trippy.models.trip_calendar import StaySegment, TripCalendarState


class CalendarBindableOption(Protocol):
    calendar_version: int | None
    date_dependency_hash: str
    valid_for_start_date: str
    valid_for_end_date: str
    valid_for_segment_id: str
    dependency_status: CalendarDependencyStatus
    booking_safe: bool
    booking_blockers: list[str]
    live_data_status: LiveDataStatus


class CalendarBindingService:
    """Apply calendar dependency metadata to shortlist state."""

    def bind_state(
        self,
        calendar: TripCalendarState,
        state: ResearchShortlistState,
    ) -> ResearchShortlistState:
        if state.category == ShortlistCategory.FLIGHTS:
            self._bind_flights(calendar, state)
        elif state.category == ShortlistCategory.LODGING:
            self._bind_lodging(calendar, state)
        elif state.category == ShortlistCategory.CARS:
            self._bind_generic(calendar, state.car_options)
        elif state.category == ShortlistCategory.ACTIVITIES:
            self._bind_activities(calendar, state)
        state.artifacts["calendar_dependency"] = {
            "calendar_version": calendar.calendar_version,
            "date_dependency_hash": calendar.date_dependency_hash,
            "calendar_status": calendar.status.value,
            "booking_safe": calendar.integrity.booking_safe,
            "blocking_issues": calendar.integrity.blocking_issues,
        }
        return state

    def _bind_flights(
        self,
        calendar: TripCalendarState,
        state: ResearchShortlistState,
    ) -> None:
        selected_ids = {
            calendar.trip_envelope.outbound_flight_option_id,
            calendar.trip_envelope.return_flight_option_id,
        }
        for option in state.flight_options:
            blockers = _base_blockers(calendar, option)
            if option.option_id.startswith("scanner-"):
                blockers.append("Scanner handoff rows require exact source evidence before booking.")
            if option.validation.verification_status != VerificationStatus.LIVE_VERIFIED:
                blockers.append("Flight row is not live verified.")
            if calendar.envelope_locked and option.option_id in selected_ids and not blockers:
                _mark_current(option, calendar, booking_safe=True)
            else:
                _mark_blocked(option, calendar, blockers)

    def _bind_lodging(
        self,
        calendar: TripCalendarState,
        state: ResearchShortlistState,
    ) -> None:
        for option in state.lodging_options:
            blockers = _base_blockers(calendar, option)
            if option.live_data_status == LiveDataStatus.SEARCH_LINK_ONLY:
                blockers.append("Search-link lodging rows are discovery inputs, not booking-safe options.")
            segment = _match_lodging_segment(calendar.stay_segments, option.island_or_region or option.location_area)
            if segment is None:
                blockers.append("Lodging row is not matched to a current stay segment.")
            else:
                option.valid_for_segment_id = segment.segment_id
                option.valid_for_start_date = segment.start_date
                option.valid_for_end_date = segment.end_date
            if option.validation.verification_status != VerificationStatus.LIVE_VERIFIED:
                blockers.append("Lodging row is not live verified for the segment dates.")
            if not blockers:
                _mark_current(option, calendar, booking_safe=True)
            else:
                _mark_blocked(option, calendar, blockers)

    def _bind_activities(
        self,
        calendar: TripCalendarState,
        state: ResearchShortlistState,
    ) -> None:
        for option in state.activity_options:
            blockers = _base_blockers(calendar, option)
            scheduled_date = option.scheduled_date or option.suggested_date
            if not scheduled_date:
                blockers.append("Activity has no scheduled or suggested date.")
            segment = _segment_for_date(calendar.stay_segments, scheduled_date)
            if segment is None:
                blockers.append("Activity date is outside current stay segments.")
            else:
                option.valid_for_segment_id = segment.segment_id
                option.valid_for_start_date = scheduled_date
                option.valid_for_end_date = scheduled_date
                if option.island_location and option.island_location.casefold() not in segment.region.casefold():
                    blockers.append("Activity location does not clearly match the active stay segment.")
            if option.validation.verification_status != VerificationStatus.LIVE_VERIFIED:
                blockers.append("Activity row is not live verified for the scheduled date.")
            if not blockers:
                _mark_current(option, calendar, booking_safe=True)
            else:
                _mark_blocked(option, calendar, blockers)

    def _bind_generic(
        self,
        calendar: TripCalendarState,
        options: Iterable[CalendarBindableOption],
    ) -> None:
        for option in options:
            blockers = _base_blockers(calendar, option)
            if option.live_data_status == LiveDataStatus.SEARCH_LINK_ONLY:
                blockers.append("Search-link rows are not booking-safe options.")
            if not blockers:
                _mark_current(option, calendar, booking_safe=False)
                option.booking_blockers = [
                    "Generic calendar binding requires category-specific date validation before booking-safe status."
                ]
            else:
                _mark_blocked(option, calendar, blockers)


def _base_blockers(
    calendar: TripCalendarState,
    option: CalendarBindableOption,
) -> list[str]:
    blockers: list[str] = []
    if not calendar.envelope_locked:
        blockers.append("Trip envelope is not locked by selected departure and return flights.")
    if calendar.integrity.blocking_issues:
        blockers.extend(calendar.integrity.blocking_issues)
    if option.date_dependency_hash and option.date_dependency_hash != calendar.date_dependency_hash:
        blockers.append("Option was generated for a stale calendar version/hash.")
    if option.live_data_status in {LiveDataStatus.HANDOFF_REQUIRED, LiveDataStatus.SEARCH_LINK_ONLY}:
        blockers.append("Option is not based on exact bookable live evidence.")
    return blockers


def _mark_current(
    option: CalendarBindableOption,
    calendar: TripCalendarState,
    *,
    booking_safe: bool,
) -> None:
    option.calendar_version = calendar.calendar_version
    option.date_dependency_hash = calendar.date_dependency_hash
    option.dependency_status = CalendarDependencyStatus.CURRENT
    option.booking_safe = booking_safe
    option.booking_blockers = [] if booking_safe else list(option.booking_blockers)


def _mark_blocked(
    option: CalendarBindableOption,
    calendar: TripCalendarState,
    blockers: list[str],
) -> None:
    option.calendar_version = calendar.calendar_version
    option.date_dependency_hash = calendar.date_dependency_hash
    option.booking_safe = False
    option.booking_blockers = _dedupe(blockers)
    if not calendar.envelope_locked:
        option.dependency_status = CalendarDependencyStatus.PROVISIONAL_NO_ENVELOPE
    elif any("stale" in blocker.lower() for blocker in blockers):
        option.dependency_status = CalendarDependencyStatus.STALE_CALENDAR_CHANGED
    elif any("date" in blocker.lower() for blocker in blockers):
        option.dependency_status = CalendarDependencyStatus.MISSING_DATES
    else:
        option.dependency_status = CalendarDependencyStatus.UNKNOWN


def _match_lodging_segment(stays: list[StaySegment], region_hint: str) -> StaySegment | None:
    hint = (region_hint or "").casefold()
    if not hint:
        return stays[0] if len(stays) == 1 else None
    return next(
        (
            segment
            for segment in stays
            if hint in segment.region.casefold() or segment.region.casefold() in hint
        ),
        stays[0] if len(stays) == 1 else None,
    )


def _segment_for_date(stays: list[StaySegment], date_value: str) -> StaySegment | None:
    if not date_value:
        return None
    return next(
        (
            segment
            for segment in stays
            if segment.start_date <= date_value < segment.end_date
        ),
        None,
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
