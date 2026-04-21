"""Conservative live-source validation for shortlist rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trippy import config
from trippy.models.shortlists import (
    AvailabilityStatus,
    FreshnessStatus,
    LiveDataStatus,
    PriceStatus,
    ResearchShortlistState,
    ShortlistRowStatus,
    SourceType,
    SourceValidation,
    VerificationStatus,
)

FetchResult = tuple[bool, int | None, str]
FetchFn = Callable[[str, float], FetchResult]


class LiveValidationService:
    """Validate shortlist links without pretending to complete booking research.

    A successful network check means the source/search page is reachable now. It does not
    mean Trippy has confirmed exact inventory, final price, bed layout, or fare rules.
    """

    def __init__(
        self,
        *,
        fetcher: FetchFn | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._fetcher = fetcher or _fetch_url
        self._timeout = timeout_seconds or config.LIVE_VALIDATION_TIMEOUT_SECONDS

    def validate_state(
        self,
        state: ResearchShortlistState,
        *,
        attempt_network: bool | None = None,
    ) -> ResearchShortlistState:
        should_fetch = (
            config.LIVE_VALIDATION_ENABLED if attempt_network is None else attempt_network
        )
        for option in _state_options(state):
            self._validate_option(option, state=state, attempt_network=should_fetch)
        state.artifacts["validation_mode"] = "network" if should_fetch else "provenance_only"
        return state

    def _validate_option(
        self,
        option: Any,
        *,
        state: ResearchShortlistState,
        attempt_network: bool,
    ) -> None:
        source_name = _source_name(option)
        url = str(getattr(option, "deep_link", ""))
        validation = getattr(option, "validation", SourceValidation())
        validation.source_name = source_name
        validation.source_type = _source_type(option)
        validation.evidence_url = url
        validation.missing_fields = _missing_fields(option, state)
        validation.notes = _base_notes(option, state)
        if not attempt_network:
            validation.verification_status = VerificationStatus.MANUAL_REQUIRED
            validation.freshness_status = FreshnessStatus.UNKNOWN
            validation.availability_status = AvailabilityStatus.UNKNOWN
            validation.price_status = _price_status(option)
            validation.confidence = min(validation.confidence, 0.55)
            option.row_status = ShortlistRowStatus.RESEARCHED
            option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED
            option.validation = validation
            return

        ok, status_code, message = self._fetcher(url, self._timeout)
        validation.verified_at = datetime.utcnow()
        validation.price_status = _price_status(option)
        validation.notes.append(message)
        if ok:
            validation.freshness_status = FreshnessStatus.CURRENT
            validation.verification_status = VerificationStatus.LINK_VALIDATED
            validation.availability_status = AvailabilityStatus.SEARCH_AVAILABLE
            validation.confidence = min(0.82, max(validation.confidence, 0.62))
            option.row_status = ShortlistRowStatus.VERIFIED_LIVE
            option.live_data_status = LiveDataStatus.PARTIAL
            validation.notes.append(
                "Live source page was reachable; exact inventory, final price, and terms still require in-page human verification."
            )
        else:
            validation.freshness_status = FreshnessStatus.UNKNOWN
            validation.verification_status = VerificationStatus.FAILED
            validation.availability_status = AvailabilityStatus.UNKNOWN
            validation.confidence = min(validation.confidence, 0.35)
            option.row_status = ShortlistRowStatus.RESEARCHED
            option.live_data_status = LiveDataStatus.HANDOFF_REQUIRED
            validation.notes.append(
                f"Live source check failed with status {status_code or 'unknown'}."
            )
        option.validation = validation


def _fetch_url(url: str, timeout: float) -> FetchResult:
    if not url:
        return False, None, "No source URL available for validation."
    request = Request(url, method="GET", headers={"User-Agent": "Trippy/0.1 live validation"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-approved source validation
            status = int(getattr(response, "status", 200))
            ok = 200 <= status < 400
            return ok, status, f"Source responded with HTTP {status}."
    except HTTPError as exc:
        status = int(exc.code)
        return 200 <= status < 400, status, f"Source responded with HTTP {status}."
    except (TimeoutError, URLError, OSError) as exc:
        return False, None, f"Source validation failed: {exc}"


def _state_options(state: ResearchShortlistState) -> list[Any]:
    return (
        list(state.flight_options)
        + list(state.lodging_options)
        + list(state.car_options)
        + list(state.activity_options)
    )


def _source_name(option: Any) -> str:
    return str(
        getattr(option, "booking_source", "")
        or getattr(option, "source", "")
        or getattr(option, "validation", SourceValidation()).source_name
        or "unknown"
    )


def _source_type(option: Any) -> SourceType:
    url = str(getattr(option, "deep_link", ""))
    if any(path in url for path in ("/hotel/", "/rooms/", "/experiences/", "/activity/")):
        return SourceType.DIRECT_LISTING
    if url:
        return SourceType.LIVE_SEARCH
    return SourceType.MANUAL


def _price_status(option: Any) -> PriceStatus:
    price = str(getattr(option, "price_band", "") or getattr(option, "fare_estimate_cad", ""))
    if "live" in price.lower():
        return PriceStatus.ESTIMATED_BAND
    if price.strip():
        return PriceStatus.ESTIMATED_BAND
    return PriceStatus.UNKNOWN


def _base_notes(option: Any, state: ResearchShortlistState) -> list[str]:
    notes = [
        f"{state.category.value} row generated from Trippy source routing and selected plan context.",
    ]
    notes.extend(str(item) for item in getattr(option, "confidence_notes", [])[:3])
    return notes


def _missing_fields(option: Any, state: ResearchShortlistState) -> list[str]:
    missing: list[str] = []
    if state.category.value == "flights":
        if not getattr(option, "flight_numbers", []):
            missing.append("flight_numbers")
        missing.extend(["exact_departure_time", "exact_fare", "fare_rules", "baggage_terms"])
    elif state.category.value == "lodging":
        for field in ("min_three_beds_satisfied", "king_bed_preference_satisfied"):
            if getattr(option, field, None) is None:
                missing.append(field)
        missing.extend(["exact_availability", "final_total_price", "cancellation_deadline"])
    elif state.category.value == "cars":
        missing.extend(
            ["exact_vehicle_model", "final_total_price", "deposit_terms", "insurance_terms"]
        )
    elif state.category.value == "activities":
        missing.extend(["exact_schedule", "remaining_capacity", "operator_safety_details"])
    return missing
