"""Tests for SkillLearningService."""

from __future__ import annotations

from pathlib import Path

import pytest

from trippy.services.skill_learning import EvaluationFixture, SkillLearningService


@pytest.fixture
def skill_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    defs_dir = tmp_path / "defs"
    defs_dir.mkdir(parents=True)
    skill_file = defs_dir / "trippy-flight-friction-audit.md"
    skill_file.write_text(
        "# Skill: trippy-flight-friction-audit\n\n## Purpose\nAudit flight plan.\n",
        encoding="utf-8",
    )
    metadata = tmp_path / "skill_learning" / "metadata.json"
    return defs_dir, metadata, skill_file


class TestLessonExtraction:
    def test_extracts_lessons_from_successful_outcomes_only(
        self,
        skill_env: tuple[Path, Path, Path],
    ) -> None:
        defs_dir, metadata, _ = skill_env
        svc = SkillLearningService(definitions_dir=defs_dir, metadata_path=metadata)

        outcomes = [
            {
                "status": "success",
                "resolved_issues": [
                    {"issue": "tight connection", "fix": "Prefer >=120 min", "confidence": 0.9}
                ],
                "quality_notes": ["Always validate baggage assumptions"],
                "evidence": ["trip japan-2026 had missed connection risk"],
            },
            {"status": "failed", "resolved_issues": [{"issue": "x", "fix": "y"}]},
        ]

        lessons = svc.extract_candidate_lessons(outcomes)
        assert len(lessons) == 2
        assert lessons[0].title == "Handle: tight connection"
        assert lessons[0].confidence == pytest.approx(0.9)


class TestPatchProposalAndGuardrails:
    def test_proposes_patch_appending_lessons(self, skill_env: tuple[Path, Path, Path]) -> None:
        defs_dir, metadata, _ = skill_env
        svc = SkillLearningService(definitions_dir=defs_dir, metadata_path=metadata)
        lessons = svc.extract_candidate_lessons(
            [
                {
                    "status": "success",
                    "resolved_issues": [{"issue": "early departure", "fix": "Avoid before 07:00"}],
                    "evidence": ["family comfort preference"],
                }
            ]
        )

        proposal = svc.propose_skill_patch("trippy-flight-friction-audit", lessons)
        assert "Learned Improvements (Proposed)" in proposal.after_text
        assert "Avoid before 07:00" in proposal.after_text
        assert proposal.trigger_evidence == ["family comfort preference"]

    def test_apply_requires_human_approval(self, skill_env: tuple[Path, Path, Path]) -> None:
        defs_dir, metadata, _ = skill_env
        svc = SkillLearningService(definitions_dir=defs_dir, metadata_path=metadata)
        proposal = svc.propose_skill_patch("trippy-flight-friction-audit", [])

        with pytest.raises(PermissionError, match="Human approval required"):
            svc.apply_patch(proposal, human_approval_required=True, approved_by_human=False)

    def test_apply_updates_version_metadata(self, skill_env: tuple[Path, Path, Path]) -> None:
        defs_dir, metadata, skill_file = skill_env
        svc = SkillLearningService(definitions_dir=defs_dir, metadata_path=metadata)
        proposal = svc.propose_skill_patch("trippy-flight-friction-audit", [])

        version = svc.apply_patch(proposal, human_approval_required=True, approved_by_human=True)
        assert version == 1
        assert metadata.exists()
        assert "Learned Improvements (Proposed)" in skill_file.read_text(encoding="utf-8")


class TestRollback:
    def test_rolls_back_to_previous_version(self, skill_env: tuple[Path, Path, Path]) -> None:
        defs_dir, metadata, skill_file = skill_env
        svc = SkillLearningService(definitions_dir=defs_dir, metadata_path=metadata)

        p1 = svc.propose_skill_patch(
            "trippy-flight-friction-audit",
            svc.extract_candidate_lessons(
                [
                    {
                        "status": "success",
                        "resolved_issues": [{"issue": "a", "fix": "first fix"}],
                    }
                ]
            ),
        )
        svc.apply_patch(p1, approved_by_human=True)

        p2 = svc.propose_skill_patch(
            "trippy-flight-friction-audit",
            svc.extract_candidate_lessons(
                [
                    {
                        "status": "success",
                        "resolved_issues": [{"issue": "b", "fix": "second fix"}],
                    }
                ]
            ),
        )
        svc.apply_patch(p2, approved_by_human=True)
        assert "second fix" in skill_file.read_text(encoding="utf-8")

        rollback_version = svc.rollback("trippy-flight-friction-audit")
        assert rollback_version == 3
        assert "first fix" in skill_file.read_text(encoding="utf-8")
        assert "second fix" not in skill_file.read_text(encoding="utf-8")


class TestEvaluationHarness:
    def test_replays_fixtures_and_compares_pre_post(
        self, skill_env: tuple[Path, Path, Path]
    ) -> None:
        defs_dir, metadata, _ = skill_env
        svc = SkillLearningService(definitions_dir=defs_dir, metadata_path=metadata)

        lessons = svc.extract_candidate_lessons(
            [
                {
                    "status": "success",
                    "resolved_issues": [
                        {"issue": "tight connection", "fix": "Require 120 min connection buffer"}
                    ],
                }
            ]
        )
        proposal = svc.propose_skill_patch("trippy-flight-friction-audit", lessons)

        fixtures = [
            EvaluationFixture(
                skill_name="trippy-flight-friction-audit",
                outcome={"status": "success"},
                expected_keywords=["connection buffer", "120 min"],
            )
        ]

        result = svc.evaluate_patch(proposal, fixtures)
        assert result.fixtures_total == 1
        assert result.post_patch_score >= result.pre_patch_score
        assert result.delta >= 0
