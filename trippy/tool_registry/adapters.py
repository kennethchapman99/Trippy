"""Printing Press-style adapters for external-world travel tools.

The first adapters are fixture-backed and intentionally marked as fixture/dry-run.
Live providers can replace the internal command body later without changing the
Hermes-facing contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError

from trippy.tool_registry.schemas import HealthcheckResult, ToolDescription, ToolError, ToolResult, utc_now_iso


class ToolAdapter(ABC):
    """Common adapter interface for all registered Trippy tools."""

    def __init__(self, description: ToolDescription) -> None:
        self.description = description

    @abstractmethod
    def healthcheck(self) -> HealthcheckResult:
        """Return adapter health without making unsafe external calls."""

    def describe(self) -> ToolDescription:
        return self.description

    def validate_input(self, input_data: dict[str, Any]) -> None:
        if not isinstance(input_data, dict):
            raise ValueError("tool input must be a JSON object")

    def validate_output(self, output: dict[str, Any]) -> ToolResult:
        return ToolResult.model_validate(output)

    def dry_run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        self.validate_input(input_data)
        return self._result(
            mode="dry_run",
            summary=f"Dry run for {self.description.id}; no external provider was called.",
            data={"input": input_data, "would_call": self.description.command},
            confidence=0.5,
            warnings=["Dry-run result only; not suitable for booking decisions."],
        )

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        self.validate_input(input_data)
        if self.description.status == "disabled":
            return self._error("tool_disabled", f"Tool {self.description.id} is disabled")
        if self.description.status == "fixture":
            return self._fixture(input_data)
        return self._error(
            "live_not_implemented",
            f"Tool {self.description.id} is registered as live but has no live adapter yet.",
        )

    @abstractmethod
    def _fixture(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Return realistic fixture-backed structured JSON."""

    def _result(
        self,
        *,
        mode: str,
        summary: str,
        data: dict[str, Any],
        confidence: float,
        warnings: list[str] | None = None,
        risk_flags: list[str] | None = None,
        source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tool_id": self.description.id,
            "source": self.description.command,
            "mode": mode,
            "type": self.description.schema.removesuffix(".v1"),
            "schema_version": self.description.schema,
            "confidence": confidence,
            "last_checked_at": utc_now_iso(),
            "stale_after_minutes": self.description.freshness_minutes,
            "summary": summary,
            "data": data,
            "warnings": warnings or [],
            "risk_flags": risk_flags or [],
            "source_urls": source_urls or [],
        }
        return self.validate_output(payload).model_dump(mode="json")

    def _error(self, code: str, message: str) -> dict[str, Any]:
        payload = ToolError(
            tool_id=self.description.id,
            source=self.description.command,
            mode="fixture" if self.description.status == "fixture" else "dry_run",
            last_checked_at=utc_now_iso(),
            summary=message,
            data={"code": code, "message": message},
            warnings=[message],
            risk_flags=[code],
            source_urls=[],
        )
        return payload.model_dump(mode="json")


class FixtureToolAdapter(ToolAdapter):
    """Base fixture implementation for generated/adapted tools."""

    def healthcheck(self) -> HealthcheckResult:
        return HealthcheckResult(
            tool_id=self.description.id,
            ok=self.description.status != "disabled",
            status=self.description.status,
            mode="fixture" if self.description.status == "fixture" else self.description.status,
            message=(
                "Fixture adapter is ready and returns normalized JSON."
                if self.description.status != "disabled"
                else "Tool is disabled."
            ),
            schema=self.description.schema,
            checked_at=utc_now_iso(),
        )

    def _fixture(self, input_data: dict[str, Any]) -> dict[str, Any]:
        builder = _FIXTURE_BUILDERS.get(self.description.schema, _generic_fixture_data)
        data = builder(self.description.id, input_data)
        return self._result(
            mode="fixture",
            summary=data.pop("summary"),
            data=data,
            confidence=0.62,
            warnings=[
                "Fixture/mock mode: this result validates the final interface but is not live inventory."
            ],
            risk_flags=data.pop("risk_flags", []),
            source_urls=data.pop("source_urls", []),
        )


def build_adapter(description: ToolDescription) -> ToolAdapter:
    """Factory used by the registry.

    Future Printing Press-generated tools can register their own adapter class here
    while preserving the same describe/healthcheck/dry_run/run contract.
    """

    return FixtureToolAdapter(description)


def validate_tool_result(payload: dict[str, Any]) -> ToolResult:
    try:
        return ToolResult.model_validate(payload)
    except ValidationError:
        raise


def _origin(input_data: dict[str, Any]) -> str:
    return str(input_data.get("origin") or input_data.get("from") or "YYZ")


def _destination(input_data: dict[str, Any]) -> str:
    return str(input_data.get("destination") or input_data.get("to") or "Destination TBD")


def _dates(input_data: dict[str, Any]) -> tuple[str, str]:
    return (
        str(input_data.get("start_date") or input_data.get("departure_date") or "date TBD"),
        str(input_data.get("end_date") or input_data.get("return_date") or "date TBD"),
    )


def _flight_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    start, end = _dates(input_data)
    origin = _origin(input_data)
    destination = _destination(input_data)
    return {
        "summary": f"Fixture flight search for {origin} to {destination}.",
        "query": input_data,
        "options": [
            {
                "option_id": "fixture-flight-1",
                "phase": input_data.get("flight_phase", "departure"),
                "origin": origin,
                "destination": destination,
                "departure_date": start,
                "return_date": end,
                "stops": 1,
                "duration": "fixture duration",
                "price_cad": None,
                "booking_readiness": "mock_only",
            }
        ],
        "risk_flags": ["fixture_not_live", "price_not_verified"],
        "source_urls": [],
    }


def _lodging_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    destination = _destination(input_data)
    start, end = _dates(input_data)
    return {
        "summary": f"Fixture lodging search for {destination}.",
        "query": input_data,
        "options": [
            {
                "option_id": "fixture-lodging-1",
                "name": "Fixture Central Family Hotel",
                "destination": destination,
                "check_in": start,
                "check_out": end,
                "room_fit": "family-fit requires live verification",
                "price_cad": None,
                "booking_readiness": "mock_only",
            }
        ],
        "risk_flags": ["fixture_not_live", "bed_layout_not_verified"],
        "source_urls": [],
    }


def _restaurant_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    destination = _destination(input_data)
    return {
        "summary": f"Fixture restaurant discovery for {destination}.",
        "query": input_data,
        "options": [
            {
                "option_id": "fixture-restaurant-1",
                "name": "Fixture Local Table",
                "destination": destination,
                "reservation_needed": "unknown",
                "family_fit": "requires live/open-hours verification",
            }
        ],
        "risk_flags": ["fixture_not_live", "hours_not_verified"],
        "source_urls": [],
    }


def _activity_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    destination = _destination(input_data)
    return {
        "summary": f"Fixture activity discovery for {destination}.",
        "query": input_data,
        "options": [
            {
                "option_id": "fixture-activity-1",
                "name": "Fixture Small-Group Food Walk",
                "destination": destination,
                "duration": "2-3 hours",
                "age_fit": "requires operator verification",
            }
        ],
        "risk_flags": ["fixture_not_live", "availability_not_verified"],
        "source_urls": [],
    }


def _weather_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    destination = _destination(input_data)
    return {
        "summary": f"Fixture weather check for {destination}.",
        "query": input_data,
        "forecast": {
            "destination": destination,
            "condition": "fixture climatology placeholder",
            "planning_note": "Promote to live weather provider before day-level decisions.",
        },
        "risk_flags": ["fixture_not_live"],
        "source_urls": [],
    }


def _route_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    origin = _origin(input_data)
    destination = _destination(input_data)
    return {
        "summary": f"Fixture route check from {origin} to {destination}.",
        "query": input_data,
        "route": {
            "origin": origin,
            "destination": destination,
            "duration_minutes": None,
            "distance_km": None,
            "planning_note": "Live maps/routing required before timeline lock.",
        },
        "risk_flags": ["fixture_not_live", "duration_not_verified"],
        "source_urls": [],
    }


def _advisory_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    destination = _destination(input_data)
    return {
        "summary": f"Fixture travel advisory check for {destination}.",
        "query": input_data,
        "advisory": {
            "destination": destination,
            "level": "unknown_fixture",
            "required_follow_up": "Check official government advisory before booking.",
        },
        "risk_flags": ["fixture_not_live", "official_advisory_not_verified"],
        "source_urls": [],
    }


def _itinerary_validation_fixture(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "Fixture itinerary validation completed against structural rules only.",
        "query": input_data,
        "validation": {
            "status": "mock_only",
            "blocking_issues": [],
            "warnings": ["Live routing, hours, weather, and booking data were not checked."],
        },
        "risk_flags": ["fixture_not_live"],
        "source_urls": [],
    }


def _generic_fixture_data(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": f"Fixture result for {tool_id}.",
        "query": input_data,
        "risk_flags": ["fixture_not_live"],
        "source_urls": [],
    }


_FIXTURE_BUILDERS = {
    "flight_option.v1": _flight_fixture,
    "lodging_option.v1": _lodging_fixture,
    "restaurant_option.v1": _restaurant_fixture,
    "activity_option.v1": _activity_fixture,
    "weather_result.v1": _weather_fixture,
    "route_result.v1": _route_fixture,
    "travel_advisory_result.v1": _advisory_fixture,
    "itinerary_validation_result.v1": _itinerary_validation_fixture,
}
