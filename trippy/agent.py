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

_MODEL = "claude-sonnet-4-6"
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

    if operations_mode:
        parts.append(_OPERATIONS_MODE_PROMPT.strip())

    if active_trip_context:
        parts.append(active_trip_context)

    if orchestration_context:
        parts.append(orchestration_context)

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
                "Write a durable preference or insight to agent memory. "
                "Use this only for genuinely reusable, non-trip-specific facts."
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
    ]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


def _execute_tool(
    name: str,
    inputs: dict[str, Any],
    memory: MemoryStore,
    trip_svc: TripStateService,
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
        entry = memory.set(
            key=inputs["key"],
            value=inputs["value"],
            category=inputs["category"],
            confidence=inputs.get("confidence", 1.0),
            source="agent",
            notes=inputs.get("notes"),
        )
        return json.dumps({"ok": True, "key": entry.key, "version": entry.version})

    if name == "run_friction_audit":
        from trippy.skills.runners.friction_audit import FrictionAuditRunner

        runner = FrictionAuditRunner(memory_store=memory)
        return json.dumps(runner.run(inputs))

    return json.dumps({"error": f"Unknown tool: {name}"})


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
    ) -> None:
        self._client = anthropic_client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._memory = MemoryStore(memory_path or config.MEMORY_PATH)
        self._trip_svc = TripStateService(trips_dir=trips_dir or config.TRIPS_PATH)
        self._history: list[dict[str, Any]] = []

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
        if any(k in msg for k in ("plan trip", "plan a trip", "itinerary", "where should we go")):
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
                {"action": "get_trip", "trip_id": active_trip.trip_id, "result": active_trip.model_dump()}
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
                f"intent={intent.value}\n"
                + json.dumps(orchestration_events, indent=2, default=str)
            )

        system_prompt = _build_system_prompt(
            self._memory,
            self._trip_svc,
            operations_mode=intent == UserIntent.IN_TRIP_OPS,
            active_trip_context=active_trip_context,
            orchestration_context=orchestration_context,
        )
        tools = _skill_tools()

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
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            # Add assistant turn to history
            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn" or not tool_results:
                final_text = "\n".join(text_parts)
                return final_text

            # Add tool results and continue
            self._history.append({"role": "user", "content": tool_results})

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
