from __future__ import annotations

from trippy.tool_registry.gateway import TrippyToolGateway
from trippy.tool_registry.registry import ToolRegistry
from trippy.tool_registry.schemas import SCHEMA_IDS, ToolResult


REQUIRED_RESULT_FIELDS = {
    "tool_id",
    "source",
    "mode",
    "type",
    "schema_version",
    "confidence",
    "last_checked_at",
    "stale_after_minutes",
    "summary",
    "data",
    "warnings",
    "risk_flags",
    "source_urls",
}


def test_registry_loads_successfully() -> None:
    registry = ToolRegistry()

    assert len(registry.list_tools()) >= 8
    assert registry.validate() == []


def test_every_registered_tool_has_known_schema() -> None:
    registry = ToolRegistry()

    for tool in registry.list_tools():
        assert tool.schema in SCHEMA_IDS
        assert tool.implementation == "printing_press_adapter"
        assert tool.supports_dry_run is True


def test_dry_run_works_for_all_registered_tools() -> None:
    registry = ToolRegistry()

    for tool in registry.list_tools():
        payload = registry.dry_run(
            tool.id,
            {"origin": "YYZ", "destination": "Santiago", "start_date": "2026-06-08"},
        )
        assert REQUIRED_RESULT_FIELDS.issubset(payload.keys())
        result = ToolResult.model_validate(payload)
        assert result.tool_id == tool.id
        assert result.schema_version == tool.schema
        assert result.mode == "dry_run"
        assert result.last_checked_at
        assert result.stale_after_minutes == tool.freshness_minutes
        assert result.summary


def test_fixture_mode_returns_valid_structured_json_for_all_tools() -> None:
    registry = ToolRegistry()

    for tool in registry.list_tools():
        payload = registry.run(
            tool.id,
            {"origin": "YYZ", "destination": "Santiago", "start_date": "2026-06-08"},
        )
        assert REQUIRED_RESULT_FIELDS.issubset(payload.keys())
        result = ToolResult.model_validate(payload)
        assert result.tool_id == tool.id
        assert result.schema_version == tool.schema
        assert result.mode == "fixture"
        assert result.confidence > 0
        assert result.last_checked_at
        assert result.stale_after_minutes == tool.freshness_minutes
        assert "Fixture/mock mode" in " ".join(result.warnings)


def test_gateway_healthcheck_and_call_shape() -> None:
    gateway = TrippyToolGateway()

    health = gateway.healthcheck()
    assert health["ok"] is True
    assert len(health["tools"]) >= 8

    result = gateway.call(
        "flight_search",
        {"origin": "YYZ", "destination": "SCL", "departure_date": "2026-06-08"},
        dry_run=True,
    )
    parsed = ToolResult.model_validate(result)
    assert parsed.tool_id == "flight_search"
    assert parsed.mode == "dry_run"
    assert parsed.schema_version == "flight_option.v1"
