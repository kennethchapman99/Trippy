"""Trippy Hermes agent — the primary reasoning and orchestration entrypoint.

This is NOT a standalone script. It IS the agent runtime that:
1. Loads memory context (preferences, family profile) at session start
2. Accepts user queries and trip-planning requests
3. Decides which skills to invoke based on user intent
4. Uses Anthropic API with tool use for structured reasoning
5. Persists new knowledge to memory after successful workflows
6. Streams responses for real-time output

Usage:
    uv run trippy agent
    uv run python -m trippy.agent
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from trippy import config
from trippy.memory.profile_manager import ProfileManager
from trippy.memory.store import MemoryStore
from trippy.models.trip import Trip, TripStatus
from trippy.services.trip_state import TripStateService
from trippy.skills import get_all_skill_summaries

logger = logging.getLogger(__name__)
console = Console()

_MODEL = config.TRIPPY_AGENT_LLM_MODEL
_MAX_TOKENS = 4096

_OPERATIONS_MODE_PROMPT = """
## Operations Mode (During-Trip)

The user is likely in-trip and needs immediate operational help.
Prioritize practical, step-by-step guidance for:
- gate and terminal navigation
- transfer instructions (family-friendly, luggage-safe routes)
- check-in/check-out timing constraints
- today's concrete day plan and contingencies

Be concise, actionable, and risk-aware. Flag any high-friction timing or transfer issue.
"""

_PLANNING_STRATEGIST_PROMPT = """
## Planning Strategy Requirements

For trip ideas, ways to experience a destination or island, stay/split-stay structure,
activity sequencing, and next-step recommendations:
- Make an explicit strategy call. Do not merely list possibilities.
- Ground the call in loaded memory, family travel preferences, country priors, the
  trip intake, the selected plan shape, and current shortlist evidence.
- Use `run_planning_service` before making stateful planning claims. For high-level
  strategy questions, call `run_planning_service` with action `planning_advice` so
  Trippy builds the preference-rich planning prompt and records the advice context.
- Never invent source facts such as prices, availability, flight numbers, drive times,
  bed layouts, or confirmation details. Label seeded/inferred/approximate items plainly.
- When evidence is missing, state the exact source facts needed before booking.
- Preserve review-gated learning. If a lesson seems reusable, propose it through the
  reviewable learning path rather than silently changing memory or skills.
"""


class UserIntent(StrEnum):
    PLAN_TRIP = "plan_trip"
    RECONCILE_BOOKINGS = "reconcile_bookings"
    AUDIT_FRICTION = "audit_friction"
    IN_TRIP_OPS = "in_trip_ops"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def _build_system_prompt(
    memory: MemoryStore,
    trip_svc: TripStateService,
    *,
    operations_mode: bool = False,
    active_trip_context: str | None = None,
    orchestration_context: str | None = None,
    setup_context: str | None = None,
) -> str:
    parts: list[str] = []

    # Load AGENTS.md
    agents_path = Path(__file__).parent.parent / "AGENTS.md"
    if agents_path.exists():
        parts.append(agents_path.read_text(encoding="utf-8"))

    # Load SOUL.md
    soul_path = Path(__file__).parent.parent / "SOUL.md"
    if soul_path.exists():
        parts.append(soul_path.read_text(encoding="utf-8"))

    # Memory context
    mem_ctx = memory.to_context_string()
    if mem_ctx:
        parts.append(mem_ctx)

    # Active trips summary
    trip_ctx = trip_svc.summary_context()
    if trip_ctx:
        parts.append(trip_ctx)

    # Skills summary
    parts.append(get_all_skill_summaries())

    parts.append(_PLANNING_STRATEGIST_PROMPT.strip())

    if operations_mode:
        parts.append(_OPERATIONS_MODE_PROMPT.strip())

    if active_trip_context:
        parts.append(active_trip_context)

    if orchestration_context:
        parts.append(orchestration_context)

    if setup_context:
        parts.append(setup_context)

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Skill tool definitions
# ---------------------------------------------------------------------------


def _skill_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "invoke_skill",
            "description": (
                "Invoke a Trippy skill runner by name. Skills are reusable travel "
                "planning workflows. Always prefer invoking a skill over ad-hoc "
                "reasoning when a skill is available for the task."
            ),
            "input_schema": {
                "type": "object",
                "required": ["skill_name"],
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "enum": [
                            "trippy-past-trip-miner",
                            "trippy-preference-extractor",
                            "trippy-trip-sheet-creator",
                            "trippy-gmail-reconciler",
                            "trippy-flight-friction-audit",
                            "trippy-family-itinerary-builder",
                        ],
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Skill-specific inputs as defined in the skill definition",
                    },
                },
            },
        },
        {
            "name": "get_trip",
            "description": "Load the canonical state for a specific trip by ID or name.",
            "input_schema": {
                "type": "object",
                "required": ["trip_id"],
                "properties": {
                    "trip_id": {
                        "type": "string",
                        "description": "Trip ID slug (e.g. 'japan-2026')",
                    },
                },
            },
        },
        {
            "name": "list_trips",
            "description": "List all active (planned/booked) trips with summaries.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "update_memory",
            "description": (
                "Create a reviewable proposal for a durable preference or insight. "
                "Use this only for genuinely reusable, non-trip-specific facts; "
                "approval is required before memory changes."
            ),
            "input_schema": {
                "type": "object",
                "required": ["key", "value", "category"],
                "properties": {
                    "key": {"type": "string"},
                    "value": {},
                    "category": {
                        "type": "string",
                        "enum": ["preference", "profile", "skill_hint", "trip_insight"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "notes": {"type": "string"},
                },
            },
        },
        {
            "name": "run_friction_audit",
            "description": "Run a friction/risk audit on a trip and return risk flags.",
            "input_schema": {
                "type": "object",
                "required": ["trip_id"],
                "properties": {
                    "trip_id": {"type": "string"},
                    "check_preferences": {"type": "boolean", "default": True},
                },
            },
        },
        {
            "name": "run_planning_service",
            "description": (
                "Run deterministic Trippy planning services for intake creation/lookup, plan drafts, "
                "plan selection, workspace creation, maps, and exact shortlists. Use this "
                "instead of duplicating planning logic in agent reasoning."
            ),
            "input_schema": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create_intake",
                            "show_intake",
                            "draft_plan",
                            "select_plan",
                            "workspace",
                            "map",
                            "flights",
                            "lodging",
                            "select_lodging",
                            "lodging_structure",
                            "cars",
                            "select_car",
                            "activities",
                            "select_activity",
                            "schedule_activity",
                            "planning_advice",
                            "propose_learning",
                        ],
                    },
                    "trip_id": {"type": "string"},
                    "trip_name": {"type": "string"},
                    "destination": {"type": "array", "items": {"type": "string"}},
                    "travel_window": {"type": "string"},
                    "duration_days": {"type": "string"},
                    "party_type": {"type": "string"},
                    "adults": {"type": "integer"},
                    "children": {"type": "integer"},
                    "goals": {"type": "array", "items": {"type": "string"}},
                    "avoidances": {"type": "array", "items": {"type": "string"}},
                    "option_id": {"type": "string"},
                    "notes": {"type": "string"},
                    "planning_question": {
                        "type": "string",
                        "enum": [
                            "trip_ideas",
                            "trip_shape",
                            "island_experience",
                            "lodging_structure",
                            "next_steps",
                        ],
                    },
                    "day": {"type": "integer"},
                    "date": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "fixed": {"type": "boolean", "default": False},
                    "no_google": {"type": "boolean", "default": False},
                    "validate_live": {"type": "boolean", "default": False},
                    "deep_research": {"type": "boolean", "default": False},
                    "strategy": {
                        "type": "string",
                        "enum": ["single_stay", "split_stay"],
                    },
                    "night_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "region": {"type": "string"},
                                "nights": {"type": "integer"},
                                "lodging_option_id": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                    "adapter": {
                        "type": "string",
                        "enum": ["auto", "link", "playwright", "firecrawl", "openclaw"],
                        "default": "auto",
                    },
                },
            },
        },
        {
            "name": "research_lodging_web",
            "description": "Research lodging pages with Firecrawl and return normalized web evidence.",
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "research_activities_web",
            "description": "Research activity pages with Firecrawl and return normalized web evidence.",
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "enrich_flight_with_web_context",
            "description": "Enrich flight recommendations with baggage/fare/change policy context.",
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "enrich_car_rental_with_web_context",
            "description": "Enrich car rental recommendations with policy/logistics context.",
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "extract_travel_page_context",
            "description": "Extract normalized context from a single travel page URL.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {"url": {"type": "string"}, "query": {"type": "string"}},
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


def _execute_tool(
    name: str,
    inputs: dict[str, Any],
    memory: MemoryStore,
    trip_svc: TripStateService,
    learning_dir: Path | None = None,
) -> str:
    if name == "invoke_skill":
        return _run_skill(inputs.get("skill_name", ""), inputs.get("inputs", {}))

    if name == "get_trip":
        trip = trip_svc.load(inputs["trip_id"])
        if trip is None:
            return json.dumps({"error": f"Trip {inputs['trip_id']!r} not found"})
        return trip.model_dump_json(indent=2)

    if name == "list_trips":
        trips = trip_svc.find_active()
        return json.dumps({"trips": [t.summary() for t in trips]})

    if name == "update_memory":
        from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType

        key = str(inputs["key"])
        existing = memory.get(key)
        proposals = LearningEventStore(learning_dir, memory_path=memory.path).add_proposals(
            [
                LearningProposal(
                    proposal_type=ProposalType.MEMORY,
                    summary=f"Review agent-proposed memory update: {key}",
                    before=existing.model_dump(mode="json") if existing else None,
                    after={
                        "key": key,
                        "value": inputs["value"],
                        "category": inputs["category"],
                        "confidence": inputs.get("confidence", 1.0),
                        "source": "agent",
                        "notes": inputs.get("notes"),
                    },
                )
            ]
        )
        return json.dumps(
            {
                "ok": True,
                "review_required": True,
                "proposal_id": proposals[0].id,
                "key": key,
            }
        )

    if name == "run_friction_audit":
        from trippy.skills.runners.friction_audit import FrictionAuditRunner

        runner = FrictionAuditRunner(memory_store=memory)
        return json.dumps(runner.run(inputs))

    if name == "run_planning_service":
        return _run_planning_service(inputs)
    if name in {
        "research_lodging_web",
        "research_activities_web",
        "enrich_flight_with_web_context",
        "enrich_car_rental_with_web_context",
        "extract_travel_page_context",
    }:
        return _run_web_intelligence_tool(name, inputs)

    return json.dumps({"error": f"Unknown tool: {name}"})


def _run_web_intelligence_tool(name: str, inputs: dict[str, Any]) -> str:
    from trippy.services.web_intelligence import TravelWebIntelligenceService

    service = TravelWebIntelligenceService()
    query = str(inputs.get("query") or "")
    if name == "research_lodging_web":
        return json.dumps(
            [row.model_dump(mode="json") for row in service.research_lodging_web(query)]
        )
    if name == "research_activities_web":
        return json.dumps(
            [row.model_dump(mode="json") for row in service.research_activities_web(query)]
        )
    if name == "enrich_flight_with_web_context":
        return service.enrich_flight_with_web_context(query).model_dump_json()
    if name == "enrich_car_rental_with_web_context":
        return json.dumps(
            [
                row.model_dump(mode="json")
                for row in service.enrich_car_rental_with_web_context(query)
            ]
        )
    return service.extract_travel_page_context(
        str(inputs.get("url") or ""),
        query=query,
    ).model_dump_json()


def _run_planning_service(inputs: dict[str, Any]) -> str:
    action = str(inputs["action"])
    trip_id = str(inputs.get("trip_id") or "")
    option_id = str(inputs.get("option_id") or "")
    validate_live = bool(inputs.get("validate_live", False))
    deep_research = bool(inputs.get("deep_research", False))
    adapter = str(inputs.get("adapter") or "auto")
    try:
        if action == "planning_advice":
            from trippy.models.planning_advice import PlanningAdviceKind
            from trippy.models.shortlists import ShortlistCategory
            from trippy.services.planning_advisor import PlanningAdvisorService
            from trippy.services.shortlist_store import ShortlistStore
            from trippy.services.trip_intake import TripIntakeService
            from trippy.services.trip_planner import TripPlannerService

            question = str(inputs.get("planning_question") or "next_steps")
            kind = PlanningAdviceKind(question)
            intake = TripIntakeService().load(trip_id) if trip_id else None
            draft = TripPlannerService().load_draft(trip_id) if trip_id else None
            if kind == PlanningAdviceKind.LODGING_STRUCTURE and intake is not None and draft:
                option = draft.get_option()
                lodging_state = ShortlistStore().load(trip_id, ShortlistCategory.LODGING)
                if option is not None:
                    return (
                        PlanningAdvisorService()
                        .advise_lodging_structure(intake, option, lodging_state)
                        .model_dump_json(indent=2)
                    )
            if (
                kind
                in {
                    PlanningAdviceKind.TRIP_SHAPE,
                    PlanningAdviceKind.ISLAND_EXPERIENCE,
                }
                and intake is not None
                and draft is not None
            ):
                advisor = PlanningAdvisorService()
                if kind == PlanningAdviceKind.ISLAND_EXPERIENCE:
                    return advisor.advise_island_experience(intake, draft).model_dump_json(indent=2)
                return advisor.advise_trip_shape(intake, draft).model_dump_json(indent=2)
            shortlists = ShortlistStore().load_all(trip_id) if trip_id else []
            return (
                PlanningAdvisorService()
                .advise_next_steps(
                    intake,
                    draft,
                    shortlists,
                    user_question=str(inputs.get("notes") or ""),
                )
                .model_dump_json(indent=2)
            )
        if action == "create_intake":
            from trippy.models.trip_planning import (
                TravelWindow,
                TripIntake,
                TripIntakeMode,
                TripParty,
                TripPartyType,
            )
            from trippy.services.trip_intake import TripIntakeService

            trip_name = str(inputs.get("trip_name") or trip_id or "New Trip")
            adults = int(inputs.get("adults") or 2)
            children = int(inputs.get("children") or 3)
            party_type = str(inputs.get("party_type") or "whole_family")
            intake = TripIntake(
                trip_id=trip_id,
                mode=TripIntakeMode.SELECTED_DESTINATION,
                trip_name=trip_name,
                destination_seeds=_as_string_list(inputs.get("destination")),
                travel_window=TravelWindow(label=str(inputs.get("travel_window") or "") or None),
                duration_days=inputs.get("duration_days"),
                travelers=adults + children,
                party=TripParty(
                    party_type=TripPartyType(
                        party_type.strip().lower().replace("-", "_").replace(" ", "_")
                    ),
                    adults=adults,
                    children=children,
                    explicit=True,
                    defaulted_from_family_profile=False,
                ),
                goals=_as_string_list(inputs.get("goals")),
                avoidances=_as_string_list(inputs.get("avoidances")),
            )
            return (
                TripIntakeService()
                .create(intake, overwrite=bool(trip_id))
                .model_dump_json(indent=2)
            )
        if not trip_id:
            return json.dumps({"error": "trip_id is required", "action": action})
        if action == "show_intake":
            from trippy.services.trip_intake import TripIntakeService

            return TripIntakeService().require(trip_id).model_dump_json(indent=2)
        if action == "draft_plan":
            from trippy.services.trip_planner import TripPlannerService

            return TripPlannerService().draft(trip_id).model_dump_json(indent=2)
        if action == "select_plan":
            from trippy.services.trip_planner import TripPlannerService

            if not option_id:
                return json.dumps({"error": "option_id is required for select_plan"})
            return TripPlannerService().select_option(trip_id, option_id).model_dump_json(indent=2)
        if action == "workspace":
            from trippy.services.trip_workspace import TripWorkspaceService

            state = TripWorkspaceService().prepare(
                trip_id,
                option_id=option_id or None,
                create_google_sheet=not bool(inputs.get("no_google", False)),
                validate_live=validate_live,
            )
            return state.model_dump_json(indent=2)
        if action == "map":
            from trippy import config
            from trippy.services.trip_map_builder import TripMapBuilder

            return (
                TripMapBuilder()
                .write_artifacts(
                    trip_id,
                    config.EXPORT_PATH / "maps",
                )
                .model_dump_json(indent=2)
            )
        if action == "flights":
            from trippy.services.flight_shortlist import FlightShortlistService

            return (
                FlightShortlistService()
                .build(
                    trip_id,
                    validate_live=validate_live,
                    deep_research=deep_research,
                    adapter_mode=adapter,
                )
                .model_dump_json(indent=2)
            )
        if action == "lodging":
            from trippy.services.lodging_shortlist import LodgingShortlistService

            return (
                LodgingShortlistService()
                .build(
                    trip_id,
                    validate_live=validate_live,
                    deep_research=deep_research,
                    adapter_mode=adapter,
                )
                .model_dump_json(indent=2)
            )
        if action == "select_lodging":
            from trippy.services.lodging_shortlist import LodgingShortlistService

            if not option_id:
                return json.dumps({"error": "option_id is required for select_lodging"})
            return (
                LodgingShortlistService()
                .select_lodging(trip_id, option_id)
                .model_dump_json(indent=2)
            )
        if action == "lodging_structure":
            from trippy.services.lodging_shortlist import LodgingShortlistService

            return (
                LodgingShortlistService()
                .update_stay_structure(
                    trip_id,
                    strategy=str(inputs.get("strategy") or "split_stay"),
                    night_plan=list(inputs.get("night_plan") or []),
                    notes=str(inputs.get("notes") or ""),
                )
                .model_dump_json(indent=2)
            )
        if action == "cars":
            from trippy.services.car_shortlist import CarShortlistService

            return (
                CarShortlistService()
                .build(
                    trip_id,
                    validate_live=validate_live,
                    deep_research=deep_research,
                    adapter_mode=adapter,
                )
                .model_dump_json(indent=2)
            )
        if action == "select_car":
            from trippy.services.car_shortlist import CarShortlistService

            option_id = str(inputs.get("option_id") or "")
            if not option_id:
                return json.dumps({"error": "option_id is required for select_car"})
            return CarShortlistService().select_car(trip_id, option_id).model_dump_json(indent=2)
        if action == "activities":
            from trippy.services.activity_shortlist import ActivityShortlistService

            return (
                ActivityShortlistService()
                .build(
                    trip_id,
                    validate_live=validate_live,
                    deep_research=deep_research,
                    adapter_mode=adapter,
                )
                .model_dump_json(indent=2)
            )
        if action == "select_activity":
            from trippy.services.activity_shortlist import ActivityShortlistService

            option_id = str(inputs.get("option_id") or "")
            if not option_id:
                return json.dumps({"error": "option_id is required for select_activity"})
            return (
                ActivityShortlistService()
                .select_activity(trip_id, option_id)
                .model_dump_json(indent=2)
            )
        if action == "schedule_activity":
            from trippy.services.activity_shortlist import ActivityShortlistService

            option_id = str(inputs.get("option_id") or "")
            if not option_id:
                return json.dumps({"error": "option_id is required for schedule_activity"})
            return (
                ActivityShortlistService()
                .schedule_activity(
                    trip_id,
                    option_id,
                    day=_optional_positive_int(inputs.get("day")),
                    date_value=str(inputs.get("date") or ""),
                    start_time=str(inputs.get("start_time") or ""),
                    end_time=str(inputs.get("end_time") or ""),
                    fixed=bool(inputs.get("fixed", False)),
                    notes=str(inputs.get("notes") or ""),
                )
                .model_dump_json(indent=2)
            )
        if action == "propose_learning":
            from trippy.services.planning_learning import PlanningLearningService

            proposals = PlanningLearningService().propose_for_trip(trip_id)
            return json.dumps({"proposal_ids": [proposal.id for proposal in proposals]})
        return json.dumps({"error": f"Unknown planning action: {action}"})
    except Exception as exc:
        logger.exception("Planning service action failed")
        return json.dumps({"error": str(exc), "action": action, "trip_id": trip_id})


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _run_skill(skill_name: str, inputs: dict[str, Any]) -> str:
    runners: dict[str, Any] = {}

    if skill_name == "trippy-past-trip-miner":
        from trippy.skills.runners.past_trip_miner import PastTripMinerRunner

        runners["runner"] = PastTripMinerRunner()
    elif skill_name == "trippy-preference-extractor":
        from trippy.skills.runners.preference_extractor import PreferenceExtractorRunner

        runners["runner"] = PreferenceExtractorRunner()
    elif skill_name == "trippy-trip-sheet-creator":
        from trippy.skills.runners.trip_sheet_creator import TripSheetCreatorRunner

        runners["runner"] = TripSheetCreatorRunner()
    elif skill_name == "trippy-gmail-reconciler":
        from trippy.skills.runners.gmail_reconciler import GmailReconcilerRunner

        runners["runner"] = GmailReconcilerRunner()
    elif skill_name == "trippy-flight-friction-audit":
        from trippy.skills.runners.friction_audit import FrictionAuditRunner

        runners["runner"] = FrictionAuditRunner()
    elif skill_name == "trippy-family-itinerary-builder":
        from trippy.skills.runners.itinerary_builder import ItineraryBuilderRunner

        runners["runner"] = ItineraryBuilderRunner()
    else:
        return json.dumps({"error": f"Unknown skill: {skill_name}"})

    try:
        result = runners["runner"].run(inputs)
        return json.dumps(result)
    except Exception as exc:
        logger.exception("Skill %s failed", skill_name)
        return json.dumps({"error": str(exc), "skill": skill_name})


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


class TrIppyAgent:
    """Interactive Hermes-native Trippy agent."""

    def __init__(
        self,
        anthropic_client: anthropic.Anthropic | None = None,
        memory_path: Path | None = None,
        trips_dir: Path | None = None,
        learning_dir: Path | None = None,
    ) -> None:
        self._client = anthropic_client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._memory = MemoryStore(memory_path or config.MEMORY_PATH)
        self._trip_svc = TripStateService(trips_dir=trips_dir or config.TRIPS_PATH)
        self._learning_dir = learning_dir or (
            memory_path.parent / "learning" if memory_path is not None else config.LEARNING_PATH
        )
        self._history: list[dict[str, Any]] = []
        self._last_workflow_id: str | None = None

    def _classify_intent(self, user_message: str) -> UserIntent:
        msg = user_message.lower()
        if any(k in msg for k in ("reconcile", "gmail", "booking email", "confirmation email")):
            return UserIntent.RECONCILE_BOOKINGS
        if any(k in msg for k in ("audit", "friction", "risk", "tight layover")):
            return UserIntent.AUDIT_FRICTION
        if any(
            k in msg
            for k in (
                "gate",
                "terminal",
                "transfer",
                "check in",
                "check-in",
                "today plan",
                "today's plan",
                "on the way",
                "we landed",
                "we are at",
            )
        ):
            return UserIntent.IN_TRIP_OPS
        if any(
            k in msg
            for k in (
                "plan trip",
                "plan a trip",
                "itinerary",
                "where should we go",
                "shortlist",
                "flight options",
                "lodging options",
                "car rental",
                "activities",
                "workspace",
                "trip map",
            )
        ):
            return UserIntent.PLAN_TRIP
        return UserIntent.GENERAL

    def _extract_explicit_trip(self, user_message: str) -> Trip | None:
        msg = user_message.lower()
        for trip in self._trip_svc.load_all():
            if trip.trip_id.lower() in msg or trip.name.lower() in msg:
                return trip
        return None

    def _nearest_upcoming_booked_trip(self) -> Trip | None:
        today = date.today()
        booked = [t for t in self._trip_svc.find_by_status(TripStatus.BOOKED) if t.start_date]
        upcoming = [t for t in booked if t.start_date and t.start_date >= today]
        if not upcoming:
            return None
        return sorted(upcoming, key=lambda t: t.start_date or datetime.max.date())[0]

    def _select_active_trip(self, user_message: str) -> tuple[Trip | None, str]:
        explicit = self._extract_explicit_trip(user_message)
        if explicit:
            return explicit, "explicit"

        upcoming = self._nearest_upcoming_booked_trip()
        if upcoming:
            return upcoming, "nearest_upcoming_booked"

        return None, "none"

    def _refresh_sheet_sync(self, trip: Trip) -> dict[str, Any]:
        if not trip.sync.google_sheet_id:
            return {"ok": False, "reason": "no_google_sheet_id"}
        try:
            from trippy.services.sheet_sync import SheetSyncService

            SheetSyncService().push_trip_to_sheet(trip, trip.sync.google_sheet_id)
            return {"ok": True, "sheet_id": trip.sync.google_sheet_id}
        except Exception as exc:
            logger.exception("Sheet sync refresh failed for trip %s", trip.trip_id)
            return {"ok": False, "error": str(exc)}

    def _setup_context(self) -> str | None:
        from trippy.services.setup import CheckStatus, SetupDoctor

        report = SetupDoctor(project_root=Path.cwd()).run(create_paths=False)
        blockers = [
            check
            for check in report.checks
            if check.status == CheckStatus.FAIL
            and check.name
            in {"anthropic_key", "google_credentials", "google_token", "google_scopes"}
        ]
        if not blockers:
            return None
        lines = [
            "## Setup Blockers",
            "Explain these blockers before attempting live Google workflows:",
        ]
        lines.extend(f"- {check.summary}" for check in blockers)
        if report.next_actions:
            lines.append("Next actions:")
            lines.extend(f"- {action}" for action in report.next_actions)
        return "\n".join(lines)

    def _record_agent_workflow(
        self,
        *,
        intent: UserIntent,
        active_trip: Trip | None,
        events: list[dict[str, Any]],
    ) -> None:
        if not events:
            self._last_workflow_id = None
            return

        from trippy.services.learning import LearningEventStore, WorkflowOutcome, WorkflowStatus

        skill_name = None
        for event in events:
            if event.get("skill_name"):
                skill_name = str(event["skill_name"])
                break

        outcome = WorkflowOutcome(
            workflow_name=f"agent:{intent.value}",
            skill_name=skill_name,
            trip_id=active_trip.trip_id if active_trip else None,
            status=WorkflowStatus.SUCCESS,
            summary=f"Agent handled {intent.value} with {len(events)} tool/orchestration event(s)",
            metrics={"events": len(events)},
            artifacts={"events": events},
            evidence_refs=[f"agent-intent:{intent.value}"],
        )
        LearningEventStore(self._learning_dir).record_workflow(outcome)
        self._last_workflow_id = outcome.id

    def chat(self, user_message: str) -> str:
        """Process a single user message and return the agent's response."""
        intent = self._classify_intent(user_message)
        trip_scoped_intents = {
            UserIntent.RECONCILE_BOOKINGS,
            UserIntent.AUDIT_FRICTION,
            UserIntent.IN_TRIP_OPS,
        }

        active_trip = None
        trip_selection_reason = "not_required"
        if intent in trip_scoped_intents:
            active_trip, trip_selection_reason = self._select_active_trip(user_message)
            if active_trip is None:
                return (
                    "I need the trip first. Which trip should I use? "
                    "Please share the trip name or trip ID."
                )

        orchestration_events: list[dict[str, Any]] = []
        if intent == UserIntent.RECONCILE_BOOKINGS:
            assert active_trip is not None
            orchestration_events.append(
                {
                    "action": "invoke_skill",
                    "skill_name": "trippy-gmail-reconciler",
                    "result": json.loads(
                        _run_skill("trippy-gmail-reconciler", {"trip_id": active_trip.trip_id})
                    ),
                }
            )
        elif intent == UserIntent.IN_TRIP_OPS and active_trip is not None:
            orchestration_events.append(
                {
                    "action": "get_trip",
                    "trip_id": active_trip.trip_id,
                    "result": active_trip.model_dump(),
                }
            )
            orchestration_events.append(
                {
                    "action": "run_friction_audit",
                    "trip_id": active_trip.trip_id,
                    "result": json.loads(
                        _execute_tool(
                            "run_friction_audit",
                            {"trip_id": active_trip.trip_id, "check_preferences": True},
                            self._memory,
                            self._trip_svc,
                            self._learning_dir,
                        )
                    ),
                }
            )
            orchestration_events.append(
                {
                    "action": "sheet_sync_refresh",
                    "trip_id": active_trip.trip_id,
                    "result": self._refresh_sheet_sync(active_trip),
                }
            )

        self._history.append({"role": "user", "content": user_message})

        active_trip_context = None
        if active_trip is not None:
            active_trip_context = (
                "## Active Trip Selection\n"
                f"Selected trip: {active_trip.trip_id} ({active_trip.name})\n"
                f"Selection policy result: {trip_selection_reason}"
            )
        orchestration_context = None
        if orchestration_events:
            orchestration_context = (
                "## Deterministic Orchestration\n"
                f"intent={intent.value}\n" + json.dumps(orchestration_events, indent=2, default=str)
            )
        setup_context = self._setup_context()

        system_prompt = _build_system_prompt(
            self._memory,
            self._trip_svc,
            operations_mode=intent == UserIntent.IN_TRIP_OPS,
            active_trip_context=active_trip_context,
            orchestration_context=orchestration_context,
            setup_context=setup_context,
        )
        tools = _skill_tools()
        workflow_events = list(orchestration_events)

        # Agentic loop — keep running until no more tool calls
        for _ in range(10):
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                tools=tools,  # type: ignore[arg-type]
                messages=self._history,  # type: ignore[arg-type]
            )

            # Collect text and tool uses
            text_parts: list[str] = []
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    result = _execute_tool(
                        block.name,
                        dict(block.input),
                        self._memory,
                        self._trip_svc,
                        self._learning_dir,
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
                    workflow_events.append(
                        {
                            "action": "tool_use",
                            "tool_name": block.name,
                            "input": dict(block.input),
                            "result": result,
                        }
                    )

            # Add assistant turn to history
            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn" or not tool_results:
                final_text = "\n".join(text_parts)
                self._record_agent_workflow(
                    intent=intent,
                    active_trip=active_trip,
                    events=workflow_events,
                )
                return final_text

            # Add tool results and continue
            self._history.append({"role": "user", "content": tool_results})

        self._record_agent_workflow(intent=intent, active_trip=active_trip, events=workflow_events)
        return "Agent loop limit reached."

    def run_interactive(self) -> None:
        """Start an interactive REPL session."""
        console.print(
            Panel.fit(
                "[bold cyan]Trippy[/bold cyan] — Chapman Family Travel Concierge\n"
                "[dim]Type your request. Ctrl+C or 'quit' to exit.[/dim]",
                border_style="cyan",
            )
        )

        # Load and display context summary
        profile_mgr = ProfileManager(memory=self._memory)
        profile = profile_mgr.load()
        if profile.travelers:
            console.print(f"[dim]Family: {profile.to_context_string()}[/dim]\n")

        mem_prefs = self._memory.to_context_string("preference")
        if mem_prefs:
            console.print("[dim]Preferences loaded from memory[/dim]\n")

        active_trips = self._trip_svc.find_active()
        if active_trips:
            console.print(f"[dim]Active trips: {', '.join(t.name for t in active_trips)}[/dim]\n")

        setup_context = self._setup_context()
        if setup_context:
            console.print("[yellow]Setup has blockers. Run `trippy doctor` for details.[/yellow]\n")

        while True:
            try:
                user_input = console.input("[bold green]You:[/bold green] ").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input or user_input.lower() in ("quit", "exit", "bye"):
                console.print("[dim]Goodbye.[/dim]")
                break

            console.print()
            try:
                with console.status("[cyan]Thinking...[/cyan]"):
                    response = self.chat(user_input)
                console.print("[bold cyan]Trippy:[/bold cyan]")
                console.print(Markdown(response))
                if self._last_workflow_id:
                    console.print(
                        f"\n[dim]Workflow ID: {self._last_workflow_id}[/dim]\n"
                        "[dim]Share feedback with:[/dim] "
                        f'trippy feedback {self._last_workflow_id} --rating helpful --notes "..." '
                        "--future-learning"
                    )
                console.print()
            except KeyboardInterrupt:
                console.print("\n[dim](interrupted)[/dim]\n")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]\n")
                logger.exception("Agent error")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    agent = TrIppyAgent()
    agent.run_interactive()


if __name__ == "__main__":
    main()
