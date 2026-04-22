"""Structured source-research observations and evidence artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceAdapterCapability(StrEnum):
    LINK = "link"
    HTTP = "http"
    PLAYWRIGHT = "playwright"
    OPENCLAW = "openclaw"


class SourceResearchMode(StrEnum):
    AUTO = "auto"
    LINK = "link"
    PLAYWRIGHT = "playwright"
    OPENCLAW = "openclaw"


class SourceResearchStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class EvidenceArtifact(BaseModel):
    artifact_type: str
    label: str
    path: str = ""
    url: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    notes: list[str] = Field(default_factory=list)


class SourceObservation(BaseModel):
    field: str
    value: Any
    confidence: float = 0.5
    source_url: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class SourceResearchRequest(BaseModel):
    trip_id: str
    category: str
    option_id: str
    source_name: str
    source_url: str
    source_type: str = "live_search"
    query: str = ""
    candidate_name: str = ""
    adapter_mode: SourceResearchMode = SourceResearchMode.AUTO
    context: dict[str, Any] = Field(default_factory=dict)


class SourceResearchResult(BaseModel):
    request: SourceResearchRequest
    adapter_used: SourceAdapterCapability
    status: SourceResearchStatus
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 0.0
    observations: list[SourceObservation] = Field(default_factory=list)
    evidence_artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))
