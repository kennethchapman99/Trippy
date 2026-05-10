"""Tool registry loader and executor for Trippy external-world tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from trippy.tool_registry.adapters import build_adapter
from trippy.tool_registry.schemas import SCHEMA_IDS, HealthcheckResult, ToolDescription, ToolError, utc_now_iso

_DEFAULT_REGISTRY_PATH = Path(__file__).with_name("registry.json")


class ToolRegistryFile(BaseModel):
    version: str = "1.0"
    tools: list[ToolDescription] = Field(default_factory=list)


class ToolRegistry:
    """Machine-readable registry of Printing Press-style tools.

    Hermes discovers tools here. Trippy services may also call this gateway when
    they need external-world data. The registry is the only authoritative catalog;
    do not create parallel registries in prompts or services.
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or _DEFAULT_REGISTRY_PATH
        self._file = self._load_registry()
        self._tools = {tool.id: tool for tool in self._file.tools}
        self._adapters = {tool.id: build_adapter(tool) for tool in self._file.tools}

    def list_tools(self) -> list[ToolDescription]:
        return list(self._file.tools)

    def get(self, tool_id: str) -> ToolDescription:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Trippy tool: {tool_id}") from exc

    def describe(self, tool_id: str | None = None) -> dict[str, Any]:
        if tool_id:
            return self.get(tool_id).model_dump(mode="json")
        return {
            "registry_path": str(self.registry_path),
            "version": self._file.version,
            "tools": [tool.model_dump(mode="json") for tool in self.list_tools()],
        }

    def healthcheck(self, tool_id: str | None = None) -> list[HealthcheckResult]:
        ids = [tool_id] if tool_id else [tool.id for tool in self._file.tools]
        return [self._adapters[item].healthcheck() for item in ids]

    def dry_run(self, tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        description = self.get(tool_id)
        if not description.supports_dry_run:
            return ToolError(
                tool_id=tool_id,
                source=description.command,
                mode="dry_run",
                last_checked_at=utc_now_iso(),
                summary=f"Tool {tool_id} does not support dry-run.",
                data={"code": "dry_run_not_supported"},
                warnings=["Dry-run unsupported."],
                risk_flags=["dry_run_not_supported"],
                source_urls=[],
            ).model_dump(mode="json")
        return self._adapters[tool_id].dry_run(input_data)

    def run(self, tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._adapters[tool_id].run(input_data)

    def validate(self) -> list[str]:
        """Return registry validation errors. Empty list means valid."""

        errors: list[str] = []
        seen: set[str] = set()
        for tool in self._file.tools:
            if tool.id in seen:
                errors.append(f"duplicate tool id: {tool.id}")
            seen.add(tool.id)
            if tool.schema not in SCHEMA_IDS:
                errors.append(f"tool {tool.id} references unknown schema {tool.schema}")
            if tool.implementation != "printing_press_adapter":
                errors.append(
                    f"tool {tool.id} uses unsupported implementation {tool.implementation!r}"
                )
        return errors

    def _load_registry(self) -> ToolRegistryFile:
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            registry = ToolRegistryFile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Unable to load Trippy tool registry: {self.registry_path}") from exc
        errors = []
        seen: set[str] = set()
        for tool in registry.tools:
            if tool.id in seen:
                errors.append(f"duplicate tool id: {tool.id}")
            seen.add(tool.id)
            if tool.schema not in SCHEMA_IDS:
                errors.append(f"tool {tool.id} references unknown schema {tool.schema}")
        if errors:
            raise RuntimeError("Invalid Trippy tool registry: " + "; ".join(errors))
        return registry
