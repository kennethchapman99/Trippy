"""Source-aware lodging shortlist generation."""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from trippy.models.shortlists import (
    LiveDataStatus,
    LodgingFitCategory,
    LodgingOption,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
)
from trippy.services import serpapi_client
from trippy.services.serpapi_options import lodging_options_from_serpapi
from trippy.models.sources import TravelSourceCategory
from trippy.models.trip_planning import TripIntake, TripPlanOption
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.live_validation import LiveValidationService
from trippy.services.planning_advisor import PlanningAdvisorService
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
        requires_three_beds = (
            ctx.intake.party.total_travelers >= 5 or ctx.intake.party.children >= 2
        )
        live_options, live_notes = _serpapi_live_lodging(ctx, requires_three_beds)
        if live_options:
            options = live_options + options
            for index, option in enumerate(options, start=1):
                option.rank = index
        recommended = next(
            (
                option.option_id
                for option in options
                if option.recommendation_grade == RecommendationGrade.GOOD
            ),
            options[0].option_id if options else None,
        )
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
        if deep_research:
            SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        return self._store.save(state)

    def select_lodging(self, trip_id: str, option_id: str) -> ResearchShortlistState:
        """Promote a lodging option as the current human-preferred planning choice."""
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
            elif option.row_status == ShortlistRowStatus.APPROVED:
                option.row_status = ShortlistRowStatus.RESEARCHED
        structure = state.artifacts.setdefault(
            "lodging_structure",
            _lodging_structure_guidance(ctx.option, ctx.intake),
        )
        if isinstance(structure, dict):
            structure["selected_lodging_option_id"] = option_id
            structure["data_status"] = (
                "manual_lodging_selection"
                if structure.get("data_status") != "manual_override"
                else "manual_override"
            )
        state.next_actions.insert(
            0,
            "Selected lodging now drives stay-structure review, workspace timeline, and map planning.",
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
                    else "king bed strongly preferred; queen compromise needs a clear upside"
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
                    "Private space usually fits Azores island travel if location, safety, and parking are strong."
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
    text = " ".join([primary_region, *intake.destination_seeds, intake.trip_name]).lower()
    if "azores" in text or "sao miguel" in text or "são miguel" in text:
        return ["Ponta Delgada / south coast", "Furnas / east side", "Ribeira Grande / north coast"]
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
            else "king bed strongly preferred; exact layout must be verified"
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
            "3br",
            "4 bed",
            "4-bedroom",
            "4 bedroom",
            "4br",
        ]
    )


def _price_signal(notes: str) -> str:
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
