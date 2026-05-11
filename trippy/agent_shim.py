"""Thin Hermes-compatible Trippy agent shim.

This module is the intended replacement for the legacy ad hoc/custom agent loop in
`trippy.agent`. It exposes only Hermes-style orchestration tools and the stable
Printing Press-style Trippy tool gateway.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
from rich.console import Console
from rich.markdown import Markdown

from trippy import config
from trippy.hermes.orchestrator import HermesCompatibilityOrchestrator
from trippy.services.learning import LearningProposal
from trippy.services.trip_state import TripStateService

console = Console()
_MODEL = config.TRIPPY_AGENT_LLM_MODEL
_MAX_TOKENS = 4096


def hermes_tool_definitions() -> list[dict[str, Any]]:
    """Return the only tools exposed to the LLM agent loop.

    External-world travel data is available exclusively through `call_trippy_tool`,
    which routes to `TrippyToolGateway` and registered Printing Press-style tools.
    """

    return [
        {
            "name": "list_trippy_tools",
            "description": "List registered Printing Press-style Trippy external travel tools.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "call_trippy_tool",
            "description": (
                "Call a registered external travel data tool through the Trippy tool gateway. "
                "Use dry_run=true unless the user explicitly needs fixture/live tool output."
            ),
            "input_schema": {
                "type": "object",
                "required": ["tool_id"],
                "properties": {
                    "tool_id": {"type": "string"},
                    "input": {"type": "object"},
                    "dry_run": {"type": "boolean", "default": True},
                },
            },
        },
        {
            "name": "get_trip_state",
            "description": "Load canonical Trippy trip state by trip_id. Does not call external providers.",
            "input_schema": {
                "type": "object",
                "required": ["trip_id"],
                "properties": {"trip_id": {"type": "string"}},
            },
        },
        {
            "name": "list_trips",
            "description": "List active canonical trips. Does not call external providers.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "propose_learning",
            "description": "Create a review-gated learning proposal. Never mutates memory directly.",
            "input_schema": {
                "type": "object",
                "required": ["observation", "proposed_rule"],
                "properties": {
                    "source_trip_id": {"type": "string"},
                    "observation": {"type": "string"},
                    "proposed_rule": {"type": "string"},
                    "scope": {"type": "string", "default": "user_preference"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    ]


class TrippyHermesAgent:
    """Small LLM loop backed by HermesCompatibilityOrchestrator.

    This class intentionally contains no provider-specific API/scraper calls.
    """

    def __init__(
        self,
        *,
        anthropic_client: Any | None = None,
        orchestrator: HermesCompatibilityOrchestrator | None = None,
        trips_dir: Path | None = None,
    ) -> None:
        self._client: Any = anthropic_client or anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY
        )
        self._orchestrator = orchestrator or HermesCompatibilityOrchestrator()
        self._trip_state = TripStateService(trips_dir=trips_dir or config.TRIPS_PATH)
        self._history: list[dict[str, Any]] = []

    def system_prompt(self) -> str:
        return "\n\n".join(
            [
                "You are Trippy, a Hermes-compatible travel planning orchestrator.",
                "Do not call external travel APIs, scrapers, browser tools, or provider helpers directly.",
                "Use call_trippy_tool for all external-world travel data access.",
                "Use canonical Trippy state for trip facts and review-gated learning for durable preferences.",
                self._orchestrator.system_context(),
            ]
        )

    def execute_tool(self, name: str, inputs: dict[str, Any]) -> str:
        if name == "list_trippy_tools":
            return json.dumps(self._orchestrator.tool_client.list_tools())
        if name == "call_trippy_tool":
            return json.dumps(
                self._orchestrator.call_external_tool(
                    str(inputs["tool_id"]),
                    inputs.get("input") if isinstance(inputs.get("input"), dict) else {},
                    dry_run=bool(inputs.get("dry_run", True)),
                )
            )
        if name == "get_trip_state":
            trip = self._trip_state.load(str(inputs["trip_id"]))
            return trip.model_dump_json(indent=2) if trip else json.dumps({"error": "trip_not_found"})
        if name == "list_trips":
            return json.dumps({"trips": [trip.summary() for trip in self._trip_state.find_active()]})
        if name == "propose_learning":
            proposal: LearningProposal = self._orchestrator.propose_learning(
                source_trip_id=str(inputs.get("source_trip_id") or "") or None,
                observation=str(inputs["observation"]),
                proposed_rule=str(inputs["proposed_rule"]),
                scope=str(inputs.get("scope") or "user_preference"),
                confidence=float(inputs.get("confidence", 0.7)),
            )
            return proposal.model_dump_json(indent=2)
        return json.dumps({"error": f"unknown_tool:{name}"})

    def ask(self, user_message: str) -> str:
        self._history.append({"role": "user", "content": user_message})
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=self.system_prompt(),
            messages=self._history,
            tools=hermes_tool_definitions(),
        )

        while response.stop_reason == "tool_use":
            assistant_content = response.content
            self._history.append({"role": "assistant", "content": assistant_content})
            tool_results: list[dict[str, Any]] = []
            for block in assistant_content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                result = self.execute_tool(block.name, dict(block.input or {}))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )
            self._history.append({"role": "user", "content": tool_results})
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=self.system_prompt(),
                messages=self._history,
                tools=hermes_tool_definitions(),
            )

        text_parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        answer = "\n".join(text_parts).strip()
        self._history.append({"role": "assistant", "content": answer})
        return answer


def main() -> None:
    agent = TrippyHermesAgent()
    console.print("[bold green]Trippy Hermes-compatible agent[/bold green]")
    console.print("Type 'exit' or Ctrl-C to quit.")
    while True:
        try:
            user_message = console.input("\n[bold cyan]you>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nbye")
            return
        if user_message.lower() in {"exit", "quit"}:
            return
        if not user_message:
            continue
        answer = agent.ask(user_message)
        console.print(Markdown(answer or "No response."))


if __name__ == "__main__":
    main()
