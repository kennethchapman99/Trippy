"""Source-aware car rental shortlist generation."""

from __future__ import annotations

from trippy.models.shortlists import (
    CarOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
)
from trippy.models.sources import TravelSourceCategory
from trippy.models.trip_planning import TripIntake
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.live_validation import LiveValidationService
from trippy.services.shortlist_store import (
    ShortlistContext,
    ShortlistStore,
    source_plan,
    source_plan_payload,
    source_search_url,
)
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
    ) -> ResearchShortlistState:
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        profile = profile_for_intake(ctx.intake)
        plan = source_plan(TravelSourceCategory.CAR_RENTALS)
        options = _options_from_profile(profile, ctx.intake)
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
                "Azores driving can be practical, but narrow roads and parking still need local validation.",
            ],
            next_actions=[
                "Open Booking.com car rental search and filter automatic SUV/minivan.",
                "Reject weak cancellation, unclear pickup, and hidden-fee listings.",
                "Cross-check Expedia and Kayak.ca for price and provider consistency.",
            ],
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        return self._store.save(state)


def _options_from_profile(profile: object, intake: TripIntake) -> list[CarOption]:
    targets = getattr(profile, "car_search_targets", [])
    party = intake.party
    traveler_count = party.total_travelers
    sources = ["Booking.com", "Expedia", "Kayak.ca"]
    options: list[CarOption] = []
    for idx, target in enumerate(targets[:5], start=1):
        source = sources[min(idx - 1, len(sources) - 1)]
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
                deep_link=source_search_url(
                    source,
                    str(target["query"]),
                    category=TravelSourceCategory.CAR_RENTALS,
                ),
                comparison_links={
                    "Expedia": source_search_url(
                        "Expedia",
                        str(target["query"]),
                        category=TravelSourceCategory.CAR_RENTALS,
                    ),
                    "Kayak.ca": source_search_url(
                        "Kayak.ca",
                        str(target["query"]),
                        category=TravelSourceCategory.CAR_RENTALS,
                    ),
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
