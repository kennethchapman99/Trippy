"""Service-level facade for external-world travel data tools.

Trippy domain services should use this facade instead of importing provider SDKs,
scrapers, or registry internals directly. The facade preserves the boundary:
external data comes through `TrippyToolGateway`; ranking and state mutation stay in
Trippy services.
"""

from __future__ import annotations

from typing import Any

from trippy.tool_registry.gateway import TrippyToolGateway
from trippy.tool_registry.schemas import ToolResult


class ExternalTravelToolService:
    """Typed convenience wrapper around the Trippy tool gateway."""

    def __init__(self, gateway: TrippyToolGateway | None = None) -> None:
        self._gateway = gateway or TrippyToolGateway()

    def healthcheck(self) -> dict[str, Any]:
        return self._gateway.healthcheck()

    def search_flights(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("flight_search", input_data, dry_run=dry_run)

    def search_lodging(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("lodging_search", input_data, dry_run=dry_run)

    def search_restaurants(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("restaurant_search", input_data, dry_run=dry_run)

    def discover_activities(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("activity_discovery", input_data, dry_run=dry_run)

    def check_weather(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("weather_check", input_data, dry_run=dry_run)

    def check_route(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("route_check", input_data, dry_run=dry_run)

    def check_travel_advisory(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("travel_advisory_check", input_data, dry_run=dry_run)

    def validate_itinerary(self, input_data: dict[str, Any], *, dry_run: bool = False) -> ToolResult:
        return self._call("itinerary_validation", input_data, dry_run=dry_run)

    def _call(self, tool_id: str, input_data: dict[str, Any], *, dry_run: bool) -> ToolResult:
        payload = self._gateway.call(tool_id, input_data, dry_run=dry_run)
        return ToolResult.model_validate(payload)
