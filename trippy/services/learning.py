"""Workflow outcome, feedback, and review-gated learning store."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from trippy import config


class WorkflowStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class FeedbackRating(StrEnum):
    HELPFUL = "helpful"
    NEEDS_WORK = "needs-work"
    WRONG = "wrong"


class ProposalType(StrEnum):
    MEMORY = "memory"
    SKILL_PATCH = "skill_patch"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def _new_id(prefix: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


class WorkflowOutcome(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("wf"))
    workflow_name: str
    skill_name: str | None = None
    trip_id: str | None = None
    status: WorkflowStatus
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    resolved_issues: list[dict[str, Any]] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)


class UserFeedback(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("fb"))
    workflow_id: str
    rating: FeedbackRating
    notes: str
    correction: str | None = None
    future_learning: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LearningProposal(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("lp"))
    proposal_type: ProposalType
    status: ProposalStatus = ProposalStatus.PENDING
    summary: str
    source_workflow_id: str | None = None
    source_feedback_id: str | None = None
    before: Any = None
    after: Any = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None


class _ProposalFile(BaseModel):
    version: str = "1.0"
    proposals: list[LearningProposal] = Field(default_factory=list)


class LearningEventStore:
    """Append-only workflow event log plus reviewable learning proposals."""

    def __init__(self, learning_dir: Path | None = None, memory_path: Path | None = None) -> None:
        self._dir = learning_dir or config.LEARNING_PATH
        self._events_path = self._dir / "events.jsonl"
        self._proposals_path = self._dir / "proposals.json"
        self._memory_path = memory_path or config.MEMORY_PATH

    @property
    def events_path(self) -> Path:
        return self._events_path

    @property
    def proposals_path(self) -> Path:
        return self._proposals_path

    def record_workflow(self, outcome: WorkflowOutcome) -> WorkflowOutcome:
        self._append_event("workflow_outcome", outcome.model_dump(mode="json"))
        return outcome

    def record_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a structured operational event to the learning log."""
        return self._append_event(event_type, payload)

    def add_feedback(self, feedback: UserFeedback) -> list[LearningProposal]:
        self._append_event("user_feedback", feedback.model_dump(mode="json"))
        proposals = self._proposals_from_feedback(feedback)
        self.add_proposals(proposals)
        return proposals

    def add_proposals(self, proposals: list[LearningProposal]) -> list[LearningProposal]:
        """Persist pending proposals without applying them."""
        if not proposals:
            return []
        proposal_file = self._load_proposal_file()
        proposal_file.proposals.extend(proposals)
        self._save_proposal_file(proposal_file)
        for proposal in proposals:
            self._append_event("learning_proposal", proposal.model_dump(mode="json"))
        return proposals

    def list_workflows(self) -> list[WorkflowOutcome]:
        workflows: list[WorkflowOutcome] = []
        for event in self._read_events():
            if event.get("event_type") == "workflow_outcome":
                workflows.append(WorkflowOutcome.model_validate(event["payload"]))
        return workflows

    def list_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return raw append-only events for diagnostics and UI run logs."""
        events = self._read_events()
        if limit is None:
            return events
        return events[-max(limit, 0) :]

    def get_workflow(self, workflow_id: str) -> WorkflowOutcome | None:
        for outcome in reversed(self.list_workflows()):
            if outcome.id == workflow_id:
                return outcome
        return None

    def list_proposals(
        self,
        status: ProposalStatus | None = ProposalStatus.PENDING,
    ) -> list[LearningProposal]:
        proposals = self._load_proposal_file().proposals
        if status is None:
            return proposals
        return [proposal for proposal in proposals if proposal.status == status]

    def approve(self, proposal_id: str) -> LearningProposal:
        proposal_file = self._load_proposal_file()
        proposal = self._find_proposal(proposal_file, proposal_id)
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal {proposal_id!r} is already {proposal.status.value}")

        if proposal.proposal_type == ProposalType.MEMORY:
            self._apply_memory_proposal(proposal)
        elif proposal.proposal_type == ProposalType.SKILL_PATCH:
            self._apply_skill_patch_proposal(proposal)

        proposal.status = ProposalStatus.APPROVED
        proposal.resolved_at = datetime.utcnow()
        self._save_proposal_file(proposal_file)
        self._append_event("learning_proposal_approved", proposal.model_dump(mode="json"))
        return proposal

    def reject(self, proposal_id: str) -> LearningProposal:
        proposal_file = self._load_proposal_file()
        proposal = self._find_proposal(proposal_file, proposal_id)
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal {proposal_id!r} is already {proposal.status.value}")
        proposal.status = ProposalStatus.REJECTED
        proposal.resolved_at = datetime.utcnow()
        self._save_proposal_file(proposal_file)
        self._append_event("learning_proposal_rejected", proposal.model_dump(mode="json"))
        return proposal

    def _proposals_from_feedback(self, feedback: UserFeedback) -> list[LearningProposal]:
        if not feedback.future_learning:
            return []

        outcome = self.get_workflow(feedback.workflow_id)
        learning_text = (feedback.correction or feedback.notes).strip()
        if not learning_text:
            return []

        proposals = [
            self._memory_proposal(feedback=feedback, outcome=outcome, learning_text=learning_text)
        ]
        if outcome and outcome.skill_name:
            skill = self._skill_patch_proposal(
                feedback=feedback,
                outcome=outcome,
                learning_text=learning_text,
            )
            if skill is not None:
                proposals.append(skill)
        return proposals

    def _memory_proposal(
        self,
        *,
        feedback: UserFeedback,
        outcome: WorkflowOutcome | None,
        learning_text: str,
    ) -> LearningProposal:
        key = f"hint:user-feedback-{feedback.workflow_id}"
        before = self._current_memory_value(key)
        after = {
            "key": key,
            "value": learning_text,
            "category": "skill_hint",
            "confidence": 0.7 if feedback.rating == FeedbackRating.NEEDS_WORK else 0.8,
            "source": "user-feedback",
            "notes": f"Feedback on {outcome.workflow_name if outcome else feedback.workflow_id}",
        }
        return LearningProposal(
            proposal_type=ProposalType.MEMORY,
            summary=f"Remember user feedback for future workflows: {learning_text[:120]}",
            source_workflow_id=feedback.workflow_id,
            source_feedback_id=feedback.id,
            before=before,
            after=after,
        )

    def _skill_patch_proposal(
        self,
        *,
        feedback: UserFeedback,
        outcome: WorkflowOutcome,
        learning_text: str,
    ) -> LearningProposal | None:
        from trippy.services.skill_learning import SkillLearningService

        if outcome.skill_name is None:
            return None

        svc = SkillLearningService()
        lessons = svc.extract_candidate_lessons(
            [
                {
                    "status": "success",
                    "skill_name": outcome.skill_name,
                    "quality_notes": [learning_text],
                    "evidence": [
                        f"workflow:{outcome.id}",
                        f"feedback:{feedback.id}",
                        *(outcome.evidence_refs or []),
                    ],
                }
            ]
        )
        if not lessons:
            return None
        proposal = svc.propose_skill_patch(outcome.skill_name, lessons)
        return LearningProposal(
            proposal_type=ProposalType.SKILL_PATCH,
            summary=f"Patch {outcome.skill_name} from reviewed feedback",
            source_workflow_id=feedback.workflow_id,
            source_feedback_id=feedback.id,
            before={"summary": proposal.before_summary},
            after={"skill_patch": proposal.model_dump(mode="json")},
        )

    def _apply_memory_proposal(self, proposal: LearningProposal) -> None:
        from trippy.memory.store import MemoryStore

        data = proposal.after
        if not isinstance(data, dict):
            raise ValueError("Memory proposal is missing after data")
        memory = MemoryStore(self._memory_path)
        memory.set(
            key=str(data["key"]),
            value=data["value"],
            category=str(data["category"]),
            confidence=float(data.get("confidence", 0.7)),
            source=str(data.get("source", "learning-review")),
            notes=str(data["notes"]) if data.get("notes") else None,
        )

    def _apply_skill_patch_proposal(self, proposal: LearningProposal) -> None:
        from trippy.services.skill_learning import (
            SkillLearningService,
            SkillPatchProposal,
        )

        data = proposal.after
        if not isinstance(data, dict) or "skill_patch" not in data:
            raise ValueError("Skill patch proposal is missing patch data")
        patch = SkillPatchProposal.model_validate(data["skill_patch"])
        SkillLearningService().apply_patch(
            patch,
            human_approval_required=True,
            approved_by_human=True,
        )

    def _current_memory_value(self, key: str) -> Any:
        from trippy.memory.store import MemoryStore

        entry = MemoryStore(self._memory_path).get(key)
        return entry.model_dump(mode="json") if entry else None

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._dir.mkdir(parents=True, exist_ok=True)
        event = {
            "event_id": _new_id("evt"),
            "event_type": event_type,
            "created_at": datetime.utcnow().isoformat(),
            "payload": payload,
        }
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def _read_events(self) -> list[dict[str, Any]]:
        if not self._events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self._events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def _load_proposal_file(self) -> _ProposalFile:
        if not self._proposals_path.exists():
            return _ProposalFile()
        raw = json.loads(self._proposals_path.read_text(encoding="utf-8"))
        return _ProposalFile.model_validate(raw)

    def _save_proposal_file(self, proposal_file: _ProposalFile) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._proposals_path.write_text(
            proposal_file.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _find_proposal(self, proposal_file: _ProposalFile, proposal_id: str) -> LearningProposal:
        for proposal in proposal_file.proposals:
            if proposal.id == proposal_id:
                return proposal
        raise ValueError(f"Proposal {proposal_id!r} not found")


EventPayload = Literal[
    "workflow_outcome",
    "user_feedback",
    "learning_proposal",
    "learning_proposal_approved",
    "learning_proposal_rejected",
    "ui_error",
]
