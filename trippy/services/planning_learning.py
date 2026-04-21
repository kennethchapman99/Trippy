"""Review-gated learning proposals from planning outcomes and shortlists."""

from __future__ import annotations

from trippy.models.shortlists import RecommendationGrade, ShortlistCategory
from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class PlanningLearningService:
    """Create reviewable memory proposals from explicit planning choices."""

    def __init__(
        self,
        planner_service: TripPlannerService | None = None,
        shortlist_store: ShortlistStore | None = None,
        learning_store: LearningEventStore | None = None,
        intake_service: TripIntakeService | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService()
        self._shortlists = shortlist_store or ShortlistStore()
        self._learning = learning_store or LearningEventStore()

    def propose_for_trip(
        self,
        trip_id: str,
        *,
        source_workflow_id: str | None = None,
    ) -> list[LearningProposal]:
        draft = self._planner.require_draft(trip_id)
        intake = self._intakes.load(trip_id)
        proposals: list[LearningProposal] = []
        if intake is not None and intake.party.explicit:
            proposals.append(
                _proposal(
                    trip_id,
                    source_workflow_id,
                    key=f"planning:traveler-composition:{trip_id}",
                    summary="Review trip-specific traveler composition signal",
                    value=(
                        f"{intake.party.summary()} changed planning requirements for flights, "
                        "lodging, cars, activities, and pacing."
                    ),
                    confidence=0.54,
                )
            )
        selected = draft.get_option()
        if selected is not None:
            proposals.append(
                LearningProposal(
                    proposal_type=ProposalType.MEMORY,
                    summary=f"Remember planning selection signal for {trip_id}: {selected.title}",
                    source_workflow_id=source_workflow_id,
                    after={
                        "key": f"planning:selected-option:{trip_id}",
                        "value": {
                            "option_id": selected.option_id,
                            "title": selected.title,
                            "regions": selected.regions,
                            "movement_friction": selected.island_region_movement_friction,
                            "comfort_score": selected.family_comfort_score,
                            "recommendation_strength": selected.recommendation_strength,
                        },
                        "category": "trip_insight",
                        "confidence": 0.72,
                        "source": "planning-selection",
                        "notes": "Review before treating this trip-specific choice as durable preference evidence.",
                    },
                )
            )
            if "ambitious" not in selected.option_id and any(
                "ambitious" in option.option_id for option in draft.options
            ):
                proposals.append(
                    LearningProposal(
                        proposal_type=ProposalType.MEMORY,
                        summary=(
                            f"Review lower-movement preference signal from {trip_id}: "
                            f"selected {selected.option_id}"
                        ),
                        source_workflow_id=source_workflow_id,
                        after={
                            "key": f"planning:lower-movement:{trip_id}",
                            "value": "Family selected a lower-friction plan shape over the ambitious island sampler.",
                            "category": "preference",
                            "confidence": 0.58,
                            "source": "planning-selection",
                            "notes": "Only approve as durable if this matches the human rationale.",
                        },
                    )
                )

        for state in self._shortlists.load_all(trip_id):
            verified_count = sum(
                1
                for option in state.options_as_dicts()
                if option.get("row_status") == "verified_live"
            )
            if verified_count:
                proposals.append(
                    _proposal(
                        trip_id,
                        source_workflow_id,
                        key=f"planning:live-validation:{state.category.value}:{trip_id}",
                        summary=f"Review live-validation evidence for {state.category.value}",
                        value=(
                            f"{verified_count} {state.category.value} option(s) had current source-link validation; "
                            "compare live-validated rows against deterministic ranking before treating as durable preference evidence."
                        ),
                        confidence=0.5,
                    )
                )
            if state.category == ShortlistCategory.FLIGHTS and state.recommended_option_id:
                proposals.append(
                    _proposal(
                        trip_id,
                        source_workflow_id,
                        key=f"planning:flight-shortlist:{trip_id}",
                        summary="Review flight shortlist preference signal",
                        value="Lower-friction flight shapes should be favored over cheaper multi-ticket or baggage-risk options.",
                        confidence=0.62,
                    )
                )
            if state.category == ShortlistCategory.LODGING:
                rejected_bed_flags = [
                    option.name
                    for option in state.lodging_options
                    if "family 3-bed layout is not proven" in option.friction_flags
                ]
                if rejected_bed_flags:
                    proposals.append(
                        _proposal(
                            trip_id,
                            source_workflow_id,
                            key=f"planning:lodging-bed-fit:{trip_id}",
                            summary="Review lodging bed-fit enforcement signal",
                            value=(
                                "Do not advance lodging unless family-of-5 occupancy and 3+ beds "
                                "are explicit; queen/ambiguous compromises need exceptional upside."
                            ),
                            confidence=0.68,
                        )
                    )
            if state.category == ShortlistCategory.ACTIVITIES and any(
                option.recommendation_grade
                in {RecommendationGrade.GOOD, RecommendationGrade.STRONG}
                for option in state.activity_options
            ):
                proposals.append(
                    _proposal(
                        trip_id,
                        source_workflow_id,
                        key=f"planning:activity-style:{trip_id}",
                        summary="Review activity style preference signal",
                        value="Small-group, safety-forward tours are preferred over large generic crowd experiences.",
                        confidence=0.6,
                    )
                )
        return self._learning.add_proposals(proposals)


def _proposal(
    trip_id: str,
    source_workflow_id: str | None,
    *,
    key: str,
    summary: str,
    value: str,
    confidence: float,
) -> LearningProposal:
    return LearningProposal(
        proposal_type=ProposalType.MEMORY,
        summary=f"{summary} for {trip_id}",
        source_workflow_id=source_workflow_id,
        after={
            "key": key,
            "value": value,
            "category": "preference",
            "confidence": confidence,
            "source": "planning-outcome",
            "notes": "Review-gated planning proposal; do not apply unless it matches human intent.",
        },
    )
