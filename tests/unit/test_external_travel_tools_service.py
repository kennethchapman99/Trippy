from __future__ import annotations

from typing import Any

from trippy.services.external_travel_tools import ExternalTravelToolService
from trippy.tool_registry.schemas import ToolResult, utc_now_iso


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def healthcheck(self) -> dict[str, Any]:
        return {"ok": True, "tools": []}

    def call(self, tool_id: str, input_data: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        self.calls.append((tool_id, input_data, dry_run))
        schema = {
            "flight_search": "flight_option.v1",
            "lodging_search": "lodging_option.v1",
            "restaurant_search": "restaurant_option.v1",
            "activity_discovery": "activity_option.v1",
            "weather_check": "weather_result.v1",
            "route_check": "route_result.v1",
            "travel_advisory_check": "travel_advisory_result.v1",
            "itinerary_validation": "itinerary_validation_result.v1",
        }[tool_id]
        return {
            "tool_id": tool_id,
            "source": f"fixture:{tool_id}",
            "mode": "dry_run" if dry_run else "fixture",
            "type": schema.removesuffix(".v1"),
            "schema_version": schema,
            "confidence": 0.5,
            "last_checked_at": utc_now_iso(),
            "stale_after_minutes": 30,
            "summary": "test result",
            "data": {"input": input_data},
            "warnings": [],
            "risk_flags": [],
            "source_urls": [],
        }


def test_external_travel_tool_service_routes_all_categories_to_gateway() -> None:
    gateway = RecordingGateway()
    service = ExternalTravelToolService(gateway=gateway)  # type: ignore[arg-type]

    results = [
        service.search_flights({"origin": "YYZ", "destination": "SCL"}, dry_run=True),
        service.search_lodging({"destination": "Valparaiso"}, dry_run=True),
        service.search_restaurants({"destination": "Santiago"}, dry_run=True),
        service.discover_activities({"destination": "Santiago"}, dry_run=True),
        service.check_weather({"destination": "Santiago"}, dry_run=True),
        service.check_route({"origin": "SCL", "destination": "Valparaiso"}, dry_run=True),
        service.check_travel_advisory({"destination": "Chile"}, dry_run=True),
        service.validate_itinerary({"trip_id": "test-trip"}, dry_run=True),
    ]

    assert all(isinstance(result, ToolResult) for result in results)
    assert [call[0] for call in gateway.calls] == [
        "flight_search",
        "lodging_search",
        "restaurant_search",
        "activity_discovery",
        "weather_check",
        "route_check",
        "travel_advisory_check",
        "itinerary_validation",
    ]
    assert all(call[2] is True for call in gateway.calls)


def test_external_travel_tool_service_healthcheck_uses_gateway() -> None:
    gateway = RecordingGateway()
    service = ExternalTravelToolService(gateway=gateway)  # type: ignore[arg-type]

    assert service.healthcheck() == {"ok": True, "tools": []}
