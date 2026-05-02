"""Two-step flight envelope: departure + return phase tracking and locking."""

from __future__ import annotations

from trippy.models.shortlists import FlightOption, ResearchShortlistState, ShortlistRowStatus


class TripEnvelopeNotLockedError(ValueError):
    """Raised when workspace finalization is attempted before both flights are selected."""


def apply_trip_envelope_artifacts(state: ResearchShortlistState) -> ResearchShortlistState:
    """Write/refresh the two_step_flight_flow metadata artifact on state."""
    selection = state.artifacts.get("flight_selection") or {}
    outbound_id = str(selection.get("selected_outbound_option_id") or "")
    return_id = str(selection.get("selected_return_option_id") or "")
    departure_options = [o for o in state.flight_options if o.flight_phase == "departure"]
    return_options = [o for o in state.flight_options if o.flight_phase == "return"]
    locked = bool(outbound_id and return_id)
    state.artifacts["two_step_flight_flow"] = {
        "current_phase": "return" if (outbound_id and not return_id) else "departure",
        "outbound_selected": bool(outbound_id),
        "return_selected": bool(return_id),
        "locked": locked,
        "departure_option_count": len(departure_options),
        "return_option_count": len(return_options),
        "selected_outbound_option_id": outbound_id,
        "selected_return_option_id": return_id,
    }
    return state


def select_flight_for_envelope(
    state: ResearchShortlistState,
    option_id: str,
    *,
    selection_kind: str = "outbound",
) -> ResearchShortlistState:
    """Apply a flight selection, update option labels, and refresh envelope artifacts."""
    normalized = (selection_kind or "outbound").strip().lower()
    kind = "return" if normalized in {"return", "inbound", "homebound"} else "outbound"

    selection = dict(state.artifacts.get("flight_selection") or {})
    selection[f"selected_{kind}_option_id"] = option_id
    state.artifacts["flight_selection"] = selection

    if kind == "outbound":
        state.recommended_option_id = option_id

    for option in state.flight_options:
        if option.option_id == option_id:
            option.row_status = ShortlistRowStatus.APPROVED
            option.recommendation_label = (
                "Departure selected" if kind == "outbound" else "Return selected"
            )
            option.planning_next_step = (
                "Use this departure timing to verify lodging check-in, car pickup, and first-day pacing."
                if kind == "outbound"
                else "Use this return timing to constrain final-night lodging, checkout, car dropoff, and last-day pacing."
            )

    apply_trip_envelope_artifacts(state)
    return state


def split_options_by_phase(
    state: ResearchShortlistState,
) -> tuple[list[FlightOption], list[FlightOption]]:
    """Return (departure_options, return_options) split from state.flight_options."""
    departure = [o for o in state.flight_options if o.flight_phase == "departure"]
    return_opts = [o for o in state.flight_options if o.flight_phase == "return"]
    return departure, return_opts


def assert_trip_envelope_locked(flight_state: ResearchShortlistState) -> None:
    """Raise TripEnvelopeNotLockedError if flights exist but both are not yet selected.

    If the shortlist has no flight options (research not yet run), the check passes
    so that early-stage workspace preparation is not blocked.
    """
    if not flight_state.flight_options:
        return
    flow = flight_state.artifacts.get("two_step_flight_flow") or {}
    if flow.get("locked"):
        return
    selection = flight_state.artifacts.get("flight_selection") or {}
    outbound = str(selection.get("selected_outbound_option_id") or "")
    return_id = str(selection.get("selected_return_option_id") or "")
    if outbound and return_id:
        return
    has_return_options = any(
        o.flight_phase == "return" for o in flight_state.flight_options
    )
    missing = []
    if not outbound:
        missing.append("outbound flight")
    if has_return_options and not return_id:
        missing.append("return flight")
    if missing:
        raise TripEnvelopeNotLockedError(
            f"Trip envelope not locked: {', '.join(missing)} not yet selected."
        )
