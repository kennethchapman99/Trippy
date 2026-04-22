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
            PlaywrightFlightAdapter(),
            PlaywrightLodgingAdapter(),
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
        if state.category not in {ShortlistCategory.LODGING, ShortlistCategory.FLIGHTS}:
            state.artifacts["deep_research"]["status"] = "skipped"
            state.artifacts["deep_research"]["notes"] = [
                "Deep adapters are implemented for lodging and flights; other categories remain source-link validated."
            ]
            return state

        run_results: list[SourceResearchResult] = []
        selected_option_ids = set(option_ids or [])
        options = (
            state.lodging_options
            if state.category == ShortlistCategory.LODGING
            else state.flight_options
        )
        for option in options:
            if selected_option_ids and option.option_id not in selected_option_ids:
                continue
            request = (
                _request_for_lodging_option(state, option, mode)
                if state.category == ShortlistCategory.LODGING
                else _request_for_flight_option(state, option, mode)
            )
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
            else:
                _apply_flight_observations(option, result, run_id=run_id)
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
        state.next_actions.insert(
            0,
            (
                "Review deep-research evidence for flight rows before treating timing, fare, baggage, "
                "or inventory as ready-to-click."
            )
            if state.category == ShortlistCategory.FLIGHTS
            else "Review deep-research evidence for lodging rows before treating any option as ready-to-click.",
        )
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
            if first_result is None:
                first_result = result
            if adapter.capability == SourceAdapterCapability.LINK:
                return result
            if mode != SourceResearchMode.AUTO:
                return result
            if result.status in {SourceResearchStatus.SUCCESS, SourceResearchStatus.PARTIAL} and (
                result.confidence >= 0.55 or not _missing_high_value_fields(result)
            ):
                return result
            if adapter.capability == SourceAdapterCapability.OPENCLAW:
                return result
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
        if mode == SourceResearchMode.OPENCLAW:
            return [
                adapter
                for adapter in self._adapters
                if adapter.capability == SourceAdapterCapability.OPENCLAW
            ]
        priority = [
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


class OpenClawResearchAdapter:
    capability = SourceAdapterCapability.OPENCLAW

    def __init__(
        self,
        *,
        command: str | None = None,
        gateway_url: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._command = command or config.OPENCLAW_COMMAND
        self._gateway_url = gateway_url or config.OPENCLAW_GATEWAY_URL
        self._timeout = timeout_seconds or config.SOURCE_RESEARCH_TIMEOUT_SECONDS
        self._enabled = config.SOURCE_RESEARCH_OPENCLAW_ENABLED if enabled is None else enabled

    def can_handle(self, request: SourceResearchRequest) -> bool:
        return (
            request.category in {ShortlistCategory.LODGING.value, ShortlistCategory.FLIGHTS.value}
            and self._enabled
            and bool(request.source_url)
            and shutil.which(self._command) is not None
            and self._gateway_is_live()
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
            completed = subprocess.run(  # noqa: S603 - configured local OpenClaw command only
                [
                    self._command,
                    "agent",
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
            missing_fields=(
                _remaining_flight_fields(observations)
                if request.category == ShortlistCategory.FLIGHTS.value
                else _remaining_lodging_fields(observations)
            ),
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


def _apply_lodging_observations(option: Any, result: SourceResearchResult, *, run_id: str) -> None:
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
            "Deep source research extracts evidence only; final inventory, fees, and booking terms still need human review before purchase.",
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
  await page.waitForTimeout(1200);
  const html = await page.content();
  await browser.close();
  process.stdout.write(html);
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
    if not departure or not arrival:
        paired_departure, paired_arrival = _time_pair_signal(cleaned)
        departure = departure or paired_departure
        arrival = arrival or paired_arrival
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
        "Azores Airlines",
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
    if any(term in lower for term in ["sold out", "not available", "unavailable"]):
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
            if value.lower() not in [snippet.lower() for snippet in snippets]:
                snippets.append(value)
            if len(snippets) >= 4:
                break
        if len(snippets) >= 4:
            break
    return "; ".join(snippets)


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
        "flight_numbers",
        "exact_departure_time",
        "exact_arrival_time",
        "total_duration",
        "exact_fare",
        "fare_rules",
        "baggage_terms",
    ]


def _missing_fields_for_category(category: str) -> list[str]:
    if category == ShortlistCategory.FLIGHTS.value:
        return _flight_missing_fields()
    return _lodging_missing_fields()


def _missing_high_value_fields(result: SourceResearchResult) -> bool:
    if result.request.category == ShortlistCategory.FLIGHTS.value:
        return bool(
            {"exact_departure_time", "exact_arrival_time", "exact_fare"}
            & set(result.missing_fields)
        )
    return bool(
        {"final_total_price", "bed_layout", "min_three_beds_satisfied"} & set(result.missing_fields)
    )


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


def _openclaw_prompt(request: SourceResearchRequest) -> str:
    if request.category == ShortlistCategory.FLIGHTS.value:
        useful_fields = (
            "airline, flight_numbers, departure_time, arrival_time, total_duration, stops, "
            "layover_airports, layover_duration, price_signal, availability_signal, "
            "cabin_signal, baggage_signal"
        )
        category_note = "flight research"
    else:
        useful_fields = (
            "price_signal, availability_signal, bed_layout_signal, "
            "min_three_beds_satisfied, king_bed_preference_satisfied, parking_signal, "
            "cancellation_signal, location_signal"
        )
        category_note = "lodging research"
    return (
        f"You are helping Trippy perform read-only {category_note}. "
        "Do not log in, do not book, do not add anything to cart, and do not take payment actions. "
        "Open or inspect this source and return ONLY valid JSON with an observations array. "
        "Each observation must include field, value, confidence, and notes. "
        f"Useful fields: {useful_fields}. "
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
        observations.append(
            SourceObservation(
                field=str(raw.get("field", "")),
                value=raw.get("value"),
                confidence=float(raw.get("confidence", 0.45) or 0.45),
                source_url=request.source_url,
                notes=_raw_notes(raw.get("notes")),
            )
        )
    notes = (
        [str(note) for note in payload.get("notes", [])]
        if isinstance(payload.get("notes"), list)
        else []
    )
    return observations, notes


def _raw_notes(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(note) for note in value]
    if value:
        return [str(value)]
    return []


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict):
        nested = loaded.get("text") or loaded.get("message") or loaded.get("reply")
        if isinstance(nested, str):
            nested_payload = _extract_json_payload(nested)
            if nested_payload is not None:
                return nested_payload
        return loaded
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        candidate = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return candidate if isinstance(candidate, dict) else None
