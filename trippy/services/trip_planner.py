"""Deterministic new-trip planning drafts."""

from __future__ import annotations

import json
from pathlib import Path

from trippy.models.ideas import TripIdeaRequest
from trippy.models.trip_planning import (
    TripIntake,
    TripIntakeMode,
    TripPlanDraft,
    TripPlanOption,
)
from trippy.services.country_priors import CountryPriorService
from trippy.services.planning_advisor import PlanningAdvisorService
from trippy.services.trip_ideation import TripIdeationService
from trippy.services.trip_intake import TripIntakeService


class TripPlannerService:
    """Generate and persist structured planning options from a TripIntake."""

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        drafts_dir: Path | None = None,
    ) -> None:
        from trippy import config

        self._intakes = intake_service or TripIntakeService()
        self._dir = drafts_dir or config.PLANS_PATH
        self._country_priors = CountryPriorService()

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.draft.json"

    def draft(self, trip_id: str) -> TripPlanDraft:
        intake = self._intakes.require(trip_id)
        draft = self._build_draft(intake)
        draft.advisor = (
            PlanningAdvisorService(enabled=False)
            .advise_trip_shape(
                intake,
                draft,
            )
            .model_dump(mode="json")
        )
        self.save_draft(draft)
        return draft

    def save_draft(self, draft: TripPlanDraft) -> TripPlanDraft:
        self._ensure_dir()
        self._path(draft.trip_id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        return draft

    def load_draft(self, trip_id: str) -> TripPlanDraft | None:
        path = self._path(trip_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_loaded_draft(TripPlanDraft.model_validate(data))

    def require_draft(self, trip_id: str) -> TripPlanDraft:
        draft = self.load_draft(trip_id)
        if draft is None:
            return self.draft(trip_id)
        return draft

    def select_option(self, trip_id: str, option_id: str) -> TripPlanDraft:
        draft = self.require_draft(trip_id)
        if not any(option.option_id == option_id for option in draft.options):
            raise ValueError(f"No plan option {option_id!r} for trip {trip_id!r}")
        draft.selected_option_id = option_id
        return self.save_draft(draft)

    def path_for(self, trip_id: str) -> Path:
        return self._path(trip_id)

    def _build_draft(self, intake: TripIntake) -> TripPlanDraft:
        if _is_azores(intake):
            return self._build_azores_draft(intake)
        if intake.mode == TripIntakeMode.IDEA and intake.destination_seeds:
            return self._build_generic_selected_destination_draft(intake)
        if intake.mode == TripIntakeMode.IDEA:
            return self._build_idea_draft(intake)
        return self._build_generic_selected_destination_draft(intake)

    def _build_azores_draft(self, intake: TripIntake) -> TripPlanDraft:
        duration = intake.duration_days or 10
        country_signals = _country_signals(self._country_priors, "Portugal")
        options = [
            _azores_easy_option(duration, country_signals),
            _azores_balanced_option(duration, country_signals),
            _azores_ambitious_option(duration, country_signals),
        ]
        ranked = sorted(options, key=lambda option: option.recommendation_strength, reverse=True)
        return TripPlanDraft(
            trip_id=intake.trip_id,
            intake_mode=intake.mode,
            options=options,
            recommended_option_id=ranked[0].option_id,
            assumptions=[
                "Azores planning starts with deterministic structure before live fares and lodging availability.",
                "Family comfort is weighted above covering every island.",
                "Inter-island movement must be validated against flight/ferry schedules before booking.",
                "Portugal is not yet a historical country-prior entry, so Trippy applies family preference patterns directly and asks for live evidence.",
            ],
            source_notes=[
                "Golden-path scenario: selected destination is Azores, Portugal.",
                "Scores are planning-shape confidence, not live price or booking availability.",
            ],
        )

    def _build_idea_draft(self, intake: TripIntake) -> TripPlanDraft:
        comparison = TripIdeationService().compare(
            TripIdeaRequest(
                time_of_year=intake.travel_window.display(),
                duration_days=intake.duration_days,
                budget_cad=intake.budget_cad,
                travelers=intake.party.total_travelers,
                party_type=intake.party.party_type.value,
                adults=intake.party.adults,
                children=intake.party.children,
                max_flight_hours=intake.max_travel_time_hours,
                direct_flight_preferred=intake.flight_preferences.prefer_direct,
                goals=intake.goals,
                avoid=intake.avoidances,
                desired_vibe=intake.freeform_notes,
            ),
            limit=3,
        )
        options = [
            TripPlanOption(
                option_id=concept.concept_id,
                title=concept.title,
                summary=", ".join(concept.destinations),
                duration_days=concept.recommended_duration_days,
                regions=concept.destinations,
                nights_by_region=_even_nights(
                    concept.destinations, concept.recommended_duration_days
                ),
                rationale=concept.rationale,
                travel_burden=concept.estimated_travel_burden,
                island_region_movement_friction="Requires live validation by exact route and lodging sequence.",
                family_comfort_score=concept.comfort_convenience_score,
                food_fit=f"{concept.food_score}/100 first-pass food fit",
                driving_fit="Favor public transit or private transfers in cities; validate any driving.",
                crowd_fit=f"Crowd risk {concept.crowd_risk}/100; avoid peak crowd windows.",
                major_risks=concept.major_risks,
                recommendation_strength=concept.total_score,
                lodging_strategy="Use family lodging rules: city core boutique hotels, private rentals outside major city cores when practical.",
                car_strategy="Only rent where driving and parking improve comfort.",
                country_prior_signals=concept.country_prior_signals,
                map_seed_queries=concept.destinations,
                required_research=concept.required_research,
            )
            for concept in comparison.concepts
        ]
        return TripPlanDraft(
            trip_id=intake.trip_id,
            intake_mode=intake.mode,
            options=options,
            recommended_option_id=comparison.recommended_concept_id,
            assumptions=comparison.scoring_notes,
            source_notes=["Idea-stage draft generated from existing trip ideation service."],
        )

    def _build_generic_selected_destination_draft(self, intake: TripIntake) -> TripPlanDraft:
        duration = intake.duration_days or 8
        geography = intake.geography
        geography_regions = geography.region_names() if geography else []
        planning_regions = geography_regions or [seed for seed in intake.destination_seeds if seed.strip()]
        destination = (
            geography.primary_destination_name
            if geography and geography.primary_destination_name
            else ", ".join(planning_regions or intake.destination_seeds)
            or intake.trip_name
            or "Destination"
        )
        map_seed_queries = geography.map_seed_queries() if geography else list(intake.destination_seeds)
        single_base_region = planning_regions[0] if planning_regions else destination
        balanced_regions = planning_regions[:2] or [single_base_region]
        signal_sources = [*intake.destination_seeds, destination]
        if geography:
            signal_sources.extend(
                source for source in [geography.country, geography.primary_destination_name] if source
            )
        signals = [
            signal.rationale
            for seed in signal_sources
            for signal in self._country_priors.fit_for_text(seed)
        ]
        if not signals:
            signals = [
                "No direct country prior matched; require live evidence and family-fit validation."
            ]
        fuller_regions = _fuller_regions(planning_regions, single_base_region)
        options = [
            TripPlanOption(
                option_id="single-base-easy",
                title=f"{single_base_region} Single-Base Easy Version",
                summary="Minimize logistics by choosing one strong home base and doing selective day trips.",
                duration_days=duration,
                regions=[single_base_region],
                nights_by_region={single_base_region: max(1, duration - 1)},
                rationale=[
                    f"Lowest movement friction and easiest to make comfortable for {intake.party.summary()}.",
                    "Best first draft when exact transport and lodging options are not yet validated.",
                ],
                travel_burden="requires live flight validation",
                island_region_movement_friction="low if one lodging base works",
                family_comfort_score=82,
                food_fit="Needs destination-specific food cluster research.",
                driving_fit="Rent only if parking and roads are practical.",
                crowd_fit="Use timing and neighborhood/activity choices to avoid large crowds.",
                major_risks=[
                    "May underuse the destination if the best experiences are spread out.",
                    "Exact lodging bed layout and location quality still need validation.",
                ],
                recommendation_strength=78,
                lodging_strategy=intake.lodging_preferences.non_city_strategy,
                car_strategy=intake.car_rental_expectations.notes
                or "Validate car need against local roads, parking, and transfer options.",
                country_prior_signals=signals,
                map_seed_queries=map_seed_queries,
                required_research=_required_research(),
            ),
            TripPlanOption(
                option_id="two-region-balanced",
                title=f"{destination} Two-Region Balanced Version",
                summary="Use two bases to improve coverage while preserving downtime.",
                duration_days=duration,
                regions=balanced_regions,
                nights_by_region=_even_nights(balanced_regions, duration),
                rationale=[
                    "Balances depth with a broader sense of place.",
                    "Usually the best pattern if the trip is at least 8-10 days.",
                ],
                travel_burden="requires live flight and transfer validation",
                island_region_movement_friction="moderate; one mid-trip transition with buffer",
                family_comfort_score=80 if duration >= 8 else 68,
                food_fit="Use the second base only if food/logistics justify the move.",
                driving_fit="Check transfer load and parking before committing.",
                crowd_fit="Can avoid crowds by splitting busy sights across days.",
                major_risks=["Too short a duration can turn the move into wasted trip time."],
                recommendation_strength=82 if duration >= 8 else 64,
                lodging_strategy=intake.lodging_preferences.non_city_strategy,
                car_strategy="Likely local transfer or car rental depending on destination geography.",
                country_prior_signals=signals,
                map_seed_queries=map_seed_queries,
                required_research=_required_research(),
            ),
            TripPlanOption(
                option_id="multi-spot-fuller-version",
                title=f"{destination} Fuller Multi-Spot Version",
                summary="Keep the destination fixed, but spend time across more distinct areas or activity clusters.",
                duration_days=duration,
                regions=fuller_regions,
                nights_by_region=_even_nights(fuller_regions, duration),
                rationale=[
                    "Useful comparison if the family wants more variety within the chosen destination.",
                    "Only worth choosing if each extra stop materially improves beach, food, activity, or drive-time fit.",
                ],
                travel_burden="requires live transfer, drive-time, and lodging validation",
                island_region_movement_friction=(
                    "higher: more local movement and possible extra lodging handoffs"
                ),
                family_comfort_score=76 if duration >= 8 else 66,
                food_fit="Best if the extra areas unlock clearly better meals or easier activity timing.",
                driving_fit="Validate drive times, parking, and whether a single lodging base can cover the same activities.",
                crowd_fit="Can spread busy sights across days, but short stays reduce flexibility.",
                major_risks=[
                    "Can turn a single chosen destination into too many hotel changes or car-transfer days.",
                    "Short trips may be better served by day trips from one strong base.",
                ],
                recommendation_strength=74 if duration >= 8 else 58,
                lodging_strategy=(
                    "Treat as a stress test: use multiple stays only if each lodging move earns its friction cost."
                ),
                car_strategy="Compare rental-car coverage against private transfers and day-trip operators.",
                country_prior_signals=signals,
                map_seed_queries=map_seed_queries,
                required_research=_required_research()
                + [
                    "Whether extra local bases improve the trip enough to justify packing and check-in friction.",
                    "Candidate day-trip version of the same route from one lodging base.",
                ],
            ),
        ]
        recommended = max(options, key=lambda option: option.recommendation_strength).option_id
        return TripPlanDraft(
            trip_id=intake.trip_id,
            intake_mode=intake.mode,
            options=options,
            recommended_option_id=recommended,
            assumptions=[
                "Generic selected-destination draft uses canonical TripGeography so connector inputs separate airports from map/search locations.",
                "Replace with a destination-specific planner once enough evidence exists.",
            ],
            source_notes=["Generated without live availability."],
        )


def _is_azores(intake: TripIntake) -> bool:
    text = " ".join([intake.trip_name, *intake.destination_seeds, intake.freeform_notes or ""])
    return "azores" in text.lower()


def _country_signals(service: CountryPriorService, country: str) -> list[str]:
    fit = service.fit_for_country(country)
    if fit is None:
        return [
            f"No direct historical country prior for {country}; use family rules around food, safety, natural beauty, practical mobility, crowd avoidance, and comfort."
        ]
    return [fit.rationale]


def _azores_easy_option(duration: int, country_signals: list[str]) -> TripPlanOption:
    strength = 88 if duration <= 8 else 82
    return TripPlanOption(
        option_id="azores-sao-miguel-easy",
        title="Azores One-Island Easy Version",
        summary="Base on Sao Miguel, prioritize Ponta Delgada/Furnas/Sete Cidades, and avoid inter-island logistics.",
        duration_days=duration,
        regions=["Sao Miguel"],
        nights_by_region={"Sao Miguel": max(1, duration - 1)},
        rationale=[
            "Best if the goal is a beautiful, low-friction first Azores trip.",
            "One rental car, one lodging base, and fewer packing/airport transitions protects family comfort.",
            "Still gives strong nature, hot springs, coast, food, whale watching, and scenic drives.",
        ],
        travel_burden="meaningful transatlantic trip; verify direct or one-stop YYZ-PDL routing",
        island_region_movement_friction="low: no inter-island flights or ferries",
        family_comfort_score=89,
        food_fit="Good for seafood, cozido in Furnas, Ponta Delgada restaurants, and casual local food.",
        driving_fit="Good if using a comfortable rental car; still vet narrow roads, parking, and night driving.",
        crowd_fit="Generally workable; avoid peak cruise-ship windows and crowded hot springs times.",
        major_risks=[
            "May feel too narrow if the family wants the broader Azores geography.",
            "Car rental fit, luggage capacity, and parking at lodging need validation.",
            "Weather can change quickly; build flexible indoor/short-drive backups.",
        ],
        recommendation_strength=strength,
        lodging_strategy="Choose a safe, practical Sao Miguel base with 3+ beds, king-bed upside if available, parking, and easy food access.",
        car_strategy="Rental car likely useful; prioritize automatic, luggage capacity, clear pickup, and cancellation terms.",
        country_prior_signals=country_signals,
        map_seed_queries=[
            "Ponta Delgada airport",
            "Ponta Delgada family lodging",
            "Furnas Azores",
            "Sete Cidades",
            "Lagoa do Fogo",
            "Sao Miguel whale watching",
            "Ponta Delgada restaurants",
        ],
        required_research=_required_research(),
    )


def _azores_balanced_option(duration: int, country_signals: list[str]) -> TripPlanOption:
    enough_time = duration >= 9
    strength = 91 if enough_time else 70
    return TripPlanOption(
        option_id="azores-two-island-balanced",
        title="Azores Two-Island Balanced Version",
        summary="Use Sao Miguel plus Pico/Faial to get the main-island ease and a second-island adventure without overpacking.",
        duration_days=duration,
        regions=["Sao Miguel", "Pico or Faial"],
        nights_by_region=_balanced_azores_nights(duration),
        rationale=[
            "Best first recommendation for 9-12 days: it materially broadens the trip while preserving downtime.",
            "Sao Miguel provides the easiest base; Pico/Faial adds volcanic landscapes, ocean, wine/food, and a more distinct island feel.",
            "One inter-island move is manageable if flights/ferries are buffered and luggage handling is simple.",
        ],
        travel_burden="meaningful international flight plus one inter-island segment",
        island_region_movement_friction="moderate: one inter-island flight or ferry with weather/schedule buffer",
        family_comfort_score=87 if enough_time else 72,
        food_fit="Strong enough if food clusters are researched in Ponta Delgada plus Horta/Madalena; validate hours and reservations.",
        driving_fit="Good with rental cars on each island; verify road comfort, parking, and pickup/dropoff logistics.",
        crowd_fit="Good: easier to avoid crowd concentrations than a single most-touristed itinerary.",
        major_risks=[
            "Inter-island weather and schedule changes can disrupt the plan; avoid same-day tight flight chains.",
            "Two car rentals and two lodgings increase admin load.",
            "Needs explicit bed-layout validation for family of 5 in both bases.",
        ],
        recommendation_strength=strength,
        lodging_strategy="Two comfortable bases: practical Sao Miguel lodging plus a well-located Pico/Faial stay with 3+ beds and parking.",
        car_strategy="Likely rent cars on both islands; avoid cross-island pickup/dropoff ambiguity and weak cancellation terms.",
        country_prior_signals=country_signals,
        map_seed_queries=[
            "Ponta Delgada airport",
            "Ponta Delgada family lodging",
            "Furnas Azores",
            "Sete Cidades",
            "Pico Island Azores family lodging",
            "Madalena Pico restaurants",
            "Horta Faial marina",
            "Capelinhos Volcano",
        ],
        required_research=_required_research()
        + [
            "Inter-island flight/ferry schedule buffers and backup plan.",
            "Whether Pico or Faial has the better lodging fit for 3+ beds and parking.",
        ],
    )


def _azores_ambitious_option(duration: int, country_signals: list[str]) -> TripPlanOption:
    enough_time = duration >= 12
    strength = 83 if enough_time else 58
    return TripPlanOption(
        option_id="azores-three-island-ambitious",
        title="Azores More Ambitious Version",
        summary="Sao Miguel plus Terceira plus Pico/Faial for a broader Azores sampler if the trip is long enough.",
        duration_days=duration,
        regions=["Sao Miguel", "Terceira", "Pico or Faial"],
        nights_by_region=_three_island_nights(duration),
        rationale=[
            "Works only if the trip is long enough to absorb multiple transitions.",
            "Adds Angra do Heroismo, more food/history, and another island personality.",
            "Useful as an upper-bound comparison, not the default comfort-first recommendation.",
        ],
        travel_burden="high: international flight plus multiple inter-island movements",
        island_region_movement_friction="high unless duration is 12+ days and schedule buffers are strong",
        family_comfort_score=81 if enough_time else 61,
        food_fit="Potentially good, but short stays risk missing the best restaurants and relaxed meals.",
        driving_fit="Several car-rental handoffs; only worth it with clear pickup/dropoff and luggage fit.",
        crowd_fit="Can avoid crowds by spreading sights, but transition days reduce flexibility.",
        major_risks=[
            "Too many moves can waste precious trip time and create stress.",
            "Weather disruption risk compounds across inter-island segments.",
            "Three lodging searches with family bed requirements is a real planning load.",
        ],
        recommendation_strength=strength,
        lodging_strategy="Only pursue if each island has a clear lodging win with 3+ beds, parking, and easy logistics.",
        car_strategy="Use car rentals selectively and compare against transfers/tours on shorter island stays.",
        country_prior_signals=country_signals,
        map_seed_queries=[
            "Ponta Delgada airport",
            "Furnas Azores",
            "Angra do Heroismo restaurants",
            "Terceira family lodging",
            "Pico Island Azores",
            "Horta Faial marina",
            "Azores whale watching",
        ],
        required_research=_required_research()
        + [
            "Exact inter-island route sequencing and weather backup.",
            "Minimum two-night stay per island with no same-day risky connections.",
        ],
    )


def _balanced_azores_nights(duration: int) -> dict[str, int]:
    nights = max(1, duration - 1)
    second = max(3, min(4, nights // 3))
    first = max(1, nights - second)
    return {"Sao Miguel": first, "Pico or Faial": second}


def _three_island_nights(duration: int) -> dict[str, int]:
    nights = max(1, duration - 1)
    sao = max(3, nights - 6)
    terceira = 3 if nights >= 8 else max(1, nights // 3)
    pico_faial = max(1, nights - sao - terceira)
    return {"Sao Miguel": sao, "Terceira": terceira, "Pico or Faial": pico_faial}


def _even_nights(regions: list[str], duration_days: int) -> dict[str, int]:
    if not regions:
        return {}
    nights = max(1, duration_days - 1)
    base = nights // len(regions)
    extra = nights % len(regions)
    return {region: base + (1 if idx < extra else 0) for idx, region in enumerate(regions)}


def _fuller_regions(destination_seeds: list[str], fallback_region: str) -> list[str]:
    regions = destination_seeds[:3]
    if len(regions) >= 3:
        return regions
    if len(regions) == 2:
        return [regions[0], regions[1], f"{regions[0]} day-trip cluster"]
    return [regions[0] if regions else fallback_region]


def _normalize_loaded_draft(draft: TripPlanDraft) -> TripPlanDraft:
    """Repair older generic drafts whose labels and stay regions disagreed."""
    for option in draft.options:
        if option.option_id == "single-base-easy" and len(option.regions) > 1:
            primary = option.regions[0]
            total_nights = sum(option.nights_by_region.values()) or max(
                1, option.duration_days - 1
            )
            option.title = option.title.replace(
                ", ".join(option.regions), primary, 1
            )
            option.regions = [primary]
            option.nights_by_region = {primary: total_nights}
        if option.option_id == "two-region-balanced" and option.nights_by_region:
            option.regions = list(option.nights_by_region)
    return draft


def _required_research() -> list[str]:
    return [
        "Live flight options, total travel time, layovers, baggage, seats, and Aeroplan application.",
        "Exact lodging shortlist with 3+ beds, king-bed upside if possible, parking/access, safe location, and cancellation terms.",
        "Car rental fit for family of 5 plus bags, pickup clarity, hidden fees, and cancellation terms.",
        "Small-group activities/tours with strong review and safety signals.",
        "Entry requirements, passport validity, health precautions, local cash guidance, and weather seasonality.",
    ]
