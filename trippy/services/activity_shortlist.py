"""Source-aware activity and tour shortlist generation."""

from __future__ import annotations

from trippy.models.shortlists import (
    ActivityOption,
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
    target_matches_selected_regions,
)
from trippy.services.source_research import SourceResearchService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class ActivityShortlistService:
    """Build safety/review/pacing-aware activity candidates."""

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
        plan = source_plan(TravelSourceCategory.TOURS)
        options = _options_from_profile(profile, ctx.intake, ctx.option.regions)
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.ACTIVITIES,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            activity_options=options,
            recommended_option_id=options[0].option_id if options else None,
            recommendation_summary=(
                "Favor small-group, safety-forward activities that anchor a balanced day. "
                "Large generic bus tours and weak-review operators should be rejected."
            ),
            warnings=[
                "Review count, operator safety practices, exact duration, and cancellation need live validation.",
                "Weather-dependent tours need backup plans and buffer days.",
            ],
            next_actions=[
                "Open GetYourGuide for top candidates and filter by rating, cancellation, and group size.",
                "Validate operator reputation on Tripadvisor.",
                "Place each activity into the map/day plan before booking to avoid overpacking.",
            ],
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        return self._store.save(state)


def _options_from_profile(
    profile: object,
    intake: TripIntake,
    selected_regions: list[str],
) -> list[ActivityOption]:
    targets = [
        target
        for target in getattr(profile, "activity_search_targets", [])
        if target_matches_selected_regions(
            target,
            selected_regions,
            getattr(profile, "island_or_region_terms", []),
        )
    ]
    party = intake.party
    traveler_count = party.total_travelers
    has_children = party.has_children
    options: list[ActivityOption] = []
    for idx, target in enumerate(targets[:5], start=1):
        query = str(target["query"])
        flags = []
        if "whale" in query.lower():
            flags.append("weather and sea-condition dependent")
        if "private" not in query.lower() and "small" not in query.lower():
            flags.append("group size must be checked")
        if "volcano" in query.lower() or "wine" in query.lower():
            flags.append("second-island logistics must match selected plan")
        if has_children and "wine" in query.lower():
            flags.append("child interest/age fit must be validated")
        options.append(
            ActivityOption(
                option_id=f"activity-{idx}",
                rank=idx,
                activity_name=str(target["name"]),
                source="GetYourGuide",
                island_location=str(target["location"]),
                group_size_signal="prefer small/private; live listing must confirm",
                review_safety_signal="require strong recent reviews and clear operator/safety details",
                age_family_fit=(
                    f"Must fit {traveler_count} traveler(s), including {party.children} child(ren)."
                    if has_children
                    else f"Must fit {traveler_count} adult traveler(s)."
                ),
                price_band="live verify per person/family total",
                duration="half-day target unless explicitly planned as a full-day anchor",
                deep_link=source_search_url("GetYourGuide", query),
                validation_links={
                    "Tripadvisor": source_search_url("Tripadvisor", query),
                    "Airbnb Experiences": source_search_url("Airbnb Experiences", query),
                },
                family_pace_fit_score=88 if idx <= 3 else 74,
                safety_confidence_score=78,
                crowd_fit_score=84
                if "private" in query.lower() or "small" in query.lower()
                else 66,
                total_friction_score=18 + len(flags) * 8,
                recommendation_grade=RecommendationGrade.GOOD
                if idx <= 3
                else RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    "Worth booking if it creates a memorable anchor without forcing a packed day.",
                    "Reject if pickup, group size, or cancellation terms are unclear.",
                ],
                friction_flags=flags,
                confidence_notes=[
                    "Source link is the start of live validation, not a confirmed booking option."
                ],
                live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
            )
        )
    return options
