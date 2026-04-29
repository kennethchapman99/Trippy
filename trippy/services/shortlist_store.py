"""Persistence and shared helpers for research shortlists."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from trippy.models.shortlists import ResearchShortlistState, ShortlistCategory
from trippy.models.sources import SourcePlan, TravelSourceCategory
from trippy.models.trip_planning import TripIntake, TripPlanDraft, TripPlanOption
from trippy.services.source_registry import TravelSourceRegistry
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class ShortlistStore:
    """Save and load category-specific shortlist state."""

    def __init__(self, shortlists_dir: Path | None = None) -> None:
        from trippy import config

        self._dir = shortlists_dir or config.SHORTLISTS_PATH

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, trip_id: str, category: ShortlistCategory) -> Path:
        return self._dir / f"{trip_id}-{category.value}.json"

    def save(self, state: ResearchShortlistState) -> ResearchShortlistState:
        if state.category == ShortlistCategory.FLIGHTS:
            _sanitize_flight_rows(state)
        self._ensure_dir()
        self.path_for(state.trip_id, state.category).write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return state

    def load(self, trip_id: str, category: ShortlistCategory) -> ResearchShortlistState | None:
        path = self.path_for(trip_id, category)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        state = ResearchShortlistState.model_validate(data)
        if category == ShortlistCategory.FLIGHTS:
            _sanitize_flight_rows(state)
        return state

    def load_all(self, trip_id: str) -> list[ResearchShortlistState]:
        states = []
        for category in ShortlistCategory:
            state = self.load(trip_id, category)
            if state is not None:
                states.append(state)
        return states


class ShortlistContext:
    """Loaded intake/draft/selected option context used by shortlist services."""

    def __init__(
        self,
        trip_id: str,
        *,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
    ) -> None:
        self.intakes = intake_service or TripIntakeService()
        self.planner = planner_service or TripPlannerService(self.intakes)
        self.intake = self.intakes.require(trip_id)
        self.draft = self.planner.require_draft(trip_id)
        option = self.draft.get_option()
        if option is None:
            raise ValueError(f"No selected or recommended plan option for trip {trip_id!r}")
        self.option = option

    intake: TripIntake
    draft: TripPlanDraft
    option: TripPlanOption


def source_plan(category: TravelSourceCategory) -> SourcePlan:
    return TravelSourceRegistry().plan_for(category)


def source_plan_payload(plan: SourcePlan) -> dict[str, object]:
    return {
        "category": plan.category.value,
        "primary": [source.platform_name for source in plan.primary],
        "secondary": [source.platform_name for source in plan.secondary],
        "validation": [source.platform_name for source in plan.validation],
        "notes": plan.notes,
    }


def source_search_url(
    source: str,
    query: str,
    *,
    category: TravelSourceCategory | None = None,
) -> str:
    encoded = quote_plus(query)
    if source == "Google Flights":
        return f"https://www.google.com/travel/flights?q={encoded}"
    if source == "Kayak.ca":
        if category == TravelSourceCategory.CAR_RENTALS:
            return f"https://www.ca.kayak.com/cars/{encoded}"
        return f"https://www.ca.kayak.com/flights/{encoded}"
    if source == "Expedia":
        if category == TravelSourceCategory.CAR_RENTALS:
            return f"https://www.expedia.ca/Cars-Search?searchProduct=cars&query={encoded}"
        return f"https://www.expedia.ca/Flights-Search?searchProduct=flights&query={encoded}"
    if source == "Flighthub":
        return f"https://www.flighthub.com/search/flights?query={encoded}"
    if source == "Booking.com":
        if category == TravelSourceCategory.CAR_RENTALS:
            return f"https://www.booking.com/cars/index.html?ss={encoded}"
        return f"https://www.booking.com/searchresults.html?ss={encoded}"
    if source == "Airbnb":
        return f"https://www.airbnb.ca/s/{encoded}/homes"
    if source == "VRBO":
        return f"https://www.vrbo.com/search/keywords:{encoded}"
    if source == "Tripadvisor":
        return f"https://www.tripadvisor.ca/Search?q={encoded}"
    if source == "Trivago":
        return f"https://www.trivago.ca/en-CA/srl?search={encoded}"
    if source == "GetYourGuide":
        return f"https://www.getyourguide.com/s/?q={encoded}"
    if source == "Airbnb Experiences":
        return f"https://www.airbnb.ca/s/{encoded}/experiences"
    return f"https://www.google.com/search?q={encoded}"


def trip_query(intake: TripIntake, extra: str) -> str:
    destinations = " ".join(intake.destination_seeds)
    timing = intake.travel_window.display()
    return " ".join(part for part in [destinations, timing, extra] if part).strip()


def selected_regions(option: TripPlanOption) -> str:
    return ", ".join(option.regions)


def target_matches_selected_regions(
    target: dict[str, str],
    selected: list[str],
    known_region_terms: list[str],
) -> bool:
    """Return whether a destination-profile target fits the selected plan geography.

    Targets that do not name a known region stay eligible for generic destinations. Targets
    that name a known region only stay eligible when the selected plan includes that region.
    """
    if not selected:
        return True
    target_text = _normalize_region_text(" ".join(str(value) for value in target.values()))
    selected_terms = _selected_region_terms(selected)
    if any(term and term in target_text for term in selected_terms):
        return True
    known_terms = [_normalize_region_text(term) for term in known_region_terms]
    return not any(term and term in target_text for term in known_terms)


def _normalize_region_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().replace("/", " ").replace("-", " ").split())


def _selected_region_terms(selected: list[str]) -> list[str]:
    terms: list[str] = []
    for region in selected:
        terms.append(_normalize_region_text(region))
        raw = region.replace("/", " or ")
        for piece in raw.split(" or "):
            normalized = _normalize_region_text(piece)
            if normalized:
                terms.append(normalized)
    return terms


USD_TO_CAD_RATE = 1.37


def _sanitize_flight_rows(state: ResearchShortlistState) -> None:
    _remove_synthetic_flight_rows(state)
    for option in state.flight_options:
        _repair_flight_duration(option)
        _normalize_flight_price_to_cad(option)


def _remove_synthetic_flight_rows(state: ResearchShortlistState) -> None:
    original_count = len(state.flight_options)
    state.flight_options = [
        option for option in state.flight_options if not _is_synthetic_flight_option(option)
    ]
    removed_count = original_count - len(state.flight_options)
    _remove_synthetic_flight_summary_text(state)
    if not removed_count:
        return
    if state.recommended_option_id and not any(
        option.option_id == state.recommended_option_id for option in state.flight_options
    ):
        state.recommended_option_id = state.flight_options[0].option_id if state.flight_options else None
    warning = f"Ignored {removed_count} Duffel sandbox/test flight row(s), including Duffel Airways."
    if warning not in state.warnings:
        state.warnings.append(warning)


def _remove_synthetic_flight_summary_text(state: ResearchShortlistState) -> None:
    state.recommendation_summary = re.sub(
        r"\s*Runner-up:\s*Duffel Airways if the tradeoff is worth it\.\s*",
        " ",
        state.recommendation_summary,
    ).strip()
    if state.recommendation_summary.startswith("Best current flight: Duffel Airways."):
        replacement = state.flight_options[0].airline if state.flight_options else "Verify live flight options"
        state.recommendation_summary = state.recommendation_summary.replace(
            "Best current flight: Duffel Airways.",
            f"Best current flight: {replacement}.",
            1,
        )


def _is_synthetic_flight_option(option: object) -> bool:
    airline = str(getattr(option, "airline", "") or "").lower()
    if "duffel airways" in airline:
        return True
    flight_numbers = getattr(option, "flight_numbers", []) or []
    return any(str(number).upper().startswith("ZZ") for number in flight_numbers)


def _repair_flight_duration(option: object) -> None:
    computed = _duration_from_option_times(option)
    if computed is None:
        return
    current = _duration_minutes(str(getattr(option, "total_travel_duration", "") or ""))
    should_repair = current is None or current >= 18 * 60 or (computed < current and current - computed > 30)
    if should_repair:
        option.total_travel_duration = _format_minutes(computed)
        validation = getattr(option, "validation", None)
        if validation is not None:
            validation.extracted_fields["total_duration"] = _format_minutes(computed)
            validation.notes = _dedupe(
                [
                    *validation.notes,
                    "Corrected flight duration from departure/arrival timestamps; ignored conflicting scraped duration text.",
                ]
            )


def _duration_from_option_times(option: object) -> int | None:
    departure = _parse_flight_datetime(
        str(getattr(option, "departure_date", "") or ""),
        str(getattr(option, "departure_time", "") or ""),
        str(getattr(option, "departure_airport", "") or ""),
    )
    arrival = _parse_flight_datetime(
        str(getattr(option, "arrival_date", "") or ""),
        str(getattr(option, "arrival_time", "") or ""),
        str(getattr(option, "arrival_airport", "") or ""),
    )
    if departure is None or arrival is None:
        return None
    if (departure.tzinfo is None) != (arrival.tzinfo is None):
        return None
    if arrival <= departure:
        return None
    total = int((arrival - departure).total_seconds() // 60)
    if total <= 0 or total > 48 * 60:
        return None
    return total


AIRPORT_TIME_ZONES: dict[str, str] = {
    "BOS": "America/New_York",
    "GCM": "America/Cayman",
    "LIS": "Europe/Lisbon",
    "PDL": "Atlantic/Azores",
    "YYZ": "America/Toronto",
}


def _parse_flight_datetime(date_text: str, time_text: str, airport: str) -> datetime | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text.strip()):
        return None
    cleaned_time = time_text.strip().upper().replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", cleaned_time)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if hour == 12:
        hour = 0
    if meridiem == "PM":
        hour += 12
    try:
        parsed = datetime.fromisoformat(date_text).replace(hour=hour, minute=minute)
    except ValueError:
        return None
    timezone_name = AIRPORT_TIME_ZONES.get(airport.strip().upper())
    if not timezone_name:
        return parsed
    return parsed.replace(tzinfo=ZoneInfo(timezone_name))


def _duration_minutes(value: str) -> int | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\s*(?:(\d+)\s*(?:m|min|mins|minute|minutes))?",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return int(round(float(match.group(1)) * 60 + float(match.group(2) or 0)))


def _format_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _normalize_flight_price_to_cad(option: object) -> None:
    raw = str(getattr(option, "fare_estimate_cad", "") or getattr(option, "price_band", "") or "")
    parsed = _parse_price_signal(raw)
    if parsed is None:
        return
    amount, currency, basis = parsed
    traveler_count = int(getattr(option, "traveler_count", 0) or 0) or 1
    cad_amount = amount * (USD_TO_CAD_RATE if currency == "USD" else 1)
    if basis == "per_person":
        per_person = cad_amount
        total = cad_amount * traveler_count
    else:
        total = cad_amount
        per_person = cad_amount / traveler_count
    normalized = f"CAD {_money(total)} total; CAD {_money(per_person)} per person"
    option.fare_estimate_cad = normalized
    option.price_band = normalized
    validation = getattr(option, "validation", None)
    if validation is not None:
        validation.extracted_fields["price_signal"] = normalized
        if currency == "USD":
            validation.notes = _dedupe(
                [
                    *validation.notes,
                    f"Converted USD fare signal to CAD using USD/CAD {USD_TO_CAD_RATE:.2f}; verify final charged currency before booking.",
                ]
            )


def _parse_price_signal(value: str) -> tuple[float, str, str] | None:
    if not value or "live verify" in value.lower() or "unavailable" in value.lower():
        return None
    cad_amounts = [
        float(match.replace(",", ""))
        for match in re.findall(r"CAD\s*\$?\s*(\d[\d,]*(?:\.\d{1,2})?)", value, flags=re.IGNORECASE)
    ]
    if len(cad_amounts) >= 2:
        return cad_amounts[0], "CAD", "total"
    currency = "CAD"
    if re.search(r"\bUSD\b|US\$", value, flags=re.IGNORECASE):
        currency = "USD"
    elif not re.search(r"\bCAD\b|CA\$|C\$", value, flags=re.IGNORECASE):
        return None
    match = re.search(r"(\d[\d,]*(?:\.\d{1,2})?)", value)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    basis = "per_person" if re.search(r"per\s*(?:person|traveler|passenger|pp)", value, flags=re.IGNORECASE) else "total"
    return amount, currency, basis


def _money(value: float) -> str:
    rounded = int(round(value))
    return f"{rounded:,}"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
