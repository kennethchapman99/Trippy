"""Backend-owned flight flow and trip-date constraint engine.

Flights are not just another shortlist. Trippy has two different flight jobs:

1. Envelope flights
   - departure from home/origin to trip destination
   - return from trip destination to home/origin
   - these are the only flights that lock the trip start/end dates

2. In-trip transfer flights
   - optional one-way inter-location flights inside the already-locked trip
   - these may be needed later depending on trip shape
   - these must never redefine the overall trip envelope

This service owns the departure -> return -> locked-envelope state machine so the
UI and downstream planners do not infer dates from mixed shortlist rows.
"""

from __future__ import annotations

from typing import Any, Literal

from trippy.models.shortlists import (
    FlightOption,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
)
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.flight_trip_envelope import (
    FlightEnvelopeError,
    apply_trip_envelope_artifacts,
    derive_trip_envelope,
)
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService

FlightFlowPhase = Literal["departure_required", "return_required", "locked"]
EnvelopeFlightPhase = Literal["departure", "return"]


class FlightFlowService:
    """Owns Trippy's envelope-flight flow.

    Only the selected departure and selected return are allowed to lock the trip
    envelope. Future in-trip one-way flights are treated as transfer flights and
    remain downstream consumers of the envelope, not producers of it.
    """

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        store: ShortlistStore | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._store = store or ShortlistStore()

    def get_state(self, trip_id: str) -> dict[str, Any]:
        state = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        return self._payload(trip_id, state)

    def search_departures(
        self,
        trip_id: str,
        *,
        validate_live: bool = True,
        deep_research: bool = True,
        adapter_mode: str = "auto",
    ) -> dict[str, Any]:
        state = FlightShortlistService(self._intakes, self._planner).build(
            trip_id,
            flight_phase="departure",
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter_mode,
        )
        self._mark_envelope_role(state, "departure")
        return self._payload(trip_id, state)

    def select_departure(self, trip_id: str, option_id: str) -> dict[str, Any]:
        state = FlightShortlistService(self._intakes, self._planner).select_flight(
            trip_id,
            option_id,
            selection_kind="outbound",
        )
        self._mark_envelope_role(state, "departure")
        return self._payload(trip_id, state)

    def search_returns(
        self,
        trip_id: str,
        *,
        validate_live: bool = True,
        deep_research: bool = False,
        adapter_mode: str = "auto",
    ) -> dict[str, Any]:
        existing = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        if existing is None or self._selected_departure(existing) is None:
            raise FlightEnvelopeError("Select a departure flight before searching returns.")
        state = FlightShortlistService(self._intakes, self._planner).build(
            trip_id,
            flight_phase="return",
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter_mode,
        )
        self._mark_envelope_role(state, "return")
        return self._payload(trip_id, state)

    def select_return(self, trip_id: str, option_id: str) -> dict[str, Any]:
        state = FlightShortlistService(self._intakes, self._planner).select_flight(
            trip_id,
            option_id,
            selection_kind="return",
        )
        self._mark_envelope_role(state, "return")
        return self._payload(trip_id, state)

    def reset_departure(self, trip_id: str) -> dict[str, Any]:
        """Clear the envelope and all return/transfer state derived from it."""
        state = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        if state is None:
            return self._payload(trip_id, None)

        artifacts = dict(state.artifacts or {})
        for key in (
            "flight_selection",
            "trip_envelope",
            "two_step_flight_flow",
            "downstream_planning_lock",
            "return_search",
            "inter_location_flights",
            "flight_flow",
        ):
            artifacts.pop(key, None)

        kept_options: list[FlightOption] = []
        for option in state.flight_options:
            role = self._flight_role(option)
            if role in {"return", "inter_location"}:
                continue
            if option.row_status == ShortlistRowStatus.APPROVED:
                option.row_status = ShortlistRowStatus.RESEARCHED
            if "selected" in (option.recommendation_label or "").lower():
                option.recommendation_label = ""
            kept_options.append(option)

        state.flight_options = kept_options
        state.artifacts = artifacts
        state.recommended_option_id = None
        state.recommendation_summary = "Choose a departure flight first. Return options come after that selection."
        state.next_actions = ["Choose a departure flight to start the two-step flight flow."]
        saved = self._store.save(state)
        return self._payload(trip_id, saved)

    def require_locked_envelope(self, trip_id: str) -> dict[str, Any]:
        """Return the locked envelope or fail fast for downstream finalization."""
        state = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        envelope = derive_trip_envelope(state) if state else None
        if not envelope:
            raise FlightEnvelopeError(
                "Trip envelope is not locked. Select both departure and return flights first."
            )
        return envelope

    def _payload(
        self,
        trip_id: str,
        state: ResearchShortlistState | None,
    ) -> dict[str, Any]:
        if state is not None:
            self._repair_orphan_return_state(state)
            self._write_flow_artifact(state)
            apply_trip_envelope_artifacts(state)
            state = self._store.save(state)

        departure_options = self._departure_options(state)
        return_options = self._return_options(state)
        transfer_options = self._inter_location_options(state)
        selected_departure = self._selected_departure(state) if state else None
        selected_return = self._selected_return(state) if state else None
        envelope = derive_trip_envelope(state) if state else None
        phase: FlightFlowPhase
        if envelope:
            phase = "locked"
        elif selected_departure:
            phase = "return_required"
        else:
            phase = "departure_required"

        flow = {
            "trip_id": trip_id,
            "phase": phase,
            "selected_departure": self._option_json(selected_departure),
            "selected_return": self._option_json(selected_return),
            "trip_envelope": envelope,
            "departure_options": [self._option_json(option) for option in departure_options],
            "return_options": [self._option_json(option) for option in return_options],
            "inter_location_options": [self._option_json(option) for option in transfer_options],
            "return_search": (state.artifacts or {}).get("return_search") if state else None,
            "can_continue": phase == "locked",
            "downstream_unlocked": phase == "locked",
            "date_source": "locked_trip_envelope" if phase == "locked" else "target_window_only",
            "next_action": self._next_action(phase),
            "invariants": {
                "final_dates_require_return": True,
                "inter_location_flights_do_not_define_trip_dates": True,
                "downstream_finalization_requires_locked_envelope": True,
            },
        }
        return {
            "flight_flow": flow,
            "shortlist": state.model_dump(mode="json") if state else None,
        }

    def _repair_orphan_return_state(self, state: ResearchShortlistState) -> None:
        """Drop stale return state when the selected departure is missing.

        This protects the UI from impossible states such as "Return selected" while
        the flow is still asking for a departure. Return rows are only valid after a
        departure route has been selected because they are derived from that route.
        """
        if self._selected_departure(state) is not None:
            return

        artifacts = dict(state.artifacts or {})
        selection = dict(artifacts.get("flight_selection") or {})
        changed = False

        if selection.get("selected_return_option_id") or selection.get("trip_envelope_locked"):
            selection.pop("selected_return_option_id", None)
            selection["trip_envelope_locked"] = False
            artifacts["flight_selection"] = selection
            changed = True

        for key in (
            "trip_envelope",
            "two_step_flight_flow",
            "downstream_planning_lock",
            "return_search",
            "inter_location_flights",
        ):
            if key in artifacts:
                artifacts.pop(key, None)
                changed = True

        kept_options: list[FlightOption] = []
        for option in state.flight_options:
            role = self._flight_role(option)
            if role in {"return", "inter_location"}:
                changed = True
                continue
            if option.row_status == ShortlistRowStatus.APPROVED:
                option.row_status = ShortlistRowStatus.RESEARCHED
                changed = True
            if "selected" in (option.recommendation_label or "").lower():
                option.recommendation_label = ""
                changed = True
            kept_options.append(option)

        if not changed:
            return

        state.flight_options = kept_options
        state.artifacts = artifacts
        state.recommended_option_id = kept_options[0].option_id if kept_options else None
        state.recommendation_summary = "Choose a departure flight first. Return options come after that selection."
        state.next_actions = [
            "Choose a departure flight to start the two-step flight flow.",
            *[action for action in state.next_actions if "return" not in action.lower()],
        ]

    def _write_flow_artifact(self, state: ResearchShortlistState) -> None:
        artifacts = dict(state.artifacts or {})
        artifacts["flight_flow"] = {
            "schema": "trippy.flight_flow.v1",
            "envelope_flight_phases": ["departure", "return"],
            "transfer_flight_phase": "inter_location",
            "date_constraint_owner": "selected_departure_plus_selected_return",
            "inter_location_flights_are_downstream": True,
        }
        state.artifacts = artifacts

    def _mark_envelope_role(self, state: ResearchShortlistState, phase: EnvelopeFlightPhase) -> None:
        for option in state.flight_options:
            if phase == "departure" and getattr(option, "flight_phase", "departure") != "return":
                option.flight_phase = "departure"
            elif phase == "return" and getattr(option, "flight_phase", "departure") == "return":
                option.flight_phase = "return"

    def _departure_options(self, state: ResearchShortlistState | None) -> list[FlightOption]:
        if state is None:
            return []
        return [option for option in state.flight_options if self._flight_role(option) == "departure"]

    def _return_options(self, state: ResearchShortlistState | None) -> list[FlightOption]:
        if state is None:
            return []
        if self._selected_departure(state) is None:
            return []
        return [option for option in state.flight_options if self._flight_role(option) == "return"]

    def _inter_location_options(self, state: ResearchShortlistState | None) -> list[FlightOption]:
        if state is None:
            return []
        return [option for option in state.flight_options if self._flight_role(option) == "inter_location"]

    def _flight_role(self, option: FlightOption) -> str:
        phase = str(getattr(option, "flight_phase", "departure") or "departure").lower()
        if phase in {"return", "inbound", "homebound"}:
            return "return"
        if phase in {"inter_location", "interlocation", "transfer", "one_way", "in_trip"}:
            return "inter_location"
        return "departure"

    def _selected_departure(self, state: ResearchShortlistState | None) -> FlightOption | None:
        if state is None:
            return None
        selection = state.artifacts.get("flight_selection") or {}
        option_id = str(selection.get("selected_outbound_option_id") or "")
        if option_id:
            match = next((option for option in self._departure_options(state) if option.option_id == option_id), None)
            if match:
                return match
        return next(
            (
                option
                for option in self._departure_options(state)
                if option.row_status == ShortlistRowStatus.APPROVED
            ),
            None,
        )

    def _selected_return(self, state: ResearchShortlistState | None) -> FlightOption | None:
        if state is None:
            return None
        selected_departure = self._selected_departure(state)
        if selected_departure is None:
            return None
        selection = state.artifacts.get("flight_selection") or {}
        option_id = str(selection.get("selected_return_option_id") or "")
        if not option_id:
            return None
        return next((option for option in self._return_options(state) if option.option_id == option_id), None)

    def _option_json(self, option: FlightOption | None) -> dict[str, Any] | None:
        return option.model_dump(mode="json") if option is not None else None

    def _next_action(self, phase: FlightFlowPhase) -> str:
        if phase == "departure_required":
            return "Search and choose a departure flight."
        if phase == "return_required":
            return "Search and choose a return flight based on the selected departure."
        return "Flight envelope is locked; continue to stays. Inter-location flights can be planned later inside this envelope."
