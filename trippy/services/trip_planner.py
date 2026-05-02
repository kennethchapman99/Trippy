"""Deterministic new-trip planning drafts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trippy import config
from trippy.models.ideas import TripIdeaRequest
from trippy.models.trip_planning import (
    TripIntake,
    TripIntakeMode,
    TripPlanDraft,
    TripPlanOption,
)
from trippy.services.country_priors import CountryPriorService
from trippy.services.llm_client import TrippyLLMClient
from trippy.services.planning_advisor import PlanningAdvisorService
from trippy.services.trip_ideation import TripIdeationService
from trippy.services.trip_intake import TripIntakeService


class TripPlannerService:
    """Generate and persist structured planning options from a TripIntake."""

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        drafts_dir: Path | None = None,
        anthropic_client: Any | None = None,
        enabled: bool | None = None,
        model: str | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._dir = drafts_dir or config.PLANS_PATH
        self._country_priors = CountryPriorService()
        self._enabled = config.TRIPPY_TRIP_PLANNER_LLM_ENABLED if enabled is None else enabled
        self._model = model or config.TRIPPY_TRIP_PLANNER_MODEL
        self._llm = TrippyLLMClient(anthropic_client=anthropic_client)

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.draft.json"

    def draft(self, trip_id: str) -> TripPlanDraft:
        intake = self._intakes.require(trip_id)
        draft = self._build_draft(intake)
        draft.advisor = (
            PlanningAdvisorService(enabled=config.TRIPPY_PLANNING_LLM_ENABLED)
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
        if self._enabled:
            draft = self._build_llm_draft(intake)
            if draft is not None and draft.options:
                return draft
            if self._llm.mode == "required":
                raise RuntimeError("Trip planner LLM is required but unavailable")
        if intake.mode == TripIntakeMode.IDEA and intake.destination_seeds:
            return self._build_generic_selected_destination_draft(intake)
        if intake.mode == TripIntakeMode.IDEA:
            return self._build_idea_draft(intake)
        return self._build_generic_selected_destination_draft(intake)

    def _build_llm_draft(self, intake: TripIntake) -> TripPlanDraft | None:
        prompt = _planner_prompt(intake)
        result = self._llm.complete_json(
            service="trip_planner",
            model=self._model,
            prompt=prompt,
            system=(
                "You are Trippy's senior AI trip-planning strategist. Return strict JSON only. "
                "Use source facts only when provided, and mark missing facts as required research."
            ),
            max_tokens=3200,
            trip_id=intake.trip_id,
            prompt_version="trip-planner-v2",
        )
        if result.status != "success" or result.json is None:
            return None
        try:
            payload = result.json
            options = [
                _plan_option_from_llm(item, intake)
                for item in payload.get("options", [])
                if isinstance(item, dict)
            ]
            if not options:
                raise ValueError("Trip planner LLM returned no plan options")
            warnings: list[str] = _string_list(payload.get("warnings"))
            for option in options:
                warnings.extend(_validate_nights(option))
            recommended = str(payload.get("recommended_option_id") or options[0].option_id)
            raw_advisor = payload.get("advisor")
            advisor: dict[str, Any] = raw_advisor if isinstance(raw_advisor, dict) else {}
            advisor.update(
                {
                    "status": payload.get("status") or "llm_success",
                    "model": payload.get("model") or self._model,
                    "raw_response": result.text,
                }
            )
            return TripPlanDraft(
                trip_id=intake.trip_id,
                intake_mode=intake.mode,
                options=options,
                recommended_option_id=recommended,
                assumptions=[
                    "LLM proposed the trip strategy; deterministic code validated basic night allocation.",
                    *warnings,
                ],
                source_notes=[
                    "Generated by LLM planning synthesis without inventing live availability, prices, drive times, or booking facts."
                ],
                advisor=advisor,
            )
        except Exception as exc:
            return TripPlanDraft(
                trip_id=intake.trip_id,
                intake_mode=intake.mode,
                options=[],
                assumptions=[f"Trip planner LLM response failed validation: {exc}"],
                source_notes=["LLM planning failed closed; deterministic fallback may be used by caller."],
                advisor={"status": "llm_unavailable", "model": self._model, "error": str(exc)},
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
        signal = (
            self._country_priors.fit_for_country(geography.country)
            if geography and geography.country
            else None
        )
        signals = [signal.rationale] if signal else []
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
                title=(
                    f"{balanced_regions[0]} + {balanced_regions[1]} Without the Rush"
                    if len(balanced_regions) > 1
                    else f"{destination} With a Second-Base Check"
                ),
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
                title=f"{destination} Best-Of Sampler",
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
                "Enrich TripGeography with scanner evidence before connector-specific searches that require resolved facts.",
            ],
            source_notes=["Generated without live availability."],
        )


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


def _planner_prompt(intake: TripIntake) -> str:
    output_schema = {
        "status": "llm_success",
        "model": "model name",
        "trip_id": intake.trip_id,
        "recommended_option_id": "string",
        "options": [
            {
                "option_id": "string",
                "title": "string",
                "summary": "string",
                "duration_days": 0,
                "regions": ["string"],
                "nights_by_region": {"region": 0},
                "rationale": ["string"],
                "travel_burden": "string",
                "movement_friction": "string",
                "family_comfort_score": 0,
                "food_fit": "string",
                "driving_fit": "string",
                "crowd_fit": "string",
                "major_risks": ["string"],
                "recommendation_strength": 0,
                "lodging_strategy": "string",
                "car_strategy": "string",
                "required_research": ["string"],
                "evidence_needed_before_booking": ["string"],
            }
        ],
        "advisor": {},
        "warnings": ["string"],
    }
    return "\n".join(
        [
            "# Trippy Trip Planner (trip-planner-v2)",
            "Create strategic plan options from this intake, geography, preferences, memory-compatible family defaults, country priors if present, and any selected destination/concept context.",
            "Do not use canned single-base/two-region/full-version templates. Make the option structure fit the actual destination and constraints.",
            "Never invent prices, live availability, booking links, bed layouts, exact drive times, flight numbers, or confirmation facts.",
            "If a fact is not provided, put it in required_research or evidence_needed_before_booking.",
            "",
            "## Intake",
            json.dumps(intake.model_dump(mode="json"), indent=2, sort_keys=True, default=str),
            "",
            "## Output JSON Schema",
            json.dumps(output_schema, indent=2, sort_keys=True),
        ]
    )


def _plan_option_from_llm(item: dict[str, Any], intake: TripIntake) -> TripPlanOption:
    regions = _string_list(item.get("regions")) or [intake.geography.primary_destination_name if intake.geography else intake.trip_name]
    duration = max(1, _int(item.get("duration_days"), intake.duration_days or 8))
    nights_raw = item.get("nights_by_region")
    nights_by_region = (
        {str(k): max(0, _int(v, 0)) for k, v in nights_raw.items()}
        if isinstance(nights_raw, dict)
        else _even_nights(regions, duration)
    )
    required = _string_list(item.get("required_research"))
    required.extend(_string_list(item.get("evidence_needed_before_booking")))
    return TripPlanOption(
        option_id=str(item.get("option_id") or _slug(str(item.get("title") or "llm-plan"))),
        title=str(item.get("title") or "LLM Plan Option"),
        summary=str(item.get("summary") or ""),
        duration_days=duration,
        regions=regions,
        nights_by_region=nights_by_region,
        rationale=_string_list(item.get("rationale")),
        travel_burden=str(item.get("travel_burden") or "requires live flight validation"),
        island_region_movement_friction=str(
            item.get("movement_friction") or item.get("island_region_movement_friction") or ""
        ),
        family_comfort_score=_score(item.get("family_comfort_score")),
        food_fit=str(item.get("food_fit") or "requires source-backed food/location research"),
        driving_fit=str(item.get("driving_fit") or "requires source-backed road/parking research"),
        crowd_fit=str(item.get("crowd_fit") or "requires season and timing research"),
        major_risks=_string_list(item.get("major_risks")),
        recommendation_strength=_score(item.get("recommendation_strength")),
        lodging_strategy=str(item.get("lodging_strategy") or ""),
        car_strategy=str(item.get("car_strategy") or ""),
        country_prior_signals=[],
        map_seed_queries=regions,
        required_research=required or _required_research(),
    )


def _validate_nights(option: TripPlanOption) -> list[str]:
    expected = max(0, option.duration_days - 1)
    actual = sum(option.nights_by_region.values())
    if actual == expected:
        return []
    if option.nights_by_region:
        return [
            f"Option {option.option_id} night allocation sums to {actual}, expected {expected}; verify before booking."
        ]
    return [f"Option {option.option_id} has no night allocation; verify before booking."]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _score(value: Any) -> int:
    return max(0, min(100, _int(value, 0)))


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "llm-plan"
