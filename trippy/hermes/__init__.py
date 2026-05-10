"""Hermes-compatible orchestration boundary for Trippy.

This package is a compatibility layer, not a full Hermes runtime. It makes the
ownership boundaries explicit:
- Hermes: planning/orchestration/skills/memory/learning proposals
- Tool gateway: Printing Press-style external-world calls
- Trippy services: canonical state, ranking, UX, saved trips, review gates
"""

from trippy.hermes.orchestrator import HermesCompatibilityOrchestrator
from trippy.hermes.tool_client import HermesToolClient

__all__ = ["HermesCompatibilityOrchestrator", "HermesToolClient"]
