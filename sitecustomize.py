"""Runtime compatibility hooks for local Trippy development.

The real flight state machine now lives in :mod:`trippy.services.flight_flow`.
This file only wires the existing lightweight local HTTP server to the new
flight-flow endpoints without forcing a large server.py rewrite in this PR.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse


def _install_two_step_return_patch() -> None:
    try:
        import trippy.services.flight_shortlist as flight_shortlist
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
        from trippy.models.sources import TravelSourceCategory
        from trippy.services.flight_trip_envelope import apply_trip_envelope_artifacts
        from trippy.services.shortlist_store import source_plan, source_plan_payload
    except Exception:
        return

    cls = flight_shortlist.FlightShortlistService
    if getattr(cls, "_trippy_two_step_return_patch", False):
        return

    original_build = cls.build

    def patched_build(
        self: Any,
        trip_id: str,
        *,
        flight_phase: str = "departure",
        validate_live: bool | None = None,
        deep_research: bool = False,
        adapter_mode: str = "auto",
    ) -> ResearchShortlistState:
        existing = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        requested_phase = _normalize_phase(flight_phase)
        auto_return = _should_auto_search_return(existing)
        phase = "return" if requested_phase == "return" or auto_return else "departure"
        if phase != "return":
            return original_build(
                self,
                trip_id,
                flight_phase="departure",
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter_mode,
            )
        return _build_return_state(
            self,
            trip_id,
            existing,
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter_mode,
        )

    def _build_return_state(
        self: Any,
        trip_id: str,
        existing: ResearchShortlistState | None,
        *,
        validate_live: bool | None,
        deep_research: bool,
        adapter_mode: str,
    ) -> ResearchShortlistState:
        if existing is None:
            return original_build(
                self,
                trip_id,
                flight_phase="departure",
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter_mode,
            )

        ctx = flight_shortlist.ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        outbound = _selected_outbound(existing)
        if outbound is None:
            return original_build(
                self,
                trip_id,
                flight_phase="departure",
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter_mode,
            )

        live_notes: list[str] = []
        return_options: list[FlightOption] = []
        gateway = (outbound.arrival_airport or "").strip().upper()

        if gateway:
            try:
                return_options, notes = flight_shortlist._duffel_live_options(
                    ctx,
                    gateway,
                    flight_phase="return",
                )
                live_notes.extend(notes)
            except Exception as exc:
                live_notes.append(f"Duffel return search failed: {exc}")

        if not return_options and gateway and hasattr(flight_shortlist, "_serpapi_live_flights"):
            try:
                serp_options, notes = flight_shortlist._serpapi_live_flights(
                    ctx,
                    gateway,
                    flight_phase="return",
                )
                live_notes.extend(notes)
                return_options = serp_options
            except Exception as exc:
                live_notes.append(f"SerpAPI return search failed: {exc}")

        fallback_used = False
        if not return_options:
            return_options = _fallback_return_options(ctx, existing, outbound)
            fallback_used = bool(return_options)
            if fallback_used:
                live_notes.append(
                    "No exact live return offers were returned; created date-specific return search rows from the selected departure and flexible trip window."
                )

        for option in return_options:
            option.flight_phase = "return"

        departure_options = [
            option
            for option in existing.flight_options
            if getattr(option, "flight_phase", "departure") != "return"
        ]
        artifacts = dict(existing.artifacts or {})
        if fallback_used:
            artifacts["return_search"] = _return_search_artifact(ctx, outbound, return_options)

        plan = source_plan(TravelSourceCategory.FLIGHTS)
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.FLIGHTS,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            flight_options=[*departure_options, *return_options],
            recommended_option_id=return_options[0].option_id if return_options else existing.recommended_option_id,
            recommendation_summary=(
                "Return flight options are generated only after a departure is selected. The selected return locks the trip envelope."
            ),
            artifacts=artifacts,
            warnings=[
                "Return search uses the selected departure arrival airport and the home/origin airport.",
                *live_notes,
            ],
            next_actions=[
                "Select a return flight to lock the trip envelope.",
                "Use fallback return search rows only as handoffs until exact airline, time, price, and baggage terms are verified.",
            ],
        )
        try:
            flight_shortlist._refresh_flight_recommendations(state, ctx, preserve_selection=True)
        except TypeError:
            flight_shortlist._refresh_flight_recommendations(state, ctx)
        apply_trip_envelope_artifacts(state)
        return self._store.save(state)

    def _fallback_return_options(
        ctx: Any,
        existing: ResearchShortlistState,
        outbound: FlightOption,
    ) -> list[FlightOption]:
        origin = (outbound.arrival_airport or "").strip().upper()
        destination = (outbound.departure_airport or "").strip().upper()
        if not _looks_like_iata(origin) or not _looks_like_iata(destination):
            return []
        arrival_date = _parse_date(outbound.arrival_date)
        if arrival_date is None:
            return []

        duration_days = _duration_days(ctx)
        base_nights = max(1, duration_days - 1)
        candidate_nights = sorted({base_nights - 1, base_nights, base_nights + 1, base_nights + 2})
        candidate_dates = [arrival_date + timedelta(days=nights) for nights in candidate_nights if nights >= 1]
        candidate_dates = candidate_dates[:5]

        rows: list[FlightOption] = []
        for index, return_date in enumerate(candidate_dates, start=1):
            link = _return_search_link(origin, destination, return_date)
            rows.append(
                FlightOption(
                    option_id=f"return-search-{index}",
                    rank=index,
                    airline=f"Return search · {return_date.isoformat()}",
                    flight_numbers=[],
                    departure_date=return_date.isoformat(),
                    arrival_date=return_date.isoformat(),
                    departure_airport=origin,
                    arrival_airport=destination,
                    departure_time="Open search",
                    arrival_time="Verify time",
                    stops=0,
                    total_travel_duration="provider search required",
                    timing_fit="Open this date-specific return search and choose the best verified option.",
                    timing_implication="Return timing will define final-day checkout, car dropoff, and timeline buffers.",
                    date_viability_signal="candidate return date from selected departure and trip duration window",
                    recommendation_label="Return search option",
                    recommendation_rationale="Fallback date-specific return search generated because no exact live return rows were returned.",
                    planning_next_step="Open search, choose an exact return itinerary, then paste it back if required.",
                    fare_estimate_cad="live quote required",
                    price_band="live quote required",
                    baggage_cabin_notes="Baggage, fare, and seat terms require provider verification.",
                    booking_source="Google Flights search handoff",
                    deep_link=link,
                    traveler_count=ctx.intake.party.total_travelers,
                    traveler_fit=f"Return search for {ctx.intake.party.summary()}.",
                    comparison_links={"Google Flights": link},
                    friction_score=55,
                    family_comfort_score=50,
                    recommendation_grade=RecommendationGrade.CONDITIONAL,
                    tradeoffs=[
                        "Search handoff only; not verified inventory.",
                        "Exact airline, time, price, baggage, and cancellation terms still need confirmation.",
                    ],
                    friction_flags=[
                        "exact return flight not verified yet",
                        "provider search required before booking",
                    ],
                    confidence_notes=[
                        "Generated from selected departure arrival date and trip duration window.",
                    ],
                    flight_phase="return",
                    live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
                    row_status=ShortlistRowStatus.RESEARCHED,
                    validation=SourceValidation(
                        source_name="Google Flights search handoff",
                        source_type=SourceType.SEARCH_HANDOFF,
                        verification_status=VerificationStatus.MANUAL_REQUIRED,
                        confidence=0.25,
                        evidence_url=link,
                        missing_fields=[
                            "exact_return_airline",
                            "exact_return_flight_numbers",
                            "exact_return_departure_time",
                            "exact_return_arrival_time",
                            "exact_return_fare",
                            "baggage_terms",
                        ],
                        notes=["Fallback return search row; not a confirmed live offer."],
                    ),
                )
            )
        return rows

    def _return_search_artifact(
        ctx: Any,
        outbound: FlightOption,
        return_options: list[FlightOption],
    ) -> dict[str, Any]:
        candidate_dates = [option.departure_date for option in return_options if option.departure_date]
        return {
            "based_on_outbound_option_id": outbound.option_id,
            "origin_airport": outbound.arrival_airport,
            "destination_airport": outbound.departure_airport,
            "candidate_return_dates": candidate_dates,
            "flexible_window_used": len(set(candidate_dates)) > 1,
            "source": "runtime_two_step_return_flow",
        }

    def _should_auto_search_return(existing: ResearchShortlistState | None) -> bool:
        if existing is None:
            return False
        selection = existing.artifacts.get("flight_selection") or {}
        return bool(selection.get("selected_outbound_option_id") and not selection.get("selected_return_option_id"))

    def _selected_outbound(existing: ResearchShortlistState) -> FlightOption | None:
        selection = existing.artifacts.get("flight_selection") or {}
        selected_id = str(selection.get("selected_outbound_option_id") or "")
        if selected_id:
            match = next((option for option in existing.flight_options if option.option_id == selected_id), None)
            if match is not None:
                return match
        return next(
            (
                option
                for option in existing.flight_options
                if getattr(option, "flight_phase", "departure") == "departure"
                and option.row_status == ShortlistRowStatus.APPROVED
            ),
            None,
        )

    def _duration_days(ctx: Any) -> int:
        value = getattr(ctx.intake, "duration_days", None) or 7
        try:
            return int(value)
        except (TypeError, ValueError):
            return 7

    def _return_search_link(origin: str, destination: str, return_date: date) -> str:
        return (
            "https://www.google.com/travel/flights/search?"
            f"q={origin}%20to%20{destination}%20{return_date.isoformat()}"
            "&hl=en-CA&gl=ca&curr=CAD"
        )

    def _parse_date(value: str) -> date | None:
        try:
            return date.fromisoformat((value or "").strip())
        except ValueError:
            return None

    def _looks_like_iata(value: str) -> bool:
        return len((value or "").strip()) == 3 and (value or "").strip().isalpha()

    def _normalize_phase(value: str) -> str:
        return "return" if (value or "").strip().lower() in {"return", "inbound", "homebound"} else "departure"

    cls.build = patched_build
    cls._trippy_two_step_return_patch = True


def _install_flight_flow_routes() -> None:
    try:
        import trippy.ui.server as ui_server
        from trippy.services.flight_flow import FlightFlowService
    except Exception:
        return

    for value in vars(ui_server).values():
        if not isinstance(value, type):
            continue
        if not issubclass(value, BaseHTTPRequestHandler):
            continue
        if getattr(value, "_trippy_flight_flow_routes", False):
            continue
        _patch_handler(value, FlightFlowService)


def _patch_handler(handler_cls: type[BaseHTTPRequestHandler], service_cls: type[Any]) -> None:
    original_get = getattr(handler_cls, "do_GET", None)
    original_post = getattr(handler_cls, "do_POST", None)

    def do_GET(self: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/flights/state":
            query = parse_qs(parsed.query)
            trip_id = (query.get("trip_id") or [""])[0]
            _write_json(self, service_cls().get_state(trip_id))
            return
        if original_get is not None:
            return original_get(self)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/flights/"):
            if original_post is not None:
                return original_post(self)
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = _read_json(self)
            trip_id = str(payload.get("trip_id") or "")
            option_id = str(payload.get("option_id") or "")
            service = service_cls()
            if parsed.path == "/api/flights/search-departures":
                result = service.search_departures(
                    trip_id,
                    validate_live=bool(payload.get("validate_live", True)),
                    deep_research=bool(payload.get("deep_research", True)),
                    adapter_mode=str(payload.get("adapter") or "auto"),
                )
            elif parsed.path == "/api/flights/select-departure":
                result = service.select_departure(trip_id, option_id)
            elif parsed.path == "/api/flights/search-returns":
                result = service.search_returns(
                    trip_id,
                    validate_live=bool(payload.get("validate_live", True)),
                    deep_research=bool(payload.get("deep_research", False)),
                    adapter_mode=str(payload.get("adapter") or "auto"),
                )
            elif parsed.path == "/api/flights/select-return":
                result = service.select_return(trip_id, option_id)
            elif parsed.path == "/api/flights/reset-departure":
                result = service.reset_departure(trip_id)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            _write_json(self, result)
        except Exception as exc:
            _write_json(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    handler_cls.do_GET = do_GET
    handler_cls.do_POST = do_POST
    handler_cls._trippy_flight_flow_routes = True


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _write_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
    data = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


_install_two_step_return_patch()
_install_flight_flow_routes()
