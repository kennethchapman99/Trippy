"""Source-aware lodging shortlist generation."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from trippy.models.shortlists import (
    AvailabilityStatus,
    FreshnessStatus,
    LiveDataStatus,
    LodgingFitCategory,
    LodgingOption,
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
from trippy.models.trip_planning import TripIntake, TripPlanOption
from trippy.models.web_research import WebResearchResult
from trippy.services import serpapi_client
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.firecrawl import FirecrawlService
from trippy.services.live_validation import LiveValidationService
from trippy.services.planning_advisor import PlanningAdvisorService
from trippy.services.scanner_fallback import run_scanner_fallback, scanner_fallback_available
from trippy.services.serpapi_options import lodging_options_from_serpapi
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


class LodgingShortlistService:
    """Build family-fit lodging candidates from destination profile targets."""

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
        category = (
            TravelSourceCategory.PRIVATE_LODGING
            if any("Pico" in region or "Faial" in region for region in ctx.option.regions)
            else TravelSourceCategory.CITY_LODGING
        )
        plan = source_plan(category)
        options = _options_from_profile(profile, ctx.intake, ctx.option.regions)
        options = _dedupe_lodging_options(
            [
                *options,
                *_curated_list_lodging_options(
                    ctx.intake,
                    ctx.option.regions,
                    profile_title=getattr(profile, "title", ""),
                    rank_offset=len(options),
                ),
            ]
        )
        for index, option in enumerate(options, start=1):
            option.rank = index
        requires_three_beds = (
            ctx.intake.party.total_travelers >= 5 or ctx.intake.party.children >= 2
        )
        live_options, live_notes = _serpapi_live_lodging(ctx, requires_three_beds)
        if live_options:
            options = live_options + options
            for index, option in enumerate(options, start=1):
                option.rank = index
        recommended = _recommended_lodging_option_id(options)
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.LODGING,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            lodging_options=options,
            recommended_option_id=recommended,
            recommendation_summary=(
                "Prioritize lodging that proves king-bed comfort, parking/access clarity, and safe practical "
                "location before optimizing price."
                if not requires_three_beds
                else "Prioritize lodging that proves 3+ beds, parking/access clarity, and safe practical "
                "location before optimizing price. Queen-bed compromises remain conditional."
            ),
            warnings=[
                "Airbnb, VRBO, and boutique-hotel list rows are discovery inputs only; Trippy must promote exact properties only after reviewing source evidence, dates, beds, price, location, cancellation, and access.",
                (
                    "Exact room availability, king-bed signal, cancellation, and location/access must be verified live."
                    if not requires_three_beds
                    else "Exact room/rental availability and bed layout must be verified live before recommendation handoff."
                ),
                (
                    "For a couple trip, avoid overpaying for unnecessary space unless the location or experience is exceptional."
                    if not requires_three_beds
                    else "Two-room hotel solutions can work, but only if total comfort beats a private rental."
                ),
                *live_notes,
            ],
            next_actions=[
                (
                    f"Open the recommended option source link and validate occupancy for {ctx.intake.party.total_travelers} traveler(s)."
                    if not requires_three_beds
                    else "Open the recommended option source link and validate 5-person occupancy."
                ),
                (
                    "Confirm king-bed or clearly worthwhile queen-bed tradeoff."
                    if not requires_three_beds
                    else "Reject any option that cannot explicitly prove 3+ beds."
                ),
                "Cross-check location and review/safety signals on Tripadvisor or Booking.com.",
            ],
            artifacts={
                "lodging_structure": _lodging_structure_guidance(ctx.option, ctx.intake),
            },
        )
        advisor = PlanningAdvisorService(enabled=False).advise_lodging_structure(
            ctx.intake,
            ctx.option,
            state,
        )
        state.artifacts["planning_advisor"] = advisor.model_dump(mode="json")
        structure = state.artifacts.get("lodging_structure")
        if isinstance(structure, dict):
            structure["options"] = _stay_structure_options(ctx.option, ctx.intake)
            structure["recommended_structure_id"] = (
                structure["options"][0]["structure_id"] if structure["options"] else ""
            )
            structure["advisor_status"] = advisor.status
            structure["advisor_summary"] = advisor.summary
            if advisor.stay_strategy in {"single_stay", "split_stay", "unclear"}:
                structure["advisor_stay_strategy"] = advisor.stay_strategy
            if advisor.night_plan:
                structure["advisor_night_plan"] = advisor.night_plan
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        fallback_research = bool(
            not live_options and _serpapi_lodging_problem(live_notes) and scanner_fallback_available()
        )
        if deep_research or fallback_research:
            if fallback_research and not deep_research:
                state = run_scanner_fallback(
                    state,
                    adapter_mode=adapter_mode,
                    reason=(
                        "SerpAPI did not return usable lodging rows, so Trippy ran "
                        "Firecrawl/OpenClaw scanner fallback against lodging source links."
                    ),
                )
            else:
                SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        if deep_research:
            _review_lodging_discovery_sources(state, ctx.intake)
            state.recommended_option_id = _recommended_lodging_option_id(state.lodging_options)
        return self._store.save(state)

    def select_lodging(self, trip_id: str, option_id: str) -> ResearchShortlistState:
        """Add a lodging option to the current human-preferred planning set."""
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.LODGING)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        option_ids = {option.option_id for option in state.lodging_options}
        if option_id not in option_ids:
            raise ValueError(f"Lodging option {option_id!r} was not found for trip {trip_id!r}")
        state.recommended_option_id = option_id
        for option in state.lodging_options:
            if option.option_id == option_id:
                option.row_status = ShortlistRowStatus.APPROVED
        structure = state.artifacts.setdefault(
            "lodging_structure",
            _lodging_structure_guidance(ctx.option, ctx.intake),
        )
        if isinstance(structure, dict):
            selected_ids = [
                str(value)
                for value in structure.get("selected_lodging_option_ids", [])
                if isinstance(value, str)
            ]
            legacy_id = structure.get("selected_lodging_option_id")
            if isinstance(legacy_id, str) and legacy_id and legacy_id not in selected_ids:
                selected_ids.append(legacy_id)
            if option_id not in selected_ids:
                selected_ids.append(option_id)
            structure["selected_lodging_option_id"] = option_id
            structure["selected_lodging_option_ids"] = selected_ids
            structure["data_status"] = (
                "manual_lodging_selection"
                if structure.get("data_status") != "manual_override"
                else "manual_override"
            )
        state.next_actions.insert(
            0,
            "Selected lodging now drives stay-structure review, workspace timeline, and map planning. Select additional stays when the trip needs a split, then allocate nights.",
        )
        return self._store.save(state)

    def deselect_lodging(self, trip_id: str, option_id: str) -> ResearchShortlistState:
        """Remove a lodging option from the current human-preferred planning set."""
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.LODGING)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        option_ids = {option.option_id for option in state.lodging_options}
        if option_id not in option_ids:
            raise ValueError(f"Lodging option {option_id!r} was not found for trip {trip_id!r}")

        for option in state.lodging_options:
            if option.option_id == option_id and option.row_status == ShortlistRowStatus.APPROVED:
                option.row_status = ShortlistRowStatus.RESEARCHED

        selected_ids = [
            option.option_id
            for option in state.lodging_options
            if option.row_status == ShortlistRowStatus.APPROVED
        ]
        state.recommended_option_id = (
            selected_ids[-1]
            if selected_ids
            else _recommended_lodging_option_id(state.lodging_options)
        )

        structure = state.artifacts.setdefault(
            "lodging_structure",
            _lodging_structure_guidance(ctx.option, ctx.intake),
        )
        if isinstance(structure, dict):
            existing_selected_ids = [
                str(value)
                for value in structure.get("selected_lodging_option_ids", [])
                if isinstance(value, str)
            ]
            selected_ids = [value for value in existing_selected_ids if value != option_id]
            current_selected = structure.get("selected_lodging_option_id")
            structure["selected_lodging_option_ids"] = selected_ids
            structure["selected_lodging_option_id"] = (
                current_selected
                if isinstance(current_selected, str) and current_selected in selected_ids
                else None
            )
            if selected_ids and not structure["selected_lodging_option_id"]:
                structure["selected_lodging_option_id"] = selected_ids[-1]
            for row in structure.get("night_plan", []):
                if isinstance(row, dict) and row.get("lodging_option_id") == option_id:
                    row.pop("lodging_option_id", None)

        state.next_actions.insert(
            0,
            "Removed lodging from the selected stay set. Pick another stay or adjust the stay structure before continuing.",
        )
        return self._store.save(state)

    def update_stay_structure(
        self,
        trip_id: str,
        *,
        strategy: str,
        night_plan: list[dict[str, object]],
        notes: str = "",
    ) -> ResearchShortlistState:
        """Persist a manual one-base or split-stay lodging structure override."""
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.LODGING)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        normalized = _normalize_night_plan(night_plan)
        if not normalized:
            raise ValueError("Stay structure requires at least one region/night row.")
        strategy_value = strategy if strategy in {"single_stay", "split_stay"} else "split_stay"
        expected_nights = (
            ctx.intake.duration_days or ctx.intake.duration_min_days or ctx.option.duration_days
        )
        total_nights = sum(int(str(item["nights"])) for item in normalized)
        reasoning = [
            "Manual stay structure saved from the UI.",
            "Use this to test one-base vs split-stay tradeoffs before booking lodging.",
        ]
        if total_nights != expected_nights:
            reasoning.append(
                f"Manual stay nights total {total_nights}; current trip duration signal is {expected_nights}."
            )
        if notes:
            reasoning.append(notes)
        selected_lodging = state.recommended_option_id
        previous_structure = state.artifacts.get("lodging_structure", {})
        existing_options = (
            previous_structure.get("options", []) if isinstance(previous_structure, dict) else []
        )
        state.artifacts["lodging_structure"] = {
            "strategy": strategy_value,
            "confidence": "manual",
            "data_status": "manual_override",
            "summary": _manual_structure_summary(strategy_value, normalized, total_nights),
            "reasoning": reasoning,
            "night_plan": normalized,
            "selected_plan_option_id": ctx.option.option_id,
            "selected_plan_title": ctx.option.title,
            "lodging_strategy": ctx.option.lodging_strategy,
            "selected_lodging_option_id": selected_lodging,
            "manual_notes": notes,
            "options": existing_options,
            "tradeoffs": [
                ctx.option.island_region_movement_friction,
                "Manual split plans still need exact check-in/out, luggage, parking, and transfer validation.",
            ],
        }
        _ensure_options_for_stay_regions(state, ctx.intake, normalized)
        state.next_actions.insert(
            0,
            "Review the manual stay structure against flights, check-in/out times, driving burden, and activities.",
        )
        return self._store.save(state)

    def suggest_stay_structures(
        self,
        trip_id: str,
        *,
        use_llm: bool = True,
    ) -> ResearchShortlistState:
        """Generate editable one-base and split-stay options for the selected plan."""
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.LODGING)
        if state is None:
            state = self.build(trip_id, validate_live=False)

        structure = state.artifacts.setdefault(
            "lodging_structure",
            _lodging_structure_guidance(ctx.option, ctx.intake),
        )
        if not isinstance(structure, dict):
            structure = _lodging_structure_guidance(ctx.option, ctx.intake)
            state.artifacts["lodging_structure"] = structure

        options = _stay_structure_options(ctx.option, ctx.intake)
        advisor = PlanningAdvisorService(enabled=use_llm).advise_lodging_structure(
            ctx.intake,
            ctx.option,
            state,
        )
        advisor_option = _advisor_stay_structure_option(advisor, ctx.option, ctx.intake)
        if advisor_option:
            options = _dedupe_structure_options([advisor_option, *options])

        structure["options"] = options[:3]
        structure["recommended_structure_id"] = options[0]["structure_id"] if options else ""
        structure["advisor_status"] = advisor.status
        structure["advisor_summary"] = advisor.summary
        structure["advisor_recommendation"] = advisor.recommendation
        structure["advisor_confidence"] = advisor.confidence
        state.next_actions.insert(
            0,
            "Pick a stay-structure option or edit the night allocation before choosing exact lodging.",
        )
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
        """Add a user-supplied lodging candidate into the canonical lodging shortlist."""
        if not link.strip() and not notes.strip():
            raise ValueError("lodging candidate requires a link or notes")
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.LODGING)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        option = _user_candidate_option(
            state,
            ctx.intake,
            link=link.strip(),
            notes=notes.strip(),
            name=name.strip(),
        )
        state.lodging_options.append(option)
        state.lodging_options.sort(key=lambda item: item.rank)
        state.artifacts.setdefault(
            "lodging_structure",
            _lodging_structure_guidance(ctx.option, ctx.intake),
        )
        state.recommendation_summary = (
            state.recommendation_summary
            + " User-supplied candidates are scored in the same lodging model and should be validated against sourced options."
        )
        state.next_actions.insert(
            0,
            "Review the user-supplied lodging candidate against bed, location, parking, cancellation, and value.",
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(
                state,
                adapter_mode=adapter_mode,
                option_ids=[option.option_id],
            )
        return self._store.save(state)


def _options_from_profile(
    profile: object,
    intake: TripIntake,
    selected_regions: list[str],
) -> list[LodgingOption]:
    targets = [
        target
        for target in getattr(profile, "lodging_search_targets", [])
        if target_matches_selected_regions(
            target,
            selected_regions,
            getattr(profile, "island_or_region_terms", []),
        )
    ]
    party = intake.party
    traveler_count = party.total_travelers
    requires_three_beds = traveler_count >= 5 or getattr(party, "children", 0) >= 2
    privacy_needed = bool(
        getattr(party, "separate_rooms_preferred", False) or getattr(party, "privacy_needs", None)
    )
    options: list[LodgingOption] = []
    for idx, target in enumerate(targets[:5], start=1):
        source = "Booking.com" if target.get("lodging_type") != "private rental" else "Airbnb"
        query = _query_for_party(str(target["query"]), requires_three_beds)
        validation = {
            "Tripadvisor": source_search_url("Tripadvisor", query),
            "Booking.com": _lodging_source_url("Booking.com", query, intake),
        }
        deep_link = _lodging_source_url(source, query, intake)
        is_private = target.get("lodging_type") == "private rental"
        bed_fit_known = True if is_private else None
        king_known = None
        parking = (
            "likely practical but live-verify exact property parking"
            if is_private
            else "verify paid/free parking and loading access"
        )
        flags = []
        if requires_three_beds and bed_fit_known is None:
            flags.append("family 3-bed layout is not proven")
        if king_known is None:
            flags.append("king-bed preference is unverified")
        if not is_private:
            flags.append(f"hotel may require two rooms for {traveler_count} traveler(s)")
        if privacy_needed and not is_private:
            flags.append("separate-room/privacy needs must be proven")
        fit_category = _fit_category(
            is_private=is_private,
            bed_fit_known=bed_fit_known,
            privacy_needed=privacy_needed,
            traveler_count=traveler_count,
            flags=flags,
        )
        score = 22 + len(flags) * 8
        comfort = 86 - len(flags) * 8 + (4 if is_private else 0)
        options.append(
            LodgingOption(
                option_id=f"lodging-{idx}",
                rank=idx,
                source=source,
                name=str(target["name"]),
                location_area=str(target["location_area"]),
                island_or_region=str(target["island_or_region"]),
                lodging_type=str(target["lodging_type"]),
                room_layout="whole-home/unit target"
                if is_private
                else "hotel room or two-room setup; live-verify",
                bed_layout=(
                    "target 3+ beds; exact layout must be live-verified"
                    if requires_three_beds
                    else "bed layout not confirmed yet"
                ),
                adult_child_fit=(
                    f"Validate {party.adults} adult(s), {party.children} child(ren), "
                    f"{traveler_count} traveler(s) total."
                ),
                traveler_roster_supported=bed_fit_known,
                min_three_beds_satisfied=bed_fit_known,
                king_bed_preference_satisfied=king_known,
                family_of_five_fit=bed_fit_known if traveler_count >= 5 else None,
                separate_room_privacy_fit=True if is_private else None,
                occupancy_fit=(
                    f"Technically plausible for {traveler_count} traveler(s), but live occupancy must be confirmed."
                    if bed_fit_known is not False
                    else f"Does not currently prove occupancy for {traveler_count} traveler(s)."
                ),
                comfort_fit=_comfort_fit(fit_category, party.summary()),
                fit_category=fit_category,
                bed_layout_confidence=0.62 if is_private else 0.28,
                current_availability_signal="live availability required",
                current_price_signal="live price required",
                parking_practicality=parking,
                driving_practicality="good only if roads, driveway, and loading access are clear",
                walkability="validate restaurants/groceries and whether driving is required every meal",
                cancellation_notes="live-verify free cancellation/refund deadline before handoff",
                price_band="live verify; compare total stay cost including taxes/fees",
                deep_link=deep_link,
                validation_links=validation,
                friction_score=score,
                family_comfort_score=comfort,
                recommendation_grade=RecommendationGrade.GOOD
                if is_private
                else RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    "Private space can fit destination travel if location, safety, and parking are strong."
                    if is_private
                    else "Boutique hotel comfort can be excellent, but family bed fit may require two rooms.",
                    "Do not advance unless occupancy, beds, cancellation, and access are explicit.",
                ],
                friction_flags=flags,
                confidence_notes=[
                    "Source link starts exact validation; availability is not asserted."
                ],
                live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
            )
        )
    return options


def _curated_list_lodging_options(
    intake: TripIntake,
    selected_regions: list[str],
    *,
    profile_title: str,
    rank_offset: int = 0,
) -> list[LodgingOption]:
    regions = _lodging_search_regions(intake, selected_regions, profile_title)
    options: list[LodgingOption] = []
    rank = rank_offset
    for region in regions:
        for source, lodging_type in [
            ("Google Search", "boutique hotel best-of list search"),
            ("Airbnb", "Airbnb vacation rental best-of search"),
            ("VRBO", "VRBO vacation rental best-of search"),
        ]:
            rank += 1
            options.append(
                _curated_list_lodging_option(
                    intake,
                    region=region,
                    source=source,
                    lodging_type=lodging_type,
                    rank=rank,
                )
            )
    return options


def _lodging_search_regions(
    intake: TripIntake,
    selected_regions: list[str],
    profile_title: str,
) -> list[str]:
    selected = [region for region in selected_regions if region.strip()]
    candidates = selected or [
        *(seed for seed in intake.destination_seeds if seed.strip()),
        profile_title.strip(),
        intake.trip_name.strip(),
    ]
    regions: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        regions.append(normalized)
    return regions[:4]


def _curated_list_lodging_option(
    intake: TripIntake,
    *,
    region: str,
    source: str,
    lodging_type: str,
    rank: int,
) -> LodgingOption:
    party = intake.party
    traveler_count = party.total_travelers
    requires_three_beds = traveler_count >= 5 or party.children >= 2
    is_private = source in {"Airbnb", "VRBO"}
    source_slug = source.lower().replace(".", "").replace(" ", "-")
    if source == "Google Search":
        query = _query_for_party(f"best boutique hotels {region} family rooms walkable", requires_three_beds)
        direct_link = source_search_url("Google", query)
        validation_links = {
            "Best boutique hotel lists": source_search_url(
                "Google", f"best boutique hotels {region} family rooms"
            ),
            "Booking.com": _lodging_source_url("Booking.com", query, intake),
            "Tripadvisor": source_search_url("Tripadvisor", f"best boutique hotels {region}"),
        }
        name = f"{region} best boutique hotels list search"
        room_layout = "best-of list search seed; choose exact hotel and room next"
        bed_layout = (
            "target family room or two-room setup; exact beds must be verified"
            if requires_three_beds
            else "target king room; exact bed must be verified"
        )
        bed_confidence = 0.2
        fit_category = LodgingFitCategory.TECHNICAL
        grade = RecommendationGrade.CONDITIONAL
        comfort = 58
        friction = 52
        flags = [
            "best-of list search seed; exact property still required",
            "hotel bed layout not proven",
        ]
    else:
        query = (
            f"{region} 3 bedroom vacation rental family parking"
            if requires_three_beds
            else f"{region} vacation rental king bed parking"
        )
        direct_link = _lodging_source_url(source, query, intake)
        validation_links = {
            source: direct_link,
            "Best vacation rental lists": source_search_url(
                "Google", f"best {source} vacation rentals {region} family"
            ),
            "Tripadvisor": source_search_url(
                "Tripadvisor", f"{region} vacation rentals family reviews"
            ),
        }
        name = f"{region} best {source} vacation rentals search"
        room_layout = "whole-home/unit list search seed; choose exact rental next"
        bed_layout = (
            "target 3+ beds; exact layout must be verified"
            if requires_three_beds
            else "target king bed or strong couple setup; exact bed must be verified"
        )
        bed_confidence = 0.3 if requires_three_beds else 0.22
        fit_category = LodgingFitCategory.TECHNICAL
        grade = RecommendationGrade.CONDITIONAL
        comfort = 54
        friction = 56
        flags = [
            "vacation-rental list search seed; exact property still required",
            "bed layout not proven",
            "parking/access practicality not proven",
        ]
    option_id = f"list-{source_slug}-lodging-{_slug(region)}"
    return LodgingOption(
        option_id=option_id,
        rank=rank,
        source=source,
        name=name,
        location_area=region,
        island_or_region=region,
        lodging_type=lodging_type,
        room_layout=room_layout,
        bed_layout=bed_layout,
        adult_child_fit=(
            f"Use list results to find candidates for {party.adults} adult(s), "
            f"{party.children} child(ren), {traveler_count} traveler(s) total."
        ),
        traveler_roster_supported=None,
        min_three_beds_satisfied=None,
        king_bed_preference_satisfied=None,
        family_of_five_fit=None,
        separate_room_privacy_fit=True if is_private else None,
        occupancy_fit=f"Search seed only; exact occupancy for {traveler_count} traveler(s) is not proven.",
        comfort_fit=_comfort_fit(fit_category, party.summary()),
        fit_category=fit_category,
        bed_layout_confidence=bed_confidence,
        current_availability_signal="list/direct source search required",
        current_price_signal="live price required",
        parking_practicality="not proven; filter for practical parking/loading access",
        driving_practicality="validate road access, driveway/loading, and daily route fit",
        walkability="validate map position against meals, groceries, activities, and transit",
        cancellation_notes="not supplied; verify refund deadline before shortlisting exact property",
        price_band="live verify; compare total stay cost including taxes/fees",
        deep_link=direct_link,
        validation_links=validation_links,
        friction_score=friction,
        family_comfort_score=comfort,
        recommendation_grade=grade,
        tradeoffs=[
            "This row exists to force best-of list discovery into the lodging shortlist.",
            "Promote only after an exact property proves beds, price, cancellation, location, and access.",
        ],
        friction_flags=flags,
        confidence_notes=[
            "Generated from the selected city/location so Airbnb, VRBO, vacation rentals, and boutique-hotel lists are always represented.",
            "This is a source-list search row, not a verified property.",
        ],
        live_data_status=LiveDataStatus.SEARCH_LINK_ONLY,
    )


def _recommended_lodging_option_id(options: list[LodgingOption]) -> str | None:
    vetted = [
        option
        for option in options
        if option.live_data_status != LiveDataStatus.SEARCH_LINK_ONLY
        and not option.option_id.startswith("list-")
    ]
    return next(
        (
            option.option_id
            for option in vetted
            if option.recommendation_grade == RecommendationGrade.GOOD
        ),
        vetted[0].option_id if vetted else None,
    )


def _review_lodging_discovery_sources(
    state: ResearchShortlistState,
    intake: TripIntake,
    *,
    max_candidates: int = 6,
) -> None:
    discovery_rows = [
        option
        for option in state.lodging_options
        if option.option_id.startswith("list-")
    ]
    review_queries: list[str] = []
    review_notes = [
        "Discovery rows are reviewed into exact candidates only when a source result names a property/listing."
    ]
    review: dict[str, object] = {
        "status": "skipped",
        "started_at": datetime.utcnow().isoformat(),
        "source_rows": len(discovery_rows),
        "queries": review_queries,
        "accepted_candidates": [],
        "rejected_candidates": [],
        "notes": review_notes,
    }
    state.artifacts["lodging_discovery_review"] = review
    if not discovery_rows:
        review_notes.append("No lodging discovery source rows were available.")
        return
    firecrawl = FirecrawlService()
    availability = firecrawl.availability()
    if not availability.available:
        review["status"] = "blocked"
        review_notes.append(availability.reason)
        state.warnings.append(
            "Lodging discovery review could not fetch list/search evidence because Firecrawl is unavailable."
        )
        return

    existing_keys = {_lodging_candidate_key(option.name, option.deep_link) for option in state.lodging_options}
    candidates: list[tuple[LodgingOption, int]] = []
    rejected: list[dict[str, str]] = []
    for source_row in discovery_rows[:12]:
        query = _discovery_review_query(source_row, intake)
        review_queries.append(query)
        rows = firecrawl.research(query, limit=4)
        for row in rows:
            for candidate in _exact_lodging_candidates_from_result(
                row,
                source_row,
                intake,
                state,
            ):
                key = _lodging_candidate_key(candidate.name, candidate.deep_link)
                if key in existing_keys:
                    rejected.append({"name": candidate.name, "reason": "duplicate candidate"})
                    continue
                score = _reviewed_candidate_priority(candidate)
                if score <= 0:
                    rejected.append({"name": candidate.name, "reason": "insufficient exact lodging evidence"})
                    continue
                existing_keys.add(key)
                candidates.append((candidate, score))

    candidates.sort(key=lambda item: item[1], reverse=True)
    next_rank = max((option.rank for option in state.lodging_options), default=0) + 1
    accepted = [candidate for candidate, _score in candidates[:max_candidates]]
    for candidate in accepted:
        candidate.rank = next_rank
        next_rank += 1
        state.lodging_options.append(candidate)
    state.lodging_options.sort(key=lambda option: option.rank)
    review["status"] = "completed"
    review["ended_at"] = datetime.utcnow().isoformat()
    review["accepted_candidates"] = [
        {
            "option_id": candidate.option_id,
            "name": candidate.name,
            "source": candidate.source,
            "grade": candidate.recommendation_grade.value,
            "fit_category": candidate.fit_category.value,
        }
        for candidate in accepted
    ]
    review["rejected_candidates"] = rejected[:20]
    if accepted:
        state.next_actions.insert(
            0,
            "Review the exact lodging candidates Trippy promoted from boutique-hotel/Airbnb/VRBO discovery, then open only the strongest few for final date/price verification.",
        )
    else:
        state.warnings.append(
            "Lodging discovery reviewed the source lists/searches but did not find enough exact property evidence to promote candidates."
        )


def _discovery_review_query(source_row: LodgingOption, intake: TripIntake) -> str:
    checkin, checkout = _booking_dates(intake)
    date_text = f"{checkin} to {checkout}" if checkin and checkout else intake.travel_window.display()
    party_text = f"{max(1, intake.party.total_travelers or intake.travelers or 1)} travelers"
    if source_row.source == "Airbnb":
        source_text = "Airbnb vacation rental listing"
    elif source_row.source == "VRBO":
        source_text = "VRBO vacation rental listing"
    else:
        source_text = "best boutique hotels family rooms"
    return " ".join(
        part
        for part in [
            source_text,
            source_row.location_area,
            date_text,
            party_text,
            "3 bedrooms parking cancellation reviews",
        ]
        if part
    )


def _exact_lodging_candidates_from_result(
    row: WebResearchResult,
    source_row: LodgingOption,
    intake: TripIntake,
    state: ResearchShortlistState,
) -> list[LodgingOption]:
    names = _property_name_candidates(row, source_row)
    candidates: list[LodgingOption] = []
    for index, name in enumerate(names[:4], start=1):
        option = _reviewed_lodging_candidate_option(
            row,
            source_row,
            intake,
            state,
            name=name,
            index=index,
        )
        if option is not None:
            candidates.append(option)
    return candidates


def _property_name_candidates(row: WebResearchResult, source_row: LodgingOption) -> list[str]:
    candidates: list[str] = []
    title = _clean_property_name(row.source_title)
    if title and not _is_generic_lodging_result_title(title, source_row):
        candidates.append(title)
    text = row.raw_markdown_excerpt or str(row.structured_data.get("description") or "")
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^(?:#{1,4}\s*)?(?:\d+[\).]\s*)?(?:\*\*)?([^#\n\[][^:\n]{4,90})(?:\*\*)?", stripped)
        if not match:
            link_match = re.search(r"\[([^\]]{4,90})\]\((https?://[^)]+)\)", stripped)
            if link_match:
                candidates.append(_clean_property_name(link_match.group(1)))
            continue
        value = _clean_property_name(match.group(1))
        if value and not _is_generic_lodging_result_title(value, source_row):
            candidates.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if key and key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped[:6]


def _reviewed_lodging_candidate_option(
    row: WebResearchResult,
    source_row: LodgingOption,
    intake: TripIntake,
    state: ResearchShortlistState,
    *,
    name: str,
    index: int,
) -> LodgingOption | None:
    evidence_text = " ".join(
        [
            row.source_title,
            str(row.structured_data.get("description") or ""),
            row.raw_markdown_excerpt,
        ]
    )
    lower = evidence_text.lower()
    if _has_unavailable_lodging_signal(lower):
        return None
    is_private = source_row.source in {"Airbnb", "VRBO"} or any(
        token in lower for token in ["vacation rental", "villa", "condo", "apartment", "entire home"]
    )
    party = intake.party
    traveler_count = party.total_travelers
    requires_three_beds = traveler_count >= 5 or party.children >= 2
    three_beds = _mentions_three_beds(lower)
    king = True if "king" in lower else False if "queen" in lower and "king" not in lower else None
    price = _price_signal(evidence_text)
    availability = _reviewed_availability_signal(lower, intake)
    parking = "parking mentioned; verify exact access and fees" if "parking" in lower else "not proven"
    cancellation = _reviewed_cancellation_signal(lower)
    fit_category = _reviewed_fit_category(
        is_private=is_private,
        requires_three_beds=requires_three_beds,
        three_beds=three_beds,
        availability=availability,
        price=price,
    )
    grade = (
        RecommendationGrade.GOOD
        if fit_category in {LodgingFitCategory.PREFERRED, LodgingFitCategory.COMFORTABLE}
        and "not date-verified" not in availability
        else RecommendationGrade.CONDITIONAL
    )
    flags = _reviewed_lodging_flags(
        requires_three_beds=requires_three_beds,
        three_beds=three_beds,
        availability=availability,
        price=price,
        parking=parking,
        cancellation=cancellation,
    )
    source_name = source_row.source if source_row.source in {"Airbnb", "VRBO"} else _source_label_from_url(row.source_url)
    option_id = _reviewed_lodging_option_id(state, name, source_name, index)
    evidence_url = row.source_url or source_row.deep_link
    source_type = SourceType.DIRECT_LISTING if _looks_like_direct_lodging_url(evidence_url) else SourceType.VALIDATION
    confidence = _reviewed_candidate_confidence(
        name=name,
        price=price,
        availability=availability,
        three_beds=three_beds,
        parking=parking,
        evidence_url=evidence_url,
    )
    return LodgingOption(
        option_id=option_id,
        rank=9999,
        source=source_name,
        name=name,
        location_area=source_row.location_area,
        island_or_region=source_row.island_or_region,
        lodging_type="private rental candidate" if is_private else "boutique hotel candidate",
        room_layout="exact candidate promoted from reviewed lodging discovery evidence",
        bed_layout=(
            "3+ bed/bedroom evidence visible"
            if three_beds
            else "bed layout not proven from discovery evidence"
        ),
        adult_child_fit=(
            f"Reviewed for {party.adults} adult(s), {party.children} child(ren), "
            f"{traveler_count} traveler(s) total."
        ),
        traveler_roster_supported=True if three_beds or not requires_three_beds else None,
        min_three_beds_satisfied=True if three_beds else None,
        king_bed_preference_satisfied=king,
        family_of_five_fit=True if requires_three_beds and three_beds else None,
        separate_room_privacy_fit=True if is_private else None,
        occupancy_fit=(
            f"Strong candidate for {traveler_count} travelers only if source confirms occupancy on final dated listing."
            if three_beds or not requires_three_beds
            else f"Not enough bed/occupancy proof yet for {traveler_count} travelers."
        ),
        comfort_fit=_comfort_fit(fit_category, party.summary()),
        fit_category=fit_category,
        bed_layout_confidence=0.74 if three_beds else 0.28,
        current_availability_signal=availability,
        current_price_signal=price or "price not proven from discovery evidence",
        parking_practicality=parking,
        driving_practicality="validate route, road access, luggage loading, and daily driving burden",
        walkability="validate exact map position against meals, groceries, activities, and transit",
        cancellation_notes=cancellation,
        price_band=price or "live verify total including taxes/fees",
        deep_link=evidence_url,
        validation_links={
            source_name: evidence_url,
            "Tripadvisor": source_search_url("Tripadvisor", f"{name} {source_row.location_area} reviews"),
            "Booking.com": _lodging_source_url("Booking.com", f"{name} {source_row.location_area}", intake),
        },
        friction_score=min(90, 18 + len(flags) * 8),
        family_comfort_score=max(35, 86 - len(flags) * 7 + (6 if is_private else 0)),
        recommendation_grade=grade,
        tradeoffs=[
            "Promoted from a reviewed lodging source/list result, not from a blind search row.",
            "Final handoff still requires opening the dated source page to confirm inventory, taxes/fees, cancellation, and exact bed setup.",
        ],
        friction_flags=flags,
        confidence_notes=[
            f"Evidence source: {row.source_title or row.source_domain or evidence_url}",
            "Trippy reviewed source text for exact-property fit signals before adding this row.",
        ],
        live_data_status=LiveDataStatus.PARTIAL,
        row_status=ShortlistRowStatus.RESEARCHED,
        validation=SourceValidation(
            source_name=source_name,
            source_type=source_type,
            verified_at=datetime.utcnow(),
            freshness_status=FreshnessStatus.CURRENT,
            verification_status=VerificationStatus.PARTIAL,
            availability_status=(
                AvailabilityStatus.UNAVAILABLE_SIGNAL
                if "unavailable" in availability
                else AvailabilityStatus.AVAILABILITY_SIGNAL
                if "not date-verified" not in availability
                else AvailabilityStatus.UNKNOWN
            ),
            price_status=PriceStatus.LIVE_SIGNAL if price else PriceStatus.UNKNOWN,
            confidence=confidence,
            evidence_url=evidence_url,
            adapter_used="firecrawl/lodging-discovery-review",
            extracted_fields={
                "candidate_name": name,
                "price_signal": price,
                "availability_signal": availability,
                "min_three_beds_satisfied": three_beds,
                "king_bed_preference_satisfied": king,
                "parking_signal": parking,
                "cancellation_signal": cancellation,
                "source_list_option_id": source_row.option_id,
            },
            notes=[
                "Exact candidate promoted from lodging discovery review.",
                "Treat as ready for human comparison, not purchase, until the dated source page is opened.",
            ],
            missing_fields=_reviewed_missing_fields(
                price=price,
                availability=availability,
                three_beds=three_beds,
                requires_three_beds=requires_three_beds,
                cancellation=cancellation,
            ),
        ),
    )


def _reviewed_candidate_priority(option: LodgingOption) -> int:
    if option.validation.availability_status == AvailabilityStatus.UNAVAILABLE_SIGNAL:
        return 0
    score = option.family_comfort_score - option.friction_score
    if option.min_three_beds_satisfied is True:
        score += 22
    if option.current_price_signal and "not proven" not in option.current_price_signal:
        score += 8
    if option.current_availability_signal and "not date-verified" not in option.current_availability_signal:
        score += 10
    if option.parking_practicality.startswith("parking mentioned"):
        score += 5
    if option.validation.source_type == SourceType.DIRECT_LISTING:
        score += 6
    return score


def _reviewed_lodging_flags(
    *,
    requires_three_beds: bool,
    three_beds: bool,
    availability: str,
    price: str,
    parking: str,
    cancellation: str,
) -> list[str]:
    flags = []
    if requires_three_beds and not three_beds:
        flags.append("3+ beds not proven for family roster")
    if "not date-verified" in availability:
        flags.append("date-specific availability not proven")
    if not price:
        flags.append("total price not proven")
    if parking == "not proven":
        flags.append("parking/access practicality not proven")
    if cancellation == "cancellation terms not proven":
        flags.append("cancellation terms not proven")
    return flags


def _reviewed_fit_category(
    *,
    is_private: bool,
    requires_three_beds: bool,
    three_beds: bool,
    availability: str,
    price: str,
) -> LodgingFitCategory:
    if requires_three_beds and not three_beds:
        return LodgingFitCategory.TECHNICAL
    if "unavailable" in availability:
        return LodgingFitCategory.WEAK
    if three_beds and price and "not date-verified" not in availability:
        return LodgingFitCategory.PREFERRED if is_private else LodgingFitCategory.COMFORTABLE
    if three_beds:
        return LodgingFitCategory.COMFORTABLE
    return LodgingFitCategory.TECHNICAL


def _reviewed_availability_signal(lower: str, intake: TripIntake) -> str:
    if _has_unavailable_lodging_signal(lower):
        return "unavailable/no-inventory signal visible"
    checkin, checkout = _booking_dates(intake)
    if checkin and checkout and checkin in lower and checkout in lower:
        return f"date-specific availability signal visible for {checkin} to {checkout}; final inventory still needs source review"
    if any(term in lower for term in ["available", "reserve", "book now", "check availability"]):
        return "availability/search-result signal visible; final inventory still needs dated source review"
    return "not date-verified; open dated source link before recommending"


def _reviewed_cancellation_signal(lower: str) -> str:
    if "free cancellation" in lower:
        return "free cancellation mentioned; verify deadline"
    if "refundable" in lower:
        return "refundable terms mentioned; verify deadline and exclusions"
    if "cancellation" in lower or "cancel" in lower:
        return "cancellation terms mentioned; verify exact deadline"
    return "cancellation terms not proven"


def _reviewed_missing_fields(
    *,
    price: str,
    availability: str,
    three_beds: bool,
    requires_three_beds: bool,
    cancellation: str,
) -> list[str]:
    missing = []
    if "not date-verified" in availability:
        missing.append("exact_availability")
    if not price:
        missing.append("final_total_price")
    if requires_three_beds and not three_beds:
        missing.append("min_three_beds_satisfied")
    if cancellation == "cancellation terms not proven":
        missing.append("cancellation_terms")
    return missing


def _reviewed_candidate_confidence(
    *,
    name: str,
    price: str,
    availability: str,
    three_beds: bool,
    parking: str,
    evidence_url: str,
) -> float:
    score = 0.35
    if name:
        score += 0.12
    if evidence_url:
        score += 0.1
    if price:
        score += 0.12
    if "not date-verified" not in availability:
        score += 0.12
    if three_beds:
        score += 0.12
    if parking.startswith("parking mentioned"):
        score += 0.05
    return min(0.88, score)


def _reviewed_lodging_option_id(
    state: ResearchShortlistState,
    name: str,
    source_name: str,
    index: int,
) -> str:
    base = f"reviewed-lodging-{_slug(source_name)}-{_slug(name)}"
    existing = {option.option_id for option in state.lodging_options}
    if base not in existing:
        return base
    suffix = index + 1
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def _lodging_candidate_key(name: str, link: str) -> str:
    host = urlparse(link).netloc.lower()
    normalized_name = re.sub(r"[^a-z0-9]+", "", name.lower())
    return f"{normalized_name}:{host}"


def _clean_property_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.replace("|", " - ")).strip(" -*#")
    cleaned = re.sub(
        r"\s+-\s+(?:official site|booking\.com|airbnb|vrbo|tripadvisor|expedia).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned[:90]


def _is_generic_lodging_result_title(value: str, source_row: LodgingOption) -> bool:
    lower = value.lower()
    generic_terms = [
        "search results",
        "best hotels",
        "best boutique hotels",
        "vacation rentals",
        "airbnb",
        "vrbo",
        "booking.com",
        "tripadvisor",
        "things to do",
        "hotels in",
    ]
    if any(term == lower or lower.startswith(term) for term in generic_terms):
        return True
    if source_row.location_area.lower() == lower:
        return True
    return len(value.split()) > 12


def _looks_like_direct_lodging_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "airbnb." in host and "/rooms/" in path:
        return True
    if "vrbo." in host and ("/vacation-rental/" in path or "/property/" in path):
        return True
    return bool("booking." in host and "/hotel/" in path)


def _source_label_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "airbnb" in host:
        return "Airbnb"
    if "vrbo" in host:
        return "VRBO"
    if "booking" in host:
        return "Booking.com"
    if "tripadvisor" in host:
        return "Tripadvisor"
    return host.replace("www.", "") or "Reviewed web source"


def _has_unavailable_lodging_signal(lower: str) -> bool:
    return any(
        term in lower
        for term in [
            "sold out",
            "not available",
            "unavailable",
            "no availability",
            "no rooms available",
            "no properties available",
        ]
    )


def _dedupe_lodging_options(options: list[LodgingOption]) -> list[LodgingOption]:
    deduped: list[LodgingOption] = []
    seen_ids: set[str] = set()
    for option in options:
        base_id = option.option_id
        candidate_id = base_id
        suffix = 2
        while candidate_id in seen_ids:
            candidate_id = f"{base_id}-{suffix}"
            suffix += 1
        option.option_id = candidate_id
        seen_ids.add(candidate_id)
        deduped.append(option)
    return deduped


def _query_for_party(query: str, requires_three_beds: bool) -> str:
    if requires_three_beds:
        return query
    replacements = {
        "family room 3 beds": "king room",
        "family room": "king room",
        "3 bedroom vacation rental family": "comfortable stay king bed",
        "family parking": "parking",
        "family": "couple",
        "3 beds": "king bed",
    }
    adjusted = query
    for old, new in replacements.items():
        adjusted = adjusted.replace(old, new)
    return adjusted


def _lodging_source_url(source: str, query: str, intake: TripIntake) -> str:
    if source == "Booking.com":
        return _booking_url(query, intake)
    if source == "Airbnb":
        return _airbnb_url(query, intake)
    if source == "VRBO":
        return _vrbo_url(query, intake)
    if source in {"Tripadvisor", "Trivago"}:
        return _dated_lodging_search_url(source, query, intake)
    return source_search_url(source, query)


def _normalize_lodging_link(link: str, intake: TripIntake) -> str:
    parsed = urlparse(link)
    if "booking.com" not in parsed.netloc.lower():
        return link
    return _booking_url("", intake, base_url=link)


def _booking_url(query: str, intake: TripIntake, *, base_url: str = "") -> str:
    parsed = urlparse(base_url or "https://www.booking.com/searchresults.html")
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params: dict[str, object] = {
        **existing,
        "group_adults": max(1, intake.party.adults or intake.party.total_travelers or 1),
        "group_children": max(0, intake.party.children or 0),
        "no_rooms": 1,
        "selected_currency": "CAD",
    }
    if query and not base_url:
        params.update({"ss": query, "sb": 1, "src": "searchresults"})
    checkin, checkout = _booking_dates(intake)
    if checkin and checkout:
        params["checkin"] = checkin
        params["checkout"] = checkout
    ages = _booking_child_ages(intake)
    if ages:
        params["age"] = ages
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc or "www.booking.com",
            parsed.path or "/searchresults.html",
            parsed.params,
            urlencode(params, doseq=True),
            parsed.fragment,
        )
    )


def _booking_dates(intake: TripIntake) -> tuple[str, str]:
    start = intake.travel_window.start_date
    if not start:
        return "", ""
    end = intake.travel_window.end_date
    if end is None:
        nights = max(1, (intake.duration_days or intake.duration_min_days or 2) - 1)
        end = start + timedelta(days=nights)
    if end <= start:
        end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _airbnb_url(query: str, intake: TripIntake) -> str:
    checkin, checkout = _booking_dates(intake)
    params: dict[str, object] = {
        "adults": max(1, intake.party.adults or intake.party.total_travelers or 1),
        "children": max(0, intake.party.children or 0),
        "currency": "CAD",
    }
    if checkin and checkout:
        params["checkin"] = checkin
        params["checkout"] = checkout
    return f"https://www.airbnb.ca/s/{quote_plus(query)}/homes?{urlencode(params)}"


def _vrbo_url(query: str, intake: TripIntake) -> str:
    checkin, checkout = _booking_dates(intake)
    params: dict[str, object] = {
        "adults": max(1, intake.party.adults or intake.party.total_travelers or 1),
        "children": max(0, intake.party.children or 0),
    }
    if checkin and checkout:
        params["startDate"] = checkin
        params["endDate"] = checkout
    return f"https://www.vrbo.com/search/keywords:{quote_plus(query)}?{urlencode(params)}"


def _dated_lodging_search_url(source: str, query: str, intake: TripIntake) -> str:
    checkin, checkout = _booking_dates(intake)
    details = [query]
    if checkin and checkout:
        details.append(f"{checkin} to {checkout}")
    details.append(f"{max(1, intake.party.total_travelers or intake.travelers or 1)} travelers")
    return source_search_url(source, " ".join(details))


def _booking_child_ages(intake: TripIntake) -> list[int]:
    child_count = max(0, intake.party.children or 0)
    if child_count == 0:
        return []
    ages = list(intake.party.child_ages or [])[:child_count]
    while len(ages) < child_count:
        ages.append(10)
    return [max(0, min(17, int(age))) for age in ages]


def _lodging_structure_guidance(
    option: TripPlanOption,
    intake: TripIntake,
) -> dict[str, object]:
    night_plan = [
        {"region": region, "nights": nights}
        for region, nights in option.nights_by_region.items()
        if nights
    ]
    stay_count = len(night_plan) or len(option.regions) or 1
    duration = intake.duration_display()
    traveler_summary = intake.party.summary()
    if stay_count <= 1:
        strategy = "single_stay"
        summary = (
            f"One stay is the cleaner default for {duration}: it protects downtime, unpacking ease, "
            "and first/last-day simplicity unless exact flight or lodging evidence proves a split is worth it."
        )
        reasoning = [
            "The selected plan has one primary region/base.",
            "One lodging search reduces bed-layout, parking, cancellation, and check-in risk.",
            f"Still validate that the property comfortably fits {traveler_summary}.",
        ]
    else:
        strategy = "split_stay"
        summary = (
            f"Split stays are expected for this selected shape: {stay_count} base(s) reduce backtracking "
            "but add check-in, luggage, transfer, and bed-validation risk."
        )
        reasoning = [
            "The selected plan covers multiple regions where one base may create wasted driving.",
            "Only keep the split if each stay has clear comfort upside and enough nights to justify repacking.",
            "Avoid same-day tight transfers around inter-island flights, ferries, tours, or early returns.",
        ]
    return {
        "strategy": strategy,
        "confidence": "plan-based",
        "data_status": "inferred_from_selected_plan",
        "summary": summary,
        "reasoning": reasoning,
        "night_plan": night_plan
        or [{"region": region, "nights": "TBD"} for region in option.regions],
        "selected_plan_option_id": option.option_id,
        "selected_plan_title": option.title,
        "lodging_strategy": option.lodging_strategy,
        "tradeoffs": [
            option.island_region_movement_friction,
            "Exact property availability, bed layout, cancellation, and access remain manual/live-verification items.",
        ],
    }


def _stay_structure_options(
    option: TripPlanOption,
    intake: TripIntake,
) -> list[dict[str, object]]:
    total_nights = _structure_total_nights(option, intake)
    selected_regions = [region for region in option.regions if region]
    existing = [
        {"region": region, "nights": nights}
        for region, nights in option.nights_by_region.items()
        if nights
    ]
    if len(existing) > 1:
        return _multi_region_structure_options(option, total_nights, existing)
    primary = (
        existing[0]["region"]
        if existing
        else selected_regions[0]
        if selected_regions
        else "Main base"
    )
    return _single_region_structure_options(option, intake, str(primary), total_nights)


def _single_region_structure_options(
    option: TripPlanOption,
    intake: TripIntake,
    primary_region: str,
    total_nights: int,
) -> list[dict[str, object]]:
    anchors = _same_region_stay_anchors(primary_region, intake)
    split_a = _two_part_split(total_nights, short_second=True)
    split_b = _two_part_split(total_nights, short_second=False)
    return [
        {
            "structure_id": "stay-one-base",
            "title": f"One base: {primary_region}",
            "strategy": "single_stay",
            "recommendation_label": "smoothest",
            "confidence": "plan-based",
            "summary": "Best default if one location keeps drives reasonable and protects unpacking ease.",
            "night_plan": [
                {
                    "region": primary_region,
                    "nights": total_nights,
                    "lodging_option_id": "",
                    "notes": "single base; lowest check-in/luggage friction",
                }
            ],
            "reasoning": [
                "One check-in and one bed-layout validation keeps the trip simpler.",
                "Use this if daily drives from the base are acceptable and food access is strong.",
            ],
            "tradeoffs": [
                option.island_region_movement_friction,
                "May create backtracking if activities cluster far from the base.",
            ],
            "map_regions": [primary_region],
            "thumbnail_variant": 1,
        },
        {
            "structure_id": "stay-central-plus-scenic",
            "title": f"{anchors[0]} + {anchors[1]}",
            "strategy": "split_stay",
            "recommendation_label": "balanced split",
            "confidence": "planner-suggested",
            "summary": "Tests whether a short second base cuts backtracking enough to justify repacking.",
            "night_plan": [
                {
                    "region": anchors[0],
                    "nights": split_a[0],
                    "lodging_option_id": "",
                    "notes": "arrival/food/airport-friendly base",
                },
                {
                    "region": anchors[1],
                    "nights": split_a[1],
                    "lodging_option_id": "",
                    "notes": "activity-side base; verify check-in and parking",
                },
            ],
            "reasoning": [
                "Keeps most nights in the practical base while giving the far side of the destination its own window.",
                "Only worth it if the second location has a lodging win and activities nearby.",
            ],
            "tradeoffs": [
                "Adds one checkout/check-in and luggage move.",
                "Can reduce late-day driving after remote activities.",
            ],
            "map_regions": anchors[:2],
            "thumbnail_variant": 2,
        },
        {
            "structure_id": "stay-loop-split",
            "title": f"{anchors[2]} + {anchors[0]}",
            "strategy": "split_stay",
            "recommendation_label": "route-first",
            "confidence": "planner-suggested",
            "summary": "Starts or ends near a different activity cluster so the route feels less repetitive.",
            "night_plan": [
                {
                    "region": anchors[2],
                    "nights": split_b[0],
                    "lodging_option_id": "",
                    "notes": "scenic/activity cluster first; validate road and parking comfort",
                },
                {
                    "region": anchors[0],
                    "nights": split_b[1],
                    "lodging_option_id": "",
                    "notes": "finish near food/airport logistics",
                },
            ],
            "reasoning": [
                "Useful if the best activities naturally form a loop instead of out-and-back drives.",
                "Return to the practical base before departure if flight timing or airport access matters.",
            ],
            "tradeoffs": [
                "More sequencing-dependent than the balanced split.",
                "Reject if exact lodging options make the second base weaker or less comfortable.",
            ],
            "map_regions": [anchors[2], anchors[0]],
            "thumbnail_variant": 3,
        },
    ]


def _multi_region_structure_options(
    option: TripPlanOption,
    total_nights: int,
    existing: list[dict[str, object]],
) -> list[dict[str, object]]:
    primary = str(existing[0]["region"])
    secondary = str(existing[1]["region"]) if len(existing) > 1 else primary
    consolidated_nights = max(1, total_nights - 2)
    return [
        {
            "structure_id": "stay-plan-default",
            "title": "Use selected trip shape",
            "strategy": "split_stay",
            "recommendation_label": "shape-based",
            "confidence": "plan-based",
            "summary": "Matches the chosen plan and avoids excessive backtracking between regions.",
            "night_plan": [
                {
                    "region": str(item["region"]),
                    "nights": int(str(item["nights"])),
                    "lodging_option_id": "",
                    "notes": "from selected plan shape",
                }
                for item in existing
            ],
            "reasoning": [
                "The selected option already spans multiple regions.",
                "Keep the split only if each base has strong lodging fit and protected transfer timing.",
            ],
            "tradeoffs": [option.island_region_movement_friction],
            "map_regions": [str(item["region"]) for item in existing],
            "thumbnail_variant": min(len(existing), 3),
        },
        {
            "structure_id": "stay-reduced-moves",
            "title": f"Reduce moves: {primary} + {secondary}",
            "strategy": "split_stay",
            "recommendation_label": "lower friction",
            "confidence": "planner-suggested",
            "summary": "Consolidates the trip into fewer bases if comfort beats complete coverage.",
            "night_plan": [
                {
                    "region": primary,
                    "nights": consolidated_nights,
                    "lodging_option_id": "",
                    "notes": "primary comfort base",
                },
                {
                    "region": secondary,
                    "nights": total_nights - consolidated_nights,
                    "lodging_option_id": "",
                    "notes": "secondary base only if transfer timing is clean",
                },
            ],
            "reasoning": [
                "Fewer lodging searches means fewer bed, parking, and check-in risks.",
                "Use if the broader route starts to feel overcompressed.",
            ],
            "tradeoffs": ["May sacrifice coverage or create longer day trips."],
            "map_regions": [primary, secondary],
            "thumbnail_variant": 2,
        },
        {
            "structure_id": "stay-one-base-test",
            "title": f"Stress-test one base: {primary}",
            "strategy": "single_stay",
            "recommendation_label": "comfort test",
            "confidence": "planner-suggested",
            "summary": "Useful as a comparison baseline: only choose if drives/transfers stay comfortable.",
            "night_plan": [
                {
                    "region": primary,
                    "nights": total_nights,
                    "lodging_option_id": "",
                    "notes": "one-base stress test against selected multi-region shape",
                }
            ],
            "reasoning": [
                "Shows what the trip would feel like with maximum unpacking simplicity.",
                "Reject if it creates wasted travel days or too much backtracking.",
            ],
            "tradeoffs": ["Likely weaker for genuinely multi-region trips."],
            "map_regions": [primary],
            "thumbnail_variant": 1,
        },
    ]


def _advisor_stay_structure_option(
    advisor: object,
    option: TripPlanOption,
    intake: TripIntake,
) -> dict[str, object] | None:
    night_plan = getattr(advisor, "night_plan", None) or []
    normalized = _normalize_advisor_night_plan(night_plan)
    if not normalized:
        return None
    strategy = getattr(advisor, "stay_strategy", "") or (
        "split_stay" if len(normalized) > 1 else "single_stay"
    )
    return {
        "structure_id": "stay-advisor",
        "title": "Advisor pick",
        "strategy": strategy if strategy in {"single_stay", "split_stay"} else "split_stay",
        "recommendation_label": "agent call",
        "confidence": f"advisor {getattr(advisor, 'confidence', 0.35):.0%}",
        "summary": getattr(advisor, "recommendation", "")
        or getattr(advisor, "summary", "")
        or "Advisor-generated stay structure.",
        "night_plan": normalized,
        "reasoning": getattr(advisor, "rationale", []) or [option.lodging_strategy],
        "tradeoffs": getattr(advisor, "warnings", []) or [option.island_region_movement_friction],
        "map_regions": [str(item["region"]) for item in normalized],
        "thumbnail_variant": min(max(len(normalized), 1), 3),
        "advisor_status": getattr(advisor, "status", ""),
        "advisor_prompt_version": getattr(advisor, "prompt_version", ""),
        "duration_context": intake.duration_display(),
    }


def _normalize_advisor_night_plan(rows: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        region = str(row.get("region") or row.get("location") or "").strip()
        if not region:
            continue
        try:
            nights = int(str(row.get("nights") or 0))
        except ValueError:
            continue
        if nights < 1:
            continue
        normalized.append(
            {
                "region": region,
                "nights": nights,
                "lodging_option_id": str(row.get("lodging_option_id") or "").strip(),
                "notes": str(row.get("reason") or row.get("notes") or "").strip(),
            }
        )
    return normalized


def _dedupe_structure_options(options: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[tuple[str, int], ...]] = set()
    deduped: list[dict[str, object]] = []
    for option in options:
        raw_night_plan = option.get("night_plan", [])
        night_plan = raw_night_plan if isinstance(raw_night_plan, list) else []
        signature = tuple(
            (str(item.get("region") or ""), int(item.get("nights") or 0))
            for item in night_plan
            if isinstance(item, dict)
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(option)
    return deduped


def _structure_total_nights(option: TripPlanOption, intake: TripIntake) -> int:
    total = sum(int(nights) for nights in option.nights_by_region.values() if nights)
    if total:
        return total
    return intake.duration_days or intake.duration_min_days or option.duration_days or 1


def _same_region_stay_anchors(primary_region: str, intake: TripIntake) -> list[str]:
    destination = primary_region or ", ".join(intake.destination_seeds) or "destination"
    return [
        f"{destination} central base",
        f"{destination} scenic/activity side",
        f"{destination} arrival/departure-friendly base",
    ]


def _two_part_split(total_nights: int, *, short_second: bool) -> tuple[int, int]:
    if total_nights <= 2:
        return (1, max(1, total_nights - 1))
    second = max(2, round(total_nights * 0.35)) if short_second else max(2, total_nights // 2)
    second = min(second, total_nights - 1)
    first = max(1, total_nights - second)
    return (first, second)


def _normalize_night_plan(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        region = str(row.get("region") or row.get("location") or "").strip()
        if not region:
            raise ValueError(f"Stay row {index} is missing a region/location.")
        nights_raw = row.get("nights")
        try:
            nights = int(str(nights_raw))
        except (TypeError, ValueError):
            raise ValueError(f"Stay row {index} has invalid nights {nights_raw!r}.") from None
        if nights < 1:
            raise ValueError(f"Stay row {index} must have at least one night.")
        lodging_option_id = str(row.get("lodging_option_id") or "").strip()
        notes = str(row.get("notes") or "").strip()
        normalized.append(
            {
                "region": region,
                "nights": nights,
                "lodging_option_id": lodging_option_id,
                "notes": notes,
            }
        )
    return normalized


def _ensure_options_for_stay_regions(
    state: ResearchShortlistState,
    intake: TripIntake,
    night_plan: list[dict[str, object]],
) -> None:
    next_rank = max((option.rank for option in state.lodging_options), default=0) + 1
    for stay in night_plan:
        region = str(stay.get("region") or "").strip()
        if not region:
            continue
        if any(_lodging_option_matches_region(option, region) for option in state.lodging_options):
            continue
        state.lodging_options.append(
            _stay_region_search_option(
                state,
                intake,
                region=region,
                rank=next_rank,
            )
        )
        next_rank += 1
    state.lodging_options.sort(key=lambda option: option.rank)


def _lodging_option_matches_region(option: LodgingOption, region: str) -> bool:
    tokens = _region_match_tokens(region)
    if not tokens:
        return False
    haystack = " ".join(
        [
            option.name,
            option.location_area,
            option.island_or_region,
            option.lodging_type,
        ]
    ).lower()
    return any(token in haystack for token in tokens)


def _stay_region_search_option(
    state: ResearchShortlistState,
    intake: TripIntake,
    *,
    region: str,
    rank: int,
) -> LodgingOption:
    party = intake.party
    traveler_count = party.total_travelers
    requires_three_beds = traveler_count >= 5 or party.children >= 2
    query = _query_for_party(f"{region} lodging parking walkable restaurants", requires_three_beds)
    if requires_three_beds:
        query = f"{query} 3 beds family"
    option_id = f"stay-region-lodging-{_slug(region)}"
    existing_ids = {option.option_id for option in state.lodging_options}
    if option_id in existing_ids:
        option_id = f"{option_id}-{rank}"
    flags = [
        "location-specific search seed; exact property still required",
        "bed layout not proven",
        "parking/access practicality not proven",
    ]
    return LodgingOption(
        option_id=option_id,
        rank=rank,
        source="Booking.com",
        name=f"{region} lodging search",
        location_area=region,
        island_or_region=", ".join(intake.destination_seeds) or region,
        lodging_type="location-specific lodging search",
        room_layout="search target for this stay base; choose exact property next",
        bed_layout=(
            "target 3+ beds; exact layout must be live-verified"
            if requires_three_beds
            else "bed layout not confirmed yet"
        ),
        adult_child_fit=(
            f"Validate {party.adults} adult(s), {party.children} child(ren), "
            f"{traveler_count} traveler(s) total for this base."
        ),
        traveler_roster_supported=None,
        min_three_beds_satisfied=None,
        king_bed_preference_satisfied=None,
        family_of_five_fit=None,
        separate_room_privacy_fit=None,
        occupancy_fit=f"Search seed only; exact occupancy for {traveler_count} traveler(s) is not proven.",
        comfort_fit="Potential fit only after exact property, beds, cancellation, and access are verified.",
        fit_category=LodgingFitCategory.TECHNICAL,
        bed_layout_confidence=0.15,
        current_availability_signal="live availability required",
        current_price_signal="live price required",
        parking_practicality="not proven",
        driving_practicality="validate road access, driveway/loading, and daily route fit",
        walkability="validate food/grocery/activity access from this base",
        cancellation_notes="not supplied",
        price_band="live verify; compare total stay cost including taxes/fees",
        deep_link=_lodging_source_url("Booking.com", query, intake),
        validation_links={
            "Booking.com": _lodging_source_url("Booking.com", query, intake),
            "Tripadvisor": source_search_url("Tripadvisor", f"{region} hotels lodging"),
            "Airbnb": source_search_url("Airbnb", f"{region} vacation rental parking"),
        },
        friction_score=58,
        family_comfort_score=52,
        recommendation_grade=RecommendationGrade.CONDITIONAL,
        tradeoffs=[
            "Created because the chosen stay split needs lodging options for this specific base.",
            "Promote only after exact property fit is verified.",
        ],
        friction_flags=flags,
        confidence_notes=[
            "This is a location-specific search seed, not a verified lodging recommendation."
        ],
        live_data_status=LiveDataStatus.SEARCH_LINK_ONLY,
    )


def _region_match_tokens(region: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "base",
        "side",
        "coast",
        "area",
        "near",
        "central",
        "north",
        "south",
        "east",
        "west",
        "sao",
        "são",
        "miguel",
    }
    return {
        token
        for token in re.split(r"[^a-z0-9]+", region.lower())
        if len(token) >= 4 and token not in stopwords
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "base"


def _manual_structure_summary(
    strategy: str,
    night_plan: list[dict[str, object]],
    total_nights: int,
) -> str:
    if strategy == "single_stay" or len(night_plan) == 1:
        region = str(night_plan[0]["region"])
        return (
            f"Manual one-stay plan: {total_nights} night(s) based in {region}. "
            "This favors unpacking ease and fewer check-in transitions."
        )
    labels = ", ".join(f"{item['region']} ({item['nights']}n)" for item in night_plan)
    return (
        f"Manual split-stay plan across {len(night_plan)} base(s): {labels}. "
        "This can reduce backtracking, but adds luggage, parking, and check-in friction."
    )


def _user_candidate_option(
    state: ResearchShortlistState,
    intake: TripIntake,
    *,
    link: str,
    notes: str,
    name: str,
) -> LodgingOption:
    party = intake.party
    traveler_count = party.total_travelers
    source = _source_from_link(link)
    lower = f"{link} {notes} {name}".lower()
    is_private = any(token in lower for token in ["airbnb", "vrbo", "villa", "home", "rental"])
    three_beds = _mentions_three_beds(lower)
    king = True if "king" in lower else None
    parking_known = "parking" in lower or "park" in lower
    privacy_needed = bool(party.separate_rooms_preferred or party.privacy_needs)
    flags = []
    if traveler_count >= 5 and three_beds is not True:
        flags.append("user candidate does not yet prove 3+ beds for the roster")
    if king is None:
        flags.append("king-bed preference not proven")
    if privacy_needed and not is_private:
        flags.append("privacy/separate-room fit is not proven")
    if not parking_known:
        flags.append("parking/access practicality not proven")
    if "cancel" not in lower and "refundable" not in lower:
        flags.append("cancellation terms not provided")

    rank = max((option.rank for option in state.lodging_options), default=0) + 1
    option_id = f"user-lodging-{rank}"
    fit_category = (
        LodgingFitCategory.PREFERRED
        if three_beds and (king or traveler_count < 5) and parking_known
        else LodgingFitCategory.COMFORTABLE
        if three_beds
        else LodgingFitCategory.TECHNICAL
    )
    friction = min(90, 18 + len(flags) * 10)
    comfort = max(35, 88 - len(flags) * 9 + (4 if is_private else 0))
    display_name = name or _name_from_link(link) or "User lodging candidate"
    price = _price_signal(notes)
    return LodgingOption(
        option_id=option_id,
        rank=rank,
        source=source,
        name=display_name,
        location_area=_location_hint(notes, intake),
        island_or_region=", ".join(intake.destination_seeds) or "destination TBD",
        lodging_type="private rental" if is_private else "hotel/listing candidate",
        room_layout="user-supplied candidate; parse and validate exact room/unit terms",
        bed_layout="user notes suggest 3+ beds"
        if three_beds
        else "bed layout not proven from supplied notes",
        adult_child_fit=(
            f"Evaluate for {party.adults} adult(s), {party.children} child(ren), "
            f"{traveler_count} traveler(s) total."
        ),
        traveler_roster_supported=True if three_beds else None,
        min_three_beds_satisfied=True if three_beds else None,
        king_bed_preference_satisfied=king,
        family_of_five_fit=True if traveler_count >= 5 and three_beds else None,
        separate_room_privacy_fit=True if is_private and privacy_needed else None,
        occupancy_fit=(
            f"User candidate may fit {traveler_count} traveler(s); exact occupancy must be confirmed on source."
        ),
        comfort_fit=_comfort_fit(fit_category, party.summary()),
        fit_category=fit_category,
        bed_layout_confidence=0.68 if three_beds else 0.22,
        current_availability_signal="user-supplied; live source still required",
        current_price_signal=price or "live price required",
        parking_practicality="parking mentioned; verify exact access"
        if parking_known
        else "not proven",
        driving_practicality="validate road access, driveway/loading, and daily drive burden",
        walkability="validate food/grocery/activity access from exact location",
        cancellation_notes="mentioned in notes; verify deadline"
        if "cancel" in lower
        else "not supplied",
        price_band=price or "live price required",
        deep_link=_normalize_lodging_link(link, intake),
        validation_links={
            "Tripadvisor": source_search_url(
                "Tripadvisor", f"{display_name} {intake.travel_window.display()}"
            ),
            "Booking.com": _lodging_source_url(
                "Booking.com", f"{display_name} {intake.travel_window.display()}", intake
            ),
        },
        friction_score=friction,
        family_comfort_score=comfort,
        recommendation_grade=RecommendationGrade.GOOD
        if fit_category in {LodgingFitCategory.PREFERRED, LodgingFitCategory.COMFORTABLE}
        else RecommendationGrade.CONDITIONAL,
        tradeoffs=[
            "User-supplied option is compared in the same shortlist model as sourced options.",
            "Promote only after exact bed layout, total price, cancellation, location, and access are verified.",
        ],
        friction_flags=flags,
        confidence_notes=[
            "Candidate came from user input, not autonomous sourcing.",
            notes or "No extra user notes supplied.",
        ],
        live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
    )


def _source_from_link(link: str) -> str:
    host = urlparse(link).netloc.lower()
    if "booking" in host:
        return "Booking.com"
    if "airbnb" in host:
        return "Airbnb"
    if "vrbo" in host:
        return "VRBO"
    if "expedia" in host:
        return "Expedia"
    if "tripadvisor" in host:
        return "Tripadvisor"
    return "User supplied"


def _name_from_link(link: str) -> str:
    parsed = urlparse(link)
    pieces = [piece for piece in parsed.path.split("/") if piece]
    if pieces:
        return pieces[-1].replace("-", " ").replace("_", " ").title()[:80]
    return parsed.netloc or ""


def _mentions_three_beds(text: str) -> bool:
    return any(
        token in text
        for token in [
            "3 bed",
            "three bed",
            "3-bedroom",
            "3 bedroom",
            "3 bedrooms",
            "3br",
            "4 bed",
            "4-bedroom",
            "4 bedroom",
            "4 bedrooms",
            "4br",
        ]
    )


def _price_signal(notes: str) -> str:
    match = re.search(
        r"(?:(?:CAD|USD|EUR|CA\$|C\$|US\$|\$|€)\s?[\d][\d,]*(?:\.\d{2})?(?:\s?(?:/night|per night|night|total|pp|per person))?)",
        notes,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(0).strip()
    tokens = [token.strip(",.;") for token in notes.replace("\n", " ").split()]
    for index, token in enumerate(tokens):
        upper = token.upper()
        if "$" in token:
            return token
        if upper in {"CAD", "USD", "EUR"} and index + 1 < len(tokens):
            return f"{token} {tokens[index + 1]}"
        if upper.startswith(("CAD", "USD", "EUR")):
            return token
    return ""


def _location_hint(notes: str, intake: TripIntake) -> str:
    if notes:
        first = notes.split(".")[0].strip()
        if first:
            return first[:90]
    return ", ".join(intake.destination_seeds) or "location TBD"


def _fit_category(
    *,
    is_private: bool,
    bed_fit_known: bool | None,
    privacy_needed: bool,
    traveler_count: int,
    flags: list[str],
) -> LodgingFitCategory:
    if traveler_count >= 5 and bed_fit_known is None:
        return LodgingFitCategory.TECHNICAL
    if flags and not is_private:
        return LodgingFitCategory.WEAK
    if is_private and not privacy_needed:
        return LodgingFitCategory.PREFERRED
    if is_private:
        return LodgingFitCategory.COMFORTABLE
    return LodgingFitCategory.TECHNICAL


def _comfort_fit(fit_category: LodgingFitCategory, party_summary: str) -> str:
    value = fit_category.value
    if value == "preferred_fit":
        return f"Clearly preferred if live listing confirms beds/parking for {party_summary}."
    if value == "comfortable_fit":
        return f"Actually comfortable if privacy/access details hold for {party_summary}."
    if value == "weak_fit":
        return f"Technically possible but likely uncomfortable or admin-heavy for {party_summary}."
    return f"Technical fit only until live bed/privacy details are proven for {party_summary}."


def _serpapi_live_lodging(
    ctx: ShortlistContext,
    requires_three_beds: bool,
) -> tuple[list[LodgingOption], list[str]]:
    """Pull a few live Google Hotels listings via SerpAPI for the selected region."""
    if not serpapi_client.is_configured():
        return [], ["SERPAPI_KEY is not configured, so lodging rows are search handoffs."]
    region = (ctx.option.regions[0] if ctx.option.regions else "") or (
        ctx.intake.destination_seeds[0] if ctx.intake.destination_seeds else ""
    )
    if not region:
        return [], ["SerpAPI lodging skipped: no destination region on the trip plan yet."]
    check_in, check_out = _serpapi_lodging_dates(ctx)
    children_ages = list(ctx.intake.party.child_ages or [])
    properties, notes = serpapi_client.search_hotels(
        query=region,
        check_in=check_in,
        check_out=check_out,
        adults=max(1, ctx.intake.party.adults or 2),
        children_ages=children_ages,
    )
    if not properties:
        return [], notes
    deep_link = (
        f"https://www.google.com/travel/hotels?q={region.replace(' ', '+')}"
        f"&checkin={check_in.isoformat()}&checkout={check_out.isoformat()}"
    )
    options = lodging_options_from_serpapi(
        properties,
        region=region,
        deep_link=deep_link,
        requires_three_beds=requires_three_beds,
    )
    return options, notes


def _serpapi_lodging_problem(notes: list[str]) -> bool:
    text = " ".join(notes).lower()
    return any(
        marker in text
        for marker in (
            "serpapi_key is not configured",
            "serpapi request failed",
            "serpapi returned error",
            "returned no properties",
            "returned no payload",
        )
    )


def _serpapi_lodging_dates(ctx: ShortlistContext) -> tuple[date, date]:
    window = ctx.intake.travel_window
    if window.start_date and window.end_date:
        return window.start_date, window.end_date
    today = date.today()
    nights = ctx.intake.duration_days or ctx.intake.duration_min_days or ctx.option.duration_days or 7
    if window.start_date:
        return window.start_date, window.start_date + timedelta(days=max(1, nights))
    fallback_start = today + timedelta(days=60)
    return fallback_start, fallback_start + timedelta(days=max(1, nights))
