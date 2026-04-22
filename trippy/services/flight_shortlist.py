"""Source-aware flight shortlist generation."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from trippy.models.shortlists import (
    FlightOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
)
from trippy.models.sources import TravelSourceCategory
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.live_validation import LiveValidationService
from trippy.services.shortlist_store import (
    ShortlistContext,
    ShortlistStore,
    source_plan,
    source_plan_payload,
    source_search_url,
    trip_query,
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
        options = _azores_options(
            ctx, profile.gateway_airports[0] if profile.gateway_airports else "destination"
        )
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.FLIGHTS,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            flight_options=options,
            recommended_option_id=options[0].option_id if options else None,
            recommendation_summary=(
                "Start with the lowest-friction same-ticket or nonstop shape, then verify live "
                "availability, fare rules, baggage, seats, and Aeroplan eligibility before handoff."
            ),
            warnings=[
                "Flight numbers and fares are not asserted unless the source link confirms them live.",
                *profile.flight_notes,
            ],
            next_actions=[
                "Open the Google Flights link for the top option and verify exact dates.",
                "Cross-check the same routing on Kayak.ca, Expedia, and Flighthub.",
                "Reject multi-ticket routings unless airport, baggage, and delay protection are clearly acceptable.",
            ],
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(state, adapter_mode=adapter_mode)
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

    def select_flight(self, trip_id: str, option_id: str) -> ResearchShortlistState:
        """Promote a flight option as the current human-preferred planning choice."""
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
        state.recommended_option_id = option_id
        for option in state.flight_options:
            option.row_status = (
                ShortlistRowStatus.APPROVED if option.option_id == option_id else option.row_status
            )
            if option.option_id == option_id:
                option.recommendation_label = "Selected"
                option.planning_next_step = "Use this flight timing to verify lodging check-in, car pickup, and first/last day pacing."
        _refresh_flight_recommendations(state, ctx, preserve_selection=True)
        state.next_actions.insert(
            0,
            "Selected flight now drives lodging check-in, car pickup, Master Timeline, and date-fit review.",
        )
        return self._store.save(state)


def _azores_options(ctx: ShortlistContext, gateway: str) -> list[FlightOption]:
    origin = ctx.intake.departure_airports[0] if ctx.intake.departure_airports else "YYZ"
    traveler_count = ctx.intake.party.total_travelers
    party_note = ctx.intake.party.summary()
    query_base = trip_query(
        ctx.intake,
        f"flights {origin} to {gateway} {traveler_count} travelers",
    )
    comparison = {
        "Kayak.ca": source_search_url("Kayak.ca", query_base),
        "Expedia": source_search_url("Expedia", query_base),
        "Flighthub": source_search_url("Flighthub", query_base),
    }
    return [
        FlightOption(
            option_id="flight-direct-yyz-pdl",
            rank=1,
            airline="Azores Airlines / SATA candidate",
            flight_numbers=[],
            departure_airport=origin,
            arrival_airport=gateway,
            departure_time="target evening departure if nonstop operates",
            arrival_time="target next-morning or same-day arrival; verify check-in gap",
            stops=0,
            layover_airports=[],
            layover_duration=None,
            total_travel_duration="about 5.5-6.5h if seasonal nonstop is operating",
            timing_fit=(
                "Best timing shape if arrival is not stranded before lodging check-in; "
                "consider prior-night lodging if arrival is very early."
            ),
            fare_estimate_cad="live verify; often worth a premium for family smoothness",
            price_band="CAD 900-1,600 pp live-verify band",
            baggage_cabin_notes="Validate included bags, seat selection, and family seating before booking.",
            booking_source="Google Flights",
            deep_link=source_search_url("Google Flights", query_base + " nonstop Azores Airlines"),
            traveler_count=traveler_count,
            traveler_fit=f"Best fit for {party_note}: one plane, no layover, simplest baggage/seat path.",
            comparison_links=comparison,
            aeroplan_relevance="Low/uncertain; verify partner earning before assuming Aeroplan value.",
            friction_score=8,
            family_comfort_score=94,
            recommendation_grade=RecommendationGrade.STRONG,
            tradeoffs=[
                "Likely highest comfort if available because it avoids layover failure and travel-day loss.",
                "May cost more or operate seasonally; price premium can still be rational for a short family trip.",
            ],
            friction_flags=[
                "seasonal availability must be verified",
                "baggage and seat terms unknown",
            ],
            confidence_notes=["This is a source-linked candidate, not a confirmed fare."],
            live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
        ),
        FlightOption(
            option_id="flight-star-alliance-lis-pdl",
            rank=2,
            airline="Air Canada / TAP Portugal same-ticket candidate",
            flight_numbers=[],
            departure_airport=origin,
            arrival_airport=gateway,
            departure_time="target overnight YYZ departure or clean daytime connection",
            arrival_time="target afternoon/evening PDL arrival for check-in alignment",
            stops=1,
            layover_airports=["LIS"],
            layover_duration="target 2-4h, avoid tight Schengen transfer",
            total_travel_duration="about 10-13h depending on Lisbon connection",
            timing_fit="Acceptable only if Lisbon buffer preserves a sane PDL arrival and first-night check-in.",
            fare_estimate_cad="live verify; compare against direct premium",
            price_band="CAD 850-1,500 pp live-verify band",
            baggage_cabin_notes="Prefer same-ticket baggage through-check and long-haul seat selection clarity.",
            booking_source="Google Flights",
            deep_link=source_search_url("Google Flights", query_base + " Air Canada TAP Lisbon"),
            traveler_count=traveler_count,
            traveler_fit=f"Acceptable for {party_note} only with same-ticket baggage and sane Lisbon buffer.",
            comparison_links=comparison,
            aeroplan_relevance="High if booked on eligible Air Canada/TAP Star Alliance fare; verify booking class.",
            friction_score=24,
            family_comfort_score=82,
            recommendation_grade=RecommendationGrade.GOOD,
            tradeoffs=[
                "Aeroplan relevance may offset some friction if the fare is same-ticket and well timed.",
                "Lisbon transfer adds Schengen connection risk and can burn a larger travel day.",
            ],
            friction_flags=[
                "layover timing needs validation",
                "avoid overnight or very tight Lisbon transfer",
            ],
            confidence_notes=[
                "Use as the best backup if nonstop is unavailable or irrationally expensive."
            ],
        ),
        FlightOption(
            option_id="flight-boston-positioning-pdl",
            rank=3,
            airline="Toronto-Boston positioning + Azores gateway candidate",
            flight_numbers=[],
            departure_airport=origin,
            arrival_airport=gateway,
            departure_time="variable; avoid early positioning unless buffer is generous",
            arrival_time="variable; high check-in and fatigue risk if split across tickets",
            stops=1,
            layover_airports=["BOS"],
            layover_duration="requires generous protected buffer or overnight",
            total_travel_duration="variable; often high friction if multi-ticket",
            timing_fit="Weak unless protected routing and lodging timing are both unusually clean.",
            fare_estimate_cad="live verify; only consider with a meaningful upside",
            price_band="CAD 700-1,400 pp live-verify band",
            baggage_cabin_notes="Do not accept unprotected baggage recheck with a tight family connection.",
            booking_source="Kayak.ca",
            deep_link=source_search_url("Kayak.ca", query_base + " via Boston"),
            traveler_count=traveler_count,
            traveler_fit=f"Weak fit for {party_note} unless protected, because luggage/recheck risk scales with party size.",
            comparison_links={
                "Google Flights": source_search_url("Google Flights", query_base + " via Boston"),
                "Expedia": source_search_url("Expedia", query_base + " via Boston"),
            },
            aeroplan_relevance="Possible on the Toronto-Boston leg only; weak overall unless same-ticket.",
            friction_score=48,
            family_comfort_score=62,
            recommendation_grade=RecommendationGrade.CONDITIONAL,
            tradeoffs=[
                "Could be cheaper, but multi-ticket or baggage recheck risk can erase the value.",
                "Only acceptable with protected routing, sane layover, and clear luggage path.",
            ],
            friction_flags=[
                "airport mismatch/recheck risk",
                "delay protection risk",
                "family luggage burden",
            ],
            confidence_notes=["Use mainly as a price sanity check, not default recommendation."],
        ),
    ]


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
        comparison_links={
            "Google Flights": source_search_url(
                "Google Flights",
                trip_query(intake, f"flights {origin} to {destination} {traveler_count} travelers"),
            ),
            "Kayak.ca": source_search_url(
                "Kayak.ca",
                trip_query(intake, f"flights {origin} to {destination} {traveler_count} travelers"),
            ),
        },
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
    return ", ".join(ctx.intake.destination_seeds) or "destination TBD"


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
        "Azores Airlines",
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
