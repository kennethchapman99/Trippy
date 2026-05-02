"""Models for best-effort per-trip LLM usage accounting."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class LLMAccountingRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    trip_id: str | None = None
    service: str
    model: str
    mode: str
    prompt_version: str = ""
    status: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    estimate_incomplete: bool = False
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime = Field(default_factory=datetime.utcnow)
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMTripUsageSummary(BaseModel):
    trip_id: str
    total_calls: int = 0
    total_estimated_cost_usd: float = 0.0
    estimate_incomplete: bool = False
    by_service: dict[str, int] = Field(default_factory=dict)
    by_model: dict[str, int] = Field(default_factory=dict)
    records: list[LLMAccountingRecord] = Field(default_factory=list)
