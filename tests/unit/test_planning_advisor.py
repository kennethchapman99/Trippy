"""Tests for preference-rich planning-advisor prompts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from trippy.models.ideas import TripIdeaRequest
from trippy.models.planning_advice import PlanningAdviceKind
from trippy.models.trip_planning import (
    TravelWindow,
    TripIntake,
    TripIntakeMode,
    TripParty,
    TripPartyType,
)
from trippy.services.lodging_shortlist import LodgingShortlistService
from trippy.services.planning_advisor import PlanningAdvisorService
from trippy.services.trip_ideation import TripIdeationService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


def test_planning_advisor_prompt_is_deeply_contextual(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)
    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_couple_intake())
    draft = TripPlannerService(intake_service).draft(intake.trip_id)

    result = PlanningAdvisorService(enabled=False).advise_lodging_structure(
        intake,
        draft.get_option(),
    )

    assert result.kind == PlanningAdviceKind.LODGING_STRUCTURE
    assert result.status == "disabled"
    assert "Family Travel Preferences" in result.prompt
    assert "Azores 2026" in result.prompt
    assert "6-8 days" in result.prompt
    assert "couple" in result.prompt
    assert "king bed strongly preferred" in result.prompt
    assert "one stay or split stays" in result.prompt


def test_planning_advisor_parses_llm_json_response() -> None:
    client = _FakeAnthropicClient(
        {
            "summary": "Split only if the second base cuts real driving.",
            "recommendation": "Use two bases if Pico is kept; otherwise one Sao Miguel base.",
            "rationale": ["Protects downtime", "Avoids backtracking"],
            "next_actions": ["Verify exact flight timing", "Compare two lodging bases"],
            "questions_for_user": ["Is Pico a must-have?"],
            "warnings": ["Do not add a one-night move."],
            "evidence_needed": ["Exact inter-island schedule"],
            "stay_strategy": "split_stay",
            "night_plan": [{"region": "Sao Miguel", "nights": 5, "reason": "main base"}],
            "confidence": 0.72,
        }
    )
    service = PlanningAdvisorService(anthropic_client=client, enabled=True)

    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            duration_days=6,
            travelers=2,
            party_type="couple",
            goals=["food", "nature"],
            avoid=["crowds"],
        )
    )
    result = service.advise_trip_ideas(comparison.request, comparison)

    assert result.status == "llm_success"
    assert result.confidence == 0.72
    assert result.stay_strategy == "split_stay"
    assert result.next_actions[0] == "Verify exact flight timing"
    assert client.calls
    assert "Return JSON only" in client.calls[0]["messages"][0]["content"]


def test_idea_comparison_and_lodging_shortlist_record_advisor_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_planning_paths(tmp_path, monkeypatch)

    comparison = TripIdeationService().compare(
        TripIdeaRequest(
            duration_days=6,
            travelers=2,
            party_type="couple",
            goals=["food", "nature"],
            avoid=["crowds"],
        )
    )
    assert comparison.advisor["kind"] == "trip_ideas"
    assert "duration" in comparison.advisor["prompt"].lower()

    intake_service = TripIntakeService()
    intake = intake_service.create(_azores_couple_intake())
    planner = TripPlannerService(intake_service)
    planner.select_option(intake.trip_id, planner.draft(intake.trip_id).recommended_option_id or "")
    lodging = LodgingShortlistService(intake_service, planner).build(intake.trip_id)

    advisor = lodging.artifacts["planning_advisor"]
    structure = lodging.artifacts["lodging_structure"]
    assert advisor["kind"] == "lodging_structure"
    assert "Current Trip Intake" in advisor["prompt"]
    assert structure["advisor_status"] in {
        "disabled",
        "skipped_no_api_key",
        "llm_success",
        "llm_failed",
    }


class _FakeAnthropicClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text=json.dumps(self.payload),
                )
            ]
        )


def _azores_couple_intake() -> TripIntake:
    return TripIntake(
        trip_id="azores-2026",
        mode=TripIntakeMode.SELECTED_DESTINATION,
        trip_name="Azores 2026",
        destination_seeds=["Azores"],
        travel_window=TravelWindow(label="late summer 2026"),
        duration_days="6 to 8 days",
        travelers=2,
        party=TripParty(
            party_type=TripPartyType.COUPLE,
            adults=2,
            children=0,
            explicit=True,
            defaulted_from_family_profile=False,
        ),
        goals=["food", "nature", "hot springs", "not overpacked"],
        avoidances=["stressful driving", "crowds"],
        freeform_notes="KenNSue trip. Prefer practical bases and great food.",
    )


def _patch_planning_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trippy.config as config

    monkeypatch.setattr(config, "INTAKES_PATH", tmp_path / "intakes")
    monkeypatch.setattr(config, "PLANS_PATH", tmp_path / "plans")
    monkeypatch.setattr(config, "SHORTLISTS_PATH", tmp_path / "shortlists")
    monkeypatch.setattr(config, "LEARNING_PATH", tmp_path / "learning")
    monkeypatch.setattr(config, "MEMORY_PATH", tmp_path / "memory.json")
    monkeypatch.setattr(config, "TRIPS_PATH", tmp_path / "trips")
    monkeypatch.setattr(config, "WORKSPACES_PATH", tmp_path / "workspaces")
    monkeypatch.setattr(config, "EXPORT_PATH", tmp_path / "export")
