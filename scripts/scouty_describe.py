#!/usr/bin/env python
"""Emit JSON that helps Scouty inspect Trippy's agent/tool architecture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trippy import config
from trippy.tool_registry.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


def _existing(paths: list[str]) -> list[str]:
    return [path for path in paths if (ROOT / path).exists()]


def _grep(paths: list[str], needles: list[str]) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    for rel in paths:
        path = ROOT / rel
        if not path.exists() or path.is_dir():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = [needle for needle in needles if needle in text]
        if found:
            matches[rel] = found
    return matches


def main() -> None:
    registry = ToolRegistry()
    source_files = [
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "trippy").rglob("*.py"))
        if ".venv" not in path.parts
    ]
    payload: dict[str, Any] = {
        "app_name": "Trippy",
        "architecture": {
            "hermes_owns": ["planning", "reasoning", "orchestration", "skills", "memory", "review_gated_learning"],
            "trippy_owns": ["canonical_trip_state", "ranking", "UX", "saved_trips", "review_gates", "domain_logic"],
            "printing_press_tools_own": ["external_world_tool_commands", "structured_JSON", "healthchecks", "dry_run", "fixtures", "schemas"],
        },
        "tool_registry_path": str(registry.registry_path.relative_to(ROOT)),
        "registered_tools": [tool.model_dump(mode="json") for tool in registry.list_tools()],
        "schemas": sorted({tool.schema for tool in registry.list_tools()}),
        "schema_manifest_path": "trippy/tool_registry/schema_definitions/manifest.json",
        "llm_calls": _grep(source_files, ["anthropic", "messages.create", "TRIPPY_AGENT_LLM_MODEL"]),
        "external_apis": _grep(
            source_files,
            ["Duffel", "DUFFEL_ACCESS_TOKEN", "Firecrawl", "FIRECRAWL", "urlopen", "googleapiclient", "serpapi"],
        ),
        "learning_memory_files": {
            "memory_path": str(config.MEMORY_PATH),
            "learning_path": str(config.LEARNING_PATH),
            "trips_path": str(config.TRIPS_PATH),
            "files": _existing([
                "trippy/hermes/orchestrator.py",
                "trippy/hermes/tool_client.py",
                "trippy/services/learning.py",
                "trippy/memory/store.py",
            ]),
        },
        "healthcheck_command": "python scripts/trippy_tool_gateway.py healthcheck",
        "fixture_mode_command": "python scripts/trippy_tool_gateway.py run flight_search '{\"origin\":\"YYZ\",\"destination\":\"SCL\"}'",
        "dry_run_command": "python scripts/trippy_tool_gateway.py dry-run lodging_search '{\"destination\":\"Valparaiso\"}'",
        "test_command": "uv run pytest tests/unit/test_tool_registry_gateway.py tests/unit/test_hermes_orchestration.py",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
