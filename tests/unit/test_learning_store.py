"""Tests for workflow feedback and review-gated learning."""

from __future__ import annotations

from pathlib import Path

import pytest

from trippy.memory.store import MemoryStore
from trippy.services.learning import (
    FeedbackRating,
    LearningEventStore,
    ProposalStatus,
    ProposalType,
    UserFeedback,
    WorkflowOutcome,
    WorkflowStatus,
)


def test_records_workflow_outcomes_deterministically(tmp_path: Path) -> None:
    store = LearningEventStore(tmp_path / "learning")
    outcome = WorkflowOutcome(
        workflow_name="friction-audit",
        skill_name="trippy-flight-friction-audit",
        trip_id="japan-2027",
        status=WorkflowStatus.SUCCESS,
        summary="Found one tight connection",
        metrics={"total_risks": 1},
    )

    store.record_workflow(outcome)

    loaded = store.list_workflows()
    assert [item.id for item in loaded] == [outcome.id]
    assert store.events_path.exists()


def test_feedback_creates_reviewable_memory_proposal_without_mutating_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trippy import config

    memory_path = tmp_path / "memory.json"
    monkeypatch.setattr(config, "MEMORY_PATH", memory_path)

    store = LearningEventStore(tmp_path / "learning")
    outcome = store.record_workflow(
        WorkflowOutcome(
            workflow_name="gmail-reconciler",
            skill_name=None,
            trip_id="japan-2027",
            status=WorkflowStatus.SUCCESS,
            summary="Reconciled Gmail",
        )
    )

    proposals = store.add_feedback(
        UserFeedback(
            workflow_id=outcome.id,
            rating=FeedbackRating.NEEDS_WORK,
            notes="Prefer direct transfers when arriving late with luggage.",
            future_learning=True,
        )
    )

    assert len(proposals) == 1
    assert proposals[0].proposal_type == ProposalType.MEMORY
    assert proposals[0].status == ProposalStatus.PENDING
    assert not memory_path.exists()


def test_approving_memory_proposal_writes_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trippy import config

    memory_path = tmp_path / "memory.json"
    monkeypatch.setattr(config, "MEMORY_PATH", memory_path)

    store = LearningEventStore(tmp_path / "learning")
    outcome = store.record_workflow(
        WorkflowOutcome(
            workflow_name="trip-sheet-creator",
            skill_name=None,
            trip_id="japan-2027",
            status=WorkflowStatus.SUCCESS,
            summary="Created sheet",
        )
    )
    proposals = store.add_feedback(
        UserFeedback(
            workflow_id=outcome.id,
            rating=FeedbackRating.HELPFUL,
            notes="Always add a JR Pass checklist item for Japan rail-heavy trips.",
            future_learning=True,
        )
    )

    approved = store.approve(proposals[0].id)

    assert approved.status == ProposalStatus.APPROVED
    entries = MemoryStore(memory_path).all_entries()
    assert len(entries) == 1
    assert "JR Pass" in str(entries[0].value)
