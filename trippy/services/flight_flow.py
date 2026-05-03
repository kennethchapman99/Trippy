"""Backend-owned two-step flight flow.

This service makes flights a real state machine instead of asking the generic
shortlist UI to infer departure/return phase from mixed rows.
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


class FlightFlowService:
    """Owns Trippy's departure -> return -> locked-envelope flight flow."""

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
        return self._payload(trip_id, state)

    def select_departure(self, trip_id: str, option_id: str) -> dict[str, Any]:
        state = FlightShortlistService(self._intakes, self._planner).select_flight(
            trip_id,
            option_id,
            selection_kind="outbound",
        )
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
        return self._payload(trip_id, state)

    def select_return(self, trip_id: str, option_id: str) -> dict[str, Any]:
        state = FlightShortlistService(self._intakes, self._planner).select_flight(
            trip_id,
            option_id,
            selection_kind="return",
        )
        return self._payload(trip_id, state)

    def reset_departure(self, trip_id: str) -> dict[str, Any]:
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
        ):
            artifacts.pop(key, None)

        kept_options: list[FlightOption] = []
        for option in state.flight_options:
            if getattr(option, "flight_phase", "departure") == "return":
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

    def _payload(
        self,
        trip_id: str,
        state: ResearchShortlistState | None,
    ) -> dict[str, Any]:
        if state is not None:
            apply_trip_envelope_artifacts(state)
            state = self._store.save(state)

        departure_options = self._departure_options(state)
        return_options = self._return_options(state)
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
            "return_search": (state.artifacts or {}).get("return_search") if state else None,
            "can_continue": phase == "locked",
            "next_action": self._next_action(phase),
        }
        return {
            "flight_flow": flow,
            "shortlist": state.model_dump(mode="json") if state else None,
        }

    def _departure_options(self, state: ResearchShortlistState | None) -> list[FlightOption]:
        if state is None:
            return []
        return [
            option
            for option in state.flight_options
            if getattr(option, "flight_phase", "departure") != "return"
        ]

    def _return_options(self, state: ResearchShortlistState | None) -> list[FlightOption]:
        if state is None:
            return []
        return [
            option
            for option in state.flight_options
            if getattr(option, "flight_phase", "departure") == "return"
        ]

    def _selected_departure(self, state: ResearchShortlistState | None) -> FlightOption | None:
        if state is None:
            return None
        selection = state.artifacts.get("flight_selection") or {}
        option_id = str(selection.get("selected_outbound_option_id") or "")
        if option_id:
            match = next((option for option in state.flight_options if option.option_id == option_id), None)
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
        selection = state.artifacts.get("flight_selection") or {}
        option_id = str(selection.get("selected_return_option_id") or "")
        if not option_id:
            return None
        return next((option for option in state.flight_options if option.option_id == option_id), None)

    def _option_json(self, option: FlightOption | None) -> dict[str, Any] | None:
        return option.model_dump(mode="json") if option is not None else None

    def _next_action(self, phase: FlightFlowPhase) -> str:
        if phase == "departure_required":
            return "Search and choose a departure flight."
        if phase == "return_required":
            return "Search and choose a return flight based on the selected departure."
        return "Flight envelope is locked; continue to stays."
