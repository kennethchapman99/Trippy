"""Skill-learning service for proposing, evaluating, and versioning skill definition updates.

The service is intentionally deterministic and file-based:
- Learns from *structured workflow outcomes* (not raw logs)
- Proposes markdown patches for trippy/skills/definitions/*.md
- Stores version metadata and snapshots for rollback
- Requires explicit human approval before applying production changes
- Provides a replay harness for pre/post quality comparison
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LessonCandidate(BaseModel):
    """A distilled reusable lesson extracted from successful outcomes."""

    title: str
    recommendation: str
    trigger_evidence: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class SkillPatchProposal(BaseModel):
    """Proposed patch for a single skill definition file."""

    skill_name: str
    definition_path: str
    before_text: str
    after_text: str
    before_summary: str
    after_summary: str
    lessons: list[LessonCandidate]
    trigger_evidence: list[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SkillVersionMetadata(BaseModel):
    """Version history entry for an applied skill definition update."""

    skill_name: str
    version: int
    timestamp: datetime
    trigger_evidence: list[str]
    before_summary: str
    after_summary: str
    before_text: str
    after_text: str


class EvaluationFixture(BaseModel):
    """Replay fixture for patch evaluation."""

    skill_name: str
    outcome: dict[str, Any]
    expected_keywords: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    """Output from the replay/evaluation harness."""

    fixtures_total: int
    pre_patch_score: float
    post_patch_score: float
    delta: float
    details: list[dict[str, Any]]


class _MetadataFile(BaseModel):
    version: str = "1.0"
    entries: list[SkillVersionMetadata] = Field(default_factory=list)


@dataclass(frozen=True)
class _ApplyResult:
    path: Path
    version: int


class SkillLearningService:
    """Service for skill-definition self-improvement with safety guardrails."""

    def __init__(
        self,
        definitions_dir: Path | None = None,
        metadata_path: Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self._definitions_dir = definitions_dir or root / "trippy" / "skills" / "definitions"
        self._metadata_path = metadata_path or root / ".trippy" / "skill_learning" / "metadata.json"
        self._metadata = self._load_metadata()

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def extract_candidate_lessons(self, outcomes: list[dict[str, Any]]) -> list[LessonCandidate]:
        """Extract lessons from structured *outcomes* only.

        Expected outcome shape (minimal):
        {
            "status": "success",
            "skill_name": "trippy-flight-friction-audit",
            "resolved_issues": [{"issue": "tight connection", "fix": "..."}],
            "quality_notes": ["..."],
            "evidence": ["..."]
        }
        """
        lessons: list[LessonCandidate] = []
        for outcome in outcomes:
            if outcome.get("status") != "success":
                continue

            evidence = [str(e) for e in outcome.get("evidence", [])]
            for resolved in outcome.get("resolved_issues", []):
                issue = str(resolved.get("issue", "")).strip()
                fix = str(resolved.get("fix", "")).strip()
                if not issue or not fix:
                    continue
                lessons.append(
                    LessonCandidate(
                        title=f"Handle: {issue}",
                        recommendation=fix,
                        trigger_evidence=evidence,
                        confidence=float(resolved.get("confidence", 1.0)),
                    )
                )

            for note in outcome.get("quality_notes", []):
                note_text = str(note).strip()
                if note_text:
                    lessons.append(
                        LessonCandidate(
                            title="Quality improvement",
                            recommendation=note_text,
                            trigger_evidence=evidence,
                            confidence=0.8,
                        )
                    )
        return lessons

    def propose_skill_patch(
        self,
        skill_name: str,
        lessons: list[LessonCandidate],
    ) -> SkillPatchProposal:
        """Create a patch proposal for a specific skill definition markdown."""
        path = self._definition_path(skill_name)
        before_text = path.read_text(encoding="utf-8")

        additions = [
            "\n## Learned Improvements (Proposed)\n",
            "Derived from successful workflow outcomes (not raw logs).\n",
        ]
        trigger_evidence: list[str] = []
        for lesson in lessons:
            trigger_evidence.extend(lesson.trigger_evidence)
            additions.append(f"- **{lesson.title}**: {lesson.recommendation}\n")

        after_text = before_text.rstrip() + "\n" + "".join(additions)
        return SkillPatchProposal(
            skill_name=skill_name,
            definition_path=str(path),
            before_text=before_text,
            after_text=after_text,
            before_summary=self._summarize(before_text),
            after_summary=self._summarize(after_text),
            lessons=lessons,
            trigger_evidence=sorted(set(trigger_evidence)),
        )

    # ------------------------------------------------------------------
    # Guarded apply + rollback
    # ------------------------------------------------------------------

    def apply_patch(
        self,
        proposal: SkillPatchProposal,
        *,
        human_approval_required: bool = True,
        approved_by_human: bool = False,
    ) -> int:
        """Apply a proposal to the skill definition, guarded by approval flag."""
        if human_approval_required and not approved_by_human:
            raise PermissionError("Human approval required before applying skill definition changes")

        path = Path(proposal.definition_path)
        if not path.exists():
            raise FileNotFoundError(f"Skill definition not found: {path}")

        path.write_text(proposal.after_text, encoding="utf-8")
        result = self._record_version(proposal)
        return result.version

    def rollback(self, skill_name: str, target_version: int | None = None) -> int:
        """Rollback a skill definition to a previous stored version.

        If target_version is omitted, rolls back to the immediate previous version.
        Returns the version restored.
        """
        history = [e for e in self._metadata.entries if e.skill_name == skill_name]
        if not history:
            raise ValueError(f"No metadata history for skill {skill_name!r}")

        history_sorted = sorted(history, key=lambda e: e.version)
        current = history_sorted[-1]

        if target_version is None:
            if len(history_sorted) < 2:
                raise ValueError(f"No previous version available for {skill_name!r}")
            restore_from = history_sorted[-2]
        else:
            candidates = [e for e in history_sorted if e.version == target_version]
            if not candidates:
                raise ValueError(f"Version {target_version} not found for {skill_name!r}")
            restore_from = candidates[0]

        path = self._definition_path(skill_name)
        path.write_text(restore_from.after_text, encoding="utf-8")

        proposal = SkillPatchProposal(
            skill_name=skill_name,
            definition_path=str(path),
            before_text=current.after_text,
            after_text=restore_from.after_text,
            before_summary=f"rollback-from-v{current.version}",
            after_summary=f"rollback-to-v{restore_from.version}",
            lessons=[],
            trigger_evidence=[f"rollback:{skill_name}"],
        )
        applied = self._record_version(proposal)
        return applied.version

    # ------------------------------------------------------------------
    # Evaluation harness
    # ------------------------------------------------------------------

    def evaluate_patch(
        self,
        proposal: SkillPatchProposal,
        fixtures: list[EvaluationFixture],
    ) -> EvaluationResult:
        """Replay fixtures and compare quality metrics pre/post patch.

        Metric: keyword-hit ratio across fixture expected_keywords in skill text.
        """
        relevant = [f for f in fixtures if f.skill_name == proposal.skill_name]
        if not relevant:
            return EvaluationResult(
                fixtures_total=0,
                pre_patch_score=0.0,
                post_patch_score=0.0,
                delta=0.0,
                details=[],
            )

        details: list[dict[str, Any]] = []
        pre_scores: list[float] = []
        post_scores: list[float] = []

        pre_text = proposal.before_text.lower()
        post_text = proposal.after_text.lower()
        for fx in relevant:
            kws = [k.lower() for k in fx.expected_keywords]
            if not kws:
                continue
            pre_hits = sum(1 for k in kws if k in pre_text)
            post_hits = sum(1 for k in kws if k in post_text)
            pre_score = pre_hits / len(kws)
            post_score = post_hits / len(kws)
            pre_scores.append(pre_score)
            post_scores.append(post_score)
            details.append(
                {
                    "skill_name": fx.skill_name,
                    "pre_score": pre_score,
                    "post_score": post_score,
                    "expected_keywords": fx.expected_keywords,
                }
            )

        pre_avg = sum(pre_scores) / len(pre_scores) if pre_scores else 0.0
        post_avg = sum(post_scores) / len(post_scores) if post_scores else 0.0
        return EvaluationResult(
            fixtures_total=len(relevant),
            pre_patch_score=pre_avg,
            post_patch_score=post_avg,
            delta=post_avg - pre_avg,
            details=details,
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _record_version(self, proposal: SkillPatchProposal) -> _ApplyResult:
        latest = self._latest_version(proposal.skill_name)
        new_version = latest + 1
        metadata = SkillVersionMetadata(
            skill_name=proposal.skill_name,
            version=new_version,
            timestamp=datetime.utcnow(),
            trigger_evidence=proposal.trigger_evidence,
            before_summary=proposal.before_summary,
            after_summary=proposal.after_summary,
            before_text=proposal.before_text,
            after_text=proposal.after_text,
        )
        self._metadata.entries.append(metadata)
        self._save_metadata()
        return _ApplyResult(path=Path(proposal.definition_path), version=new_version)

    def _latest_version(self, skill_name: str) -> int:
        versions = [e.version for e in self._metadata.entries if e.skill_name == skill_name]
        return max(versions, default=0)

    def _definition_path(self, skill_name: str) -> Path:
        path = self._definitions_dir / f"{skill_name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Skill definition for {skill_name!r} not found at {path}")
        return path

    def _load_metadata(self) -> _MetadataFile:
        if not self._metadata_path.exists():
            return _MetadataFile()
        raw = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        return _MetadataFile.model_validate(raw)

    def _save_metadata(self) -> None:
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata_path.write_text(self._metadata.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _summarize(text: str, max_lines: int = 3) -> str:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return " | ".join(lines[:max_lines])
