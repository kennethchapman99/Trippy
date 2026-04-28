"""Per-option anti-friction post-processor for researched shortlists.

Run after `SourceResearchService.research_state` enriches a state with deep-research
observations. The post-processor reads canonical option fields plus the freshly
populated `validation.extracted_fields`, applies deterministic per-option checks,
and mutates each option's `friction_flags`, `confidence_notes`, `recommendation_grade`,
and `live_data_status`. It also re-ranks options so HIGH-flagged candidates fall
below safer ones within the same recommendation grade.

Pure-deterministic and side-effect free apart from in-memory option updates and
a structured summary at `state.artifacts["friction_postprocess"]`. No I/O, no
LLM calls, no memory or skill writes.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from trippy.models.shortlists import (
    LiveDataStatus,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
)

_HIGH = "high"
_MEDIUM = "medium"
_LOW = "low"

_GRADE_ORDER: dict[RecommendationGrade, int] = {
    RecommendationGrade.STRONG: 0,
    RecommendationGrade.GOOD: 1,
    RecommendationGrade.CONDITIONAL: 2,
    RecommendationGrade.WEAK: 3,
}

Flag = tuple[str, str]


def apply_shortlist_friction(
    state: ResearchShortlistState,
    *,
    complementary_states: dict[ShortlistCategory, ResearchShortlistState] | None = None,
    party_size: int | None = None,
) -> ResearchShortlistState:
    """Annotate, downgrade, and re-rank options based on deterministic friction checks."""
    comp = complementary_states or {}
    if state.category == ShortlistCategory.FLIGHTS:
        flagged: list[tuple[Any, list[Flag]]] = [
            (opt, _flight_flags(opt)) for opt in state.flight_options
        ]
    elif state.category == ShortlistCategory.LODGING:
        flight_state = comp.get(ShortlistCategory.FLIGHTS)
        flagged = [
            (opt, _lodging_flags(opt, party_size, flight_state)) for opt in state.lodging_options
        ]
    elif state.category == ShortlistCategory.CARS:
        flagged = [
            (opt, _car_flags(opt, party_size, comp.get(ShortlistCategory.FLIGHTS)))
            for opt in state.car_options
        ]
    elif state.category == ShortlistCategory.ACTIVITIES:
        flight_state = comp.get(ShortlistCategory.FLIGHTS)
        flagged = [(opt, _activity_flags(opt, flight_state)) for opt in state.activity_options]
    else:
        return state

    flags_by_option: dict[str, list[dict[str, str]]] = {}
    downgrades: list[dict[str, str]] = []

    for option, flags in flagged:
        flags_by_option[str(option.option_id)] = [
            {"severity": severity, "flag": text} for severity, text in flags
        ]
        if not flags:
            continue
        formatted = [f"[{severity.upper()}] {text}" for severity, text in flags]
        option.friction_flags = _dedupe([*option.friction_flags, *formatted])
        option.confidence_notes = _dedupe(
            [
                *option.confidence_notes,
                *(text for severity, text in flags if severity in {_HIGH, _MEDIUM}),
            ]
        )
        if any(severity == _HIGH for severity, _ in flags):
            if option.recommendation_grade in {
                RecommendationGrade.STRONG,
                RecommendationGrade.GOOD,
            }:
                downgrades.append(
                    {
                        "option_id": str(option.option_id),
                        "from_grade": option.recommendation_grade.value,
                        "to_grade": RecommendationGrade.CONDITIONAL.value,
                    }
                )
                option.recommendation_grade = RecommendationGrade.CONDITIONAL
            if option.live_data_status == LiveDataStatus.LIVE_VERIFIED:
                option.live_data_status = LiveDataStatus.PARTIAL

    options_sorted = sorted(
        flagged,
        key=lambda pair: (
            _GRADE_ORDER.get(pair[0].recommendation_grade, 99),
            1 if any(severity == _HIGH for severity, _ in pair[1]) else 0,
            pair[0].rank,
        ),
    )
    for new_rank, (option, _flags) in enumerate(options_sorted, start=1):
        option.rank = new_rank
    ordered = [opt for opt, _ in options_sorted]
    if state.category == ShortlistCategory.FLIGHTS:
        state.flight_options = ordered
    elif state.category == ShortlistCategory.LODGING:
        state.lodging_options = ordered
    elif state.category == ShortlistCategory.CARS:
        state.car_options = ordered
    elif state.category == ShortlistCategory.ACTIVITIES:
        state.activity_options = ordered

    state.artifacts["friction_postprocess"] = {
        "ran_at": datetime.utcnow().isoformat(),
        "category": state.category.value,
        "flags_by_option": flags_by_option,
        "downgrades": downgrades,
    }
    return state


def _flight_flags(option: Any) -> list[Flag]:
    flags: list[Flag] = []
    extracted = _extracted(option)
    missing = _missing(option)

    arrival = _coerce(extracted.get("arrival_time"), getattr(option, "arrival_time", ""))
    if _hour_at_or_after(arrival, 23):
        flags.append(
            (
                _HIGH,
                "flight arrival at or after 23:00 risks lodging check-in cutoff and first-night access",
            )
        )
    departure = _coerce(
        extracted.get("departure_time"), getattr(option, "departure_time", "")
    )
    if _hour_before(departure, 6):
        flags.append(
            (_MEDIUM, "very early departure (before 06:00) compresses sleep and transfer time")
        )

    layover = _coerce(
        extracted.get("layover_duration"), getattr(option, "layover_duration", "") or ""
    )
    if _layover_minutes_below(layover, 50):
        flags.append(
            (_HIGH, "layover under 50 minutes risks a misconnect with checked bags")
        )

    if "baggage_terms" in missing or not (
        extracted.get("baggage_signal")
        or getattr(option, "baggage_cabin_notes", "")
    ):
        flags.append(
            (_LOW, "baggage terms not pinned — verify checked-bag fees before booking")
        )
    if "exact_fare" in missing:
        flags.append((_MEDIUM, "exact fare is not pinned in extracted observations"))

    flight_numbers = extracted.get("flight_numbers") or getattr(
        option, "flight_numbers", []
    )
    airline_codes: set[str] = set()
    for number in flight_numbers or []:
        text = str(number).strip().upper()
        match = re.match(r"^([A-Z]{2,3})\d", text)
        if match:
            airline_codes.add(match.group(1))
    if len(airline_codes) > 1:
        flags.append(
            (
                _HIGH,
                "multi-airline flight numbers suggest separate-ticket misconnect risk",
            )
        )
    return flags


def _lodging_flags(
    option: Any,
    party_size: int | None,
    flight_state: ResearchShortlistState | None,
) -> list[Flag]:
    flags: list[Flag] = []
    extracted = _extracted(option)
    missing = _missing(option)

    bed_layout = _coerce(extracted.get("bed_layout_signal"), getattr(option, "bed_layout", ""))
    min_three = getattr(option, "min_three_beds_satisfied", None)
    family_fit = getattr(option, "family_of_five_fit", None)
    if (party_size is None or party_size >= 5) and (
        not bed_layout or min_three is False or "bed_layout" in missing
    ):
        flags.append(
            (_HIGH, "bed/occupancy proof missing for a 5+ traveler party")
        )
    if family_fit is False:
        flags.append((_HIGH, "lodging explicitly does not fit a family of five"))

    cancellation = _coerce(
        extracted.get("cancellation_signal"),
        getattr(option, "cancellation_notes", ""),
    )
    if not cancellation or "manual" in cancellation.lower():
        flags.append(
            (_MEDIUM, "cancellation terms unclear — confirm refund window before booking")
        )

    if "final_total_price" in missing or not (
        extracted.get("total_price")
        or extracted.get("price_signal")
        or getattr(option, "current_price_signal", "")
    ):
        flags.append((_HIGH, "final total price is not pinned in extracted observations"))

    if flight_state is not None:
        late_arrival = _latest_arrival(flight_state)
        if late_arrival and _hour_at_or_after(late_arrival, 23):
            lodging_text = " ".join([
                getattr(option, "cancellation_notes", ""),
                getattr(option, "current_availability_signal", ""),
                str(extracted.get("check_in_signal", "")),
            ]).lower()
            if not any(
                token in lodging_text
                for token in ["late check", "self check", "24h", "24-hour", "key box", "keybox", "lockbox"]
            ):
                flags.append((
                    _HIGH,
                    "late-arriving flight (23:00+) may conflict with lodging check-in cutoff — verify late check-in policy",
                ))
        early_departure = _earliest_departure(flight_state)
        if early_departure and _hour_before(early_departure, 9):
            flags.append((
                _MEDIUM,
                "early departure flight (before 09:00) — confirm checkout time allows airport transfer",
            ))

    return flags


def _car_flags(
    option: Any,
    party_size: int | None,
    flight_state: ResearchShortlistState | None,
) -> list[Flag]:
    flags: list[Flag] = []
    extracted = _extracted(option)
    missing = _missing(option)

    seats = extracted.get("seats")
    if not isinstance(seats, int):
        seats = getattr(option, "seating_capacity", None)
    if isinstance(party_size, int) and isinstance(seats, int) and seats < party_size:
        flags.append(
            (
                _HIGH,
                f"vehicle seats {seats} below party size {party_size} — comfort and luggage at risk",
            )
        )

    transmission = _coerce(extracted.get("transmission_signal"), "")
    if not transmission and "transmission" in missing:
        flags.append(
            (_MEDIUM, "transmission unknown — confirm automatic vs manual before booking")
        )

    if "total_price" in missing and not (
        extracted.get("total_price")
        or extracted.get("price_signal")
        or getattr(option, "current_price_signal", "")
    ):
        flags.append((_HIGH, "total price is not pinned in extracted observations"))

    insurance = _coerce(extracted.get("insurance_signal"), "")
    fees = _coerce(extracted.get("fees_signal"), "")
    if not insurance and not fees and "fees_breakdown" in missing:
        flags.append(
            (_MEDIUM, "deposit, insurance, or fee breakdown unclear — verify before booking")
        )

    cancellation = _coerce(
        extracted.get("cancellation_signal"),
        getattr(option, "cancellation_notes", ""),
    )
    if not cancellation:
        flags.append((_MEDIUM, "cancellation terms unclear for the rental"))

    if flight_state is not None:
        for flight_option in flight_state.flight_options:
            arrival = _coerce(
                _extracted(flight_option).get("arrival_time"),
                getattr(flight_option, "arrival_time", ""),
            )
            pickup = _coerce(extracted.get("pickup_datetime"), "")
            if arrival and pickup and _within_minutes(arrival, pickup, 60):
                flags.append(
                    (
                        _HIGH,
                        "car pickup within 60 minutes of flight arrival risks misconnect with luggage",
                    )
                )
                break
    return flags


def _activity_flags(
    option: Any,
    flight_state: ResearchShortlistState | None,
) -> list[Flag]:
    flags: list[Flag] = []
    extracted = _extracted(option)
    missing = _missing(option)

    if "current_price" in missing and not (
        extracted.get("price_signal") or getattr(option, "price_band", "")
    ):
        flags.append((_MEDIUM, "activity price is not pinned in extracted observations"))

    cancellation = _coerce(extracted.get("cancellation_signal"), "")
    if "cancellation_policy" in missing or not cancellation:
        flags.append(
            (_MEDIUM, "activity cancellation policy unclear — verify refund window")
        )

    group_size = _coerce(
        extracted.get("group_size_signal"),
        getattr(option, "group_size_signal", ""),
    )
    if not group_size:
        flags.append((_LOW, "group size limits unclear — verify family fit"))

    if flight_state is not None:
        suggested_day = getattr(option, "suggested_day", None) or getattr(option, "scheduled_day", None)
        late_arrival = _latest_arrival(flight_state)
        if late_arrival and _hour_at_or_after(late_arrival, 22):
            severity = _HIGH if suggested_day == 1 else _LOW
            flags.append((
                severity,
                "late-arriving flight compresses day-1 scheduling — avoid full-day activities on arrival day",
            ))
        early_departure = _earliest_departure(flight_state)
        if early_departure and _hour_before(early_departure, 10):
            severity = _MEDIUM if suggested_day is not None else _LOW
            flags.append((
                severity,
                "early departure flight — buffer the final day and avoid same-day activities before the airport transfer",
            ))

    return flags


def _extracted(option: Any) -> dict[str, Any]:
    validation = getattr(option, "validation", None)
    if validation is None:
        return {}
    return dict(getattr(validation, "extracted_fields", {}) or {})


def _missing(option: Any) -> set[str]:
    validation = getattr(option, "validation", None)
    if validation is None:
        return set()
    return set(getattr(validation, "missing_fields", []) or [])


def _coerce(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


_TIME_RE = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>am|pm)?", re.IGNORECASE
)


def _parse_hour(time_text: str) -> int | None:
    if not time_text:
        return None
    match = _TIME_RE.search(time_text)
    if not match:
        return None
    try:
        hour = int(match.group("hour"))
    except (TypeError, ValueError):
        return None
    if not 0 <= hour <= 23:
        return None
    meridiem = (match.group("meridiem") or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour


def _hour_at_or_after(time_text: str, threshold_hour: int) -> bool:
    hour = _parse_hour(time_text)
    return hour is not None and hour >= threshold_hour


def _hour_before(time_text: str, threshold_hour: int) -> bool:
    hour = _parse_hour(time_text)
    return hour is not None and hour < threshold_hour


_LAYOVER_RE = re.compile(
    r"(?:(?P<hours>\d+)\s*h)?\s*(?:(?P<minutes>\d+)\s*m)?", re.IGNORECASE
)


def _layover_minutes_below(layover_text: str, threshold_minutes: int) -> bool:
    if not layover_text:
        return False
    match = _LAYOVER_RE.search(layover_text)
    if not match or not (match.group("hours") or match.group("minutes")):
        return False
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total = hours * 60 + minutes
    if total <= 0:
        return False
    return total < threshold_minutes


def _latest_arrival(flight_state: ResearchShortlistState) -> str:
    """Return the latest arrival time string across all flight options, or empty string."""
    latest_hour = -1
    latest_text = ""
    for opt in flight_state.flight_options:
        arrival = _coerce(
            _extracted(opt).get("arrival_time"),
            getattr(opt, "arrival_time", ""),
        )
        hour = _parse_hour(arrival)
        if hour is not None and hour > latest_hour:
            latest_hour = hour
            latest_text = arrival
    return latest_text


def _earliest_departure(flight_state: ResearchShortlistState) -> str:
    """Return the earliest departure time string across all flight options, or empty string."""
    earliest_hour = 25
    earliest_text = ""
    for opt in flight_state.flight_options:
        departure = _coerce(
            _extracted(opt).get("departure_time"),
            getattr(opt, "departure_time", ""),
        )
        hour = _parse_hour(departure)
        if hour is not None and hour < earliest_hour:
            earliest_hour = hour
            earliest_text = departure
    return earliest_text


def _within_minutes(time_a: str, time_b: str, threshold_minutes: int) -> bool:
    hour_a = _parse_hour(time_a)
    hour_b = _parse_hour(time_b)
    if hour_a is None or hour_b is None:
        return False
    minute_a = _parse_minute(time_a)
    minute_b = _parse_minute(time_b)
    diff = abs((hour_a * 60 + minute_a) - (hour_b * 60 + minute_b))
    return diff < threshold_minutes


def _parse_minute(time_text: str) -> int:
    match = _TIME_RE.search(time_text)
    if not match:
        return 0
    try:
        return int(match.group("minute"))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen
