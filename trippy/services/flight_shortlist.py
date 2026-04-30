"""Source-aware flight shortlist generation."""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from trippy import config
from trippy.models.shortlists import (
    AvailabilityStatus,
    FlightOption,
    FreshnessStatus,
    LiveDataStatus,
    PriceStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
    SourceType,
    SourceValidation,
    VerificationStatus,
)
from trippy.models.sources import TravelSourceCategory
from trippy.services import serpapi_client
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.live_validation import LiveValidationService
from trippy.services.scanner_fallback import run_scanner_fallback, scanner_fallback_available
from trippy.services.serpapi_options import flight_options_from_serpapi
from trippy.services.shortlist_store import (
    ShortlistContext,
    ShortlistStore,
    source_plan,
    source_plan_payload,
)
from trippy.services.source_research import SourceResearchService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class FlightShortlistService:
    """Build deterministic, source-linked flight candidate shortlists."""

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        store: ShortlistStore | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._store = store or ShortlistStore()

    def build(
        self,
        trip_id: str,
        *,
        validate_live: bool | None = None,
        deep_research: bool = False,
        adapter_mode: str = "auto",
    ) -> ResearchShortlistState:
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        plan = source_plan(TravelSourceCategory.FLIGHTS)
        profile = profile_for_intake(ctx.intake)
        gateway = profile.gateway_airports[0] if profile.gateway_airports else ""
        live_options: list[FlightOption] = []
        live_notes: list[str] = []
        if gateway:
            live_options, live_notes = _duffel_live_options(ctx, gateway)
        if not live_options:
            serp_options: list[FlightOption] = []
            serp_notes: list[str] = []
            if gateway:
                serp_options, serp_notes = _serpapi_live_flights(ctx, gateway)
                live_notes = [*live_notes, *serp_notes]
                if serp_options:
                    live_options = serp_options
        options = live_options
        scanner_fallback = bool(gateway and not live_options and scanner_fallback_available())
        if scanner_fallback:
            fallback_option = _scanner_fallback_option(ctx, gateway)
            if fallback_option is not None:
                options = [fallback_option]
        if gateway and not options:
            live_notes.append(
                "No flight options were created because configured flight providers returned no usable live rows; add a user-supplied candidate or configure a live provider."
            )
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.FLIGHTS,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            flight_options=options,
            recommended_option_id=options[0].option_id if options else None,
            recommendation_summary=(
                "Flight options require explicit origin and destination airport codes plus live provider rows or user-supplied itinerary evidence."
            ),
            warnings=[
                (
                    "Live Duffel offers populated exact flight rows."
                    if live_options
                    else "Flight shortlist failed closed; no placeholder flight rows, fares, airlines, or booking links were generated."
                ),
                *live_notes,
                *profile.flight_notes,
            ],
            next_actions=[
                (
                    "Review the live provider offer details, then cross-check the top option in Google Flights."
                    if live_options
                    else "Configure DUFFEL_ACCESS_TOKEN, enable a live flight adapter, or add a flight candidate with exact itinerary text."
                ),
                "Cross-check the same routing on Kayak.ca before booking.",
                "Reject multi-ticket routings unless airport, baggage, and delay protection are clearly acceptable.",
            ],
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        elif scanner_fallback and state.flight_options:
            state = run_scanner_fallback(
                state,
                adapter_mode=adapter_mode,
                reason=(
                    "Configured flight APIs returned no usable rows, so Trippy ran "
                    "Firecrawl/OpenClaw scanner fallback against the route search."
                ),
            )
        _refresh_flight_recommendations(state, ctx)
        return self._store.save(state)

    def add_candidate(
        self,
        trip_id: str,
        *,
        link: str,
        notes: str = "",
        name: str = "",
        validate_live: bool | None = None,
        deep_research: bool = False,
        adapter_mode: str = "auto",
    ) -> ResearchShortlistState:
        """Add a user-supplied flight candidate into the canonical flight shortlist."""
        if not link.strip() and not notes.strip():
            raise ValueError("flight candidate requires a link or notes")
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        option = _user_candidate_option(
            state,
            ctx,
            link=link.strip(),
            notes=notes.strip(),
            name=name.strip(),
        )
        state.flight_options.append(option)
        state.flight_options.sort(key=lambda item: item.rank)
        state.recommendation_summary = (
            state.recommendation_summary
            + " User-supplied flight candidates are scored in the same timing and friction model as sourced options."
        )
        state.next_actions.insert(
            0,
            "Review the user-supplied flight against timing, baggage, fare, layover, and check-in alignment.",
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(
                state,
                adapter_mode=adapter_mode,
                option_ids=[option.option_id],
            )
        _refresh_flight_recommendations(state, ctx)
        return self._store.save(state)

    def select_flight(
        self,
        trip_id: str,
        option_id: str,
        *,
        selection_kind: str = "outbound",
    ) -> ResearchShortlistState:
        """Promote a flight option as a human-preferred outbound or return choice."""
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.FLIGHTS)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        option_ids = {option.option_id for option in state.flight_options}
        if option_id not in option_ids:
            raise ValueError(f"Flight option {option_id!r} was not found for trip {trip_id!r}")
        kind = _normalize_selection_kind(selection_kind)
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
        _refresh_flight_recommendations(state, ctx, preserve_selection=True)
        _write_flight_selection_artifact(state)
        state.next_actions.insert(
            0,
            (
                "Selected departure flight now drives lodging check-in, car pickup, Master Timeline, and date-fit review."
                if kind == "outbound"
                else "Selected return flight now constrains final-night lodging, car dropoff, Master Timeline, and last-day pacing."
            ),
        )
        return self._store.save(state)


def _scanner_fallback_option(
    ctx: ShortlistContext,
    gateway: str,
) -> FlightOption | None:
    origin = _iata_or_text(
        ctx.intake.departure_airports[0] if ctx.intake.departure_airports else "YYZ"
    )
    destination = _iata_or_text(gateway)
    if not _looks_like_iata(origin) or not _looks_like_iata(destination):
        return None
    deep_link = _flight_source_url("Google Flights", origin, destination, ctx)
    return FlightOption(
        option_id="scanner-flight-search-1",
        rank=1,
        airline="Scanner fallback route search",
        flight_numbers=[],
        departure_airport=origin,
        arrival_airport=destination,
        stops=0,
        total_travel_duration="scanner evidence required",
        timing_fit=(
            "Firecrawl/OpenClaw will inspect public route evidence; no exact flight is "
            "trusted until the scanner extracts itinerary facts."
        ),
        fare_estimate_cad="scanner evidence required",
        price_band="scanner evidence required",
        baggage_cabin_notes="Baggage and fare rules require provider evidence.",
        booking_source="Google Flights scanner fallback",
        deep_link=deep_link,
        traveler_count=ctx.intake.party.total_travelers,
        traveler_fit=f"Route search for {ctx.intake.party.total_travelers} traveler(s).",
        comparison_links=_flight_comparison_links(origin, destination, ctx),
        friction_score=55,
        family_comfort_score=45,
        recommendation_grade=RecommendationGrade.CONDITIONAL,
        tradeoffs=[
            "This row exists only to drive scanner fallback after API failure.",
            "Do not treat it as an itinerary until source research extracts flight numbers, timing, fare, and baggage evidence.",
        ],
        friction_flags=["API search returned no usable flight rows"],
        confidence_notes=[
            "Scanner fallback candidate; public source evidence required before recommendation."
        ],
        live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
        validation=SourceValidation(
            source_name="Google Flights scanner fallback",
            source_type=SourceType.LIVE_SEARCH,
            verification_status=VerificationStatus.MANUAL_REQUIRED,
            confidence=0.2,
            evidence_url=deep_link,
            missing_fields=[
                "exact_departure_date",
                "exact_arrival_date",
                "flight_numbers",
                "exact_departure_time",
                "exact_arrival_time",
                "total_duration",
                "exact_fare",
                "fare_rules",
                "baggage_terms",
            ],
            notes=[
                "Generated only because configured live flight APIs returned no usable rows and scanner fallback is configured."
            ],
        ),
    )


def _duffel_live_options(
    ctx: ShortlistContext,
    gateway: str,
) -> tuple[list[FlightOption], list[str]]:
    token = config.DUFFEL_ACCESS_TOKEN.strip()
    if not token:
        return [], ["DUFFEL_ACCESS_TOKEN is not configured, so flight rows are search handoffs."]
    origin = _iata_or_text(
        ctx.intake.departure_airports[0] if ctx.intake.departure_airports else "YYZ"
    )
    destination = _iata_or_text(gateway)
    if not _looks_like_iata(origin) or not _looks_like_iata(destination):
        return [], [
            f"Duffel live search skipped because route codes are not IATA: {origin} to {destination}."
        ]
    departure_date, return_date = _flight_dates(ctx)
    try:
        payload = _duffel_offer_request_payload(
            ctx, origin, destination, departure_date, return_date
        )
        response = _post_duffel_offer_request(token, payload)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return [], [f"Duffel live flight search failed: {exc}"]
    _data = response.get("data")
    _raw_offers = _data.get("offers") if isinstance(_data, dict) else None
    offers: list[dict[str, object]] = (
        [item for item in _raw_offers if isinstance(item, dict)]
        if isinstance(_raw_offers, list)
        else []
    )
    if not offers:
        return [], ["Duffel returned no live offers for this route/date search."]
    comparison = _flight_comparison_links(origin, destination, ctx)
    skipped_sandbox = sum(1 for offer in offers[:8] if _is_duffel_sandbox_offer(offer))
    usable_offers = [offer for offer in offers[:8] if not _is_duffel_sandbox_offer(offer)]
    timing_valid_offers: list[dict[str, object]] = []
    rejected_timing: list[str] = []
    for offer in usable_offers:
        reason = _duffel_offer_timing_rejection_reason(offer)
        if reason:
            rejected_timing.append(reason)
        else:
            timing_valid_offers.append(offer)
    usable_offers = timing_valid_offers
    options = [
        option
        for option in (
            _duffel_offer_to_option(offer, index, ctx, origin, destination, comparison)
            for index, offer in enumerate(usable_offers, start=1)
        )
        if option is not None
    ]
    if not options:
        notes = ["Duffel returned no usable real-carrier offers for this route/date search."]
        if skipped_sandbox:
            notes.append(
                f"Ignored {skipped_sandbox} Duffel sandbox/test offer row(s), including Duffel Airways."
            )
        if rejected_timing:
            notes.append(
                f"Ignored {len(rejected_timing)} Duffel offer row(s) with impossible timing/date spans."
            )
        return [], notes
    notes = [
        f"Duffel returned {len(options)} exact offer row(s) for {origin}-{destination}.",
        "Duffel prices are live offer signals but can expire; verify before booking.",
    ]
    if skipped_sandbox:
        notes.append(
            f"Ignored {skipped_sandbox} Duffel sandbox/test offer row(s), including Duffel Airways."
        )
    if rejected_timing:
        notes.append(
            f"Ignored {len(rejected_timing)} Duffel offer row(s) with impossible timing/date spans."
        )
    return options, notes


def _duffel_offer_request_payload(
    ctx: ShortlistContext,
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date,
) -> dict[str, object]:
    return {
        "data": {
            "slices": [
                {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date.isoformat(),
                },
                {
                    "origin": destination,
                    "destination": origin,
                    "departure_date": return_date.isoformat(),
                },
            ],
            "passengers": _duffel_passengers(ctx),
            "cabin_class": "economy",
            "max_connections": 1,
        }
    }


def _duffel_passengers(ctx: ShortlistContext) -> list[dict[str, object]]:
    party = ctx.intake.party
    passengers: list[dict[str, object]] = []
    passengers.extend({"type": "adult"} for _ in range(max(1, party.adults or 1)))
    child_ages = list(party.child_ages or [])
    for index in range(max(0, party.children)):
        if index < len(child_ages):
            passengers.append({"age": int(child_ages[index])})
        else:
            passengers.append({"type": "child"})
    total = ctx.intake.party.total_travelers or ctx.intake.travelers or len(passengers)
    while len(passengers) < total:
        passengers.append({"type": "adult"})
    return passengers


def _post_duffel_offer_request(token: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        "https://api.duffel.com/air/offer_requests?return_offers=true&supplier_timeout=10000",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Duffel-Version": "v2",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Trippy/0.2 flight-offer-search",
        },
        method="POST",
    )
    with urlopen(request, timeout=max(15, config.SOURCE_RESEARCH_TIMEOUT_SECONDS)) as response:  # noqa: S310 - configured authenticated API endpoint
        result: dict[str, object] = json.loads(response.read().decode("utf-8"))
        return result


def _duffel_offer_to_option(
    offer: dict[str, object],
    rank: int,
    ctx: ShortlistContext,
    origin: str,
    destination: str,
    comparison: dict[str, str],
) -> FlightOption | None:
    _raw_slices = offer.get("slices")
    slices = [item for item in _raw_slices if isinstance(item, dict)] if isinstance(_raw_slices, list) else []
    if not slices:
        return None
    outbound = slices[0]
    _raw_segments = outbound.get("segments")
    segments = [item for item in _raw_segments if isinstance(item, dict)] if isinstance(_raw_segments, list) else []
    if not segments:
        return None
    first = segments[0]
    last = segments[-1]
    flight_numbers = [_segment_flight_number(segment) for segment in segments]
    flight_numbers = [number for number in flight_numbers if number]
    carriers = _segment_carriers(segments)
    airline_logo_url = _segment_airline_logo_url(segments)
    owner = offer.get("owner")
    owner_name = str(owner.get("name") or "") if isinstance(owner, dict) else ""
    airline = " / ".join(carriers) if carriers else owner_name or "Live flight offer"
    departing_at = str(first.get("departing_at") or "")
    arriving_at = str(last.get("arriving_at") or "")
    departure_date, departure_time = _split_duffel_timestamp(departing_at)
    arrival_date, arrival_time = _split_duffel_timestamp(arriving_at)
    stops = max(0, len(segments) - 1)
    layover_airports = [
        str(seg_dest.get("iata_code") or "")
        for segment in segments[:-1]
        if isinstance(seg_dest := segment.get("destination"), dict)
    ]
    layover_airports = [airport for airport in layover_airports if airport]
    layover_duration = _duffel_layover_duration(segments)
    duration = _duffel_duration(outbound, first, last)
    price = _duffel_price(offer)
    google_link = _flight_source_url("Google Flights", origin, destination, ctx)
    offer_id = str(offer.get("id") or f"duffel-offer-{rank}")
    validation = SourceValidation(
        source_name="Duffel",
        source_type=SourceType.LIVE_SEARCH,
        verified_at=datetime.utcnow(),
        freshness_status=FreshnessStatus.CURRENT,
        verification_status=VerificationStatus.LIVE_VERIFIED,
        availability_status=AvailabilityStatus.AVAILABILITY_SIGNAL,
        price_status=PriceStatus.LIVE_SIGNAL if price else PriceStatus.UNKNOWN,
        confidence=0.86,
        evidence_url=f"duffel:{offer_id}",
        adapter_used="duffel",
        extracted_fields={
            "airline": airline,
            "airline_logo_url": airline_logo_url,
            "flight_numbers": flight_numbers,
            "departure_date": departure_date,
            "arrival_date": arrival_date,
            "departure_time": departure_time,
            "arrival_time": arrival_time,
            "total_duration": duration,
            "stops": stops,
            "layover_airports": layover_airports,
            "layover_duration": layover_duration or "",
            "price_signal": price,
            "availability_signal": "live offer returned",
            "offer_id": offer_id,
        },
        notes=[
            "Offer came from Duffel live flight search; fare and inventory can expire.",
            "Cross-check public search links before booking if not purchasing through Duffel.",
        ],
        missing_fields=[],
    )
    friction = min(
        90,
        8 + stops * 16 + (8 if layover_duration and "overnight" in layover_duration.lower() else 0),
    )
    comfort = max(35, 94 - stops * 12)
    return FlightOption(
        option_id=f"duffel-flight-{rank}",
        rank=rank,
        airline=airline,
        airline_logo_url=airline_logo_url,
        flight_numbers=flight_numbers,
        departure_date=departure_date,
        arrival_date=arrival_date,
        departure_airport=_segment_airport(first, "origin") or origin,
        arrival_airport=_segment_airport(last, "destination") or destination,
        departure_time=departure_time,
        arrival_time=arrival_time,
        stops=stops,
        layover_airports=layover_airports,
        layover_duration=layover_duration,
        total_travel_duration=duration,
        timing_fit=_timing_fit(arrival_time, departure_time),
        fare_estimate_cad=price,
        price_band=price,
        baggage_cabin_notes=_duffel_baggage_notes(offer),
        booking_source="Duffel",
        deep_link=google_link,
        traveler_count=ctx.intake.party.total_travelers,
        traveler_fit=f"Live offer for {ctx.intake.party.summary()}; verify fare expiry, baggage, seats, and booking channel.",
        comparison_links={**comparison, "Duffel offer id": offer_id},
        aeroplan_relevance="Verify earning by carrier and fare class before assuming Aeroplan value.",
        friction_score=friction,
        family_comfort_score=comfort,
        recommendation_grade=RecommendationGrade.STRONG if stops == 0 else RecommendationGrade.GOOD,
        tradeoffs=[
            "Specific live offer with flight numbers, times, duration, and fare signal.",
            "Offer may expire or reprice before booking.",
        ],
        friction_flags=_planning_timing_flags_for_values(stops, layover_duration),
        confidence_notes=[
            "Exact itinerary fields came from Duffel offer segments.",
            f"Duffel offer id: {offer_id}",
        ],
        live_data_status=LiveDataStatus.LIVE_VERIFIED,
        row_status=ShortlistRowStatus.VERIFIED_LIVE,
        validation=validation,
    )


def _user_candidate_option(
    state: ResearchShortlistState,
    ctx: ShortlistContext,
    *,
    link: str,
    notes: str,
    name: str,
) -> FlightOption:
    intake = ctx.intake
    origin = intake.departure_airports[0] if intake.departure_airports else "origin TBD"
    destination = _destination_gateway(ctx, notes)
    traveler_count = intake.party.total_travelers
    lower = f"{name} {link} {notes}".lower()
    stops = _stops_from_notes(lower)
    layovers = _layovers_from_notes(notes)
    duration = _duration_from_notes(notes) or "duration not supplied"
    departure = _time_from_notes(notes, ["depart", "departure", "leaves", "outbound"])
    arrival = _time_from_notes(notes, ["arrive", "arrival", "lands"])
    departure_date = _date_from_notes(notes, ["depart", "departure", "outbound", "leave", "leaves"])
    arrival_date = _date_from_notes(notes, ["arrive", "arrival", "lands"])
    price = _price_signal(notes) or "not supplied"
    flags = []
    if stops is None:
        flags.append("stop count not proven")
    elif stops > 1:
        flags.append("multiple stops increase travel-day and baggage friction")
    elif stops == 1 and not layovers:
        flags.append("layover airport and duration not proven")
    if not departure:
        flags.append("departure time not supplied")
    if not arrival:
        flags.append("arrival time not supplied")
    if not price:
        flags.append("fare not supplied")
    if "bag" not in lower and "baggage" not in lower:
        flags.append("baggage terms not supplied")
    if intake.max_travel_time_hours and _duration_hours(duration) > intake.max_travel_time_hours:
        flags.append("total travel time may exceed intake max")
    rank = max((option.rank for option in state.flight_options), default=0) + 1
    option_id = f"user-flight-{rank}"
    source = _source_from_link(link)
    friction = min(90, 16 + len(flags) * 8 + (12 if (stops or 0) > 1 else 0))
    comfort = max(35, 92 - len(flags) * 8 - (10 if (stops or 0) > 1 else 0))
    display_name = (
        name or _airline_from_notes(notes) or _name_from_link(link) or "User flight candidate"
    )
    return FlightOption(
        option_id=option_id,
        rank=rank,
        airline=display_name,
        flight_numbers=_flight_numbers(notes),
        departure_date=departure_date,
        arrival_date=arrival_date,
        departure_airport=origin,
        arrival_airport=destination,
        departure_time=departure or "not supplied",
        arrival_time=arrival or "not supplied",
        stops=stops if stops is not None else 0,
        layover_airports=layovers,
        layover_duration=_layover_duration_from_notes(notes),
        total_travel_duration=duration,
        timing_fit=_timing_fit(arrival, departure),
        fare_estimate_cad=price,
        price_band=price,
        baggage_cabin_notes=_baggage_notes(notes),
        booking_source=source,
        deep_link=link,
        traveler_count=traveler_count,
        traveler_fit=(
            f"User-supplied flight for {intake.party.summary()}; verify timing, fare, baggage, and source evidence."
        ),
        comparison_links=_flight_comparison_links(origin, destination, ctx),
        aeroplan_relevance="User-supplied candidate; verify carrier, fare class, and Aeroplan earning.",
        friction_score=friction,
        family_comfort_score=comfort,
        recommendation_grade=RecommendationGrade.GOOD
        if stops == 0 and len(flags) <= 3
        else RecommendationGrade.CONDITIONAL,
        tradeoffs=[
            "User-supplied option is compared in the same flight model as sourced options.",
            "Promote only after exact schedule, fare, baggage, seats, and connection protection are verified.",
        ],
        friction_flags=flags,
        confidence_notes=[
            "Candidate came from user input, not autonomous sourcing.",
            notes or "No extra user notes supplied.",
        ],
        live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
    )


def _flight_source_url(
    source: str,
    origin: str,
    destination: str,
    ctx: ShortlistContext,
) -> str:
    """Build route-specific flight handoff URLs instead of generic query pages.

    Google Flights ignores the old natural-language ``?q=`` URLs. Its share/search
    links need structured route data, so fuzzy trips receive deterministic placeholder
    dates from the intake window and carry confidence notes explaining that the dates
    must be adjusted before booking.
    """
    origin_code = _iata_or_text(origin)
    destination_code = _iata_or_text(destination)
    if not _looks_like_iata(origin_code) or not _looks_like_iata(destination_code):
        return ""
    departure_date, return_date = _flight_dates(ctx)
    adults = max(1, ctx.intake.party.adults or ctx.intake.party.total_travelers or 1)
    total_travelers = max(1, ctx.intake.party.total_travelers or ctx.intake.travelers or adults)
    if source == "Google Flights":
        tfs = _google_flights_tfs(
            origin_code,
            destination_code,
            departure_date.isoformat(),
            return_date.isoformat(),
            adults=adults,
        )
        return "https://www.google.com/travel/flights/search?" + urlencode(
            {
                "tfs": tfs,
                "tfu": "EgIIACIA",
                "hl": "en-CA",
                "gl": "ca",
                "curr": "CAD",
                "origin": origin_code,
                "destination": destination_code,
                "departure": departure_date.isoformat(),
                "return": return_date.isoformat(),
            }
        )
    if source == "Kayak.ca":
        return (
            "https://www.ca.kayak.com/flights/"
            f"{origin_code}-{destination_code}/{departure_date.isoformat()}/{return_date.isoformat()}"
            f"/{total_travelers}adults?sort=bestflight_a"
        )
    return _flight_source_url("Google Flights", origin_code, destination_code, ctx)


def _flight_comparison_links(
    origin: str,
    destination: str,
    ctx: ShortlistContext,
) -> dict[str, str]:
    """Only expose providers with route URLs that reliably preserve search fields."""
    links = {
        "Google Flights": _flight_source_url("Google Flights", origin, destination, ctx),
        "Kayak.ca": _flight_source_url("Kayak.ca", origin, destination, ctx),
    }
    return {source: url for source, url in links.items() if url}


def _looks_like_iata(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", value.strip().upper()))


def _segment_flight_number(segment: dict[str, object]) -> str:
    carrier = segment.get("marketing_carrier")
    carrier_code = ""
    if isinstance(carrier, dict):
        carrier_code = str(carrier.get("iata_code") or "")
    number = str(
        segment.get("marketing_carrier_flight_number") or segment.get("flight_number") or ""
    )
    return f"{carrier_code}{number}".strip().upper() if number else ""


def _segment_carriers(segments: list[dict[str, object]]) -> list[str]:
    carriers: list[str] = []
    for segment in segments:
        carrier = segment.get("operating_carrier") or segment.get("marketing_carrier")
        name = ""
        if isinstance(carrier, dict):
            name = str(carrier.get("name") or carrier.get("iata_code") or "")
        if name and name not in carriers:
            carriers.append(name)
    return carriers


def _segment_airline_logo_url(segments: list[dict[str, object]]) -> str:
    for segment in segments:
        for key in ("marketing_carrier", "operating_carrier"):
            carrier = segment.get(key)
            if not isinstance(carrier, dict):
                continue
            for logo_key in ("logo_symbol_url", "logo_lockup_url", "logo_url"):
                logo = str(carrier.get(logo_key) or "")
                if logo:
                    return logo
    return ""


def _is_duffel_sandbox_offer(offer: dict[str, object]) -> bool:
    owner = offer.get("owner")
    owner_name = str(owner.get("name") or "") if isinstance(owner, dict) else ""
    if _is_synthetic_duffel_carrier(owner_name):
        return True
    slices = offer.get("slices")
    raw_segments: list[object] = []
    if isinstance(slices, list):
        for item in slices:
            if isinstance(item, dict):
                segments = item.get("segments")
                if isinstance(segments, list):
                    raw_segments.extend(segments)
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        for carrier_key in ("marketing_carrier", "operating_carrier"):
            carrier = segment.get(carrier_key)
            if not isinstance(carrier, dict):
                continue
            name = str(carrier.get("name") or "")
            iata_code = str(carrier.get("iata_code") or "")
            if _is_synthetic_duffel_carrier(name) or iata_code.upper() == "ZZ":
                return True
    return False


def _duffel_offer_timing_rejection_reason(offer: dict[str, object]) -> str:
    slices = offer.get("slices")
    if not isinstance(slices, list) or not slices:
        return ""
    outbound = slices[0]
    if not isinstance(outbound, dict):
        return ""
    segments = outbound.get("segments")
    if not isinstance(segments, list) or not segments:
        return ""
    typed_segments = [segment for segment in segments if isinstance(segment, dict)]
    if not typed_segments:
        return ""
    first = typed_segments[0]
    last = typed_segments[-1]
    start = _parse_duffel_datetime(str(first.get("departing_at") or ""))
    end = _parse_duffel_datetime(str(last.get("arriving_at") or ""))
    if not start or not end:
        return ""
    elapsed_minutes = int((end - start).total_seconds() // 60)
    if elapsed_minutes <= 0:
        return "arrival timestamp is not after departure timestamp"
    advertised_minutes = _iso_duration_minutes(str(outbound.get("duration") or ""))
    if advertised_minutes and elapsed_minutes - advertised_minutes > 12 * 60:
        return "segment timestamps are inconsistent with slice duration"
    if elapsed_minutes > 72 * 60:
        return "outbound elapsed time exceeds three days"
    return ""


def _is_synthetic_duffel_carrier(value: str) -> bool:
    return "duffel airways" in value.strip().lower()


def _segment_airport(segment: dict[str, object], key: str) -> str:
    airport = segment.get(key)
    if isinstance(airport, dict):
        return str(airport.get("iata_code") or "")
    return ""


def _split_duffel_timestamp(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10], value[11:16] if len(value) >= 16 else ""
    return parsed.date().isoformat(), parsed.strftime("%-I:%M %p")


def _duffel_duration(
    outbound_slice: dict[str, object],
    first_segment: dict[str, object],
    last_segment: dict[str, object],
) -> str:
    duration = str(outbound_slice.get("duration") or "")
    if duration:
        return _format_iso_duration(duration)
    start = _parse_duffel_datetime(str(first_segment.get("departing_at") or ""))
    end = _parse_duffel_datetime(str(last_segment.get("arriving_at") or ""))
    if not start or not end:
        return "duration unavailable"
    return _format_minutes(int((end - start).total_seconds() // 60))


def _duffel_layover_duration(segments: list[dict[str, object]]) -> str | None:
    if len(segments) <= 1:
        return None
    pieces: list[str] = []
    for previous, next_segment in zip(segments, segments[1:], strict=False):
        arrival = _parse_duffel_datetime(str(previous.get("arriving_at") or ""))
        departure = _parse_duffel_datetime(str(next_segment.get("departing_at") or ""))
        airport = ""
        destination = previous.get("destination")
        if isinstance(destination, dict):
            airport = str(destination.get("iata_code") or "")
        if arrival and departure:
            pieces.append(
                f"{airport} {_format_minutes(int((departure - arrival).total_seconds() // 60))}".strip()
            )
    return ", ".join(pieces) or None


def _parse_duffel_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_iso_duration(value: str) -> str:
    total_minutes = _iso_duration_minutes(value)
    if not total_minutes:
        return value
    return _format_minutes(total_minutes)


def _iso_duration_minutes(value: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?", value)
    if not match:
        return 0
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    return days * 24 * 60 + hours * 60 + minutes


def _format_minutes(total_minutes: int) -> str:
    if total_minutes <= 0:
        return "duration unavailable"
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _duffel_price(offer: dict[str, object]) -> str:
    amount = str(offer.get("total_amount") or "")
    currency = str(offer.get("total_currency") or "")
    if not amount:
        return "live fare returned; amount unavailable"
    if currency.upper() == "CAD":
        return f"CAD {amount} total"
    return f"{currency} {amount} total".strip()


def _duffel_baggage_notes(offer: dict[str, object]) -> str:
    conditions = offer.get("conditions")
    notes: list[str] = []
    if isinstance(conditions, dict):
        for key in ("refund_before_departure", "change_before_departure"):
            value = conditions.get(key)
            if isinstance(value, dict) and value.get("allowed") is not None:
                notes.append(
                    f"{key.replace('_', ' ')}: {'allowed' if value.get('allowed') else 'not allowed'}"
                )
    return (
        "; ".join(notes) or "Validate bags, seats, fare rules, and family seating before booking."
    )


def _planning_timing_flags_for_values(stops: int, layover_duration: str | None) -> list[str]:
    flags: list[str] = []
    if stops > 1:
        flags.append("multiple connections increase travel-day friction")
    elif stops == 1:
        flags.append("connection timing must be checked against family luggage and delay risk")
    if layover_duration and "overnight" in layover_duration.lower():
        flags.append("overnight layover requires lodging plan")
    return flags


def _flight_date_hint(ctx: ShortlistContext) -> str:
    window = ctx.intake.travel_window
    if window.start_date and window.end_date:
        return "Source links use the exact intake date range."
    departure_date, return_date = _flight_dates(ctx)
    return (
        "Source links use placeholder search dates "
        f"{departure_date.isoformat()} to {return_date.isoformat()} from the fuzzy intake window; "
        "adjust dates in the source before treating fares as real."
    )


def _google_flights_tfs(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    *,
    adults: int,
) -> str:
    """Build the Google Flights ``tfs`` search payload for a basic round trip.

    Google ignores readable natural-language query params on the flights page.
    The accepted handoff is a URL-safe protobuf blob; this encoder intentionally
    stays narrow and only represents facts Trippy knows: route, dates, economy,
    and adult passenger count.
    """
    info = (
        _protobuf_varint_field(1, 28)
        + _protobuf_varint_field(2, 2)
        + _protobuf_len_field(3, _google_flight_leg(departure_date, origin, destination))
        + _protobuf_len_field(3, _google_flight_leg(return_date, destination, origin))
    )
    for _ in range(max(1, adults)):
        info += _protobuf_varint_field(8, 1)
    info += _protobuf_varint_field(9, 1)  # economy
    info += _protobuf_varint_field(14, 1)
    info += _protobuf_len_field(16, b"\x08" + b"\xff" * 9 + b"\x01")
    info += _protobuf_varint_field(19, 1)  # round trip
    return base64.urlsafe_b64encode(info).rstrip(b"=").decode("ascii")


def _google_flight_leg(leg_date: str, origin: str, destination: str) -> bytes:
    return (
        _protobuf_len_field(2, leg_date.encode())
        + _protobuf_len_field(13, _google_airport(origin))
        + _protobuf_len_field(14, _google_airport(destination))
    )


def _google_airport(code: str) -> bytes:
    return _protobuf_varint_field(1, 1) + _protobuf_len_field(2, code.upper().encode())


def _protobuf_varint_field(field_no: int, value: int) -> bytes:
    return _protobuf_varint((field_no << 3) | 0) + _protobuf_varint(value)


def _protobuf_len_field(field_no: int, value: bytes) -> bytes:
    return _protobuf_varint((field_no << 3) | 2) + _protobuf_varint(len(value)) + value


def _protobuf_varint(value: int) -> bytes:
    chunks: list[int] = []
    while value > 0x7F:
        chunks.append((value & 0x7F) | 0x80)
        value >>= 7
    chunks.append(value & 0x7F)
    return bytes(chunks)


def _flight_dates(ctx: ShortlistContext) -> tuple[date, date]:
    window = ctx.intake.travel_window
    has_exact_start = window.start_date is not None
    departure_date = window.start_date or _representative_departure_date(window.display())
    if not has_exact_start:
        minimum_search_date = date.today() + timedelta(days=30)
        while departure_date < minimum_search_date:
            departure_date = date(departure_date.year + 1, departure_date.month, departure_date.day)
    duration_days = (
        ctx.intake.duration_days or ctx.intake.duration_min_days or ctx.option.duration_days or 7
    )
    if window.end_date and window.start_date:
        return_date = window.end_date
    else:
        return_date = departure_date + timedelta(days=max(1, duration_days))
    if return_date <= departure_date:
        return_date = departure_date + timedelta(days=max(1, duration_days))
    return departure_date, return_date


def _representative_departure_date(label: str) -> date:
    cleaned = label.lower()
    year_match = re.search(r"\b(20\d{2})\b", cleaned)
    year = int(year_match.group(1)) if year_match else date.today().year
    month_lookup = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month_positions = [
        (match.start(), month)
        for name, month in month_lookup.items()
        if (match := re.search(rf"\b{name}\b", cleaned))
    ]
    if not month_positions:
        return date(year, 6, 15)
    index, month = min(month_positions, key=lambda item: item[0])
    nearby = cleaned[max(0, index - 18) : index + 24]
    if "late" in nearby:
        day = 24
    elif "early" in nearby:
        day = 5
    elif "mid" in nearby:
        day = 15
    else:
        day = 15
    return date(year, month, day)


def _iata_or_text(value: str) -> str:
    cleaned = value.strip().upper()
    if _looks_like_iata(cleaned):
        return cleaned
    return "DESTINATION_AIRPORT_REQUIRED"


def _refresh_flight_recommendations(
    state: ResearchShortlistState,
    ctx: ShortlistContext,
    *,
    preserve_selection: bool = False,
) -> None:
    """Keep recommendation labels and trip-fit reasoning in canonical flight state."""
    if not state.flight_options:
        return
    scored = sorted(
        state.flight_options,
        key=lambda option: _recommendation_score(option, ctx),
        reverse=True,
    )
    best = (
        next(
            (
                option
                for option in state.flight_options
                if option.option_id == state.recommended_option_id
            ),
            None,
        )
        if preserve_selection and state.recommended_option_id
        else scored[0]
    )
    if best is None:
        best = scored[0]
    runner = next((option for option in scored if option.option_id != best.option_id), None)
    priced = [option for option in state.flight_options if _price_amount(option.price_band) > 0]
    budget_best = min(priced, key=lambda option: _price_amount(option.price_band), default=None)
    durations = [
        option
        for option in state.flight_options
        if _duration_hours(option.total_travel_duration) > 0
    ]
    shortest = min(
        durations, key=lambda option: _duration_hours(option.total_travel_duration), default=None
    )
    lowest_friction = min(state.flight_options, key=lambda option: option.friction_score)
    state.recommended_option_id = best.option_id
    for option in state.flight_options:
        labels: list[str] = []
        if option.option_id == best.option_id:
            labels.append("Selected" if preserve_selection else "Recommended")
        if runner and option.option_id == runner.option_id:
            labels.append("Runner-up")
        if (
            budget_best
            and option.option_id == budget_best.option_id
            and option.option_id != best.option_id
        ):
            labels.append("Budget-best")
        if (
            shortest
            and option.option_id == shortest.option_id
            and option.option_id != best.option_id
        ):
            labels.append("Shortest")
        if (
            lowest_friction.option_id == option.option_id
            and option.option_id != best.option_id
            and "Shortest" not in labels
        ):
            labels.append("Lowest-friction")
        option.recommendation_label = (
            " · ".join(labels) or option.recommendation_grade.value.title()
        )
        option.recommendation_rationale = _recommendation_rationale(
            option,
            ctx,
            is_best=option.option_id == best.option_id,
            best=best,
        )
        option.timing_implication = _timing_implication(option)
        option.date_viability_signal = _date_viability_signal(ctx, option)
        option.planning_next_step = _flight_next_step(option)
        option.friction_flags = _dedupe_flags(
            [*option.friction_flags, *_planning_timing_flags(option)]
        )
    state.flight_options.sort(
        key=lambda option: (
            option.option_id != state.recommended_option_id,
            option.row_status.value != ShortlistRowStatus.APPROVED.value,
            -_recommendation_score(option, ctx),
            option.rank,
        )
    )
    for index, option in enumerate(state.flight_options, start=1):
        option.rank = index
    state.recommendation_summary = _flight_summary(best, runner, ctx)
    state.artifacts["flight_recommendation"] = {
        "recommended_option_id": best.option_id,
        "recommended_label": best.recommendation_label,
        "rationale": best.recommendation_rationale,
        "timing_implication": best.timing_implication,
        "date_viability_signal": best.date_viability_signal,
        "runner_up_option_id": runner.option_id if runner else "",
        "budget_best_option_id": budget_best.option_id if budget_best else "",
        "shortest_option_id": shortest.option_id if shortest else "",
        "lowest_friction_option_id": lowest_friction.option_id,
    }
    _write_flight_selection_artifact(state)


def _normalize_selection_kind(value: str) -> str:
    normalized = (value or "outbound").strip().lower()
    if normalized in {"return", "inbound", "homebound"}:
        return "return"
    return "outbound"


def _write_flight_selection_artifact(state: ResearchShortlistState) -> None:
    selection = dict(state.artifacts.get("flight_selection") or {})
    outbound_id = selection.get("selected_outbound_option_id") or ""
    return_id = selection.get("selected_return_option_id") or ""
    outbound = _flight_option_by_id(state, str(outbound_id)) if outbound_id else None
    return_flight = _flight_option_by_id(state, str(return_id)) if return_id else None

    if outbound:
        outbound.row_status = ShortlistRowStatus.APPROVED
        outbound.recommendation_label = _selection_label(outbound.recommendation_label, "Departure")
    if return_flight:
        return_flight.row_status = ShortlistRowStatus.APPROVED
        return_flight.recommendation_label = _selection_label(return_flight.recommendation_label, "Return")

    selection.update(
        {
            "selected_outbound_option_id": outbound.option_id if outbound else "",
            "selected_return_option_id": return_flight.option_id if return_flight else "",
            "outbound_summary": _selection_summary(outbound),
            "return_summary": _selection_summary(return_flight),
            "constraint_status": "complete" if outbound and return_flight else "return_needed",
        }
    )
    state.artifacts["flight_selection"] = selection


def _flight_option_by_id(state: ResearchShortlistState, option_id: str) -> FlightOption | None:
    return next((option for option in state.flight_options if option.option_id == option_id), None)


def _selection_label(current: str, prefix: str) -> str:
    parts = [part.strip() for part in (current or "").split("·") if part.strip()]
    parts = [part for part in parts if part not in {"Selected", "Departure selected", "Return selected"}]
    return " · ".join([f"{prefix} selected", *parts])


def _selection_summary(option: FlightOption | None) -> dict[str, str]:
    if option is None:
        return {}
    return {
        "option_id": option.option_id,
        "airline": option.airline,
        "flight_numbers": " + ".join(option.flight_numbers),
        "departure_date": option.departure_date,
        "departure_time": option.departure_time,
        "arrival_date": option.arrival_date,
        "arrival_time": option.arrival_time,
        "route": f"{option.departure_airport} to {option.arrival_airport}",
        "duration": option.total_travel_duration,
        "source": option.booking_source,
    }


def _recommendation_score(option: FlightOption, ctx: ShortlistContext) -> float:
    score = float(option.family_comfort_score - option.friction_score)
    score += option.validation.confidence * 12
    if option.validation.verification_status.value in {
        "live_verified",
        "partial",
        "link_validated",
    }:
        score += 5
    if option.stops == 0:
        score += 8
    if option.stops > 1:
        score -= 12
    duration_hours = _duration_hours(option.total_travel_duration)
    if ctx.intake.max_travel_time_hours and duration_hours > ctx.intake.max_travel_time_hours:
        score -= min(18, (duration_hours - ctx.intake.max_travel_time_hours) * 3)
    if any(
        "multi-ticket" in flag.lower() or "recheck" in flag.lower()
        for flag in option.friction_flags
    ):
        score -= 10
    if option.row_status == ShortlistRowStatus.APPROVED:
        score += 18
    return score


def _recommendation_rationale(
    option: FlightOption,
    ctx: ShortlistContext,
    *,
    is_best: bool,
    best: FlightOption,
) -> str:
    parts: list[str] = []
    if is_best:
        parts.append("Best current fit because it has the strongest comfort-to-friction balance.")
    elif option.friction_score < best.friction_score:
        parts.append(
            "Lower friction than the current top pick, but weaker on overall confidence or comfort."
        )
    elif (
        _price_amount(option.price_band)
        and _price_amount(best.price_band)
        and _price_amount(option.price_band) < _price_amount(best.price_band)
    ):
        parts.append("Potential budget alternative, but the timing/friction tradeoff needs review.")
    if option.stops == 0:
        parts.append("Nonstop shape protects the first day and avoids layover baggage risk.")
    elif option.stops == 1:
        parts.append(
            "One-stop option is workable only if the connection is protected and buffered."
        )
    else:
        parts.append("Multi-stop or unclear routing adds travel-day and baggage uncertainty.")
    arrival_hour = _time_hour(option.arrival_time)
    if arrival_hour is not None and arrival_hour < 11:
        parts.append(
            "Early arrival may require luggage storage, early check-in, or prior-night lodging."
        )
    elif arrival_hour is not None and arrival_hour >= 20:
        parts.append("Late arrival raises car pickup, food, fatigue, and self-check-in risk.")
    duration_hours = _duration_hours(option.total_travel_duration)
    if ctx.intake.duration_max_days and duration_hours >= 10 and ctx.intake.duration_max_days <= 8:
        parts.append(
            "Longer travel time hurts a short trip more than the fare savings may justify."
        )
    if option.validation.confidence < 0.6:
        parts.append(
            "Confidence is still partial; verify exact fare, dates, baggage, and schedule before booking."
        )
    return " ".join(parts)


def _timing_implication(option: FlightOption) -> str:
    arrival_hour = _time_hour(option.arrival_time)
    departure_hour = _time_hour(option.departure_time)
    if arrival_hour is not None and arrival_hour < 11:
        return "Early arrival: check lodging storage/early check-in and keep day one light."
    if arrival_hour is not None and arrival_hour >= 20:
        return "Late arrival: favor simple airport transfer, flexible check-in, and no first-night driving surprises."
    if departure_hour is not None and departure_hour < 8:
        return "Very early departure: protect the last night near the airport or add a larger transfer buffer."
    if option.stops == 0:
        return "Cleanest timing shape if exact dates and fare remain reasonable."
    if option.stops == 1:
        return "Connection timing must preserve baggage, immigration, and first-day energy."
    return "Timing needs full review before shaping lodging or activities around it."


def _date_viability_signal(ctx: ShortlistContext, option: FlightOption) -> str:
    min_days = ctx.intake.duration_min_days or ctx.intake.duration_days
    max_days = ctx.intake.duration_max_days or ctx.intake.duration_days
    if not min_days or not max_days:
        return "Dates need exact flight timing before viability can be ranked."
    duration_hours = _duration_hours(option.total_travel_duration)
    arrival_hour = _time_hour(option.arrival_time)
    short_trip = max_days <= 7
    if duration_hours >= 10 and short_trip:
        return f"Awkward for {min_days}-{max_days} days; prefer the longest span or a lower-friction routing."
    if arrival_hour is not None and (arrival_hour < 11 or arrival_hour >= 20):
        return f"Workable for {min_days}-{max_days} days, best with flexible check-in and a light first day."
    if min_days != max_days:
        return f"Best span: {max(7, min_days) if max_days >= 7 else max_days}-{max_days} days if pricing is similar; shorter spans need cleaner timing."
    return f"Workable for {min_days} days if arrival/check-in and return buffers validate."


def _flight_next_step(option: FlightOption) -> str:
    if option.validation.verification_status.value in {"live_verified", "partial"}:
        return "Cross-check fare rules, bags, seat selection, and date alignment before booking handoff."
    if option.deep_link:
        return "Open source link and deep-verify exact schedule, price, bags, and inventory."
    return "Add a source link or pasted itinerary so Trippy can verify timing and evidence."


def _flight_summary(
    best: FlightOption,
    runner: FlightOption | None,
    ctx: ShortlistContext,
) -> str:
    runner_text = (
        f" Runner-up: {runner.airline} if the tradeoff is worth it." if runner is not None else ""
    )
    date_text = best.date_viability_signal
    return (
        f"Best current flight: {best.airline}. {best.recommendation_rationale} "
        f"{date_text} {runner_text} Trippy is not claiming final fare or inventory until the source evidence proves it."
    )


def _planning_timing_flags(option: FlightOption) -> list[str]:
    flags: list[str] = []
    arrival_hour = _time_hour(option.arrival_time)
    departure_hour = _time_hour(option.departure_time)
    if arrival_hour is not None and arrival_hour < 11:
        flags.append("early arrival/check-in gap")
    if arrival_hour is not None and arrival_hour >= 20:
        flags.append("late arrival transfer/check-in risk")
    if departure_hour is not None and departure_hour < 8:
        flags.append("early departure transfer burden")
    if option.stops > 1:
        flags.append("too many stops for comfort-first planning")
    if option.stops == 1 and not option.layover_duration:
        flags.append("layover duration unknown")
    return flags


def _price_amount(value: str) -> float:
    match = re.search(r"([\d][\d,]*(?:\.\d{2})?)", value or "")
    return float(match.group(1).replace(",", "")) if match else 0.0


def _time_hour(value: str) -> float | None:
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?\b", value or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour + minute / 60


def _dedupe_flags(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _source_from_link(link: str) -> str:
    host = urlparse(link).netloc.lower()
    if "google" in host:
        return "Google Flights"
    if "kayak" in host:
        return "Kayak.ca"
    if "expedia" in host:
        return "Expedia"
    if "flighthub" in host:
        return "Flighthub"
    return "User supplied"


def _name_from_link(link: str) -> str:
    parsed = urlparse(link)
    pieces = [piece for piece in parsed.path.split("/") if piece]
    if pieces:
        return pieces[-1].replace("-", " ").replace("_", " ").title()[:80]
    return parsed.netloc or ""


def _destination_gateway(ctx: ShortlistContext, notes: str) -> str:
    codes: list[str] = [str(code) for code in re.findall(r"\b[A-Z]{3}\b", notes)]
    if len(codes) >= 2:
        return codes[1]
    profile = profile_for_intake(ctx.intake)
    if profile.gateway_airports:
        return str(profile.gateway_airports[0])
    return "DESTINATION_AIRPORT_REQUIRED"


def _stops_from_notes(lower: str) -> int | None:
    if "nonstop" in lower or "non-stop" in lower or "direct" in lower:
        return 0
    match = re.search(r"(\d+)\s+stop", lower)
    return int(match.group(1)) if match else None


def _layovers_from_notes(notes: str) -> list[str]:
    values = []
    for match in re.finditer(
        r"(?:layover|connection|via)\s+(?:in|at|through)?\s*([A-Z]{3})\b",
        notes,
        flags=re.IGNORECASE,
    ):
        value = match.group(1).upper()
        if value not in values:
            values.append(value)
    return values


def _duration_from_notes(notes: str) -> str:
    match = re.search(
        r"(?:duration|travel time|total)\s*(?:is|:|-)?\s*((?:\d+\s?h(?:ours?)?)\s*(?:\d+\s?m(?:in(?:utes?)?)?)?)",
        notes,
        flags=re.IGNORECASE,
    )
    return " ".join(match.group(1).split()) if match and match.group(1).strip() else ""


def _duration_hours(value: str) -> float:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s?h(?:ours?)?\s*(?:(\d+)\s?m(?:in(?:utes?)?)?)?",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0.0
    hours = float(match.group(1))
    minutes = float(match.group(2) or 0)
    return hours + minutes / 60


def _time_from_notes(notes: str, labels: list[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})(?:ure|s|ing)?\s*(?:time)?\s*(?:at|:|-)?\s*(\d{{1,2}}(?::\d{{2}})?\s?(?:AM|PM|am|pm)?)",
        notes,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _date_from_notes(notes: str, labels: list[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})(?:ure|s|ing)?\s*(?:date)?\s*(?:on|:|-)?\s*"
        r"((?:20\d{2}-\d{2}-\d{2})|(?:\d{4}-\d{2}-\d{2})|"
        r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2})|"
        r"(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2}))",
        notes,
        flags=re.IGNORECASE,
    )
    return " ".join(match.group(1).replace(",", "").split()) if match else ""


def _layover_duration_from_notes(notes: str) -> str | None:
    match = re.search(
        r"(?:layover|connection)\s*(?:of|:|-)?\s*((?:\d+\s?h(?:ours?)?)\s*(?:\d+\s?m(?:in(?:utes?)?)?)?)",
        notes,
        flags=re.IGNORECASE,
    )
    return " ".join(match.group(1).split()) if match and match.group(1).strip() else None


def _price_signal(notes: str) -> str:
    match = re.search(
        r"(?:(?:CAD|USD|EUR|CA\$|C\$|US\$|\$|€)\s?[\d][\d,]*(?:\.\d{2})?(?:\s?(?:pp|per person|total))?)",
        notes,
        flags=re.IGNORECASE,
    )
    return match.group(0).strip() if match else ""


def _airline_from_notes(notes: str) -> str:
    for candidate in [
        "SATA",
        "Air Canada",
        "TAP Portugal",
        "United",
        "Delta",
        "WestJet",
        "Porter",
    ]:
        if candidate.lower() in notes.lower():
            return candidate
    return ""


def _flight_numbers(notes: str) -> list[str]:
    values = []
    for match in re.finditer(
        r"\b(?:AC|TP|S4|SATA|UA|DL|WS|PD|AA|LH)\s?-?\s?\d{2,4}\b", notes, flags=re.IGNORECASE
    ):
        value = re.sub(r"\s+", "", match.group(0).upper().replace("-", ""))
        if value not in values:
            values.append(value)
    return values[:4]


def _baggage_notes(notes: str) -> str:
    lower = notes.lower()
    if "checked bag" in lower or "checked baggage" in lower:
        return "User notes mention checked bags; verify included count and fees."
    if "carry-on" in lower or "carry on" in lower:
        return "User notes mention carry-on; verify checked-bag fees before booking."
    return "Baggage/cabin terms not supplied; verify before booking."


def _timing_fit(arrival: str, departure: str) -> str:
    if not arrival and not departure:
        return "Timing not supplied; cannot assess check-in or travel-day friction yet."
    if arrival.lower().endswith("am") or "early" in arrival.lower():
        return "Check early-arrival luggage and lodging access before accepting this option."
    if arrival.lower().endswith("pm"):
        return "Check whether arrival aligns with car pickup, lodging check-in, and first-night access."
    return "Timing supplied by user; validate against source before treating as exact."


def _serpapi_live_flights(
    ctx: ShortlistContext,
    gateway: str,
) -> tuple[list[FlightOption], list[str]]:
    if not serpapi_client.is_configured():
        return [], ["SERPAPI_KEY is not configured, so SerpAPI flight fallback is unavailable."]
    origin = _iata_or_text(ctx.intake.departure_airports[0] if ctx.intake.departure_airports else "YYZ")
    destination = _iata_or_text(gateway)
    if not _looks_like_iata(origin) or not _looks_like_iata(destination):
        return [], [
            f"SerpAPI flight search skipped because route codes are not IATA: {origin} to {destination}."
        ]
    departure_date, return_date = _flight_dates(ctx)
    offers, notes = serpapi_client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        adults=max(1, ctx.intake.party.adults or 1),
        children=max(0, ctx.intake.party.children or 0),
    )
    if not offers:
        return [], notes
    deep_link = _flight_source_url("Google Flights", origin, destination, ctx)
    options = flight_options_from_serpapi(
        offers,
        origin=origin,
        destination=destination,
        deep_link=deep_link,
    )
    return options, notes
