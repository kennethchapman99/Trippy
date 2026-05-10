"""Stable gateway that Hermes uses for external-world travel tools."""

from __future__ import annotations

from typing import Any

from trippy.tool_registry.registry import ToolRegistry


class TrippyToolGateway:
    """Single call path for external travel data access.

    This gateway is intentionally thin: it owns discovery, schema validation,
    health checks, dry-run support, and dispatch to Printing Press-style adapters.
    It does not rank trips, mutate canonical state, or learn preferences.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry()

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.model_dump(mode="json") for tool in self.registry.list_tools()]

    def describe(self, tool_id: str | None = None) -> dict[str, Any]:
        return self.registry.describe(tool_id)

    def healthcheck(self, tool_id: str | None = None) -> dict[str, Any]:
        results = self.registry.healthcheck(tool_id)
        return {
            "ok": all(item.ok for item in results),
            "registry_path": str(self.registry.registry_path),
            "tools": [item.model_dump(mode="json") for item in results],
        }

    def call(
        self,
        tool_id: str,
        input_data: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = input_data or {}
        if dry_run:
            return self.registry.dry_run(tool_id, payload)
        return self.registry.run(tool_id, payload)

    def call_many(
        self,
        calls: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for call in calls:
            tool_id = str(call.get("tool_id") or call.get("id") or "")
            input_data = call.get("input") if isinstance(call.get("input"), dict) else {}
            results.append(self.call(tool_id, input_data, dry_run=dry_run))
        return results
