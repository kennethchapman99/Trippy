"""Source-aware flight shortlist generation."""

from __future__ import annotations

from trippy.models.shortlists import (
    FlightOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
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
            stops=0,
            layover_airports=[],
            layover_duration=None,
            total_travel_duration="about 5.5-6.5h if seasonal nonstop is operating",
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
            stops=1,
            layover_airports=["LIS"],
            layover_duration="target 2-4h, avoid tight Schengen transfer",
            total_travel_duration="about 10-13h depending on Lisbon connection",
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
            stops=1,
            layover_airports=["BOS"],
            layover_duration="requires generous protected buffer or overnight",
            total_travel_duration="variable; often high friction if multi-ticket",
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
