from __future__ import annotations

from pathlib import Path
from typing import Any

from trippy.hermes.orchestrator import HermesCompatibilityOrchestrator
from trippy.services.learning import LearningEventStore, ProposalStatus


class RecordingToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def describe(self, tool_id: str | None = None) -> dict[str, Any]:
        return {"registry_path": "test-registry.json", "tools": [], "tool_id": tool_id}

    def call_tool(
        self,
        tool_id: str,
        input_data: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = input_data or {}
        self.calls.append((tool_id, payload, dry_run))
        return {"tool_id": tool_id, "passed_gateway": True, "input": payload}


def test_orchestrator_calls_tool_gateway_for_external_tools(tmp_path: Path) -> None:
    client: Any = RecordingToolClient()
    orchestrator = HermesCompatibilityOrchestrator(
        tool_client=client,
        memory_path=tmp_path / "memory.json",
        trips_dir=tmp_path / "trips",
        learning_dir=tmp_path / "learning",
    )

    result = orchestrator.call_external_tool(
        "flight_search",
        {"origin": "YYZ", "destination": "SCL"},
        dry_run=True,
    )

    assert result["passed_gateway"] is True
    assert client.calls == [("flight_search", {"origin": "YYZ", "destination": "SCL"}, True)]


def test_learning_proposals_are_created_pending_review(tmp_path: Path) -> None:
    orchestrator = HermesCompatibilityOrchestrator(
        memory_path=tmp_path / "memory.json",
        trips_dir=tmp_path / "trips",
        learning_dir=tmp_path / "learning",
    )

    proposal = orchestrator.propose_learning(
        source_trip_id="trip_test",
        observation="Ken rejected hotels more than 25 minutes from the main experience zone.",
        proposed_rule="Downrank lodging more than 25 minutes away unless the property is exceptional.",
        scope="user_preference",
        confidence=0.74,
    )

    assert proposal.status == ProposalStatus.PENDING
    assert proposal.after["value"]["status"] == "pending_review"
    assert proposal.after["value"]["scope"] == "user_preference"

    store = LearningEventStore(tmp_path / "learning", memory_path=tmp_path / "memory.json")
    proposals = store.list_proposals(status=ProposalStatus.PENDING)
    assert [item.id for item in proposals] == [proposal.id]
