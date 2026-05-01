"""Small durable cache for repeated LLM responses."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trippy import config


class LLMCache:
    def __init__(self, cache_dir: Path | None = None, ttl_seconds: int | None = None) -> None:
        self._dir = cache_dir or config.LLM_CACHE_PATH
        self._ttl = ttl_seconds if ttl_seconds is not None else config.LLM_CACHE_TTL_SECONDS

    def key_for(
        self,
        *,
        service: str,
        model: str,
        prompt_version: str,
        payload: Any,
    ) -> str:
        raw = json.dumps(
            {
                "service": service,
                "model": model,
                "prompt_version": prompt_version,
                "payload": payload,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if not config.LLM_CACHE_ENABLED:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(str(data.get("expires_at")))
            if datetime.utcnow() > expires_at:
                path.unlink(missing_ok=True)
                return None
            response = data.get("response")
            return response if isinstance(response, dict) else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def set(self, key: str, response: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> None:
        if not config.LLM_CACHE_ENABLED:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "key": key,
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(seconds=self._ttl)).isoformat(),
                "response": response,
                "metadata": metadata or {},
            }
            self._path(key).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            return

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"
