"""Shared Anthropic LLM wrapper for Trippy services."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic

from trippy import config
from trippy.models.llm_accounting import LLMAccountingRecord
from trippy.services.llm_accountant import LLMAccountant, estimate_cost_usd, usage_from_response


@dataclass
class LLMResult:
    status: str
    model: str
    text: str = ""
    json: dict[str, Any] | None = None
    error: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


class TrippyLLMClient:
    def __init__(
        self,
        *,
        anthropic_client: Any | None = None,
        mode: str | None = None,
        accountant: LLMAccountant | None = None,
    ) -> None:
        self._client = anthropic_client
        self._mode = mode or config.TRIPPY_LLM_MODE
        self._accountant = accountant or LLMAccountant()

    @property
    def mode(self) -> str:
        return self._mode

    def complete_json(
        self,
        *,
        service: str,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int = 1800,
        trip_id: str | None = None,
        prompt_version: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LLMResult:
        result = self.complete_text(
            service=service,
            model=model,
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            trip_id=trip_id,
            prompt_version=prompt_version,
            metadata=metadata,
        )
        if result.status != "success":
            return result
        try:
            result.json = parse_json_object(result.text)
            return result
        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            self._record(
                service=service,
                model=model,
                status="failed",
                trip_id=trip_id,
                prompt_version=prompt_version,
                started_at=datetime.utcnow(),
                ended_at=datetime.utcnow(),
                error=str(exc),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                metadata=metadata or {},
            )
            return result

    def complete_text(
        self,
        *,
        service: str,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int = 1800,
        trip_id: str | None = None,
        prompt_version: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LLMResult:
        started = datetime.utcnow()
        if self._mode in {"off", "test"} or (
            "PYTEST_CURRENT_TEST" in os.environ and self._client is None
        ):
            self._record(service, model, "skipped", trip_id, prompt_version, started, datetime.utcnow(), metadata=metadata or {})
            return LLMResult(status="skipped", model=model, error=f"LLM mode is {self._mode}")
        if not config.ANTHROPIC_API_KEY and self._client is None:
            status = "failed" if self._mode == "required" else "skipped"
            error = "ANTHROPIC_API_KEY is missing"
            self._record(service, model, status, trip_id, prompt_version, started, datetime.utcnow(), error=error, metadata=metadata or {})
            return LLMResult(status=status, model=model, error=error)
        try:
            client = self._client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response_text(response)
            input_tokens, output_tokens = usage_from_response(response)
            self._record(
                service,
                model,
                "success",
                trip_id,
                prompt_version,
                started,
                datetime.utcnow(),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                metadata=metadata or {},
            )
            return LLMResult(
                status="success",
                model=model,
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception as exc:
            self._record(service, model, "failed", trip_id, prompt_version, started, datetime.utcnow(), error=str(exc), metadata=metadata or {})
            if self._mode == "required":
                raise
            return LLMResult(status="failed", model=model, error=str(exc))

    def _record(
        self,
        service: str,
        model: str,
        status: str,
        trip_id: str | None,
        prompt_version: str,
        started_at: datetime,
        ended_at: datetime,
        *,
        error: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        self._accountant.record(
            LLMAccountingRecord(
                trip_id=trip_id,
                service=service,
                model=model,
                mode=self._mode,
                prompt_version=prompt_version,
                status=status,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
                estimate_incomplete=cost is None,
                started_at=started_at,
                ended_at=ended_at,
                error=error,
                metadata=metadata or {},
            )
        )


def response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", "") == "text":
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(part for part in parts if part).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped.removeprefix("json").strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data
