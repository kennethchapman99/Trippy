"""Two-step flight selection and trip-envelope helpers.

Flights are the authoritative source for the trip timeline. Trippy should first
select an outbound/departure flight, then select a return flight, then unlock
lodging, cars, activities, and timeline planning from the selected flight pair.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from trippy.models.shortlists import FlightOption, ResearchShortlistState, ShortlistCategory, ShortlistRowStatus

FlightSelectionKind = Literal["outbound", "return"]

FLIGHT_SELECTION_ARTIFACT = "flight_selection"
TRIP_ENVELOPE_ARTIFACT = "trip_envelope"
TWO_STEP_FLOW_ARTIFACT = "two_step_flight_flow"
DOWNSTREAM_LOCK_ARTIFACT = "downstream_planning_lock"
DOWNSTREAM_CATEGORIES = ("lodging", "cars", "activities", "timeline")
_IATA_PATTERN = re.compile(r"^[A-Z]{3}$")


class FlightEnvelopeError(ValueError):
    """Raised when a downstream planning step tries to skip the flight gate."""


class TripEnvelopeNotLockedError(FlightEnvelopeError):
    """Raised when downstream planning is attempted before the flight envelope is locked."""


def is_iata_code(value: str) -> bool:
    """Return True only for valid three-letter IATA-style airport codes."""

    return bool(_IATA_PATTERN.fullmatch((value or "").strip().upper()))


def normalized_iata_or_none(value: str) -> str | None:
    """Normalize an airport code, never a freeform destination string."""

    candidate = (value or "").strip().upper()
    return candidate if is_iata_code(candidate) else None


def normalize_selection_kind(selection_kind: str) -> FlightSelectionKind:
    kind = (selection_kind or "outbound").strip().lower()
    if kind in {"departure", "depart", "out", "outbound"}:
        return "outbound"
    if kind in {"return", "homebound", "inbound", "back"}:
        return "return"
    raise FlightEnvelopeError(
        "selection_kind must be either 'outbound'/'departure' or 'return'."
    )


def select_flight_for_envelope(
    state: ResearchShortlistState,
    option_id: str,
    *,
    selection_kind: str = "outbound",
) -> ResearchShortlistState:
    """Select a flight using the required departure -> return sequence.

    Return selection is intentionally blocked until a departure option is selected.
    The trip envelope is only written after both selections are present.
    """

    _require_flight_state(state)
    option = _find_option(state, option_id)
    kind = normalize_selection_kind(selection_kind)
    selection = dict(state.artifacts.get(FLIGHT_SELECTION_ARTIFACT) or {})
    if kind == "return" and not selection.get("selected_outbound_option_id"):
        raise FlightEnvelopeError(
            "Select a departure flight before searching for or selecting return options."
        )

    selection[f"selected_{kind}_option_id"] = option_id
    selection["trip_envelope_locked"] = False
    state.artifacts[FLIGHT_SELECTION_ARTIFACT] = selection

    if kind == "outbound":
        state.recommended_option_id = option_id
    option.row_status = ShortlistRowStatus.APPROVED
    option.recommendation_label = "Departure selected" if kind == "outbound" else "Return selected"
    option.planning_next_step = (
        "Next: search and choose the return flight before locking lodging, cars, activities, or the timeline."
        if kind == "outbound"
        else "Trip envelope can now lock; downstream planning should use these selected flight datetimes."
    )
    return apply_trip_envelope_artifacts(state)


def apply_trip_envelope_artifacts(state: ResearchShortlistState) -> ResearchShortlistState:
    """Refresh selection, envelope, flow, and downstream lock artifacts."""

    _require_flight_state(state)
    envelope = derive_trip_envelope(state)
    selection = dict(state.artifacts.get(FLIGHT_SELECTION_ARTIFACT) or {})
    if envelope is None:
        selected_outbound = bool(selection.get("selected_outbound_option_id"))
        phase = "return_required" if selected_outbound else "departure_required"
        missing = ["selected_return_flight"] if selected_outbound else ["selected_departure_flight", "selected_return_flight"]
        selection["trip_envelope_locked"] = False
        state.artifacts.pop(TRIP_ENVELOPE_ARTIFACT, None)
        state.artifacts[TWO_STEP_FLOW_ARTIFACT] = {
            "phase": phase,
            "departure_selected": selected_outbound,
            "return_selected": bool(selection.get("selected_return_option_id")),
            "requires_user_choice": True,
            "missing": missing,
        }
        state.artifacts[DOWNSTREAM_LOCK_ARTIFACT] = _downstream_lock_payload(
            locked=False,
            reason="Flights do not yet define the authoritative trip envelope.",
            missing=missing,
        )
        state.next_actions = _dedupe(
            [
                (
                    "Search and choose return flight options for the selected departure arrival airport."
                    if selected_outbound
                    else "Choose a departure flight before searching return options."
                ),
                *state.next_actions,
            ]
        )
    else:
        selection["trip_envelope_locked"] = True
        state.artifacts[TRIP_ENVELOPE_ARTIFACT] = envelope
        state.artifacts[TWO_STEP_FLOW_ARTIFACT] = {
            "phase": "trip_envelope_locked",
            "departure_selected": True,
            "return_selected": True,
            "requires_user_choice": False,
            "missing": [],
        }
        state.artifacts[DOWNSTREAM_LOCK_ARTIFACT] = _downstream_lock_payload(
            locked=True,
            reason="Selected departure and return flights define the trip timeline.",
            missing=[],
        )
        state.next_actions = _dedupe(
            [
                "Use the locked flight envelope for lodging check-in/out, car pickup/dropoff, activities, and Master Timeline dates.",
                *state.next_actions,
            ]
        )
    state.artifacts[FLIGHT_SELECTION_ARTIFACT] = selection
    return state


def derive_trip_envelope(state: ResearchShortlistState) -> dict[str, object] | None:
    """Return the authoritative trip envelope after both flight choices exist."""

    _require_flight_state(state)
    outbound = selected_flight_option(state, "outbound")
    return_flight = selected_flight_option(state, "return")
    if outbound is None or return_flight is None:
        return None

    origin_airport = _require_iata(outbound.departure_airport, "origin_airport")
    destination_airport = _require_iata(outbound.arrival_airport, "destination_airport")
    return_airport = _require_iata(return_flight.departure_airport, "return_airport")
    home_arrival_airport = _require_iata(return_flight.arrival_airport, "home_arrival_airport")

    return {
        "status": "locked",
        "selected_departure_flight": True,
        "selected_return_flight": True,
        "selected_outbound_option_id": outbound.option_id,
        "selected_return_option_id": return_flight.option_id,
        "trip_start_datetime": _combine_date_time(outbound.arrival_date, outbound.arrival_time),
        "trip_end_datetime": _combine_date_time(return_flight.departure_date, return_flight.departure_time),
        "home_return_datetime": _combine_date_time(return_flight.arrival_date, return_flight.arrival_time),
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "return_airport": return_airport,
        "home_arrival_airport": home_arrival_airport,
        "trip_nights": _trip_nights(outbound.arrival_date, return_flight.departure_date),
        "timeline_source": "selected_flight_datetimes",
    }


def assert_trip_envelope_locked(state: ResearchShortlistState) -> dict[str, object]:
    """Return the envelope or fail fast for downstream finalization."""

    envelope = derive_trip_envelope(state)
    if envelope is None:
        raise TripEnvelopeNotLockedError(
            "Trip envelope is not locked. Select both departure and return flights first."
        )
    return envelope


def selected_flight_option(
    state: ResearchShortlistState,
    selection_kind: str,
) -> FlightOption | None:
    kind = normalize_selection_kind(selection_kind)
    selection = state.artifacts.get(FLIGHT_SELECTION_ARTIFACT) or {}
    if not isinstance(selection, dict):
        return None
    option_id = str(selection.get(f"selected_{kind}_option_id") or "")
    if not option_id:
        return None
    return next((option for option in state.flight_options if option.option_id == option_id), None)


def split_options_by_phase(state: ResearchShortlistState) -> dict[str, object]:
    """Expose options appropriate to the current two-step flight phase.

    Before departure selection, every current option is treated as a departure option.
    After departure selection, return options are limited to routes from the selected
    destination airport back to the selected origin airport.
    """

    outbound = selected_flight_option(state, "outbound")
    if outbound is None:
        return {
            "phase": "departure_required",
            "departure_options": state.flight_options,
            "return_options": [],
            "route": None,
        }
    origin = normalized_iata_or_none(outbound.departure_airport)
    destination = normalized_iata_or_none(outbound.arrival_airport)
    return_options = [
        option
        for option in state.flight_options
        if normalized_iata_or_none(option.departure_airport) == destination
        and normalized_iata_or_none(option.arrival_airport) == origin
    ]
    return {
        "phase": "return_required" if selected_flight_option(state, "return") is None else "trip_envelope_locked",
        "departure_options": [],
        "return_options": return_options,
        "route": {
            "origin_airport": destination,
            "destination_airport": origin,
            "based_on_selected_outbound_option_id": outbound.option_id,
        },
    }


def downstream_status_for_category(
    state: ResearchShortlistState,
    category: str,
) -> str:
    lock = state.artifacts.get(DOWNSTREAM_LOCK_ARTIFACT) or {}
    categories = lock.get("categories") if isinstance(lock, dict) else {}
    if isinstance(categories, dict):
        return str(categories.get(category, "blocked"))
    return "blocked"


def _downstream_lock_payload(*, locked: bool, reason: str, missing: list[str]) -> dict[str, object]:
    status = "ready" if locked else "blocked"
    return {
        "status": "locked" if locked else "provisional",
        "reason": reason,
        "missing": missing,
        "categories": {category: status for category in DOWNSTREAM_CATEGORIES},
    }


def _require_flight_state(state: ResearchShortlistState) -> None:
    if state.category != ShortlistCategory.FLIGHTS:
        raise FlightEnvelopeError("Flight envelope helpers require a flights shortlist state.")


def _find_option(state: ResearchShortlistState, option_id: str) -> FlightOption:
    option = next((item for item in state.flight_options if item.option_id == option_id), None)
    if option is None:
        raise FlightEnvelopeError(f"Flight option {option_id!r} was not found.")
    return option


def _require_iata(value: str, field_name: str) -> str:
    code = normalized_iata_or_none(value)
    if code is None:
        raise FlightEnvelopeError(
            f"{field_name} must be a normalized IATA airport code before live flight search or envelope lock: {value!r}"
        )
    return code


def _combine_date_time(date_text: str, time_text: str) -> str:
    cleaned_date = (date_text or "").strip()
    if not _parse_date(cleaned_date):
        return cleaned_date
    cleaned_time = (time_text or "").strip()
    parsed_time = _parse_time(cleaned_time)
    if parsed_time is None:
        return cleaned_date
    return f"{cleaned_date}T{parsed_time}"


def _trip_nights(start_date: str, end_date: str) -> int | None:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is None or end is None:
        return None
    return max(0, (end - start).days)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_time(value: str) -> str | None:
    cleaned = (value or "").strip().upper().replace(".", "")
    if not cleaned:
        return None
    for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
