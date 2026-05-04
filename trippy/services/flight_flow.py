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

import re
from typing import Any, Literal
from urllib.parse import quote_plus

from trippy.models.shortlists import (
    FlightOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
    SourceType,
    SourceValidation,
    VerificationStatus,
)
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.flight_trip_envelope import (
    FlightEnvelopeError,
    apply_trip_envelope_artifacts,
    derive_trip_envelope,
)
from trippy.services.scanner_fallback import run_scanner_fallback, scanner_fallback_available
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService

FlightFlowPhase = Literal["departure_required", "return_required", "locked"]
EnvelopeFlightPhase = Literal["departure", "return"]
FlightRoutePhase = Literal["departure", "return", "inter_location"]
_IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
_SCANNER_REQUIRED_FIELDS = [
    "flight_numbers",
    "exact_departure_date",
    "exact_arrival_date",
    "exact_departure_time",
    "exact_arrival_time",
    "total_duration",
    "exact_fare",
    "fare_rules",
    "baggage_terms",
]


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
        state = FlightShortlistService(self._intakes, self._planner, store=self._store).build(
            trip_id,
            flight_phase="departure",
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter_mode,
        )
        self._mark_envelope_role(state, "departure")
        state = self._ensure_scanner_handoff(
            trip_id,
            state,
            "departure",
            adapter_mode=adapter_mode,
        )
        return self._payload(trip_id, state)

    def select_departure(self, trip_id: str, option_id: str) -> dict[str, Any]:
        existing = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        self._assert_selectable_flight(existing, option_id)
        state = FlightShortlistService(self._intakes, self._planner, store=self._store).select_flight(
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
        state = FlightShortlistService(self._intakes, self._planner, store=self._store).build(
            trip_id,
            flight_phase="return",
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter_mode,
        )
        self._mark_envelope_role(state, "return")
        state = self._ensure_scanner_handoff(
            trip_id,
            state,
            "return",
            adapter_mode=adapter_mode,
        )
        return self._payload(trip_id, state)

    def select_return(self, trip_id: str, option_id: str) -> dict[str, Any]:
        existing = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        self._assert_selectable_flight(existing, option_id)
        state = FlightShortlistService(self._intakes, self._planner, store=self._store).select_flight(
            trip_id,
            option_id,
            selection_kind="return",
        )
        self._mark_envelope_role(state, "return")
        return self._payload(trip_id, state)

    def search_inter_location(
        self,
        trip_id: str,
        *,
        origin_airport: str,
        destination_airport: str,
        departure_date: str = "",
        adapter_mode: str = "auto",
    ) -> dict[str, Any]:
        """Create or refresh a scanner-backed in-trip transfer flight search.

        Inter-location flights are downstream of the locked envelope. They can be
        searched, scanned, and compared, but they never define the trip start/end.
        """
        origin = _iata_or_none(origin_airport)
        destination = _iata_or_none(destination_airport)
        if not origin or not destination:
            raise FlightEnvelopeError(
                "Inter-location flight search requires normalized IATA origin and destination airports."
            )
        state = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        if state is None:
            state = ResearchShortlistState(
                trip_id=trip_id,
                category=ShortlistCategory.FLIGHTS,
                recommendation_summary=(
                    "In-trip transfer flights are scanner-backed research rows until exact itinerary evidence is extracted."
                ),
            )
        option = self._scanner_handoff_option(
            trip_id,
            phase="inter_location",
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            rank=max((item.rank for item in state.flight_options), default=0) + 1,
        )
        state.flight_options = [
            item
            for item in state.flight_options
            if item.option_id != option.option_id
        ]
        state.flight_options.append(option)
        state = self._run_or_record_scanner(
            state,
            option_phase="inter_location",
            adapter_mode=adapter_mode,
            reason=(
                f"No exact API row existed for in-trip flight {origin}-{destination}; "
                "Trippy created a scanner handoff row that must be populated from live evidence."
            ),
        )
        saved = self._store.save(state)
        return self._payload(trip_id, saved)

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
                "scanner_handoff_rows_are_not_selectable_until_exact_evidence_exists": True,
            },
        }
        return {
            "flight_flow": flow,
            "shortlist": state.model_dump(mode="json") if state else None,
        }

    def _ensure_scanner_handoff(
        self,
        trip_id: str,
        state: ResearchShortlistState,
        phase: FlightRoutePhase,
        *,
        adapter_mode: str,
    ) -> ResearchShortlistState:
        route_options = self._options_for_phase(state, phase)
        if route_options and any(not self._is_scanner_handoff(option) for option in route_options):
            return state

        route = self._route_for_phase(trip_id, state, phase)
        if route is None:
            state.warnings.append(
                f"No scanner route was created for {phase} flights because normalized airport codes were not available."
            )
            return state

        origin, destination, departure_date = route
        if not route_options:
            state.flight_options.append(
                self._scanner_handoff_option(
                    trip_id,
                    phase=phase,
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    rank=max((item.rank for item in state.flight_options), default=0) + 1,
                )
            )
        return self._run_or_record_scanner(
            state,
            option_phase=phase,
            adapter_mode=adapter_mode,
            reason=(
                f"Configured flight APIs returned no exact {phase} rows for {origin}-{destination}; "
                "Trippy used the scanner fallback path without inventing airline, fare, timing, or booking data."
            ),
        )

    def _run_or_record_scanner(
        self,
        state: ResearchShortlistState,
        *,
        option_phase: FlightRoutePhase,
        adapter_mode: str,
        reason: str,
    ) -> ResearchShortlistState:
        artifacts = dict(state.artifacts or {})
        scanner = dict(artifacts.get("scanner_fallback") or {})
        scanner.setdefault("routes", [])
        scanner["routes"].append(
            {
                "phase": option_phase,
                "status": "attempted" if scanner_fallback_available() else "unavailable",
                "reason": reason,
                "data_policy": "exact_facts_only_no_generated_flight_details",
            }
        )
        artifacts["scanner_fallback"] = scanner
        state.artifacts = artifacts
        state.next_actions = _dedupe(
            [
                "Scanner rows are search tasks, not bookable recommendations, until live itinerary evidence fills exact fields.",
                *state.next_actions,
            ]
        )
        if not scanner_fallback_available():
            state.warnings.append(
                "No exact flight rows were returned, and Firecrawl/OpenClaw scanner fallback is not configured or reachable. No made-up flight data was generated."
            )
            return state
        return run_scanner_fallback(
            state,
            adapter_mode=adapter_mode,
            reason=reason,
        )

    def _scanner_handoff_option(
        self,
        trip_id: str,
        *,
        phase: FlightRoutePhase,
        origin: str,
        destination: str,
        departure_date: str = "",
        rank: int,
    ) -> FlightOption:
        option_id = f"scanner-{phase}-{origin}-{destination}"
        deep_link = _flight_search_url(origin, destination, departure_date)
        return FlightOption(
            option_id=option_id,
            rank=rank,
            airline="Flight scanner handoff — exact evidence required",
            flight_numbers=[],
            flight_phase=phase,
            departure_date=departure_date,
            arrival_date="",
            departure_airport=origin,
            arrival_airport=destination,
            departure_time="source evidence required",
            arrival_time="source evidence required",
            stops=0,
            layover_airports=[],
            total_travel_duration="source evidence required",
            timing_fit=(
                "Not selectable yet. Firecrawl/OpenClaw or a live API must extract exact itinerary evidence first."
            ),
            recommendation_label="Scanner handoff",
            recommendation_rationale=(
                "This row prevents empty flight states but does not claim a flight exists. It must be populated from live source evidence before selection."
            ),
            planning_next_step="Run scanner fallback or paste an exact itinerary with source evidence.",
            fare_estimate_cad="source evidence required",
            price_band="source evidence required",
            baggage_cabin_notes="source evidence required",
            booking_source="Scanner fallback",
            deep_link=deep_link,
            traveler_count=0,
            traveler_fit="Traveler fit requires exact fare, baggage, seats, and itinerary evidence.",
            comparison_links={"Google Flights search": deep_link},
            aeroplan_relevance="Unknown until carrier and fare class are extracted from source evidence.",
            friction_score=70,
            family_comfort_score=30,
            recommendation_grade=RecommendationGrade.CONDITIONAL,
            tradeoffs=[
                "Created only because exact API rows were unavailable.",
                "Not a recommendation and not selectable until exact source evidence exists.",
            ],
            friction_flags=["Exact flight evidence missing", "Scanner handoff row only"],
            confidence_notes=[
                "No airline, flight number, fare, baggage, timing, or availability has been invented.",
                f"Route: {origin}-{destination}; phase: {phase}; trip: {trip_id}.",
            ],
            live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
            row_status=ShortlistRowStatus.RESEARCHED,
            validation=SourceValidation(
                source_name="Flight scanner fallback",
                source_type=SourceType.SEARCH_HANDOFF,
                verification_status=VerificationStatus.MANUAL_REQUIRED,
                confidence=0.15,
                evidence_url=deep_link,
                adapter_used="firecrawl/openclaw pending",
                missing_fields=list(_SCANNER_REQUIRED_FIELDS),
                notes=[
                    "Scanner handoff row only. It is blocked from flight selection until exact source evidence is extracted."
                ],
            ),
        )

    def _route_for_phase(
        self,
        trip_id: str,
        state: ResearchShortlistState,
        phase: FlightRoutePhase,
    ) -> tuple[str, str, str] | None:
        if phase == "return":
            departure = self._selected_departure(state)
            if departure is None:
                return None
            origin = _iata_or_none(departure.arrival_airport)
            destination = _iata_or_none(departure.departure_airport)
            return_date = _intake_end_date(self._intakes.load(trip_id))
            if origin and destination:
                return (origin, destination, return_date)
            return None

        if phase == "inter_location":
            return None

        intake = self._intakes.load(trip_id)
        if intake is None:
            return None
        profile = profile_for_intake(intake)
        origin = _iata_or_none(intake.departure_airports[0] if intake.departure_airports else "")
        destination = _iata_or_none(profile.gateway_airports[0] if profile.gateway_airports else "")
        if origin and destination:
            return (origin, destination, _intake_start_date(intake))
        return None

    def _options_for_phase(
        self,
        state: ResearchShortlistState,
        phase: FlightRoutePhase,
    ) -> list[FlightOption]:
        if phase == "departure":
            return self._departure_options(state)
        if phase == "return":
            return self._return_options(state)
        return self._inter_location_options(state)

    def _assert_selectable_flight(
        self,
        state: ResearchShortlistState | None,
        option_id: str,
    ) -> None:
        if state is None:
            return
        option = next((item for item in state.flight_options if item.option_id == option_id), None)
        if option is None:
            return
        if self._is_scanner_handoff(option):
            raise FlightEnvelopeError(
                "This is a scanner handoff row, not an exact flight. Run Firecrawl/OpenClaw extraction or paste an exact itinerary before selecting it."
            )

    def _is_scanner_handoff(self, option: FlightOption) -> bool:
        if not option.option_id.startswith("scanner-"):
            return False
        if option.validation.verification_status == VerificationStatus.LIVE_VERIFIED:
            return False
        if any("evidence required" in value.lower() for value in (
            option.departure_time,
            option.arrival_time,
            option.total_travel_duration,
            option.fare_estimate_cad,
            option.price_band,
        )):
            return True
        return bool(option.validation.missing_fields)

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
            "scanner_handoff_policy": "exact_evidence_required_no_made_up_flight_data",
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
            if match and not self._is_scanner_handoff(match):
                return match
        return next(
            (
                option
                for option in self._departure_options(state)
                if option.row_status == ShortlistRowStatus.APPROVED
                and not self._is_scanner_handoff(option)
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
        match = next((option for option in self._return_options(state) if option.option_id == option_id), None)
        if match and not self._is_scanner_handoff(match):
            return match
        return None

    def _option_json(self, option: FlightOption | None) -> dict[str, Any] | None:
        return option.model_dump(mode="json") if option is not None else None

    def _next_action(self, phase: FlightFlowPhase) -> str:
        if phase == "departure_required":
            return "Search and choose a departure flight."
        if phase == "return_required":
            return "Search and choose a return flight based on the selected departure."
        return "Flight envelope is locked; continue to stays. Inter-location flights can be planned later inside this envelope."


def _iata_or_none(value: str) -> str | None:
    candidate = (value or "").strip().upper()
    return candidate if _IATA_PATTERN.fullmatch(candidate) else None


def _flight_search_url(origin: str, destination: str, departure_date: str = "") -> str:
    query = f"flights {origin} to {destination}"
    if departure_date:
        query += f" {departure_date}"
    return "https://www.google.com/travel/flights/search?q=" + quote_plus(query) + "&hl=en-CA&gl=ca&curr=CAD"


def _intake_start_date(intake: Any | None) -> str:
    window = getattr(intake, "travel_window", None)
    value = getattr(window, "start_date", None)
    return value.isoformat() if value else ""


def _intake_end_date(intake: Any | None) -> str:
    window = getattr(intake, "travel_window", None)
    value = getattr(window, "end_date", None)
    return value.isoformat() if value else ""


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
