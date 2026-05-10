"""Normalized Printing Press-style tool result contracts for Trippy.

External-world travel tools must return compact structured JSON through this
contract before Hermes or Trippy domain logic consumes the result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ToolMode = Literal["live", "cache", "fixture", "dry_run"]

SCHEMA_IDS = {
    "flight_option.v1",
    "lodging_option.v1",
    "restaurant_option.v1",
    "activity_option.v1",
    "weather_result.v1",
    "route_result.v1",
    "travel_advisory_result.v1",
    "itinerary_validation_result.v1",
    "tool_error.v1",
}


class ToolResult(BaseModel):
    """Stable result envelope returned by every external-world tool."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str
    source: str
    mode: ToolMode
    type: str
    schema_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    last_checked_at: str
    stale_after_minutes: int = Field(ge=0)
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def known_schema(cls, value: str) -> str:
        if value not in SCHEMA_IDS:
            raise ValueError(f"Unknown Trippy tool schema: {value}")
        return value

    @field_validator("last_checked_at")
    @classmethod
    def iso_timestamp(cls, value: str) -> str:
        parsed = value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(parsed)
        except ValueError as exc:
            raise ValueError("last_checked_at must be ISO-8601") from exc
        return value


class ToolError(ToolResult):
    """Typed failure result. Tools should return this instead of prose errors."""

    schema_version: str = "tool_error.v1"
    type: str = "tool_error"
    confidence: float = 0.0
    stale_after_minutes: int = 0


class ToolDescription(BaseModel):
    """Machine-readable tool card exposed to Hermes and Scouty."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    implementation: str
    command: str
    schema: str
    supports_dry_run: bool
    supports_cache: bool
    requires_network: bool
    requires_api_key: bool
    freshness_minutes: int
    last_verified_at: str | None = None
    status: Literal["fixture", "live", "disabled"]
    description: str = ""


class HealthcheckResult(BaseModel):
    """Structured healthcheck for a registered tool."""

    tool_id: str
    ok: bool
    status: str
    mode: str
    message: str
    schema: str
    checked_at: str


def utc_now_iso() -> str:
    """Return an ISO timestamp with a stable UTC suffix."""

    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
