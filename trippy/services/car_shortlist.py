"""Source-aware car rental shortlist generation."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote, urlencode

from trippy.models.shortlists import (
    CarOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
)
from trippy.models.sources import TravelSourceCategory
from trippy.models.trip_planning import TripIntake
from trippy.services import serpapi_client
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.live_validation import LiveValidationService
from trippy.services.scanner_fallback import run_scanner_fallback, scanner_fallback_available
from trippy.services.serpapi_options import car_options_from_serpapi
from trippy.services.shortlist_store import (
    ShortlistContext,
    ShortlistStore,
    source_plan,
    source_plan_payload,
    source_search_url,
    target_matches_selected_regions,
)
from trippy.services.source_research import SourceResearchService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class CarShortlistService:
    """Build family/luggage-aware rental car candidates."""

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
        profile = profile_for_intake(ctx.intake)
        plan = source_plan(TravelSourceCategory.CAR_RENTALS)
        options = _options_from_profile(profile, ctx.intake, ctx.option.regions)
        live_options, live_notes = _serpapi_live_cars(ctx)
        if live_options:
            options = live_options + options
            for index, option in enumerate(options, start=1):
                option.rank = index
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.CARS,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            car_options=options,
            recommended_option_id=options[0].option_id if options else None,
            recommendation_summary=(
                "Use Booking.com first for comparison, then verify final provider terms. "
                "Choose the simplest pickup/dropoff and luggage-safe vehicle over the cheapest ambiguous listing."
            ),
            warnings=[
                "Vehicle model, transmission, luggage capacity, and fees must be confirmed on the live listing.",
                "Driving practicality, road conditions, and parking need local validation from current evidence.",
                *live_notes,
            ],
            next_actions=[
                "Open Booking.com car rental search and filter automatic SUV/minivan.",
                "Reject weak cancellation, unclear pickup, and hidden-fee listings.",
                "Cross-check Expedia and Kayak.ca for price and provider consistency.",
            ],
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        fallback_research = bool(not live_options and scanner_fallback_available())
        if deep_research or fallback_research:
            if fallback_research and not deep_research:
                state = run_scanner_fallback(
                    state,
                    adapter_mode=adapter_mode,
                    reason=(
                        "No live car inventory rows returned, so Trippy ran "
                        "Firecrawl/OpenClaw scanner fallback against date-aware car source links."
                    ),
                )
            else:
                SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        _annotate_flight_envelope_status(state, trip_id, self._store)
        return self._store.save(state)

    def select_car(self, trip_id: str, option_id: str) -> ResearchShortlistState:
        """Approve a car option so it can drive pickup/dropoff planning."""
        state = self._store.load(trip_id, ShortlistCategory.CARS) or self.build(trip_id)
        option = _car_by_id(state, option_id)
        if option is None:
            raise ValueError(f"No car option {option_id!r} for trip {trip_id!r}")
        for candidate in state.car_options:
            if candidate.option_id == option_id:
                candidate.row_status = ShortlistRowStatus.APPROVED
            elif candidate.row_status == ShortlistRowStatus.APPROVED:
                candidate.row_status = ShortlistRowStatus.RESEARCHED
        state.recommended_option_id = option_id
        state.recommendation_summary = (
            f"Selected {option.vehicle_class} from {option.booking_source}. Confirm live price, "
            "provider terms, luggage fit, automatic transmission, deposit, and pickup details before booking."
        )
        state.artifacts["selected_car_option_id"] = option_id
        if (
            "Selected car now drives pickup/dropoff, luggage-fit, parking, and timeline checks."
            not in (state.next_actions)
        ):
            state.next_actions.insert(
                0,
                "Selected car now drives pickup/dropoff, luggage-fit, parking, and timeline checks.",
            )
        return self._store.save(state)


def _options_from_profile(
    profile: object,
    intake: TripIntake,
    selected_regions: list[str],
) -> list[CarOption]:
    targets = [
        target
        for target in getattr(profile, "car_search_targets", [])
        if target_matches_selected_regions(
            target,
            selected_regions,
            getattr(profile, "island_or_region_terms", []),
        )
    ]
    party = intake.party
    traveler_count = party.total_travelers
    sources = ["Booking.com", "Expedia", "Kayak.ca"]
    options: list[CarOption] = []
    for idx, target in enumerate(targets[:5], start=1):
        source = sources[min(idx - 1, len(sources) - 1)]
        deep_link = _car_source_url(source, str(target["query"]), intake)
        expedia_link = _car_source_url("Expedia", str(target["query"]), intake)
        kayak_link = _car_source_url("Kayak.ca", str(target["query"]), intake)
        vehicle_class = str(target["vehicle_class"])
        is_7_seat = "7" in vehicle_class or "van" in vehicle_class.lower()
        seating_capacity = 7 if is_7_seat else 5
        flags = []
        if seating_capacity < traveler_count:
            flags.append(f"vehicle seats {seating_capacity}, below party size {traveler_count}")
        if not is_7_seat and traveler_count >= 5:
            flags.append(f"luggage fit must be proven for {traveler_count} traveler(s)")
        if "Pico" in str(target["name"]) or "Faial" in str(target["name"]):
            flags.append("second-island rental adds handoff/admin load")
        total_friction = 18 + len(flags) * 10
        options.append(
            CarOption(
                option_id=f"car-{idx}",
                rank=idx,
                booking_source=source,
                pickup_location=str(target["pickup"]),
                dropoff_location=str(target["dropoff"]),
                vehicle_class=vehicle_class,
                price_band="live quote required; compare total with taxes and fees",
                current_price_signal="not live-quoted yet",
                seating_capacity=seating_capacity,
                passenger_fit=(
                    f"{traveler_count} traveler(s) fit on seats; comfort depends on exact model"
                    if seating_capacity >= traveler_count
                    else f"{traveler_count} traveler(s) do not fit the stated seating capacity"
                ),
                luggage_fit=(
                    f"best if SUV/minivan explicitly fits {traveler_count} traveler(s) plus bags"
                ),
                cancellation_notes="prefer free cancellation and clear provider terms",
                fees_caution="verify insurance, deposit, airport fees, fuel, mileage, and automatic transmission",
                deep_link=deep_link,
                comparison_links={
                    "Expedia": expedia_link,
                    "Kayak.ca": kayak_link,
                },
                family_comfort_score=88 if is_7_seat else 78,
                luggage_practicality_score=88 if is_7_seat else 70,
                pickup_dropoff_simplicity_score=84 if idx == 1 else 72,
                driving_parking_suitability_score=76,
                total_friction_score=total_friction,
                recommendation_grade=RecommendationGrade.GOOD
                if idx == 1
                else RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    "Bigger vehicle improves family/luggage comfort but can make narrow roads and parking harder.",
                    "Airport pickup is usually simplest; avoid unclear shuttle/offsite pickup with luggage.",
                ],
                friction_flags=flags,
                confidence_notes=[
                    "This is a live-search handoff candidate, not a confirmed vehicle quote."
                ],
                live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
            )
        )
    return options


def _car_by_id(state: ResearchShortlistState, option_id: str) -> CarOption | None:
    return next((option for option in state.car_options if option.option_id == option_id), None)


def _serpapi_live_cars(ctx: ShortlistContext) -> tuple[list[CarOption], list[str]]:
    if not serpapi_client.is_configured():
        return [], ["SERPAPI_KEY is not configured, so car rows are search handoffs."]
    location = (ctx.option.regions[0] if ctx.option.regions else "") or (
        ctx.intake.destination_seeds[0] if ctx.intake.destination_seeds else ""
    )
    if not location:
        return [], ["SerpAPI car search skipped: no destination region on the trip plan yet."]
    pickup, dropoff = _serpapi_car_dates(ctx)
    results, notes = serpapi_client.search_car_rentals(
        location=location,
        pickup_date=pickup,
        return_date=dropoff,
    )
    if not results:
        return [], notes
    deep_link = (
        "https://www.google.com/search?q="
        f"car+rental+{location.replace(' ', '+')}+{pickup.isoformat()}+to+{dropoff.isoformat()}"
    )
    options = car_options_from_serpapi(results, location=location, deep_link=deep_link)
    return options, notes


def _car_source_url(source: str, query: str, intake: TripIntake) -> str:
    pickup, dropoff = _car_dates_for_intake(intake)
    travelers = max(1, intake.party.total_travelers or intake.travelers or 1)
    if source == "Kayak.ca":
        return (
            "https://www.ca.kayak.com/cars/"
            f"{quote(query.strip() or 'rental car', safe='')}/"
            f"{pickup.isoformat()}/{dropoff.isoformat()}?"
            + urlencode({"sort": "rank_a"})
        )
    if source == "Expedia":
        return "https://www.expedia.ca/Cars-Search?" + urlencode(
            {
                "searchProduct": "cars",
                "query": query,
                "pickUpDate": pickup.isoformat(),
                "dropOffDate": dropoff.isoformat(),
                "adults": travelers,
            }
        )
    if source == "Booking.com":
        return "https://www.booking.com/cars/index.html?" + urlencode(
            {
                "ss": query,
                "checkin": pickup.isoformat(),
                "checkout": dropoff.isoformat(),
                "group_adults": travelers,
                "selected_currency": "CAD",
            }
        )
    return source_search_url(
        source,
        f"{query} car rental {pickup.isoformat()} to {dropoff.isoformat()} {travelers} travelers",
        category=TravelSourceCategory.CAR_RENTALS,
    )


def _car_dates_for_intake(intake: TripIntake) -> tuple[date, date]:
    window = intake.travel_window
    if window.start_date and window.end_date:
        return window.start_date, window.end_date
    nights = intake.duration_days or intake.duration_min_days or 7
    if window.start_date:
        return window.start_date, window.start_date + timedelta(days=max(1, nights))
    fallback = date.today() + timedelta(days=60)
    return fallback, fallback + timedelta(days=max(1, nights))


def _serpapi_car_dates(ctx: ShortlistContext) -> tuple[date, date]:
    return _car_dates_for_intake(ctx.intake)


def _annotate_flight_envelope_status(
    state: ResearchShortlistState,
    trip_id: str,
    store: ShortlistStore,
) -> None:
    from trippy.models.shortlists import ShortlistCategory
    from trippy.services.flight_trip_envelope import (
        TripEnvelopeNotLockedError,
        assert_trip_envelope_locked,
    )

    flight_state = store.load(trip_id, ShortlistCategory.FLIGHTS)
    if flight_state is None:
        state.warnings.append(
            "No flight shortlist found; car pickup/dropoff dates are provisional until flights are selected."
        )
        return
    try:
        assert_trip_envelope_locked(flight_state)
    except TripEnvelopeNotLockedError as exc:
        state.warnings.append(
            f"Car dates are provisional: {exc} Select both flights before treating pickup/dropoff as fixed."
        )
