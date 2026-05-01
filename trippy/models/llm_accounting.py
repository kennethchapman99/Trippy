"""Models for Trippy LLM latency and cost accounting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LLMCallRecord(BaseModel):
    id: str
    trip_id: str | None = None
    service: str
    model: str
    mode: str = "advisory"
    prompt_version: str = ""
    status: str
    cache_hit: bool = False
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMTripAccountingSummary(BaseModel):
    trip_id: str
    total_calls: int = 0
    cache_hits: int = 0
    total_duration_ms: int = 0
    estimated_cost_usd: float = 0.0
    by_service: dict[str, int] = Field(default_factory=dict)
    by_model: dict[str, int] = Field(default_factory=dict)
    recent_calls: list[LLMCallRecord] = Field(default_factory=list)
