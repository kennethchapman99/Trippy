from __future__ import annotations

import json
from typing import Any

from trippy.agent_shim import TrippyHermesAgent, hermes_tool_definitions


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], bool]] = []
        self.tool_client = self

    def system_context(self) -> str:
        return "{}"

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"id": "flight_search"}]

    def call_external_tool(
        self,
        tool_id: str,
        input_data: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = input_data or {}
        self.calls.append((tool_id, payload, dry_run))
        return {"tool_id": tool_id, "via_gateway": True, "input": payload, "dry_run": dry_run}


def test_agent_tool_surface_only_exposes_gateway_not_direct_web_tools() -> None:
    tools = hermes_tool_definitions()
    names = {tool["name"] for tool in tools}

    assert "call_trippy_tool" in names
    assert "list_trippy_tools" in names
    assert "research_lodging_web" not in names
    assert "research_activities_web" not in names
    assert "enrich_flight_with_web_context" not in names
    assert "enrich_car_rental_with_web_context" not in names
    assert "extract_travel_page_context" not in names


def test_agent_external_tool_execution_routes_to_orchestrator_gateway() -> None:
    orchestrator: Any = RecordingOrchestrator()
    agent = TrippyHermesAgent(anthropic_client=None, orchestrator=orchestrator)

    raw = agent.execute_tool(
        "call_trippy_tool",
        {
            "tool_id": "flight_search",
            "input": {"origin": "YYZ", "destination": "SCL"},
            "dry_run": True,
        },
    )

    result = json.loads(raw)
    assert result["via_gateway"] is True
    assert orchestrator.calls == [("flight_search", {"origin": "YYZ", "destination": "SCL"}, True)]
