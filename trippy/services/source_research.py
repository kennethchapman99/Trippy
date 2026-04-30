"""Deep source-research adapters for enriching canonical shortlists."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from trippy import config
from trippy.models.shortlists import (
    AvailabilityStatus,
    FreshnessStatus,
    LiveDataStatus,
    LodgingFitCategory,
    PriceStatus,
    ResearchShortlistState,
    ShortlistCategory,
    ShortlistRowStatus,
    SourceValidation,
    VerificationStatus,
)
from trippy.models.source_research import (
    EvidenceArtifact,
    SourceAdapterCapability,
    SourceObservation,
    SourceResearchMode,
    SourceResearchRequest,
    SourceResearchResult,
    SourceResearchStatus,
)
from trippy.models.web_research import WebResearchResult
from trippy.services.firecrawl import FirecrawlService
from trippy.services.learning import LearningEventStore

HtmlFetchResult = tuple[str, str, list[str]]
HtmlFetcher = Callable[[str, float], HtmlFetchResult]


class SourceResearchAdapter(Protocol):
    """Adapter contract for read-only source observation extraction."""

    capability: SourceAdapterCapability

    def can_handle(self, request: SourceResearchRequest) -> bool:
        """Return whether this adapter can attempt the request."""
        ...

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        """Return structured observations and evidence for the request."""
        ...


class SourceResearchService:
    """Orchestrate deterministic adapters first, then optional OpenClaw fallback."""

    def __init__(
        self,
        *,
        adapters: list[SourceResearchAdapter] | None = None,
        research_dir: Path | None = None,
        learning_store: LearningEventStore | None = None,
    ) -> None:
        self._research_dir = research_dir or config.RESEARCH_PATH
        self._learning = learning_store or LearningEventStore()
        self._adapters = adapters or [
            LinkResearchAdapter(),
            FirecrawlResearchAdapter(),
            PlaywrightFlightAdapter(),
            PlaywrightLodgingAdapter(),
            PlaywrightActivityAdapter(),
            PlaywrightCarAdapter(),
            OpenClawResearchAdapter(),
        ]

    def research_state(
        self,
        state: ResearchShortlistState,
        *,
        adapter_mode: SourceResearchMode | str = SourceResearchMode.AUTO,
        option_ids: list[str] | None = None,
    ) -> ResearchShortlistState:
        mode = _coerce_mode(adapter_mode)
        run_id = _new_run_id()
        state.artifacts["deep_research"] = {
            "run_id": run_id,
            "adapter_mode": mode.value,
            "started_at": datetime.utcnow().isoformat(),
            "category": state.category.value,
        }
        if state.category not in {
            ShortlistCategory.LODGING,
            ShortlistCategory.FLIGHTS,
            ShortlistCategory.CARS,
            ShortlistCategory.ACTIVITIES,
        }:
            state.artifacts["deep_research"]["status"] = "skipped"
            state.artifacts["deep_research"]["notes"] = [
                "Deep adapters are implemented for lodging, flights, cars, and activities; other categories remain source-link validated."
            ]
            return state

        run_results: list[SourceResearchResult] = []
        selected_option_ids = set(option_ids or [])
        options: list[Any]
        if state.category == ShortlistCategory.LODGING:
            options = list(state.lodging_options)
        elif state.category == ShortlistCategory.FLIGHTS:
            options = list(state.flight_options)
        elif state.category == ShortlistCategory.CARS:
            options = list(state.car_options)
        else:
            options = list(state.activity_options)
        for option in options:
            if selected_option_ids and option.option_id not in selected_option_ids:
                continue
            if state.category == ShortlistCategory.LODGING:
                request = _request_for_lodging_option(state, option, mode)
            elif state.category == ShortlistCategory.FLIGHTS:
                request = _request_for_flight_option(state, option, mode)
            elif state.category == ShortlistCategory.CARS:
                request = _request_for_car_option(state, option, mode)
            else:
                request = _request_for_activity_option(state, option, mode)
            option_dir = (
                self._research_dir
                / state.trip_id
                / state.category.value
                / run_id
                / option.option_id
            )
            result = self._research_request(request, mode=mode, artifact_dir=option_dir)
            if state.category == ShortlistCategory.LODGING:
                _apply_lodging_observations(option, result, run_id=run_id)
            elif state.category == ShortlistCategory.FLIGHTS:
                _apply_flight_observations(option, result, run_id=run_id)
            elif state.category == ShortlistCategory.CARS:
                _apply_car_observations(option, result, run_id=run_id)
            else:
                _apply_activity_observations(option, result, run_id=run_id)
            run_results.append(result)

        state.artifacts["deep_research"].update(
            {
                "status": _aggregate_status(run_results),
                "ended_at": datetime.utcnow().isoformat(),
                "option_count": len(run_results),
                "adapters_used": sorted({result.adapter_used.value for result in run_results}),
                "artifact_root": str(
                    self._research_dir / state.trip_id / state.category.value / run_id
                ),
            }
        )
        complementary_states, party_size = _load_friction_context(state.trip_id, state.category)
        from trippy.services.shortlist_friction import apply_shortlist_friction

        apply_shortlist_friction(
            state,
            complementary_states=complementary_states,
            party_size=party_size,
        )
        if state.category == ShortlistCategory.FLIGHTS:
            review_note = (
                "Review deep-research evidence for flight rows before treating timing, fare, baggage, "
                "or inventory as ready-to-click."
            )
        elif state.category == ShortlistCategory.ACTIVITIES:
            review_note = (
                "Review deep-research evidence for activity rows before treating cost, time, duration, "
                "or availability as ready-to-click."
            )
        elif state.category == ShortlistCategory.CARS:
            review_note = (
                "Review deep-research evidence for car rows before treating total price, seats, "
                "transmission, deposit, insurance, or cancellation terms as ready-to-click."
            )
        else:
            review_note = "Review deep-research evidence for lodging rows before treating any option as ready-to-click."
        state.next_actions.insert(0, review_note)
        self._record_run_event(state, run_id, run_results)
        return state

    def _research_request(
        self,
        request: SourceResearchRequest,
        *,
        mode: SourceResearchMode,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _write_json_artifact(artifact_dir / "request.json", request.model_dump(mode="json"))
        candidates = self._candidate_adapters(mode)
        first_result: SourceResearchResult | None = None
        for adapter in candidates:
            if not adapter.can_handle(request):
                continue
            result = adapter.research(request, artifact_dir=artifact_dir)
            if first_result is None or (
                result.status in {SourceResearchStatus.SUCCESS, SourceResearchStatus.PARTIAL}
                and result.confidence > first_result.confidence
            ):
                first_result = result
            if adapter.capability == SourceAdapterCapability.LINK:
                if mode == SourceResearchMode.AUTO and first_result is not None:
                    return first_result
                return result
            if mode != SourceResearchMode.AUTO:
                return result
            if result.status == SourceResearchStatus.SUCCESS:
                return result
            if result.status == SourceResearchStatus.PARTIAL:
                if not _missing_high_value_fields(result):
                    return result
                continue
            if adapter.capability == SourceAdapterCapability.OPENCLAW:
                return first_result
        if first_result is not None:
            return first_result
        return _result(
            request,
            adapter=SourceAdapterCapability.LINK,
            status=SourceResearchStatus.SKIPPED,
            confidence=0.15,
            notes=["No enabled adapter could handle this source-research request."],
            missing_fields=_missing_fields_for_category(request.category),
        )

    def _candidate_adapters(self, mode: SourceResearchMode) -> list[SourceResearchAdapter]:
        if mode == SourceResearchMode.LINK:
            return [
                adapter
                for adapter in self._adapters
                if adapter.capability == SourceAdapterCapability.LINK
            ]
        if mode == SourceResearchMode.PLAYWRIGHT:
            return [
                adapter
                for adapter in self._adapters
                if adapter.capability == SourceAdapterCapability.PLAYWRIGHT
            ]
        if mode == SourceResearchMode.FIRECRAWL:
            return [
                adapter
                for adapter in self._adapters
                if adapter.capability == SourceAdapterCapability.FIRECRAWL
            ]
        if mode == SourceResearchMode.OPENCLAW:
            return [
                adapter
                for adapter in self._adapters
                if adapter.capability == SourceAdapterCapability.OPENCLAW
            ]
        priority = [
            SourceAdapterCapability.FIRECRAWL,
            SourceAdapterCapability.PLAYWRIGHT,
            SourceAdapterCapability.OPENCLAW,
            SourceAdapterCapability.LINK,
        ]
        return [
            adapter
            for capability in priority
            for adapter in self._adapters
            if adapter.capability == capability
        ]

    def _record_run_event(
        self,
        state: ResearchShortlistState,
        run_id: str,
        results: list[SourceResearchResult],
    ) -> None:
        payload = {
            "run_id": run_id,
            "trip_id": state.trip_id,
            "category": state.category.value,
            "status": state.artifacts.get("deep_research", {}).get("status", ""),
            "adapters_used": sorted({result.adapter_used.value for result in results}),
            "artifact_root": state.artifacts.get("deep_research", {}).get("artifact_root", ""),
            "results": [result.model_dump(mode="json") for result in results],
        }
        self._learning.record_event("source_research", payload)


class LinkResearchAdapter:
    capability = SourceAdapterCapability.LINK

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return bool(request.source_url or request.query)

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        artifact = EvidenceArtifact(
            artifact_type="source-link",
            label="Source handoff URL",
            url=request.source_url,
            notes=["Manual source review is still required; no inventory facts were extracted."],
        )
        return _result(
            request,
            adapter=self.capability,
            status=SourceResearchStatus.PARTIAL,
            confidence=0.25,
            evidence_artifacts=[artifact],
            notes=[
                "Link adapter preserved handoff evidence without claiming extracted live details."
            ],
            missing_fields=_missing_fields_for_category(request.category),
        )


class FirecrawlResearchAdapter:
    """Firecrawl-backed public web intelligence adapter (read-only evidence)."""

    capability = SourceAdapterCapability.FIRECRAWL

    def __init__(self, *, service: FirecrawlService | None = None) -> None:
        self._firecrawl = service or FirecrawlService()

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return request.category in {
            ShortlistCategory.LODGING.value,
            ShortlistCategory.FLIGHTS.value,
            ShortlistCategory.CARS.value,
            ShortlistCategory.ACTIVITIES.value,
        } and bool(request.source_url or request.query)

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        availability = self._firecrawl.availability()
        if not availability.available:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.SKIPPED,
                confidence=0.0,
                notes=[
                    "Firecrawl is unavailable; request safely skipped without pipeline failure.",
                    availability.reason,
                ],
                missing_fields=_missing_fields_for_category(request.category),
            )

        query = (
            request.query or f"{request.candidate_name} {request.source_name} travel policy details"
        )
        first, observations, evidence_refs = self._extract_first_useful_result(request, query)
        if first is None:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.BLOCKED,
                confidence=0.15,
                notes=["Firecrawl returned no usable research rows."],
                missing_fields=_missing_fields_for_category(request.category),
            )
        text = first.raw_markdown_excerpt
        evidence_url = first.source_url or request.source_url
        if not observations:
            observations = [
                SourceObservation(field="raw_markdown_excerpt", value=text[:400], confidence=0.4)
            ]
        artifact_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = artifact_dir / "firecrawl.md"
        markdown_path.write_text(text, encoding="utf-8")
        missing_fields = _remaining_fields_for_category(request.category, observations)
        confidence = max(0.25, _observation_confidence(observations))
        status = (
            SourceResearchStatus.SUCCESS
            if confidence >= 0.68 and len(missing_fields) <= 2
            else SourceResearchStatus.PARTIAL
        )
        return _result(
            request,
            adapter=self.capability,
            status=status,
            confidence=confidence,
            observations=observations,
            evidence_artifacts=[
                EvidenceArtifact(
                    artifact_type="firecrawl-markdown",
                    label="Firecrawl markdown excerpt",
                    path=str(markdown_path),
                    url=evidence_url,
                )
            ],
            notes=[
                "Firecrawl provided public-web enrichment only; live inventory and booking truth remain official APIs.",
                *first.warnings,
            ],
            missing_fields=missing_fields,
        )

    def _extract_first_useful_result(
        self, request: SourceResearchRequest, query: str
    ) -> tuple[WebResearchResult | None, list[SourceObservation], list[str]]:
        if request.source_url:
            scraped = self._firecrawl.scrape_url(request.source_url)
            if scraped.raw_markdown_excerpt:
                scraped.query = query
                evidence_refs = [scraped.source_url or request.source_url]
                observations = self._extract_observations(
                    scraped.raw_markdown_excerpt,
                    request=request,
                    evidence_refs=evidence_refs,
                )
                if observations:
                    return scraped, observations, evidence_refs
                first = scraped
                first_observations = observations
                first_refs = evidence_refs
            else:
                first = None
                first_observations = []
                first_refs = []
        else:
            first = None
            first_observations = []
            first_refs = []

        for candidate in self._firecrawl.research(query):
            if first is None:
                first = candidate
            evidence_url = candidate.source_url or request.source_url
            evidence_refs = [evidence_url] if evidence_url else []
            observations = self._extract_observations(
                candidate.raw_markdown_excerpt,
                request=request,
                evidence_refs=evidence_refs,
            )
            if first_observations == []:
                first_observations = observations
                first_refs = evidence_refs
            if observations:
                return candidate, observations, evidence_refs
        return first, first_observations, first_refs

    def _extract_observations(
        self,
        text: str,
        *,
        request: SourceResearchRequest,
        evidence_refs: list[str],
    ) -> list[SourceObservation]:
        if request.category == ShortlistCategory.FLIGHTS.value:
            return _extract_flight_observations(
                text, request=request, evidence_refs=evidence_refs
            )
        if request.category == ShortlistCategory.LODGING.value:
            return _extract_lodging_observations(
                text, request=request, evidence_refs=evidence_refs
            )
        if request.category == ShortlistCategory.CARS.value:
            return _extract_car_observations(text, request=request, evidence_refs=evidence_refs)
        return _extract_activity_observations(text, request=request, evidence_refs=evidence_refs)


class PlaywrightFlightAdapter:
    """Read-only flight source adapter with deterministic HTML/text extraction."""

    capability = SourceAdapterCapability.PLAYWRIGHT

    def __init__(
        self,
        *,
        fetcher: HtmlFetcher | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._fetcher = fetcher or _fetch_html
        self._custom_fetcher = fetcher is not None
        self._timeout = timeout_seconds or config.SOURCE_RESEARCH_TIMEOUT_SECONDS

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return request.category == ShortlistCategory.FLIGHTS.value and bool(request.source_url)

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        notes = [
            "Read-only flight source extraction; no login, booking, cart, seat, or payment action attempted."
        ]
        try:
            if (
                config.SOURCE_RESEARCH_PLAYWRIGHT_ENABLED
                and not self._custom_fetcher
                and shutil.which("npx") is not None
            ):
                html, final_url, fetch_notes = _fetch_html_with_playwright(
                    request.source_url,
                    self._timeout,
                )
            else:
                html, final_url, fetch_notes = self._fetcher(request.source_url, self._timeout)
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.BLOCKED,
                confidence=0.2,
                notes=[*notes, f"Flight source fetch was blocked: {exc}"],
                missing_fields=_flight_missing_fields(),
            )

        notes.extend(fetch_notes)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / "source.html"
        html_path.write_text(html[:500_000], encoding="utf-8")
        text = _page_text(html)
        text_path = artifact_dir / "source-text.txt"
        text_path.write_text(text[:80_000], encoding="utf-8")
        observations = _extract_flight_observations(
            text,
            request=request,
            evidence_refs=[str(html_path), str(text_path), final_url],
        )
        if not observations:
            observations = _flight_context_observations(
                request,
                evidence_refs=[str(html_path), str(text_path), final_url],
            )
        missing = _remaining_flight_fields(observations)
        confidence = _observation_confidence(observations)
        status = (
            SourceResearchStatus.SUCCESS
            if confidence >= 0.68 and len(missing) <= 3
            else SourceResearchStatus.PARTIAL
            if observations
            else SourceResearchStatus.BLOCKED
        )
        artifacts = [
            EvidenceArtifact(
                artifact_type="html",
                label="Fetched flight source HTML snapshot",
                path=str(html_path),
                url=final_url,
            ),
            EvidenceArtifact(
                artifact_type="text",
                label="Extracted flight source visible text",
                path=str(text_path),
                url=final_url,
            ),
        ]
        return _result(
            request,
            adapter=self.capability,
            status=status,
            confidence=confidence,
            observations=observations,
            evidence_artifacts=artifacts,
            notes=notes,
            missing_fields=missing,
        )


class PlaywrightLodgingAdapter:
    """Browser-capable lodging adapter with deterministic HTML extraction fallback.

    The production path is intentionally read-only. In tests, callers can inject a fetcher
    that returns fixture HTML so extraction remains deterministic.
    """

    capability = SourceAdapterCapability.PLAYWRIGHT

    def __init__(
        self,
        *,
        fetcher: HtmlFetcher | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._fetcher = fetcher or _fetch_html
        self._custom_fetcher = fetcher is not None
        self._timeout = timeout_seconds or config.SOURCE_RESEARCH_TIMEOUT_SECONDS

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return request.category == ShortlistCategory.LODGING.value and bool(request.source_url)

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        notes = [
            "Read-only lodging source extraction; no booking, login, payment, or cart action attempted."
        ]
        try:
            if (
                config.SOURCE_RESEARCH_PLAYWRIGHT_ENABLED
                and not self._custom_fetcher
                and shutil.which("npx") is not None
            ):
                html, final_url, fetch_notes = _fetch_html_with_playwright(
                    request.source_url,
                    self._timeout,
                )
            else:
                html, final_url, fetch_notes = self._fetcher(request.source_url, self._timeout)
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.BLOCKED,
                confidence=0.2,
                notes=[*notes, f"Playwright/HTML source fetch was blocked: {exc}"],
                missing_fields=_lodging_missing_fields(),
            )

        notes.extend(fetch_notes)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / "source.html"
        html_path.write_text(html[:500_000], encoding="utf-8")
        text = _page_text(html)
        text_path = artifact_dir / "source-text.txt"
        text_path.write_text(text[:80_000], encoding="utf-8")
        observations = _extract_lodging_observations(
            text,
            request=request,
            evidence_refs=[str(html_path), str(text_path), final_url],
        )
        missing = _remaining_lodging_fields(observations)
        confidence = _observation_confidence(observations)
        status = (
            SourceResearchStatus.SUCCESS
            if confidence >= 0.68 and len(missing) <= 2
            else SourceResearchStatus.PARTIAL
            if observations
            else SourceResearchStatus.BLOCKED
        )
        artifacts = [
            EvidenceArtifact(
                artifact_type="html",
                label="Fetched source HTML snapshot",
                path=str(html_path),
                url=final_url,
            ),
            EvidenceArtifact(
                artifact_type="text",
                label="Extracted visible text snapshot",
                path=str(text_path),
                url=final_url,
            ),
        ]
        return _result(
            request,
            adapter=self.capability,
            status=status,
            confidence=confidence,
            observations=observations,
            evidence_artifacts=artifacts,
            notes=notes,
            missing_fields=missing,
        )


class PlaywrightActivityAdapter:
    """Browser-capable activity adapter for price, schedule, and inventory signals."""

    capability = SourceAdapterCapability.PLAYWRIGHT

    def __init__(
        self,
        *,
        fetcher: HtmlFetcher | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._fetcher = fetcher or _fetch_html
        self._custom_fetcher = fetcher is not None
        self._timeout = timeout_seconds or config.SOURCE_RESEARCH_TIMEOUT_SECONDS

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return request.category == ShortlistCategory.ACTIVITIES.value and bool(request.source_url)

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        notes = [
            "Read-only activity source extraction; no booking, login, payment, or cart action attempted."
        ]
        try:
            if (
                config.SOURCE_RESEARCH_PLAYWRIGHT_ENABLED
                and not self._custom_fetcher
                and shutil.which("npx") is not None
            ):
                html, final_url, fetch_notes = _fetch_html_with_playwright(
                    request.source_url,
                    self._timeout,
                )
            else:
                html, final_url, fetch_notes = self._fetcher(request.source_url, self._timeout)
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.BLOCKED,
                confidence=0.2,
                notes=[*notes, f"Activity source fetch was blocked: {exc}"],
                missing_fields=_activity_missing_fields(),
            )

        notes.extend(fetch_notes)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / "source.html"
        html_path.write_text(html[:500_000], encoding="utf-8")
        text = _page_text(html)
        text_path = artifact_dir / "source-text.txt"
        text_path.write_text(text[:80_000], encoding="utf-8")
        observations = _extract_activity_observations(
            text,
            request=request,
            evidence_refs=[str(html_path), str(text_path), final_url],
        )
        missing = _remaining_activity_fields(observations)
        confidence = _observation_confidence(observations)
        status = (
            SourceResearchStatus.SUCCESS
            if confidence >= 0.62 and len(missing) <= 2
            else SourceResearchStatus.PARTIAL
            if observations
            else SourceResearchStatus.BLOCKED
        )
        artifacts = [
            EvidenceArtifact(
                artifact_type="html",
                label="Fetched activity source HTML snapshot",
                path=str(html_path),
                url=final_url,
            ),
            EvidenceArtifact(
                artifact_type="text",
                label="Extracted activity source visible text",
                path=str(text_path),
                url=final_url,
            ),
        ]
        return _result(
            request,
            adapter=self.capability,
            status=status,
            confidence=confidence,
            observations=observations,
            evidence_artifacts=artifacts,
            notes=notes,
            missing_fields=missing,
        )


class PlaywrightCarAdapter:
    """Browser-capable car rental adapter for price, seats, and transmission signals."""

    capability = SourceAdapterCapability.PLAYWRIGHT

    def __init__(
        self,
        *,
        fetcher: HtmlFetcher | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._fetcher = fetcher or _fetch_html
        self._custom_fetcher = fetcher is not None
        self._timeout = timeout_seconds or config.SOURCE_RESEARCH_TIMEOUT_SECONDS

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return request.category == ShortlistCategory.CARS.value and bool(request.source_url)

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        notes = [
            "Read-only car rental source extraction; no booking, login, payment, or cart action attempted."
        ]
        try:
            if (
                config.SOURCE_RESEARCH_PLAYWRIGHT_ENABLED
                and not self._custom_fetcher
                and shutil.which("npx") is not None
            ):
                html, final_url, fetch_notes = _fetch_html_with_playwright(
                    request.source_url,
                    self._timeout,
                )
            else:
                html, final_url, fetch_notes = self._fetcher(request.source_url, self._timeout)
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.BLOCKED,
                confidence=0.2,
                notes=[*notes, f"Car rental source fetch was blocked: {exc}"],
                missing_fields=_car_missing_fields(),
            )

        notes.extend(fetch_notes)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / "source.html"
        html_path.write_text(html[:500_000], encoding="utf-8")
        text = _page_text(html)
        text_path = artifact_dir / "source-text.txt"
        text_path.write_text(text[:80_000], encoding="utf-8")
        observations = _extract_car_observations(
            text,
            request=request,
            evidence_refs=[str(html_path), str(text_path), final_url],
        )
        missing = _remaining_car_fields(observations)
        confidence = _observation_confidence(observations)
        status = (
            SourceResearchStatus.SUCCESS
            if confidence >= 0.62 and len(missing) <= 3
            else SourceResearchStatus.PARTIAL
            if observations
            else SourceResearchStatus.BLOCKED
        )
        artifacts = [
            EvidenceArtifact(
                artifact_type="html",
                label="Fetched car rental source HTML snapshot",
                path=str(html_path),
                url=final_url,
            ),
            EvidenceArtifact(
                artifact_type="text",
                label="Extracted car rental source visible text",
                path=str(text_path),
                url=final_url,
            ),
        ]
        return _result(
            request,
            adapter=self.capability,
            status=status,
            confidence=confidence,
            observations=observations,
            evidence_artifacts=artifacts,
            notes=notes,
            missing_fields=missing,
        )


OpenClawRunner = Callable[..., "subprocess.CompletedProcess[str]"]
OpenClawGatewayProbe = Callable[[], bool]


class OpenClawResearchAdapter:
    capability = SourceAdapterCapability.OPENCLAW

    def __init__(
        self,
        *,
        command: str | None = None,
        gateway_url: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
        runner: OpenClawRunner | None = None,
        gateway_probe: OpenClawGatewayProbe | None = None,
    ) -> None:
        self._command = command or config.OPENCLAW_COMMAND
        self._gateway_url = gateway_url or config.OPENCLAW_GATEWAY_URL
        self._agent_id = config.OPENCLAW_AGENT_ID
        self._timeout = timeout_seconds or config.SOURCE_RESEARCH_TIMEOUT_SECONDS
        self._enabled = config.SOURCE_RESEARCH_OPENCLAW_ENABLED if enabled is None else enabled
        self._runner: OpenClawRunner = runner or subprocess.run
        self._gateway_probe: OpenClawGatewayProbe = gateway_probe or self._gateway_is_live

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return (
            request.category
            in {
                ShortlistCategory.LODGING.value,
                ShortlistCategory.FLIGHTS.value,
                ShortlistCategory.CARS.value,
                ShortlistCategory.ACTIVITIES.value,
            }
            and self._enabled
            and bool(request.source_url)
            and shutil.which(self._command) is not None
            and self._gateway_probe()
        )

    def research(
        self,
        request: SourceResearchRequest,
        *,
        artifact_dir: Path,
    ) -> SourceResearchResult:
        prompt = _openclaw_prompt(request)
        started = datetime.utcnow()
        try:
            completed = self._runner(  # noqa: S603 - configured local OpenClaw command only
                [
                    self._command,
                    "agent",
                    "--agent",
                    self._agent_id,
                    "--local",
                    "--json",
                    "--message",
                    prompt,
                    "--timeout",
                    str(int(self._timeout)),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout + 5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.BLOCKED,
                started_at=started,
                confidence=0.15,
                notes=[f"OpenClaw invocation failed: {exc}"],
                missing_fields=_missing_fields_for_category(request.category),
            )

        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = artifact_dir / "openclaw-output.json"
        transcript_path.write_text(
            json.dumps(
                {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            return _result(
                request,
                adapter=self.capability,
                status=SourceResearchStatus.FAILED,
                started_at=started,
                confidence=0.2,
                evidence_artifacts=[
                    EvidenceArtifact(
                        artifact_type="openclaw-transcript",
                        label="OpenClaw failed transcript",
                        path=str(transcript_path),
                    )
                ],
                notes=[f"OpenClaw exited with {completed.returncode}.", completed.stderr[:500]],
                missing_fields=_missing_fields_for_category(request.category),
            )

        observations, notes = _parse_openclaw_observations(completed.stdout, request)
        confidence = _observation_confidence(observations)
        return _result(
            request,
            adapter=self.capability,
            status=SourceResearchStatus.PARTIAL if observations else SourceResearchStatus.BLOCKED,
            started_at=started,
            confidence=confidence,
            observations=observations,
            evidence_artifacts=[
                EvidenceArtifact(
                    artifact_type="openclaw-transcript",
                    label="OpenClaw JSON transcript",
                    path=str(transcript_path),
                )
            ],
            notes=[
                "OpenClaw was used as an optional read-only browser-agent fallback.",
                *notes,
            ],
            missing_fields=_remaining_fields_for_category(request.category, observations),
        )

    def _gateway_is_live(self) -> bool:
        url = self._gateway_url.rstrip("/") + "/health"
        try:
            request = Request(url, headers={"User-Agent": "Trippy/0.2 OpenClaw health"})
            with urlopen(request, timeout=2) as response:  # noqa: S310 - localhost health probe
                return 200 <= int(getattr(response, "status", 200)) < 400
        except (HTTPError, URLError, OSError, TimeoutError, ValueError):
            return False


def _request_for_lodging_option(
    state: ResearchShortlistState,
    option: Any,
    mode: SourceResearchMode,
) -> SourceResearchRequest:
    return SourceResearchRequest(
        trip_id=state.trip_id,
        category=state.category.value,
        option_id=str(option.option_id),
        source_name=str(option.source),
        source_url=str(option.deep_link),
        source_type=str(
            option.validation.source_type.value if option.validation else "live_search"
        ),
        query=" ".join(
            item
            for item in [
                str(option.name),
                str(option.location_area),
                str(option.island_or_region),
                str(option.room_layout),
                str(option.bed_layout),
            ]
            if item
        ),
        candidate_name=str(option.name),
        adapter_mode=mode,
        context=option.model_dump(mode="json"),
    )


def _request_for_flight_option(
    state: ResearchShortlistState,
    option: Any,
    mode: SourceResearchMode,
) -> SourceResearchRequest:
    return SourceResearchRequest(
        trip_id=state.trip_id,
        category=state.category.value,
        option_id=str(option.option_id),
        source_name=str(option.booking_source),
        source_url=str(option.deep_link),
        source_type=str(
            option.validation.source_type.value if option.validation else "live_search"
        ),
        query=" ".join(
            item
            for item in [
                str(option.airline),
                str(option.departure_airport),
                str(option.arrival_airport),
                str(option.total_travel_duration),
                str(option.layover_duration or ""),
                " ".join(str(airport) for airport in option.layover_airports),
            ]
            if item
        ),
        candidate_name=str(option.airline),
        adapter_mode=mode,
        context=option.model_dump(mode="json"),
    )


def _request_for_activity_option(
    state: ResearchShortlistState,
    option: Any,
    mode: SourceResearchMode,
) -> SourceResearchRequest:
    return SourceResearchRequest(
        trip_id=state.trip_id,
        category=state.category.value,
        option_id=str(option.option_id),
        source_name=str(option.source),
        source_url=str(option.deep_link),
        source_type=str(
            option.validation.source_type.value if option.validation else "live_search"
        ),
        query=" ".join(
            item
            for item in [
                str(option.activity_name),
                str(option.island_location),
                str(option.duration),
                str(option.age_family_fit),
            ]
            if item
        ),
        candidate_name=str(option.activity_name),
        adapter_mode=mode,
        context=option.model_dump(mode="json"),
    )


def _request_for_car_option(
    state: ResearchShortlistState,
    option: Any,
    mode: SourceResearchMode,
) -> SourceResearchRequest:
    return SourceResearchRequest(
        trip_id=state.trip_id,
        category=state.category.value,
        option_id=str(option.option_id),
        source_name=str(option.booking_source),
        source_url=str(option.deep_link),
        source_type=str(
            option.validation.source_type.value if option.validation else "live_search"
        ),
        query=" ".join(
            item
            for item in [
                str(option.vehicle_class),
                str(option.pickup_location),
                str(option.dropoff_location),
            ]
            if item
        ),
        candidate_name=str(option.vehicle_class),
        adapter_mode=mode,
        context=option.model_dump(mode="json"),
    )


def _apply_lodging_observations(option: Any, result: SourceResearchResult, *, run_id: str) -> None:
    validation: SourceValidation = option.validation or SourceValidation()
    previous_fields = _clean_lodging_extracted_fields(validation.extracted_fields)
    _clear_invalid_lodging_bed_state(option)
    validation.adapter_used = result.adapter_used.value
    validation.research_run_id = run_id
    validation.verified_at = result.ended_at
    validation.evidence_url = result.request.source_url or validation.evidence_url
    validation.evidence_artifacts = result.evidence_artifacts
    validation.extracted_fields = previous_fields | {
        observation.field: observation.value for observation in result.observations
    }
    _preserve_lodging_price_evidence(option, validation)
    validation.notes = _dedupe_notes(
        [
            *validation.notes,
            *result.notes,
            "Deep source research extracts evidence only; final inventory, fees, and booking terms still need human review before purchase.",
        ]
    )
    missing_fields = set(result.missing_fields)
    if validation.extracted_fields.get("price_signal") or validation.extracted_fields.get("total_price"):
        missing_fields.discard("final_total_price")
    validation.missing_fields = sorted(missing_fields)
    validation.confidence = max(validation.confidence, result.confidence)
    validation.price_status = (
        PriceStatus.LIVE_SIGNAL
        if "price_signal" in validation.extracted_fields
        else validation.price_status
    )
    validation.availability_status = (
        AvailabilityStatus.AVAILABILITY_SIGNAL
        if "availability_signal" in validation.extracted_fields
        else validation.availability_status
    )
    if result.status == SourceResearchStatus.SUCCESS:
        validation.verification_status = VerificationStatus.LIVE_VERIFIED
        validation.freshness_status = FreshnessStatus.CURRENT
        option.row_status = ShortlistRowStatus.VERIFIED_LIVE
        option.live_data_status = LiveDataStatus.LIVE_VERIFIED
    elif result.status == SourceResearchStatus.PARTIAL:
        if result.adapter_used == SourceAdapterCapability.LINK:
            validation.verification_status = VerificationStatus.MANUAL_REQUIRED
            validation.freshness_status = FreshnessStatus.UNKNOWN
            option.row_status = ShortlistRowStatus.RESEARCHED
            option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED
        else:
            validation.verification_status = VerificationStatus.PARTIAL
            validation.freshness_status = FreshnessStatus.CURRENT
            option.row_status = (
                ShortlistRowStatus.VERIFIED_LIVE
                if result.confidence >= 0.45
                else ShortlistRowStatus.RESEARCHED
            )
            option.live_data_status = LiveDataStatus.PARTIAL
    else:
        validation.verification_status = VerificationStatus.FAILED
        option.row_status = ShortlistRowStatus.RESEARCHED
        option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED

    observations = validation.extracted_fields
    if isinstance(observations.get("price_signal"), str):
        option.current_price_signal = str(observations["price_signal"])
        option.price_band = str(observations["price_signal"])
    if isinstance(observations.get("availability_signal"), str):
        option.current_availability_signal = str(observations["availability_signal"])
    if isinstance(observations.get("bed_layout_signal"), str):
        option.bed_layout = str(observations["bed_layout_signal"])
    if isinstance(observations.get("min_three_beds_satisfied"), bool):
        option.min_three_beds_satisfied = bool(observations["min_three_beds_satisfied"])
        if observations["min_three_beds_satisfied"] is True:
            option.traveler_roster_supported = True
            if option.family_of_five_fit is not False:
                option.family_of_five_fit = True
    if isinstance(observations.get("king_bed_preference_satisfied"), bool):
        option.king_bed_preference_satisfied = bool(observations["king_bed_preference_satisfied"])
    if isinstance(observations.get("parking_signal"), str):
        option.parking_practicality = str(observations["parking_signal"])
    if isinstance(observations.get("cancellation_signal"), str):
        option.cancellation_notes = str(observations["cancellation_signal"])
    option.bed_layout_confidence = max(option.bed_layout_confidence, min(result.confidence, 0.9))
    option.fit_category = _updated_fit_category(option)
    option.validation = validation


def _preserve_lodging_price_evidence(option: Any, validation: SourceValidation) -> None:
    """Keep earlier API/search price signals when a follow-up source page is sparse.

    Booking.com and some hotel sites often return a challenge or shell page to Firecrawl/
    browser fetches. That follow-up should not erase an existing SerpAPI/Google Hotels
    rate signal, but the value remains a live signal rather than purchase-ready proof.
    """
    if validation.extracted_fields.get("price_signal") or validation.extracted_fields.get("total_price"):
        return
    for value in (
        getattr(option, "price_band", ""),
        getattr(option, "current_price_signal", ""),
        str(getattr(option, "validation", SourceValidation()).extracted_fields.get("total_rate", "")),
        str(getattr(option, "validation", SourceValidation()).extracted_fields.get("rate_per_night", "")),
    ):
        price = _extract_price(str(value))
        if price and not _placeholder_price_text(str(value)):
            validation.extracted_fields["price_signal"] = str(value).strip()
            validation.notes = _dedupe_notes(
                [
                    *validation.notes,
                    "Preserved prior live price signal because follow-up source research did not expose a new total.",
                ]
            )
            return


def _clean_lodging_extracted_fields(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(fields)
    bed_signal = cleaned.get("bed_layout_signal")
    if isinstance(bed_signal, str) and _invalid_bed_layout_signal(bed_signal):
        cleaned.pop("bed_layout_signal", None)
        cleaned.pop("min_three_beds_satisfied", None)
    return cleaned


def _clear_invalid_lodging_bed_state(option: Any) -> None:
    bed_layout = str(getattr(option, "bed_layout", "") or "")
    if not _invalid_bed_layout_signal(bed_layout):
        return
    option.bed_layout = "bed layout not confirmed yet"
    option.min_three_beds_satisfied = None
    option.traveler_roster_supported = None
    option.bed_layout_confidence = min(float(getattr(option, "bed_layout_confidence", 0.35)), 0.35)


def _apply_flight_observations(option: Any, result: SourceResearchResult, *, run_id: str) -> None:
    validation: SourceValidation = option.validation or SourceValidation()
    validation.adapter_used = result.adapter_used.value
    validation.research_run_id = run_id
    validation.verified_at = result.ended_at
    validation.evidence_url = result.request.source_url or validation.evidence_url
    validation.evidence_artifacts = result.evidence_artifacts
    validation.extracted_fields = {
        observation.field: observation.value for observation in result.observations
    }
    validation.notes = _dedupe_notes(
        [
            *validation.notes,
            *result.notes,
            "Flight source research extracts evidence only; final fare, seats, baggage, and schedule can change before booking.",
        ]
    )
    validation.missing_fields = sorted(set(result.missing_fields))
    validation.confidence = max(validation.confidence, result.confidence)
    validation.price_status = (
        PriceStatus.LIVE_SIGNAL
        if "price_signal" in validation.extracted_fields
        else validation.price_status
    )
    validation.availability_status = (
        AvailabilityStatus.AVAILABILITY_SIGNAL
        if "availability_signal" in validation.extracted_fields
        else validation.availability_status
    )
    if result.status == SourceResearchStatus.SUCCESS:
        validation.verification_status = VerificationStatus.LIVE_VERIFIED
        validation.freshness_status = FreshnessStatus.CURRENT
        option.row_status = ShortlistRowStatus.VERIFIED_LIVE
        option.live_data_status = LiveDataStatus.LIVE_VERIFIED
    elif result.status == SourceResearchStatus.PARTIAL:
        if result.adapter_used == SourceAdapterCapability.LINK:
            validation.verification_status = VerificationStatus.MANUAL_REQUIRED
            validation.freshness_status = FreshnessStatus.UNKNOWN
            option.row_status = ShortlistRowStatus.RESEARCHED
            option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED
        else:
            validation.verification_status = VerificationStatus.PARTIAL
            validation.freshness_status = FreshnessStatus.CURRENT
            option.row_status = (
                ShortlistRowStatus.VERIFIED_LIVE
                if result.confidence >= 0.45
                else ShortlistRowStatus.RESEARCHED
            )
            option.live_data_status = LiveDataStatus.PARTIAL
    else:
        validation.verification_status = VerificationStatus.FAILED
        option.row_status = ShortlistRowStatus.RESEARCHED
        option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED

    observations = validation.extracted_fields
    if isinstance(observations.get("airline"), str):
        option.airline = str(observations["airline"])
    if isinstance(observations.get("flight_numbers"), list):
        option.flight_numbers = [str(value) for value in observations["flight_numbers"]]
    if isinstance(observations.get("departure_date"), str):
        option.departure_date = str(observations["departure_date"])
    if isinstance(observations.get("arrival_date"), str):
        option.arrival_date = str(observations["arrival_date"])
    if isinstance(observations.get("departure_time"), str):
        option.departure_time = str(observations["departure_time"])
    if isinstance(observations.get("arrival_time"), str):
        option.arrival_time = str(observations["arrival_time"])
    if isinstance(observations.get("total_duration"), str):
        option.total_travel_duration = str(observations["total_duration"])
    if isinstance(observations.get("stops"), int):
        option.stops = int(observations["stops"])
    if isinstance(observations.get("layover_airports"), list):
        option.layover_airports = [str(value) for value in observations["layover_airports"]]
    if isinstance(observations.get("layover_duration"), str):
        option.layover_duration = str(observations["layover_duration"])
    if isinstance(observations.get("price_signal"), str):
        option.fare_estimate_cad = str(observations["price_signal"])
        option.price_band = str(observations["price_signal"])
    notes = []
    if isinstance(observations.get("cabin_signal"), str):
        notes.append(str(observations["cabin_signal"]))
    if isinstance(observations.get("baggage_signal"), str):
        notes.append(str(observations["baggage_signal"]))
    if notes:
        option.baggage_cabin_notes = " ".join(notes)
    option.friction_flags = _dedupe_notes([*option.friction_flags, *_flight_timing_flags(option)])
    if "departure_time" in observations or "arrival_time" in observations:
        option.tradeoffs = _dedupe_notes(
            [
                *option.tradeoffs,
                "Observed timing should be checked against lodging check-in, car pickup, and first-day pacing.",
            ]
        )
    option.validation = validation


def _apply_activity_observations(option: Any, result: SourceResearchResult, *, run_id: str) -> None:
    validation: SourceValidation = option.validation or SourceValidation()
    validation.adapter_used = result.adapter_used.value
    validation.research_run_id = run_id
    validation.verified_at = result.ended_at
    validation.evidence_url = result.request.source_url or validation.evidence_url
    validation.evidence_artifacts = result.evidence_artifacts
    validation.extracted_fields = {
        observation.field: observation.value for observation in result.observations
    }
    validation.notes = _dedupe_notes(
        [
            *validation.notes,
            *result.notes,
            "Activity source research extracts evidence only; final times, inventory, pickup, and booking terms can change before purchase.",
        ]
    )
    validation.missing_fields = sorted(set(result.missing_fields))
    validation.confidence = max(validation.confidence, result.confidence)
    validation.price_status = (
        PriceStatus.LIVE_SIGNAL
        if "price_signal" in validation.extracted_fields
        else validation.price_status
    )
    validation.availability_status = (
        AvailabilityStatus.AVAILABILITY_SIGNAL
        if "availability_signal" in validation.extracted_fields
        else validation.availability_status
    )
    if result.status == SourceResearchStatus.SUCCESS:
        validation.verification_status = VerificationStatus.LIVE_VERIFIED
        validation.freshness_status = FreshnessStatus.CURRENT
        option.row_status = ShortlistRowStatus.VERIFIED_LIVE
        option.live_data_status = LiveDataStatus.LIVE_VERIFIED
    elif result.status == SourceResearchStatus.PARTIAL:
        if result.adapter_used == SourceAdapterCapability.LINK:
            validation.verification_status = VerificationStatus.MANUAL_REQUIRED
            validation.freshness_status = FreshnessStatus.UNKNOWN
            option.row_status = ShortlistRowStatus.RESEARCHED
            option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED
        else:
            validation.verification_status = VerificationStatus.PARTIAL
            validation.freshness_status = FreshnessStatus.CURRENT
            option.row_status = (
                ShortlistRowStatus.VERIFIED_LIVE
                if result.confidence >= 0.45
                else ShortlistRowStatus.RESEARCHED
            )
            option.live_data_status = LiveDataStatus.PARTIAL
    else:
        validation.verification_status = VerificationStatus.FAILED
        option.row_status = ShortlistRowStatus.RESEARCHED
        option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED

    observations = validation.extracted_fields
    if isinstance(observations.get("price_signal"), str):
        option.price_band = str(observations["price_signal"])
    if isinstance(observations.get("duration_signal"), str):
        option.duration = str(observations["duration_signal"])
    if isinstance(observations.get("start_time"), str):
        option.suggested_start_time = str(observations["start_time"])
    if isinstance(observations.get("end_time"), str):
        option.suggested_end_time = str(observations["end_time"])
    if isinstance(observations.get("rating_summary"), str):
        option.review_safety_signal = str(observations["rating_summary"])
    if isinstance(observations.get("group_size_signal"), str):
        option.group_size_signal = str(observations["group_size_signal"])
    if isinstance(observations.get("availability_signal"), str):
        option.confidence_notes = _dedupe_notes(
            [*option.confidence_notes, str(observations["availability_signal"])]
        )
    option.validation = validation


def _apply_car_observations(option: Any, result: SourceResearchResult, *, run_id: str) -> None:
    validation: SourceValidation = option.validation or SourceValidation()
    validation.adapter_used = result.adapter_used.value
    validation.research_run_id = run_id
    validation.verified_at = result.ended_at
    validation.evidence_url = result.request.source_url or validation.evidence_url
    validation.evidence_artifacts = result.evidence_artifacts
    validation.extracted_fields = {
        observation.field: observation.value for observation in result.observations
    }
    validation.notes = _dedupe_notes(
        [
            *validation.notes,
            *result.notes,
            "Car source research extracts evidence only; final vehicle, transmission, fees, deposit, and insurance still need confirmation before booking.",
        ]
    )
    validation.missing_fields = sorted(set(result.missing_fields))
    validation.confidence = max(validation.confidence, result.confidence)
    validation.price_status = (
        PriceStatus.LIVE_SIGNAL
        if "price_signal" in validation.extracted_fields
        or "total_price" in validation.extracted_fields
        else validation.price_status
    )
    validation.availability_status = (
        AvailabilityStatus.AVAILABILITY_SIGNAL
        if "availability_signal" in validation.extracted_fields
        else validation.availability_status
    )
    if result.status == SourceResearchStatus.SUCCESS:
        validation.verification_status = VerificationStatus.LIVE_VERIFIED
        validation.freshness_status = FreshnessStatus.CURRENT
        option.row_status = ShortlistRowStatus.VERIFIED_LIVE
        option.live_data_status = LiveDataStatus.LIVE_VERIFIED
    elif result.status == SourceResearchStatus.PARTIAL:
        if result.adapter_used == SourceAdapterCapability.LINK:
            validation.verification_status = VerificationStatus.MANUAL_REQUIRED
            validation.freshness_status = FreshnessStatus.UNKNOWN
            option.row_status = ShortlistRowStatus.RESEARCHED
            option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED
        else:
            validation.verification_status = VerificationStatus.PARTIAL
            validation.freshness_status = FreshnessStatus.CURRENT
            option.row_status = (
                ShortlistRowStatus.VERIFIED_LIVE
                if result.confidence >= 0.45
                else ShortlistRowStatus.RESEARCHED
            )
            option.live_data_status = LiveDataStatus.PARTIAL
    else:
        validation.verification_status = VerificationStatus.FAILED
        option.row_status = ShortlistRowStatus.RESEARCHED
        option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED

    observations = validation.extracted_fields
    price_signal = observations.get("total_price") or observations.get("price_signal")
    if isinstance(price_signal, str) and price_signal:
        option.current_price_signal = price_signal
        option.price_band = price_signal
    if isinstance(observations.get("vehicle_model_example"), str):
        option.vehicle_class = (
            f"{option.vehicle_class} ({observations['vehicle_model_example']})"
            if observations["vehicle_model_example"] not in option.vehicle_class
            else option.vehicle_class
        )
    image_url = observations.get("image_url") or observations.get("photo_url")
    if isinstance(image_url, str) and image_url.startswith("http"):
        current_photos = list(getattr(option, "photo_urls", []) or [])
        if image_url not in current_photos:
            option.photo_urls = [image_url, *current_photos][:6]
    if isinstance(observations.get("seats"), int):
        option.seating_capacity = int(observations["seats"])
    if isinstance(observations.get("cancellation_signal"), str):
        option.cancellation_notes = str(observations["cancellation_signal"])
    fees_parts: list[str] = []
    if isinstance(observations.get("transmission_signal"), str):
        fees_parts.append(f"transmission: {observations['transmission_signal']}")
    if isinstance(observations.get("insurance_signal"), str):
        fees_parts.append(f"insurance: {observations['insurance_signal']}")
    if isinstance(observations.get("fees_signal"), str):
        fees_parts.append(f"fees: {observations['fees_signal']}")
    if fees_parts:
        option.fees_caution = "; ".join([option.fees_caution, *fees_parts]).strip("; ")
    if isinstance(observations.get("luggage_capacity"), str):
        option.luggage_fit = (
            f"{option.luggage_fit} | extracted luggage: {observations['luggage_capacity']}"
        )
    if isinstance(observations.get("availability_signal"), str):
        option.confidence_notes = _dedupe_notes(
            [*option.confidence_notes, str(observations["availability_signal"])]
        )
    option.validation = validation


def _updated_fit_category(option: Any) -> LodgingFitCategory:
    if (
        option.min_three_beds_satisfied is True
        and option.king_bed_preference_satisfied is True
        and option.traveler_roster_supported is True
    ):
        return LodgingFitCategory.PREFERRED
    if option.min_three_beds_satisfied is True and option.traveler_roster_supported is True:
        return LodgingFitCategory.COMFORTABLE
    if option.traveler_roster_supported is False or option.min_three_beds_satisfied is False:
        return LodgingFitCategory.WEAK
    return cast(LodgingFitCategory, option.fit_category)


def _fetch_html(url: str, timeout: float) -> HtmlFetchResult:
    if not url:
        raise ValueError("source URL is required")
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(parsed.path)
        return path.read_text(encoding="utf-8"), url, ["Read local fixture HTML."]
    if parsed.scheme in {"", "."} and Path(url).exists():
        return (
            Path(url).read_text(encoding="utf-8"),
            str(Path(url).resolve()),
            ["Read local fixture HTML."],
        )
    request = Request(
        url,
        headers={
            "User-Agent": "Trippy/0.2 read-only travel research",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-requested source research
        raw = response.read(1_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return (
            raw.decode(charset, errors="replace"),
            response.geturl(),
            [
                "Fetched source HTML snapshot with read-only request.",
                (
                    "Browser extraction can be enabled later with Playwright-specific fetchers; "
                    "this run used deterministic HTML extraction."
                ),
            ],
        )


def _fetch_html_with_playwright(url: str, timeout: float) -> HtmlFetchResult:
    script = """
const { chromium } = require('playwright');
const url = process.argv[1];
const timeout = Number(process.argv[2] || 12000);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout });
  await page.waitForLoadState('networkidle', { timeout }).catch(() => {});
  await page.waitForTimeout(2500);
  const visibleText = await page.evaluate(() => document.body ? document.body.innerText : '');
  const html = await page.content();
  await browser.close();
  process.stdout.write(`${html}<pre id="trippy-visible-text">${visibleText}</pre>`);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""
    completed = subprocess.run(  # noqa: S603 - npx executable is fixed and opt-in
        [
            "npx",
            "--yes",
            "--package",
            "playwright",
            "node",
            "-e",
            script,
            url,
            str(int(timeout * 1000)),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout + 8,
    )
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or "Playwright browser extraction failed")
    return completed.stdout, url, ["Fetched source HTML with opt-in Playwright browser automation."]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def _page_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.parts)


def _extract_lodging_observations(
    text: str,
    *,
    request: SourceResearchRequest,
    evidence_refs: list[str],
) -> list[SourceObservation]:
    cleaned = " ".join(text.split())
    lower = cleaned.lower()
    observations: list[SourceObservation] = []
    price = _extract_price(cleaned)
    if price:
        observations.append(
            _observation("price_signal", price, 0.68, request, evidence_refs, "Visible price text")
        )
    availability = _availability_signal(lower)
    if availability:
        observations.append(
            _observation(
                "availability_signal",
                availability,
                0.58,
                request,
                evidence_refs,
                "Visible availability or booking-language signal",
            )
        )
    bed_signal = _bed_layout_signal(cleaned)
    if bed_signal:
        observations.append(
            _observation(
                "bed_layout_signal",
                bed_signal,
                0.68,
                request,
                evidence_refs,
                "Visible bed/bedroom text",
            )
        )
        observations.append(
            _observation(
                "min_three_beds_satisfied",
                _has_three_bed_signal(lower),
                0.68,
                request,
                evidence_refs,
                "Derived from visible bed/bedroom text",
            )
        )
    if "king" in lower:
        observations.append(
            _observation(
                "king_bed_preference_satisfied",
                True,
                0.7,
                request,
                evidence_refs,
                "Visible king-bed text",
            )
        )
    elif "queen" in lower and "king" not in lower:
        observations.append(
            _observation(
                "king_bed_preference_satisfied",
                False,
                0.45,
                request,
                evidence_refs,
                "Visible queen-bed text without king-bed evidence",
            )
        )
    if "parking" in lower:
        observations.append(
            _observation(
                "parking_signal",
                "parking mentioned by source; verify exact access and fees",
                0.55,
                request,
                evidence_refs,
                "Parking text was visible",
            )
        )
    cancellation = _cancellation_signal(lower)
    if cancellation:
        observations.append(
            _observation("cancellation_signal", cancellation, 0.6, request, evidence_refs)
        )
    location = _location_signal(cleaned, request)
    if location:
        observations.append(_observation("location_signal", location, 0.45, request, evidence_refs))
    return observations


def _extract_flight_observations(
    text: str,
    *,
    request: SourceResearchRequest,
    evidence_refs: list[str],
) -> list[SourceObservation]:
    cleaned = " ".join(text.split())
    lower = cleaned.lower()
    observations: list[SourceObservation] = []
    airline = _airline_signal(cleaned, request)
    if airline:
        observations.append(_observation("airline", airline, 0.62, request, evidence_refs))
    flight_numbers = _flight_numbers(cleaned)
    if flight_numbers:
        observations.append(
            _observation(
                "flight_numbers",
                flight_numbers,
                0.68,
                request,
                evidence_refs,
                "Visible flight-number-like text",
            )
        )
    price = _extract_price(cleaned)
    if price:
        observations.append(
            _observation("price_signal", price, 0.64, request, evidence_refs, "Visible fare text")
        )
    availability = _flight_availability_signal(lower)
    if availability:
        observations.append(
            _observation(
                "availability_signal",
                availability,
                0.5,
                request,
                evidence_refs,
                "Visible flight search/listing availability language",
            )
        )
    departure = _time_signal(cleaned, ["depart", "departure", "leaves", "outbound"])
    arrival = _time_signal(cleaned, ["arrive", "arrival", "lands"])
    departure_date = _date_signal(cleaned, ["depart", "departure", "outbound", "leaves"])
    arrival_date = _date_signal(cleaned, ["arrive", "arrival", "lands"])
    if not departure or not arrival:
        paired_departure, paired_arrival = _time_pair_signal(cleaned)
        departure = departure or paired_departure
        arrival = arrival or paired_arrival
    if not departure_date or not arrival_date:
        paired_departure_date, paired_arrival_date = _date_pair_signal(cleaned)
        departure_date = departure_date or paired_departure_date
        arrival_date = arrival_date or paired_arrival_date
    if departure_date:
        observations.append(
            _observation("departure_date", departure_date, 0.6, request, evidence_refs)
        )
    if arrival_date:
        observations.append(_observation("arrival_date", arrival_date, 0.6, request, evidence_refs))
    if departure:
        observations.append(_observation("departure_time", departure, 0.56, request, evidence_refs))
    if arrival:
        observations.append(_observation("arrival_time", arrival, 0.56, request, evidence_refs))
    duration = _duration_signal(cleaned)
    if duration:
        observations.append(_observation("total_duration", duration, 0.58, request, evidence_refs))
    stops = _stops_signal(lower)
    if stops is not None:
        observations.append(_observation("stops", stops, 0.62, request, evidence_refs))
    layover_airports = _layover_airports(cleaned)
    if layover_airports:
        observations.append(
            _observation("layover_airports", layover_airports, 0.55, request, evidence_refs)
        )
    layover_duration = _layover_duration(cleaned)
    if layover_duration:
        observations.append(
            _observation("layover_duration", layover_duration, 0.56, request, evidence_refs)
        )
    cabin = _cabin_signal(lower)
    if cabin:
        observations.append(_observation("cabin_signal", cabin, 0.45, request, evidence_refs))
    baggage = _baggage_signal(lower)
    if baggage:
        observations.append(_observation("baggage_signal", baggage, 0.45, request, evidence_refs))
    return observations


def _extract_activity_observations(
    text: str,
    *,
    request: SourceResearchRequest,
    evidence_refs: list[str],
) -> list[SourceObservation]:
    cleaned = " ".join(text.split())
    lower = cleaned.lower()
    observations: list[SourceObservation] = []
    price = _extract_price(cleaned)
    if price:
        observations.append(
            _observation(
                "price_signal", price, 0.64, request, evidence_refs, "Visible activity price text"
            )
        )
    availability = _activity_availability_signal(lower)
    if availability:
        observations.append(
            _observation(
                "availability_signal",
                availability,
                0.55,
                request,
                evidence_refs,
                "Visible activity booking/availability language",
            )
        )
    start_time = _time_signal(cleaned, ["start", "starts", "departure", "meet", "meeting"])
    end_time = _time_signal(cleaned, ["end", "ends", "return", "finish", "finishes"])
    if not start_time or not end_time:
        paired_start, paired_end = _time_pair_signal(cleaned)
        start_time = start_time or paired_start
        end_time = end_time or paired_end
    if start_time:
        observations.append(_observation("start_time", start_time, 0.56, request, evidence_refs))
    if end_time:
        observations.append(_observation("end_time", end_time, 0.52, request, evidence_refs))
    duration = _duration_signal(cleaned)
    if duration:
        observations.append(_observation("duration_signal", duration, 0.58, request, evidence_refs))
    cancellation = _cancellation_signal(lower)
    if cancellation:
        observations.append(
            _observation("cancellation_signal", cancellation, 0.48, request, evidence_refs)
        )
    group_size = _group_size_signal(cleaned)
    if group_size:
        observations.append(
            _observation("group_size_signal", group_size, 0.5, request, evidence_refs)
        )
    rating = _rating_signal(cleaned)
    if rating:
        observations.append(_observation("rating_summary", rating, 0.52, request, evidence_refs))
    return observations


def _extract_car_observations(
    text: str,
    *,
    request: SourceResearchRequest,
    evidence_refs: list[str],
) -> list[SourceObservation]:
    cleaned = " ".join(text.split())
    lower = cleaned.lower()
    observations: list[SourceObservation] = []
    price = _extract_price(cleaned)
    if price:
        observations.append(
            _observation(
                "total_price", price, 0.64, request, evidence_refs, "Visible car rental price text"
            )
        )
    availability = _car_availability_signal(lower)
    if availability:
        observations.append(
            _observation(
                "availability_signal",
                availability,
                0.55,
                request,
                evidence_refs,
                "Visible car rental booking/availability language",
            )
        )
    transmission = _transmission_signal(lower)
    if transmission:
        observations.append(
            _observation("transmission_signal", transmission, 0.62, request, evidence_refs)
        )
    seats = _seats_signal(cleaned)
    if seats is not None:
        observations.append(_observation("seats", seats, 0.58, request, evidence_refs))
    luggage = _luggage_capacity_signal(cleaned)
    if luggage:
        observations.append(_observation("luggage_capacity", luggage, 0.50, request, evidence_refs))
    model = _vehicle_model_signal(cleaned, request)
    if model:
        observations.append(
            _observation("vehicle_model_example", model, 0.56, request, evidence_refs)
        )
    image_url = _image_url_signal(cleaned)
    if image_url:
        observations.append(_observation("image_url", image_url, 0.42, request, evidence_refs))
    cancellation = _cancellation_signal(lower)
    if cancellation:
        observations.append(
            _observation("cancellation_signal", cancellation, 0.48, request, evidence_refs)
        )
    insurance = _insurance_signal(lower)
    if insurance:
        observations.append(
            _observation("insurance_signal", insurance, 0.45, request, evidence_refs)
        )
    fees = _car_fees_signal(lower)
    if fees:
        observations.append(_observation("fees_signal", fees, 0.48, request, evidence_refs))
    pickup_date = _date_signal(cleaned, ["pick-up", "pickup", "collect", "collection"])
    pickup_time = _time_signal(cleaned, ["pick-up", "pickup", "collect", "collection"])
    if pickup_date or pickup_time:
        observations.append(
            _observation(
                "pickup_datetime",
                f"{pickup_date} {pickup_time}".strip(),
                0.52,
                request,
                evidence_refs,
            )
        )
    dropoff_date = _date_signal(cleaned, ["drop-off", "dropoff", "return", "drop off"])
    dropoff_time = _time_signal(cleaned, ["drop-off", "dropoff", "return", "drop off"])
    if dropoff_date or dropoff_time:
        observations.append(
            _observation(
                "dropoff_datetime",
                f"{dropoff_date} {dropoff_time}".strip(),
                0.52,
                request,
                evidence_refs,
            )
        )
    return observations


def _flight_context_observations(
    request: SourceResearchRequest,
    *,
    evidence_refs: list[str],
) -> list[SourceObservation]:
    """Create low-confidence fallback observations from canonical context/query only.

    These observations preserve usefulness when dynamic source pages block extraction, but the
    low confidence and notes keep Trippy from treating them as live inventory proof.
    """
    context = request.context
    query_text = " ".join(
        [
            request.query,
            request.source_url,
            str(context.get("airline", "")),
            str(context.get("departure_time", "")),
            str(context.get("arrival_time", "")),
            str(context.get("total_travel_duration", "")),
            str(context.get("price_band", "")),
        ]
    )
    observations: list[SourceObservation] = []
    for field in ("departure_time", "arrival_time", "total_travel_duration"):
        value = str(context.get(field, "")).strip()
        if value and "live verify" not in value.lower() and "target " not in value.lower():
            observations.append(
                _observation(
                    "total_duration" if field == "total_travel_duration" else field,
                    value,
                    0.32,
                    request,
                    evidence_refs,
                    "Fallback from canonical candidate context, not live source evidence",
                )
            )
    stops = context.get("stops")
    if isinstance(stops, int):
        observations.append(
            _observation(
                "stops",
                stops,
                0.35,
                request,
                evidence_refs,
                "Fallback from canonical candidate context, not live source evidence",
            )
        )
    for field in ("departure_date", "arrival_date"):
        value = str(context.get(field, "")).strip()
        if value:
            observations.append(
                _observation(
                    field,
                    value,
                    0.32,
                    request,
                    evidence_refs,
                    "Fallback from canonical candidate context, not live source evidence",
                )
            )
    price = _extract_price(query_text)
    if price and not any(observation.field == "price_signal" for observation in observations):
        observations.append(
            _observation(
                "price_signal",
                price,
                0.3,
                request,
                evidence_refs,
                "Fallback price-like text from source URL/query/context, not verified fare evidence",
            )
        )
    return observations


def _observation(
    field: str,
    value: Any,
    confidence: float,
    request: SourceResearchRequest,
    evidence_refs: list[str],
    note: str = "",
) -> SourceObservation:
    return SourceObservation(
        field=field,
        value=value,
        confidence=confidence,
        source_url=request.source_url,
        evidence_refs=evidence_refs,
        notes=[note] if note else [],
    )


def _extract_price(text: str) -> str:
    match = re.search(
        r"(?:(?:CAD|USD|EUR|CA\$|C\$|US\$|\$|€)\s?[\d][\d,]*(?:\.\d{2})?(?:\s?(?:/night|per night|night|total|pp|per person))?)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(0).strip() if match else ""


def _airline_signal(text: str, request: SourceResearchRequest) -> str:
    candidates = [
        str(request.context.get("airline", "")),
        "SATA",
        "Air Canada",
        "TAP Portugal",
        "United",
        "Delta",
        "WestJet",
        "Porter",
        "American Airlines",
        "Lufthansa",
    ]
    lower = text.lower()
    for candidate in candidates:
        value = candidate.strip()
        if value and value.lower() in lower:
            return value
    return ""


def _flight_numbers(text: str) -> list[str]:
    values = []
    for match in re.finditer(
        r"\b(?:AC|TP|S4|SATA|UA|DL|WS|PD|AA|LH)\s?-?\s?\d{2,4}\b",
        text,
        flags=re.IGNORECASE,
    ):
        value = re.sub(r"\s+", "", match.group(0).upper().replace("-", ""))
        if value not in values:
            values.append(value)
    return values[:4]


def _flight_availability_signal(lower: str) -> str:
    if any(term in lower for term in ["sold out", "unavailable", "no flights"]):
        return "unavailable/no-flight signal visible; choose another date or route"
    if any(
        term in lower
        for term in [
            "select",
            "choose",
            "book",
            "view deal",
            "available",
            "round trip",
            "departing",
        ]
    ):
        return "flight result/listing signal visible; final inventory still needs source review"
    return ""


def _activity_availability_signal(lower: str) -> str:
    if any(
        term in lower
        for term in ["sold out", "not available", "unavailable", "no availability", "no tours"]
    ):
        return "unavailable/sold-out signal visible; choose another time, date, or operator"
    if any(
        term in lower
        for term in [
            "check availability",
            "select participants",
            "reserve now",
            "book now",
            "available",
            "free cancellation",
        ]
    ):
        return "booking or availability signal visible; final inventory still needs source review"
    return ""


def _car_availability_signal(lower: str) -> str:
    if any(term in lower for term in ["sold out", "not available", "unavailable", "no cars"]):
        return "unavailable signal visible; choose another date or vehicle category"
    if any(
        term in lower
        for term in ["reserve now", "book now", "available", "free cancellation", "select vehicle"]
    ):
        return "availability/booking signal visible; final inventory still needs source review"
    return ""


def _transmission_signal(lower: str) -> str:
    if "automatic" in lower:
        return "automatic transmission signal visible; verify exact vehicle model"
    if "manual" in lower or "standard" in lower:
        return "manual/standard transmission signal visible; confirm before booking if automatic is required"
    return ""


def _seats_signal(text: str) -> int | None:
    match = re.search(
        r"\b(\d)\s*(?:seat|passenger|pax|adult)s?\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        value = int(match.group(1))
        if 2 <= value <= 9:
            return value
    return None


def _luggage_capacity_signal(text: str) -> str:
    match = re.search(
        r"\b(\d+)\s*(?:large\s+)?(?:bag|suitcase|luggage|case)s?\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return f"{match.group(0).strip()} capacity signal visible; verify exact boot/trunk space"
    if re.search(
        r"\b(?:large\s+suitcase|full\s+size\s+luggage|luggage\s+capacity)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return "luggage capacity language visible; verify exact number of bags"
    return ""


def _vehicle_model_signal(text: str, request: SourceResearchRequest) -> str:
    context = request.context
    vehicle_class = str(context.get("vehicle_class", "")).lower()
    match = re.search(
        r"\b(Toyota\s+\w+|Renault\s+\w+|Volkswagen\s+\w+|VW\s+\w+|Opel\s+\w+|Seat\s+\w+|Ford\s+\w+|Hyundai\s+\w+|Kia\s+\w+|Peugeot\s+\w+|Fiat\s+\w+|Skoda\s+\w+|BMW\s+\w+|Mercedes\s+\w+|Audi\s+\w+|Nissan\s+\w+|Suzuki\s+\w+)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        model = match.group(0).strip()
        if not vehicle_class or vehicle_class.split()[0].lower() in model.lower():
            return model
        return model
    return ""


def _image_url_signal(text: str) -> str:
    match = re.search(r"https?://[^\s\"'<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^\s\"'<>]+)?", text)
    return match.group(0) if match else ""


def _insurance_signal(lower: str) -> str:
    if "collision damage waiver" in lower or "cdw" in lower:
        return "CDW/collision damage waiver language visible; verify what is included and excluded"
    if "theft protection" in lower or "tp" in lower:
        return "theft protection language visible; verify coverage terms"
    if "full insurance" in lower or "full protection" in lower:
        return "full insurance/protection language visible; confirm what is covered"
    if "excess" in lower and "insurance" in lower:
        return "insurance excess language visible; verify deposit and excess reduction terms"
    if "insurance" in lower:
        return "insurance language visible; verify exact coverage, exclusions, and deposit"
    return ""


def _car_fees_signal(lower: str) -> str:
    parts: list[str] = []
    if "airport surcharge" in lower or "airport fee" in lower or "airport tax" in lower:
        parts.append("airport surcharge/fee visible")
    if "young driver" in lower or "additional driver" in lower:
        parts.append("additional/young driver fee language visible")
    if "fuel" in lower and ("policy" in lower or "charge" in lower or "prepaid" in lower):
        parts.append("fuel policy language visible")
    if "gps" in lower or "sat nav" in lower or "navigation" in lower:
        parts.append("GPS/nav add-on language visible")
    if parts:
        return "; ".join(parts) + "; verify all fees in total before booking"
    return ""


def _time_signal(text: str, labels: list[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})(?:ure|s|ing)?\s*(?:time)?\s*(?:at|:|-)?\s*(\d{{1,2}}(?::\d{{2}})?\s?(?:AM|PM|am|pm)?)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _time_pair_signal(text: str) -> tuple[str, str]:
    match = re.search(
        r"\b(\d{1,2}(?::\d{2})?\s?(?:AM|PM|am|pm))\s*(?:-|–|—|to|→)\s*(\d{1,2}(?::\d{2})?\s?(?:AM|PM|am|pm))\b",
        text,
    )
    if match:
        return match.group(1).strip(), match.group(2).strip()
    times = re.findall(r"\b\d{1,2}(?::\d{2})?\s?(?:AM|PM|am|pm)\b", text)
    if len(times) >= 2:
        return times[0].strip(), times[1].strip()
    return "", ""


def _date_signal(text: str, labels: list[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    date_pattern = (
        r"(?:20\d{2}-\d{2}-\d{2})|"
        r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2})|"
        r"(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2})"
    )
    match = re.search(
        rf"(?:{label_pattern})(?:ure|s|ing)?\s*(?:date)?\s*(?:on|:|-)?\s*({date_pattern})",
        text,
        flags=re.IGNORECASE,
    )
    return " ".join(match.group(1).replace(",", "").split()) if match else ""


def _date_pair_signal(text: str) -> tuple[str, str]:
    date_pattern = (
        r"(?:20\d{2}-\d{2}-\d{2})|"
        r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2})|"
        r"(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2})"
    )
    match = re.search(rf"\b({date_pattern})\s*(?:-|–|—|to|→)\s*({date_pattern})\b", text)
    if match:
        return (
            " ".join(match.group(1).replace(",", "").split()),
            " ".join(match.group(2).replace(",", "").split()),
        )
    dates = re.findall(date_pattern, text, flags=re.IGNORECASE)
    if len(dates) >= 2:
        return (
            " ".join(str(dates[0]).replace(",", "").split()),
            " ".join(str(dates[1]).replace(",", "").split()),
        )
    return "", ""


def _duration_signal(text: str) -> str:
    match = re.search(
        r"(?:total\s+duration|duration|travel\s+time)\s*(?:is|:|-)?\s*((?:\d+\s?(?:h|hr|hrs|hour|hours))\s*(?:\d+\s?(?:m|min|mins|minute|minutes))?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b((?:\d+\s?(?:h|hr|hrs|hour|hours))\s*(?:\d+\s?(?:m|min|mins|minute|minutes))?)\b",
            text,
            flags=re.IGNORECASE,
        )
    return " ".join(match.group(1).split()) if match and match.group(1).strip() else ""


def _group_size_signal(text: str) -> str:
    lower = text.lower()
    if "private tour" in lower or "private group" in lower:
        return "private tour/group signal visible"
    match = re.search(
        r"(?:small group|group size|limited to|max(?:imum)?(?: group)?)(?:\s*(?:of|to|:|-))?\s*(\d{1,2})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return f"group size signal visible: {match.group(0).strip()}"
    if "small group" in lower:
        return "small-group signal visible"
    return ""


def _rating_signal(text: str) -> str:
    match = re.search(
        r"\b(\d(?:\.\d)?)(?:\s*/\s*5|\s+out of\s+5)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return f"visible rating {match.group(1)}/5; read recent reviews before booking"
    return ""


def _stops_signal(lower: str) -> int | None:
    if "nonstop" in lower or "non-stop" in lower or "non stop" in lower or "direct flight" in lower:
        return 0
    match = re.search(r"(\d+)\s+stop", lower)
    if match:
        return int(match.group(1))
    return None


def _layover_airports(text: str) -> list[str]:
    values = []
    for match in re.finditer(
        r"(?:layover|connection|connect|via)\s+(?:in|at|through)?\s*([A-Z]{3})\b",
        text,
        flags=re.IGNORECASE,
    ):
        value = match.group(1).upper()
        if value not in values:
            values.append(value)
    return values[:3]


def _layover_duration(text: str) -> str:
    match = re.search(
        r"(?:layover|connection)\s*(?:of|:|-)?\s*((?:\d+\s?(?:h|hr|hrs|hour|hours))\s*(?:\d+\s?(?:m|min|mins|minute|minutes))?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b((?:\d+\s?(?:h|hr|hrs|hour|hours))\s*(?:\d+\s?(?:m|min|mins|minute|minutes))?)\s+(?:layover|connection)\b",
            text,
            flags=re.IGNORECASE,
        )
    return " ".join(match.group(1).split()) if match and match.group(1).strip() else ""


def _cabin_signal(lower: str) -> str:
    if "premium economy" in lower:
        return "premium economy signal visible; verify fare class and seat terms"
    if "business class" in lower:
        return "business class signal visible; verify fare class and refund rules"
    if "economy" in lower:
        return "economy fare/cabin signal visible; verify baggage and seat selection"
    return ""


def _baggage_signal(lower: str) -> str:
    if "checked bag" in lower or "checked baggage" in lower:
        return "checked-bag language visible; verify included count and fees"
    if "carry-on" in lower or "carry on" in lower:
        return "carry-on language visible; verify checked-bag fees before booking"
    if "baggage" in lower:
        return "baggage language visible; verify exact allowance and fees"
    return ""


def _availability_signal(lower: str) -> str:
    if any(
        term in lower
        for term in ["sold out", "not available", "unavailable", "no properties found"]
    ):
        return "unavailable signal visible; do not advance without another date/property"
    if any(term in lower for term in ["reserve", "book now", "availability", "available"]):
        return (
            "availability/search-result signal visible; final inventory still needs source review"
        )
    return ""


def _bed_layout_signal(text: str) -> str:
    snippets: list[str] = []
    for pattern in [
        r"(?:\d+|one|two|three|four)\s+bedrooms?",
        r"(?:\d+|one|two|three|four)[-\s]?bed(?:room)?",
        r"(?:\d+|one|two|three|four)\s+(?:king|queen|double|single|twin|sofa)?\s*beds?",
        r"king\s+bed",
        r"queen\s+bed",
    ]:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(0).strip()
            if not _valid_bed_layout_snippet(value):
                continue
            if value.lower() not in [snippet.lower() for snippet in snippets]:
                snippets.append(value)
            if len(snippets) >= 4:
                break
        if len(snippets) >= 4:
            break
    return "; ".join(snippets)


def _valid_bed_layout_snippet(value: str) -> bool:
    lower = value.lower()
    match = re.match(r"(\d+)\s+bed(?:room)?s?$", lower)
    return not (match and int(match.group(1)) > 8)


def _invalid_bed_layout_signal(value: str) -> bool:
    snippets = [snippet.strip() for snippet in value.split(";") if snippet.strip()]
    if not snippets:
        return False
    return all(not _valid_bed_layout_snippet(snippet) for snippet in snippets)


def _placeholder_price_text(value: str) -> bool:
    lower = value.lower()
    return any(
        marker in lower
        for marker in (
            "live price required",
            "live verify",
            "source price required",
            "price not proven",
            "open listing",
            "?",
        )
    )


def _has_three_bed_signal(lower: str) -> bool:
    positive = [
        "3 bed",
        "three bed",
        "3-bedroom",
        "3 bedroom",
        "three bedroom",
        "4 bed",
        "four bed",
        "4-bedroom",
        "4 bedroom",
        "four bedroom",
    ]
    return any(term in lower for term in positive)


def _cancellation_signal(lower: str) -> str:
    if "free cancellation" in lower:
        return "free cancellation text visible; verify deadline and room/listing terms"
    if "refundable" in lower:
        return "refundable/cancellation text visible; verify deadline and penalties"
    if "non-refundable" in lower or "non refundable" in lower:
        return "non-refundable signal visible; penalize unless upside is exceptional"
    return ""


def _location_signal(text: str, request: SourceResearchRequest) -> str:
    context = request.context
    for key in ("location_area", "island_or_region"):
        value = str(context.get(key, "")).strip()
        if value and value.lower().split("/")[0].strip() in text.lower():
            return f"source text references planned area: {value}"
    return ""


def _remaining_lodging_fields(observations: Iterable[SourceObservation]) -> list[str]:
    found = {observation.field for observation in observations}
    required = set(_lodging_missing_fields())
    mapping = {
        "price_signal": "final_total_price",
        "availability_signal": "exact_availability",
        "cancellation_signal": "cancellation_deadline",
        "bed_layout_signal": "bed_layout",
        "min_three_beds_satisfied": "min_three_beds_satisfied",
        "king_bed_preference_satisfied": "king_bed_preference_satisfied",
        "parking_signal": "parking_access",
    }
    for observation_field, missing_field in mapping.items():
        if observation_field in found:
            required.discard(missing_field)
    return sorted(required)


def _remaining_flight_fields(observations: Iterable[SourceObservation]) -> list[str]:
    found = {observation.field for observation in observations}
    required = set(_flight_missing_fields())
    mapping = {
        "departure_date": "exact_departure_date",
        "arrival_date": "exact_arrival_date",
        "price_signal": "exact_fare",
        "departure_time": "exact_departure_time",
        "arrival_time": "exact_arrival_time",
        "total_duration": "total_duration",
        "flight_numbers": "flight_numbers",
        "baggage_signal": "baggage_terms",
        "cabin_signal": "fare_rules",
    }
    for observation_field, missing_field in mapping.items():
        if observation_field in found:
            required.discard(missing_field)
    return sorted(required)


def _remaining_activity_fields(observations: Iterable[SourceObservation]) -> list[str]:
    found = {observation.field for observation in observations}
    required = set(_activity_missing_fields())
    mapping = {
        "price_signal": "current_price",
        "availability_signal": "exact_availability",
        "start_time": "bookable_time",
        "end_time": "bookable_time",
        "duration_signal": "duration",
        "cancellation_signal": "cancellation_policy",
        "group_size_signal": "group_size",
    }
    for observation_field, missing_field in mapping.items():
        if observation_field in found:
            required.discard(missing_field)
    return sorted(required)


def _remaining_car_fields(observations: Iterable[SourceObservation]) -> list[str]:
    found = {observation.field for observation in observations}
    required = set(_car_missing_fields())
    mapping = {
        "total_price": "total_price",
        "price_signal": "total_price",
        "availability_signal": "exact_availability",
        "seats": "exact_seats",
        "luggage_capacity": "luggage_capacity",
        "transmission_signal": "transmission",
        "vehicle_model_example": "vehicle_model",
        "image_url": "vehicle_image",
        "photo_url": "vehicle_image",
        "cancellation_signal": "cancellation_terms",
        "insurance_signal": "insurance_terms",
        "fees_signal": "fees_breakdown",
        "pickup_datetime": "pickup_datetime",
        "dropoff_datetime": "dropoff_datetime",
    }
    for observation_field, missing_field in mapping.items():
        if observation_field in found:
            required.discard(missing_field)
    return sorted(required)


def _lodging_missing_fields() -> list[str]:
    return [
        "exact_availability",
        "final_total_price",
        "cancellation_deadline",
        "bed_layout",
        "min_three_beds_satisfied",
        "king_bed_preference_satisfied",
        "parking_access",
    ]


def _flight_missing_fields() -> list[str]:
    return [
        "exact_departure_date",
        "exact_arrival_date",
        "flight_numbers",
        "exact_departure_time",
        "exact_arrival_time",
        "total_duration",
        "exact_fare",
        "fare_rules",
        "baggage_terms",
    ]


def _activity_missing_fields() -> list[str]:
    return [
        "exact_availability",
        "current_price",
        "bookable_time",
        "duration",
        "cancellation_policy",
        "group_size",
    ]


def _car_missing_fields() -> list[str]:
    return [
        "total_price",
        "exact_availability",
        "exact_seats",
        "luggage_capacity",
        "transmission",
        "vehicle_model",
        "vehicle_image",
        "cancellation_terms",
        "insurance_terms",
        "fees_breakdown",
        "pickup_datetime",
        "dropoff_datetime",
    ]


def _missing_fields_for_category(category: str) -> list[str]:
    if category == ShortlistCategory.FLIGHTS.value:
        return _flight_missing_fields()
    if category == ShortlistCategory.ACTIVITIES.value:
        return _activity_missing_fields()
    if category == ShortlistCategory.CARS.value:
        return _car_missing_fields()
    return _lodging_missing_fields()


def _remaining_fields_for_category(
    category: str, observations: Iterable[SourceObservation]
) -> list[str]:
    if category == ShortlistCategory.FLIGHTS.value:
        return _remaining_flight_fields(observations)
    if category == ShortlistCategory.ACTIVITIES.value:
        return _remaining_activity_fields(observations)
    if category == ShortlistCategory.CARS.value:
        return _remaining_car_fields(observations)
    return _remaining_lodging_fields(observations)


def _missing_high_value_fields(result: SourceResearchResult) -> bool:
    if result.request.category == ShortlistCategory.FLIGHTS.value:
        return bool(
            {
                "exact_departure_date",
                "exact_departure_time",
                "exact_arrival_date",
                "exact_arrival_time",
                "exact_fare",
            }
            & set(result.missing_fields)
        )
    if result.request.category == ShortlistCategory.ACTIVITIES.value:
        return bool(
            {"current_price", "exact_availability", "bookable_time"} & set(result.missing_fields)
        )
    if result.request.category == ShortlistCategory.CARS.value:
        return bool(
            {"total_price", "exact_seats", "transmission", "cancellation_terms"}
            & set(result.missing_fields)
        )
    return bool(
        {"final_total_price", "bed_layout", "min_three_beds_satisfied"} & set(result.missing_fields)
    )


def _load_friction_context(
    trip_id: str, category: ShortlistCategory
) -> tuple[dict[ShortlistCategory, ResearchShortlistState], int | None]:
    """Best-effort load of complementary state and party size for friction post-processing."""
    complementary: dict[ShortlistCategory, ResearchShortlistState] = {}
    party_size: int | None = None
    try:
        from trippy.services.shortlist_store import ShortlistStore

        store = ShortlistStore()
        for other in (
            ShortlistCategory.FLIGHTS,
            ShortlistCategory.LODGING,
            ShortlistCategory.CARS,
            ShortlistCategory.ACTIVITIES,
        ):
            if other == category:
                continue
            loaded = store.load(trip_id, other)
            if loaded is not None:
                complementary[other] = loaded
    except Exception:
        complementary = {}
    try:
        from trippy.services.trip_intake import TripIntakeService

        intake = TripIntakeService().load(trip_id)
        if intake is not None:
            total = getattr(getattr(intake, "party", None), "total_travelers", None)
            if isinstance(total, int) and total > 0:
                party_size = total
    except Exception:
        party_size = None
    return complementary, party_size


def _flight_timing_flags(option: Any) -> list[str]:
    flags = []
    departure = str(getattr(option, "departure_time", "")).lower()
    arrival = str(getattr(option, "arrival_time", "")).lower()
    layover = str(getattr(option, "layover_duration", "") or "").lower()
    if "early" in departure or re.search(r"\b(?:4|5|6)(?::\d{2})?\s?am\b", departure):
        flags.append("early departure can create sleep and transfer friction")
    if "early" in arrival or re.search(r"\b(?:4|5|6|7|8)(?::\d{2})?\s?am\b", arrival):
        flags.append("early arrival may require prior-night lodging or luggage plan")
    if "late" in arrival or re.search(r"\b(?:10|11)(?::\d{2})?\s?pm\b", arrival):
        flags.append("late arrival can create check-in, car pickup, and first-night access risk")
    if re.search(r"\b(?:0|1)h\b", layover) or "tight" in layover:
        flags.append("layover may be too tight for family luggage and delay protection")
    return flags


def _observation_confidence(observations: list[SourceObservation]) -> float:
    if not observations:
        return 0.0
    return sum(observation.confidence for observation in observations) / len(observations)


def _result(
    request: SourceResearchRequest,
    *,
    adapter: SourceAdapterCapability,
    status: SourceResearchStatus,
    confidence: float,
    observations: list[SourceObservation] | None = None,
    evidence_artifacts: list[EvidenceArtifact] | None = None,
    missing_fields: list[str] | None = None,
    notes: list[str] | None = None,
    started_at: datetime | None = None,
) -> SourceResearchResult:
    return SourceResearchResult(
        request=request,
        adapter_used=adapter,
        status=status,
        started_at=started_at or datetime.utcnow(),
        ended_at=datetime.utcnow(),
        confidence=confidence,
        observations=observations or [],
        evidence_artifacts=evidence_artifacts or [],
        missing_fields=missing_fields or [],
        notes=notes or [],
    )


def _coerce_mode(value: SourceResearchMode | str) -> SourceResearchMode:
    if isinstance(value, SourceResearchMode):
        return value
    return SourceResearchMode(value)


def _new_run_id() -> str:
    return f"research-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _aggregate_status(results: list[SourceResearchResult]) -> str:
    if not results:
        return "skipped"
    statuses = {result.status for result in results}
    if statuses <= {SourceResearchStatus.SUCCESS}:
        return "success"
    if statuses & {SourceResearchStatus.SUCCESS, SourceResearchStatus.PARTIAL}:
        return "partial"
    return "blocked"


def _write_json_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _dedupe_notes(notes: list[str]) -> list[str]:
    deduped: list[str] = []
    for note in notes:
        if note and note not in deduped:
            deduped.append(note)
    return deduped


_OPENCLAW_FIELDS_BY_CATEGORY: dict[str, tuple[str, str]] = {
    ShortlistCategory.FLIGHTS.value: (
        "flight research",
        "airline, flight_numbers, departure_airport, arrival_airport, departure_date, "
        "departure_time, arrival_date, arrival_time, stops, layover_airports, "
        "layover_duration, total_duration, price_signal, availability_signal, "
        "cabin_signal, baggage_signal, source_url, booking_handoff_url, freshness_caveat",
    ),
    ShortlistCategory.LODGING.value: (
        "lodging research",
        "property_name, location_signal, check_in_date, check_out_date, "
        "occupancy_supported, bed_layout_signal, min_three_beds_satisfied, "
        "king_bed_preference_satisfied, room_count, total_price, nightly_price, "
        "price_signal, availability_signal, cancellation_signal, review_score, "
        "review_count, parking_signal, family_fit_signal, source_url, booking_handoff_url",
    ),
    ShortlistCategory.CARS.value: (
        "rental car research",
        "provider, pickup_location, dropoff_location, pickup_datetime, "
        "dropoff_datetime, vehicle_class, vehicle_model_example, seats, "
        "luggage_capacity, transmission_signal, total_price, price_signal, "
        "availability_signal, insurance_signal, fees_signal, cancellation_signal, "
        "image_url, photo_url, source_url, booking_handoff_url",
    ),
    ShortlistCategory.ACTIVITIES.value: (
        "activity research",
        "activity_name, operator, date_signal, start_time, end_time, "
        "duration_signal, location_signal, group_size_signal, age_signal, "
        "fitness_signal, cancellation_signal, price_signal, availability_signal, "
        "review_score, review_count, source_url, booking_handoff_url",
    ),
}


def _openclaw_prompt(request: SourceResearchRequest) -> str:
    category_note, useful_fields = _OPENCLAW_FIELDS_BY_CATEGORY.get(
        request.category,
        _OPENCLAW_FIELDS_BY_CATEGORY[ShortlistCategory.LODGING.value],
    )
    schema = (
        '{"observations":[{"field":"...","value":"...","confidence":0.0,'
        '"source_url":"...","notes":["..."]}],'
        '"ready_to_click":"yes|no|partial","ready_to_click_reason":"...",'
        '"missing_fields":["..."],"warnings":["..."],"notes":["..."]}'
    )
    return (
        f"You are helping Trippy perform read-only {category_note}. "
        "HARD RULES: search and read only. Do NOT log in, do NOT submit forms, "
        "do NOT click 'book' or 'reserve' or 'pay', do NOT add to cart, do NOT start "
        "checkout, do NOT take payment actions, do NOT accept cookies that require account login. "
        "If a step would require any of the above, stop and report what is missing. "
        "Return ONLY valid JSON (no prose, no markdown). "
        f"Use this exact shape: {schema}. "
        "Each observation field must be one of the requested fields below; "
        "value is the literal extracted text or structured value; confidence is 0.0-1.0 "
        "based on how directly the page evidences the value; notes is a short list. "
        "Set ready_to_click to 'yes' only if every fact a buyer needs is on the page right now; "
        "use 'partial' if key facts are present but freshness/price/availability are not pinned; "
        "use 'no' if a click would still leave the buyer guessing. "
        "ready_to_click_reason must explain in one sentence what is or is not pinned. "
        "missing_fields lists requested fields that the page does not directly evidence. "
        "warnings lists any login walls, paywalls, dynamic-pricing notices, or freshness gaps. "
        f"Requested fields: {useful_fields}. "
        f"Source URL: {request.source_url}. Candidate: {request.candidate_name}. "
        f"Context: {json.dumps(request.context, sort_keys=True)[:3000]}"
    )


def _parse_openclaw_observations(
    stdout: str,
    request: SourceResearchRequest,
) -> tuple[list[SourceObservation], list[str]]:
    payload = _extract_json_payload(stdout)
    if payload is None:
        return [], ["OpenClaw output did not contain parseable JSON observations."]
    raw_observations = payload.get("observations", [])
    if not isinstance(raw_observations, list):
        return [], ["OpenClaw JSON did not contain an observations list."]
    observations: list[SourceObservation] = []
    for raw in raw_observations:
        if not isinstance(raw, dict) or "field" not in raw:
            continue
        try:
            confidence = float(raw.get("confidence", 0.45) or 0.45)
        except (TypeError, ValueError):
            confidence = 0.45
        observations.append(
            SourceObservation(
                field=str(raw.get("field", "")),
                value=raw.get("value"),
                confidence=max(0.0, min(1.0, confidence)),
                source_url=str(raw.get("source_url") or request.source_url),
                notes=_raw_notes(raw.get("notes")),
            )
        )
    notes: list[str] = []
    raw_notes = payload.get("notes")
    if isinstance(raw_notes, list):
        notes.extend(str(note) for note in raw_notes if note)
    ready = payload.get("ready_to_click")
    reason = payload.get("ready_to_click_reason")
    if isinstance(ready, str) and ready.strip():
        ready_note = f"OpenClaw ready_to_click={ready.strip().lower()}"
        if isinstance(reason, str) and reason.strip():
            ready_note += f": {reason.strip()}"
        notes.append(ready_note)
    raw_warnings = payload.get("warnings")
    if isinstance(raw_warnings, list):
        for warning in raw_warnings:
            if warning:
                notes.append(f"OpenClaw warning: {warning}")
    raw_missing = payload.get("missing_fields")
    if isinstance(raw_missing, list) and raw_missing:
        joined = ", ".join(str(field) for field in raw_missing if field)
        if joined:
            notes.append(f"OpenClaw reported missing fields: {joined}")
    return observations, notes


def _raw_notes(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(note) for note in value if note]
    if value:
        return [str(value)]
    return []


_MARKDOWN_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n\s*```", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    match = _MARKDOWN_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None
    candidates: list[str] = [text]
    fenced = _strip_markdown_fences(text)
    if fenced != text:
        candidates.append(fenced)
    for candidate_text in candidates:
        try:
            loaded = json.loads(candidate_text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            nested = loaded.get("text") or loaded.get("message") or loaded.get("reply")
            if isinstance(nested, str):
                nested_payload = _extract_json_payload(nested)
                if nested_payload is not None:
                    return nested_payload
            return loaded
    for candidate_text in candidates:
        start = candidate_text.find("{")
        end = candidate_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            continue
        try:
            candidate = json.loads(candidate_text[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None
