"""Best-effort per-trip LLM latency and cost accounting."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from trippy import config
from trippy.models.llm_accounting import LLMCallRecord, LLMTripAccountingSummary

# Approximate USD per million tokens. Keep this conservative and configurable later.
_MODEL_PRICING_USD_PER_MTOK = {
    "haiku": {"input": 1.0, "output": 5.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "opus": {"input": 15.0, "output": 75.0},
}


class LLMAccountant:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or config.LLM_ACCOUNTING_PATH

    def record(
        self,
        *,
        trip_id: str | None,
        service: str,
        model: str,
        mode: str,
        prompt_version: str,
        status: str,
        cache_hit: bool = False,
        duration_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LLMCallRecord:
        record = LLMCallRecord(
            id=str(uuid.uuid4()),
            trip_id=trip_id,
            service=service,
            model=model,
            mode=mode,
            prompt_version=prompt_version,
            status=status,
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=_estimate_cost(model, input_tokens, output_tokens),
            started_at=started_at or datetime.utcnow(),
            ended_at=ended_at or datetime.utcnow(),
            error=error,
            metadata=metadata or {},
        )
        if not config.LLM_ACCOUNTING_ENABLED:
            return record
        try:
            path = self._path(trip_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        except OSError:
            return record
        return record

    def records_for_trip(self, trip_id: str) -> list[LLMCallRecord]:
        path = self._path(trip_id)
        if not path.exists():
            return []
        records: list[LLMCallRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(LLMCallRecord.model_validate(json.loads(line)))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return records

    def summary_for_trip(self, trip_id: str) -> LLMTripAccountingSummary:
        records = self.records_for_trip(trip_id)
        by_service = Counter(record.service for record in records)
        by_model = Counter(record.model for record in records)
        return LLMTripAccountingSummary(
            trip_id=trip_id,
            total_calls=len(records),
            cache_hits=sum(1 for record in records if record.cache_hit),
            total_duration_ms=sum(record.duration_ms for record in records),
            estimated_cost_usd=sum(record.estimated_cost_usd for record in records),
            by_service=dict(by_service),
            by_model=dict(by_model),
            recent_calls=records[-20:],
        )

    def _path(self, trip_id: str | None) -> Path:
        safe_id = trip_id or "unscoped"
        return self._root / f"{safe_id}.jsonl"


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    family = "sonnet"
    lower = model.lower()
    if "haiku" in lower:
        family = "haiku"
    elif "opus" in lower:
        family = "opus"
    pricing = _MODEL_PRICING_USD_PER_MTOK[family]
    return round(
        (input_tokens / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"],
        6,
    )
