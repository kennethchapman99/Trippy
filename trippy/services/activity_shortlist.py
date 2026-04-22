"""Source-aware activity and tour shortlist generation."""

from __future__ import annotations

import unicodedata
from datetime import date, timedelta
from typing import Any

from trippy.models.shortlists import (
    ActivityOption,
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
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
        existing = self._store.load(trip_id, ShortlistCategory.ACTIVITIES)
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
        _apply_activity_schedule_suggestions(
            state,
            ctx.intake,
            ctx.option,
            self._store.load(trip_id, ShortlistCategory.LODGING),
        )
        _merge_existing_activity_state(state, existing)
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        _write_activity_schedule_artifact(state)
        return self._store.save(state)

    def select_activity(self, trip_id: str, option_id: str) -> ResearchShortlistState:
        """Approve an activity and give it a concrete timeline slot."""
        state = self._store.load(trip_id, ShortlistCategory.ACTIVITIES) or self.build(trip_id)
        option = _activity_by_id(state, option_id)
        if option is None:
            raise ValueError(f"No activity option {option_id!r} for trip {trip_id!r}")
        _schedule_activity_option(option, {})
        state.recommended_option_id = option.option_id
        state.recommendation_summary = (
            f"Approved {option.activity_name}; keep this slot visible in the Master Timeline "
            "and adjust manually if lodging or flight timing changes."
        )
        if (
            "Approved activities now hydrate into the Master Timeline with date/time tracking."
            not in (state.next_actions)
        ):
            state.next_actions.insert(
                0,
                "Approved activities now hydrate into the Master Timeline with date/time tracking.",
            )
        _write_activity_schedule_artifact(state)
        return self._store.save(state)

    def schedule_activity(
        self,
        trip_id: str,
        option_id: str,
        *,
        day: int | None = None,
        date_value: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        fixed: bool = False,
        notes: str = "",
    ) -> ResearchShortlistState:
        """Approve or move an activity into a user-controlled day/time slot."""
        state = self._store.load(trip_id, ShortlistCategory.ACTIVITIES) or self.build(trip_id)
        option = _activity_by_id(state, option_id)
        if option is None:
            raise ValueError(f"No activity option {option_id!r} for trip {trip_id!r}")
        _schedule_activity_option(
            option,
            {
                "day": day,
                "date": date_value,
                "start_time": start_time,
                "end_time": end_time,
                "fixed": fixed,
                "notes": notes,
            },
        )
        state.recommended_option_id = option.option_id
        state.recommendation_summary = (
            "Activity schedule updated. Rebuild or refresh the workspace to see the exact "
            "slot in the Master Timeline."
        )
        _write_activity_schedule_artifact(state)
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


def _activity_by_id(
    state: ResearchShortlistState,
    option_id: str,
) -> ActivityOption | None:
    return next(
        (option for option in state.activity_options if option.option_id == option_id), None
    )


def _apply_activity_schedule_suggestions(
    state: ResearchShortlistState,
    intake: TripIntake,
    option: object,
    lodging_state: ResearchShortlistState | None,
) -> None:
    anchors = _stay_day_anchors(option, lodging_state)
    used_days: set[int] = set()
    for idx, activity in enumerate(state.activity_options, start=1):
        anchor = _best_anchor_for_activity(activity, anchors) or anchors[0]
        day = _suggested_activity_day(
            anchor, used_days, int(getattr(option, "duration_days", 0) or 0)
        )
        used_days.add(day)
        start_time = "09:30" if idx % 2 else "14:00"
        end_time = _default_end_time(start_time, activity.duration)
        date_value = _date_for_day(intake.travel_window.start_date, day)
        activity.suggested_day = day
        activity.suggested_date = date_value.isoformat() if date_value else ""
        activity.suggested_start_time = start_time
        activity.suggested_end_time = end_time
        activity.scheduling_rationale = (
            f"Suggested while based in {anchor['region']} so the activity matches lodging "
            "geography and avoids unnecessary backtracking."
        )
    _write_activity_schedule_artifact(state)


def _merge_existing_activity_state(
    state: ResearchShortlistState,
    existing: ResearchShortlistState | None,
) -> None:
    if existing is None:
        return
    existing_by_id = {option.option_id: option for option in existing.activity_options}
    for option in state.activity_options:
        previous = existing_by_id.get(option.option_id)
        if previous is None:
            continue
        option.row_status = previous.row_status
        option.scheduled_day = previous.scheduled_day
        option.scheduled_date = previous.scheduled_date
        option.scheduled_start_time = previous.scheduled_start_time
        option.scheduled_end_time = previous.scheduled_end_time
        option.scheduled_flexibility = previous.scheduled_flexibility
        option.scheduling_notes = previous.scheduling_notes
        if previous.suggested_day:
            option.suggested_day = previous.suggested_day
            option.suggested_date = previous.suggested_date
            option.suggested_start_time = previous.suggested_start_time
            option.suggested_end_time = previous.suggested_end_time
            option.scheduling_rationale = previous.scheduling_rationale
    if existing.recommended_option_id:
        state.recommended_option_id = existing.recommended_option_id
    state.artifacts.update(existing.artifacts)
    _write_activity_schedule_artifact(state)


def _schedule_activity_option(option: ActivityOption, values: dict[str, Any]) -> None:
    day = _positive_int(values.get("day")) or option.scheduled_day or option.suggested_day
    date_value = str(values.get("date") or option.scheduled_date or option.suggested_date or "")
    start_time = str(
        values.get("start_time")
        or option.scheduled_start_time
        or option.suggested_start_time
        or "09:30"
    )
    end_time = str(
        values.get("end_time")
        or option.scheduled_end_time
        or option.suggested_end_time
        or _default_end_time(start_time, option.duration)
    )
    option.row_status = ShortlistRowStatus.APPROVED
    option.scheduled_day = day
    option.scheduled_date = date_value
    option.scheduled_start_time = start_time
    option.scheduled_end_time = end_time
    option.scheduled_flexibility = "fixed" if bool(values.get("fixed", False)) else "flexible"
    notes = str(values.get("notes") or "").strip()
    if notes:
        option.scheduling_notes = notes
    elif not option.scheduling_notes:
        option.scheduling_notes = "Approved from activity shortlist; confirm exact operator time."


def _write_activity_schedule_artifact(state: ResearchShortlistState) -> None:
    entries = []
    for option in state.activity_options:
        entries.append(
            {
                "activity_option_id": option.option_id,
                "activity_name": option.activity_name,
                "location": option.island_location,
                "status": option.row_status.value,
                "suggested_day": option.suggested_day,
                "suggested_date": option.suggested_date,
                "suggested_start_time": option.suggested_start_time,
                "suggested_end_time": option.suggested_end_time,
                "scheduled_day": option.scheduled_day,
                "scheduled_date": option.scheduled_date,
                "scheduled_start_time": option.scheduled_start_time,
                "scheduled_end_time": option.scheduled_end_time,
                "fixed_vs_flexible": option.scheduled_flexibility,
                "rationale": option.scheduling_rationale,
                "notes": option.scheduling_notes,
            }
        )
    state.artifacts["activity_schedule"] = {
        "data_status": "suggested_and_manual",
        "summary": (
            "Activities are suggested against lodging geography. Approved activities get "
            "explicit day/time slots for tracking in the Master Timeline."
        ),
        "entries": entries,
    }


def _stay_day_anchors(
    option: object,
    lodging_state: ResearchShortlistState | None,
) -> list[dict[str, int | str]]:
    structure = (getattr(lodging_state, "artifacts", {}) or {}).get("lodging_structure", {})
    raw_plan = structure.get("night_plan") if isinstance(structure, dict) else None
    if not raw_plan:
        raw_plan = [
            {"region": region, "nights": nights}
            for region, nights in getattr(option, "nights_by_region", {}).items()
        ]
    if not raw_plan:
        raw_plan = [{"region": region, "nights": 2} for region in getattr(option, "regions", [])]
    anchors: list[dict[str, int | str]] = []
    cursor = 1
    for raw in raw_plan or [{"region": "destination", "nights": 2}]:
        region = str(raw.get("region") or "destination")
        nights = max(1, _positive_int(raw.get("nights")) or 1)
        anchors.append(
            {
                "region": region,
                "start_day": cursor,
                "end_day": cursor + nights,
                "nights": nights,
            }
        )
        cursor += nights
    return anchors or [{"region": "destination", "start_day": 2, "end_day": 3, "nights": 1}]


def _best_anchor_for_activity(
    activity: ActivityOption,
    anchors: list[dict[str, int | str]],
) -> dict[str, int | str] | None:
    location = _normalize_location(activity.island_location)
    for anchor in anchors:
        region = _normalize_location(str(anchor["region"]))
        if region and (region in location or location in region):
            return anchor
        for piece in region.replace(" or ", " / ").split(" / "):
            piece = piece.strip()
            if piece and piece in location:
                return anchor
    return None


def _suggested_activity_day(
    anchor: dict[str, int | str],
    used_days: set[int],
    duration_days: int,
) -> int:
    start_day = int(anchor["start_day"])
    end_day = int(anchor["end_day"])
    first_usable = start_day + (1 if start_day == 1 else 0)
    last_usable = max(first_usable, end_day - 1)
    if duration_days:
        last_usable = min(last_usable, max(1, duration_days - 1))
    candidates = list(range(first_usable, last_usable + 1)) or [max(2, start_day)]
    middle = candidates[len(candidates) // 2]
    ordered = [middle, *candidates]
    for day in ordered:
        if day not in used_days:
            return day
    return ordered[0]


def _date_for_day(start: date | None, day: int | None) -> date | None:
    if start is None or not day:
        return None
    return start + timedelta(days=max(0, day - 1))


def _default_end_time(start_time: str, duration: str) -> str:
    if start_time == "14:00":
        return "17:30" if "full" not in duration.lower() else "18:00"
    return "13:00" if "full" not in duration.lower() else "16:30"


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_location(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().replace("-", " ").split())
