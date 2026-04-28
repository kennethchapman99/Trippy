"""Firecrawl client wrapper with safe disabled-mode behavior."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from trippy import config
from trippy.models.web_research import WebResearchResult


@dataclass
class FirecrawlAvailability:
    available: bool
    reason: str = ""


class FirecrawlService:
    """Small Firecrawl REST wrapper for search/scrape/extract/research."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: float = 10.0,
        retries: int = 2,
    ) -> None:
        self._api_key = api_key if api_key is not None else config.FIRECRAWL_API_KEY
        self._base_url = (
            base_url or config.FIRECRAWL_BASE_URL or "https://api.firecrawl.dev"
        ).rstrip("/")
        self._enabled = config.FIRECRAWL_ENABLED if enabled is None else enabled
        self._timeout = timeout_seconds
        self._retries = max(0, retries)
        self._cache_ttl = max(0, config.FIRECRAWL_CACHE_TTL_SECONDS)
        self._max_results = max(1, config.FIRECRAWL_MAX_RESULTS)
        self._cache: dict[str, tuple[float, list[WebResearchResult]]] = {}

    def availability(self) -> FirecrawlAvailability:
        if not self._enabled:
            return FirecrawlAvailability(available=False, reason="FIRECRAWL_ENABLED is false")
        if not self._api_key:
            return FirecrawlAvailability(available=False, reason="FIRECRAWL_API_KEY is missing")
        return FirecrawlAvailability(available=True)

    def search(self, query: str, *, limit: int | None = None) -> list[WebResearchResult]:
        availability = self.availability()
        if not availability.available:
            return [self._unavailable_result(query, availability.reason)]
        payload = {"query": query, "limit": min(limit or self._max_results, self._max_results)}
        response = self._request("/v1/search", payload)
        entries = response.get("data", []) if isinstance(response, dict) else []
        return [
            self._result_from_entry(query, entry, extraction_type="search") for entry in entries
        ] or [self._unavailable_result(query, "Firecrawl search returned no results")]

    def scrape_url(self, url: str) -> WebResearchResult:
        availability = self.availability()
        if not availability.available:
            return self._unavailable_result(url, availability.reason, source_url=url)
        payload = {"url": url, "formats": ["markdown"]}
        response = self._request("/v1/scrape", payload)
        data = response.get("data", {}) if isinstance(response, dict) else {}
        markdown = str(data.get("markdown") or "")
        return WebResearchResult(
            id=f"firecrawl-{uuid.uuid4().hex[:12]}",
            query=url,
            source_url=url,
            source_title=str(data.get("metadata", {}).get("title") or ""),
            source_domain=urlparse(url).netloc,
            extraction_type="scrape",
            raw_markdown_excerpt=markdown[:1500],
            structured_data={"markdown_length": len(markdown)},
            confidence=0.7 if markdown else 0.3,
            warnings=[] if markdown else ["No markdown returned by Firecrawl scrape"],
        )

    def extract_from_url(
        self,
        url: str,
        *,
        schema: dict[str, Any],
        prompt: str,
    ) -> WebResearchResult:
        availability = self.availability()
        if not availability.available:
            return self._unavailable_result(prompt, availability.reason, source_url=url)
        payload = {"urls": [url], "prompt": prompt, "schema": schema}
        response = self._request("/v1/extract", payload)
        data = response.get("data", {}) if isinstance(response, dict) else {}
        return WebResearchResult(
            id=f"firecrawl-{uuid.uuid4().hex[:12]}",
            query=prompt,
            source_url=url,
            source_title=str(data.get("title") or ""),
            source_domain=urlparse(url).netloc,
            extraction_type="extract",
            structured_data=cast_dict(data),
            confidence=0.72 if data else 0.3,
            warnings=[] if data else ["No structured payload returned by Firecrawl extract"],
        )

    def research(self, query: str, *, limit: int | None = None) -> list[WebResearchResult]:
        cache_key = f"{query}:{limit or self._max_results}"
        now = time.time()
        if self._cache_ttl > 0 and cache_key in self._cache:
            created_at, results = self._cache[cache_key]
            if now - created_at <= self._cache_ttl:
                return results
        results = self.search(query, limit=limit)
        enriched: list[WebResearchResult] = []
        for item in results[: min(limit or self._max_results, self._max_results)]:
            if not item.source_url:
                enriched.append(item)
                continue
            scraped = self.scrape_url(item.source_url)
            merged = item.model_copy(deep=True)
            if scraped.raw_markdown_excerpt:
                merged.raw_markdown_excerpt = scraped.raw_markdown_excerpt
                merged.confidence = min(1.0, max(merged.confidence, scraped.confidence))
                merged.warnings = sorted({*merged.warnings, *scraped.warnings})
            enriched.append(merged)
        if self._cache_ttl > 0:
            self._cache[cache_key] = (now, enriched)
        return enriched

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(self._base_url + "/", path.lstrip("/"))
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Trippy/0.2 Firecrawl",
        }
        last_error = ""
        for attempt in range(self._retries + 1):
            try:
                request = Request(url, data=body, headers=headers, method="POST")
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    raw = response.read().decode("utf-8")
                    return cast_dict(json.loads(raw))
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                last_error = str(exc)
                if attempt >= self._retries:
                    break
                time.sleep(min(1.6, 0.3 * (2**attempt)))
        return {"warning": f"Firecrawl request failed: {last_error}"}

    def _unavailable_result(
        self, query: str, reason: str, *, source_url: str = ""
    ) -> WebResearchResult:
        return WebResearchResult(
            id=f"firecrawl-unavailable-{uuid.uuid4().hex[:8]}",
            query=query,
            source_url=source_url,
            source_domain=urlparse(source_url).netloc if source_url else "",
            extraction_type="unavailable",
            confidence=0.0,
            warnings=[reason],
            structured_data={"status": "disabled"},
        )

    def _result_from_entry(
        self, query: str, entry: Any, *, extraction_type: str
    ) -> WebResearchResult:
        obj = cast_dict(entry)
        source_url = str(obj.get("url") or obj.get("sourceURL") or "")
        return WebResearchResult(
            id=f"firecrawl-{uuid.uuid4().hex[:12]}",
            query=query,
            source_url=source_url,
            source_title=str(obj.get("title") or ""),
            source_domain=urlparse(source_url).netloc,
            extraction_type=extraction_type,
            raw_markdown_excerpt=str(obj.get("markdown") or "")[:1500],
            structured_data={
                "description": obj.get("description") or "",
                "score": obj.get("score") or 0,
            },
            confidence=0.65,
        )


def cast_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}
