"""Shared Anthropic LLM wrapper with caching and accounting."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import anthropic

from trippy import config
from trippy.services.llm_accountant import LLMAccountant
from trippy.services.llm_cache import LLMCache


class TrippyLLMClient:
    def __init__(
        self,
        *,
        anthropic_client: Any | None = None,
        cache: LLMCache | None = None,
        accountant: LLMAccountant | None = None,
    ) -> None:
        self._client = anthropic_client
        self._cache = cache or LLMCache()
        self._accountant = accountant or LLMAccountant()

    def complete_json(
        self,
        *,
        service: str,
        trip_id: str | None,
        model: str,
        prompt: str,
        system: str,
        prompt_version: str,
        cache_payload: Any | None = None,
        max_tokens: int = 1800,
        mode: str = "advisory",
    ) -> dict[str, Any]:
        started = datetime.utcnow()
        start_perf = time.perf_counter()
        cache_key = self._cache.key_for(
            service=service,
            model=model,
            prompt_version=prompt_version,
            payload=cache_payload if cache_payload is not None else prompt,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            self._accountant.record(
                trip_id=trip_id,
                service=service,
                model=model,
                mode=mode,
                prompt_version=prompt_version,
                status="cache_hit",
                cache_hit=True,
                duration_ms=duration_ms,
                started_at=started,
                ended_at=datetime.utcnow(),
                metadata={"cache_key": cache_key},
            )
            result = dict(cached)
            result.setdefault("_llm_status", {})
            if isinstance(result["_llm_status"], dict):
                result["_llm_status"].update(
                    {"cache_hit": True, "duration_ms": duration_ms, "model": model}
                )
            return result

        if mode in {"off", "test"} or not config.ANTHROPIC_API_KEY and self._client is None:
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            status = "skipped_no_api_key" if mode not in {"off", "test"} else "skipped"
            self._accountant.record(
                trip_id=trip_id,
                service=service,
                model=model,
                mode=mode,
                prompt_version=prompt_version,
                status=status,
                duration_ms=duration_ms,
                started_at=started,
                ended_at=datetime.utcnow(),
            )
            return {
                "status": status,
                "_llm_status": {
                    "status": status,
                    "model": model,
                    "duration_ms": duration_ms,
                    "cache_hit": False,
                },
            }

        input_tokens = 0
        output_tokens = 0
        try:
            client = self._client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = _response_text(response)
            parsed = _parse_json_response(text)
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            parsed.setdefault("_llm_status", {})
            if isinstance(parsed["_llm_status"], dict):
                parsed["_llm_status"].update(
                    {
                        "status": "llm_success",
                        "model": model,
                        "duration_ms": duration_ms,
                        "cache_hit": False,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    }
                )
            self._cache.set(
                cache_key,
                parsed,
                metadata={"service": service, "model": model, "prompt_version": prompt_version},
            )
            self._accountant.record(
                trip_id=trip_id,
                service=service,
                model=model,
                mode=mode,
                prompt_version=prompt_version,
                status="success",
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                started_at=started,
                ended_at=datetime.utcnow(),
                metadata={"cache_key": cache_key},
            )
            return parsed
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            self._accountant.record(
                trip_id=trip_id,
                service=service,
                model=model,
                mode=mode,
                prompt_version=prompt_version,
                status="failed",
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                started_at=started,
                ended_at=datetime.utcnow(),
                error=str(exc),
                metadata={"cache_key": cache_key},
            )
            return {
                "status": "llm_failed",
                "error": str(exc),
                "_llm_status": {
                    "status": "llm_failed",
                    "model": model,
                    "duration_ms": duration_ms,
                    "cache_hit": False,
                    "error": str(exc),
                },
            }


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", "") == "text":
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(part for part in parts if part).strip()


def _parse_json_response(text: str) -> dict[str, Any]:
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
