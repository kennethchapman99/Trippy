"""Hermes-compatible orchestration boundary for Trippy.

This module is intentionally small. It does not pretend to be the full Hermes
runtime; it gives Trippy a clean profile/skill/tool/memory boundary that can be
replaced by a real Hermes runtime later without changing external tool calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trippy import config
from trippy.hermes.tool_client import HermesToolClient
from trippy.memory.store import MemoryStore
from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType
from trippy.services.trip_state import TripStateService
from trippy.skills import get_all_skill_summaries


class HermesCompatibilityOrchestrator:
    """Profile/skill/memory orchestration shim for Trippy.

    Ownership boundaries:
    - Planning/orchestration/memory/learning proposal flow lives here.
    - External travel data access is delegated to `HermesToolClient` only.
    - Canonical trip state and ranking remain in Trippy services.
    """

    def __init__(
        self,
        *,
        tool_client: HermesToolClient | None = None,
        memory_path: Path | None = None,
        trips_dir: Path | None = None,
        learning_dir: Path | None = None,
    ) -> None:
        self.tool_client = tool_client or HermesToolClient()
        self.memory = MemoryStore(memory_path or config.MEMORY_PATH)
        self.trip_state = TripStateService(trips_dir=trips_dir or config.TRIPS_PATH)
        self.learning = LearningEventStore(
            learning_dir or config.LEARNING_PATH,
            memory_path=memory_path or config.MEMORY_PATH,
        )

    def profile_context(self) -> dict[str, Any]:
        return {
            "memory": self.memory.to_context_string(),
            "trips": self.trip_state.summary_context(),
            "skills": get_all_skill_summaries(),
            "tool_registry": self.tool_client.describe(),
        }

    def system_context(self) -> str:
        """Return compact JSON for LLM/Hermes prompt construction."""

        return json.dumps(
            {
                "runtime": "trippy-hermes-compatibility-layer",
                "warning": "This is not a full Hermes runtime; it preserves the intended boundaries.",
                "ownership": {
                    "hermes": ["planning", "orchestration", "skills", "memory", "review_gated_learning"],
                    "tool_gateway": ["external_world_tools", "schemas", "healthchecks", "dry_run"],
                    "trippy": ["canonical_trip_state", "ranking", "UX", "saved_trips", "review_gates"],
                },
                "context": self.profile_context(),
            },
            sort_keys=True,
        )

    def call_external_tool(
        self,
        tool_id: str,
        input_data: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Only approved path for Hermes to call external travel data tools."""

        return self.tool_client.call_tool(tool_id, input_data or {}, dry_run=dry_run)

    def propose_learning(
        self,
        *,
        source_trip_id: str | None,
        observation: str,
        proposed_rule: str,
        scope: str = "user_preference",
        confidence: float = 0.7,
    ) -> LearningProposal:
        """Create a pending, review-gated learning proposal.

        This does not mutate memory or tool mechanics. Approval still happens via
        existing `trippy learn approve` flow.
        """

        after = {
            "source_trip_id": source_trip_id,
            "observation": observation,
            "proposed_rule": proposed_rule,
            "scope": scope,
            "confidence": confidence,
            "status": "pending_review",
        }
        proposal = LearningProposal(
            proposal_type=ProposalType.MEMORY,
            summary=f"Review travel preference learning: {observation[:120]}",
            after={
                "key": f"preference:proposal:{scope}:{abs(hash(observation))}",
                "value": after,
                "category": "preference",
                "confidence": confidence,
                "source": "hermes-orchestrator",
                "notes": proposed_rule,
            },
        )
        return self.learning.add_proposals([proposal])[0]
