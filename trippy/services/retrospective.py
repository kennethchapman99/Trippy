"""Post-trip retrospective workflow with review-gated learning proposals."""

from __future__ import annotations

import re
from pathlib import Path

from trippy.models.retrospective import TripRetrospectiveInput, TripRetrospectiveResult
from trippy.services.learning import (
    LearningEventStore,
    LearningProposal,
    ProposalType,
    WorkflowOutcome,
    WorkflowStatus,
)
from trippy.services.trip_state import TripStateService


class RetrospectiveService:
    """Capture post-trip lessons without silently mutating memory."""

    def __init__(
        self,
        trip_state: TripStateService | None = None,
        learning_store: LearningEventStore | None = None,
    ) -> None:
        self._trip_state = trip_state or TripStateService()
        self._learning_store = learning_store or LearningEventStore()

    def record(self, retrospective: TripRetrospectiveInput) -> TripRetrospectiveResult:
        trip = self._trip_state.load(retrospective.trip_id)
        if trip is None:
            raise ValueError(f"Trip {retrospective.trip_id!r} not found")

        outcome = self._learning_store.record_workflow(
            WorkflowOutcome(
                workflow_name="post-trip-retrospective",
                skill_name="trippy-preference-extractor",
                trip_id=trip.trip_id,
                status=WorkflowStatus.SUCCESS,
                summary=f"Captured retrospective for {trip.name}",
                metrics={
                    "worked": len(retrospective.worked),
                    "friction": len(retrospective.friction),
                    "hard_rules": len(retrospective.hard_rules),
                    "never_repeat": len(retrospective.never_repeat),
                    "favorites": len(retrospective.favorites),
                },
                artifacts={"retrospective": retrospective.model_dump(mode="json")},
                evidence_refs=[f"trip:{trip.trip_id}", "source:post-trip-retrospective"],
            )
        )
        proposals = self._learning_store.add_proposals(
            _proposals_from_retrospective(retrospective, source_workflow_id=outcome.id)
        )
        return TripRetrospectiveResult(
            trip_id=trip.trip_id,
            workflow_id=outcome.id,
            proposal_ids=[proposal.id for proposal in proposals],
            summary=f"Captured retrospective and created {len(proposals)} review-gated proposal(s).",
        )


def retrospective_store(learning_dir: Path, memory_path: Path) -> LearningEventStore:
    return LearningEventStore(learning_dir, memory_path=memory_path)


def _proposals_from_retrospective(
    retrospective: TripRetrospectiveInput,
    *,
    source_workflow_id: str,
) -> list[LearningProposal]:
    proposals: list[LearningProposal] = []
    for item in retrospective.hard_rules:
        proposals.append(
            _memory_proposal(
                retrospective,
                key=f"rule:retro:{retrospective.trip_id}:{_slug(item)}",
                value=item,
                category="preference",
                confidence=0.85,
                summary=f"Review hard travel rule from retrospective: {item[:120]}",
                source_workflow_id=source_workflow_id,
            )
        )
    for item in retrospective.never_repeat:
        proposals.append(
            _memory_proposal(
                retrospective,
                key=f"rule:never-repeat:{retrospective.trip_id}:{_slug(item)}",
                value=item,
                category="skill_hint",
                confidence=0.8,
                summary=f"Review never-repeat lesson from retrospective: {item[:120]}",
                source_workflow_id=source_workflow_id,
            )
        )
    for item in retrospective.friction:
        proposals.append(
            _memory_proposal(
                retrospective,
                key=f"friction:retro:{retrospective.trip_id}:{_slug(item)}",
                value=item,
                category="skill_hint",
                confidence=0.75,
                summary=f"Review friction lesson from retrospective: {item[:120]}",
                source_workflow_id=source_workflow_id,
            )
        )
    for item in retrospective.favorites:
        proposals.append(
            _memory_proposal(
                retrospective,
                key=f"favorite:retro:{retrospective.trip_id}:{_slug(item)}",
                value=item,
                category="trip_insight",
                confidence=0.7,
                summary=f"Review favorite trip pattern from retrospective: {item[:120]}",
                source_workflow_id=source_workflow_id,
            )
        )

    if retrospective.pace:
        proposals.append(
            _memory_proposal(
                retrospective,
                key=f"pace:retro:{retrospective.trip_id}",
                value=retrospective.pace,
                category="preference",
                confidence=0.75,
                summary=f"Review pacing lesson from retrospective: {retrospective.pace[:120]}",
                source_workflow_id=source_workflow_id,
            )
        )
    return proposals


def _memory_proposal(
    retrospective: TripRetrospectiveInput,
    *,
    key: str,
    value: str,
    category: str,
    confidence: float,
    summary: str,
    source_workflow_id: str,
) -> LearningProposal:
    return LearningProposal(
        proposal_type=ProposalType.MEMORY,
        summary=summary,
        source_workflow_id=source_workflow_id,
        after={
            "key": key,
            "value": {
                "trip_id": retrospective.trip_id,
                "lesson": value,
                "evidence": "post-trip-retrospective",
            },
            "category": category,
            "confidence": confidence,
            "source": "post-trip-retrospective",
            "notes": retrospective.notes,
        },
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "lesson"
