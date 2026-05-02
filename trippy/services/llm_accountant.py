"""Best-effort LLM usage accounting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trippy import config
from trippy.models.llm_accounting import LLMAccountingRecord, LLMTripUsageSummary


class LLMAccountant:
    """Store small JSONL records without blocking user flows."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (config.LEARNING_PATH / "llm_accounting.jsonl")

    def record(self, record: LLMAccountingRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        except Exception:
            return

    def records_for_trip(self, trip_id: str) -> list[LLMAccountingRecord]:
        records: list[LLMAccountingRecord] = []
        try:
            if not self._path.exists():
                return []
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("trip_id") == trip_id:
                    records.append(LLMAccountingRecord.model_validate(data))
        except Exception:
            return records
        return records

    def summary_for_trip(self, trip_id: str) -> LLMTripUsageSummary:
        records = self.records_for_trip(trip_id)
        summary = LLMTripUsageSummary(trip_id=trip_id, records=records, total_calls=len(records))
        for record in records:
            summary.by_service[record.service] = summary.by_service.get(record.service, 0) + 1
            summary.by_model[record.model] = summary.by_model.get(record.model, 0) + 1
            if record.estimated_cost_usd is None:
                summary.estimate_incomplete = True
            else:
                summary.total_estimated_cost_usd += record.estimated_cost_usd
            if record.estimate_incomplete:
                summary.estimate_incomplete = True
        return summary


def estimate_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    pricing = config.TRIPPY_LLM_MODEL_PRICING_USD_PER_M_TOKEN.get(model)
    if pricing is None:
        return None
    try:
        input_price, output_price = float(pricing[0]), float(pricing[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)


def usage_from_response(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    return _int_or_none(input_tokens), _int_or_none(output_tokens)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
