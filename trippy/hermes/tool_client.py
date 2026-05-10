"""Hermes-facing tool client for Trippy's external-world gateway."""

from __future__ import annotations

import json
from typing import Any

from trippy.tool_registry.gateway import TrippyToolGateway


class HermesToolClient:
    """Thin client Hermes uses to discover and call external travel tools.

    The client deliberately delegates all executable external-world access to
    `TrippyToolGateway`. It contains no provider-specific logic.
    """

    def __init__(self, gateway: TrippyToolGateway | None = None) -> None:
        self.gateway = gateway or TrippyToolGateway()

    def list_tools(self) -> list[dict[str, Any]]:
        return self.gateway.list_tools()

    def describe(self, tool_id: str | None = None) -> dict[str, Any]:
        return self.gateway.describe(tool_id)

    def healthcheck(self, tool_id: str | None = None) -> dict[str, Any]:
        return self.gateway.healthcheck(tool_id)

    def call_tool(
        self,
        tool_id: str,
        input_data: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.gateway.call(tool_id, input_data or {}, dry_run=dry_run)

    def tool_context(self) -> str:
        """Compact JSON context suitable for an LLM/Hermes system prompt."""

        payload = {
            "tool_boundary": "External-world travel data must be accessed through this registry/gateway only.",
            "registry": self.describe(),
        }
        return json.dumps(payload, sort_keys=True)
