"""Optimize multi-location stay boundaries against transfer evidence.

The optimizer is deliberately destination-agnostic. It never assumes islands,
ferries, airports, prices, or schedules. It only evaluates alternate night splits
inside the already-canonical trip calendar and scores them against transfer evidence
that another connector/service has actually provided.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field, field_validator

from trippy.models.trip_calendar import StaySegment, TripCalendarState


class TransferEvidence(BaseModel):
    """Observed transfer evidence for a specific boundary date."""

    date: str
    cost_cad: float | None = None
    friction_score: int | None = None
    duration_minutes: int | None = None
    option_id: str = ""
    source: str = ""
    notes: list[str] = Field(default_factory=list)

    @field_validator("friction_score")
    @classmethod
    def _score_range(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return max(0, min(100, value))


class StaySplitCandidate(BaseModel):
    """A candidate allocation of nights across the current stay regions."""

    split_id: str
    nights_by_region: dict[str, int]
    transfer_dates: list[str]
    total_known_transfer_cost_cad: float | None = None
    average_transfer_friction_score: float | None = None
    evidence_count: int = 0
    missing_evidence_dates: list[str] = Field(default_factory=list)
    score: float
    recommendation: str
    warnings: list[str] = Field(default_factory=list)


class BoundaryOptimizerService:
    """Suggest alternate stay splits without inventing transfer facts."""

    def suggest_splits(
        self,
        calendar: TripCalendarState,
        *,
        transfer_evidence: list[TransferEvidence | dict[str, object]] | None = None,
        max_shift_nights: int = 1,
        min_nights_per_region: int = 1,
    ) -> list[StaySplitCandidate]:
        """Return ranked split candidates for the current calendar.

        The current split is included as the baseline. Alternatives move one or more
        nights across adjacent stay boundaries while preserving total trip nights and
        region order.
        """
        if not calendar.envelope_locked or calendar.trip_envelope.trip_nights is None:
            return []
        if len(calendar.stay_segments) < 2:
            return []

        evidence = _evidence_by_date(transfer_evidence or [])
        regions = [segment.region for segment in calendar.stay_segments]
        baseline = [segment.nights for segment in calendar.stay_segments]
        candidates: dict[tuple[int, ...], StaySplitCandidate] = {}

        for nights in _candidate_night_vectors(
            baseline,
            max_shift_nights=max_shift_nights,
            min_nights_per_region=min_nights_per_region,
        ):
            candidate = _candidate_from_nights(calendar, regions, nights, evidence)
            candidates[tuple(nights)] = candidate

        return sorted(
            candidates.values(),
            key=lambda item: (
                -item.evidence_count,
                item.total_known_transfer_cost_cad
                if item.total_known_transfer_cost_cad is not None
                else float("inf"),
                item.average_transfer_friction_score
                if item.average_transfer_friction_score is not None
                else float("inf"),
                -item.score,
            ),
        )


def _candidate_night_vectors(
    baseline: list[int],
    *,
    max_shift_nights: int,
    min_nights_per_region: int,
) -> list[list[int]]:
    candidates: list[list[int]] = [list(baseline)]
    for boundary_index in range(len(baseline) - 1):
        for shift in range(-max_shift_nights, max_shift_nights + 1):
            if shift == 0:
                continue
            nights = list(baseline)
            nights[boundary_index] += shift
            nights[boundary_index + 1] -= shift
            if all(value >= min_nights_per_region for value in nights):
                candidates.append(nights)
    return candidates


def _candidate_from_nights(
    calendar: TripCalendarState,
    regions: list[str],
    nights: list[int],
    evidence_by_date: dict[str, TransferEvidence],
) -> StaySplitCandidate:
    transfer_dates = _transfer_dates(calendar.trip_envelope.trip_start_date, nights)
    known_costs: list[float] = []
    known_friction: list[int] = []
    missing_dates: list[str] = []
    warnings: list[str] = []

    for transfer_date in transfer_dates:
        evidence = evidence_by_date.get(transfer_date)
        if evidence is None:
            missing_dates.append(transfer_date)
            continue
        if evidence.cost_cad is not None:
            known_costs.append(evidence.cost_cad)
        if evidence.friction_score is not None:
            known_friction.append(evidence.friction_score)

    total_cost = sum(known_costs) if known_costs else None
    average_friction = (
        sum(known_friction) / len(known_friction) if known_friction else None
    )
    if missing_dates:
        warnings.append(
            "Transfer evidence is missing for one or more boundary dates; do not treat this split as booking-safe."
        )

    score = _score_candidate(
        evidence_count=len(transfer_dates) - len(missing_dates),
        total_boundaries=len(transfer_dates),
        total_cost=total_cost,
        average_friction=average_friction,
        nights=nights,
    )
    nights_by_region = dict(zip(regions, nights, strict=True))
    return StaySplitCandidate(
        split_id="split-" + "-".join(str(value) for value in nights),
        nights_by_region=nights_by_region,
        transfer_dates=transfer_dates,
        total_known_transfer_cost_cad=total_cost,
        average_transfer_friction_score=average_friction,
        evidence_count=len(transfer_dates) - len(missing_dates),
        missing_evidence_dates=missing_dates,
        score=score,
        recommendation=_recommendation(score, missing_dates),
        warnings=warnings,
    )


def _transfer_dates(start_date: str, nights: list[int]) -> list[str]:
    start = date.fromisoformat(start_date)
    cursor = start
    transfer_dates: list[str] = []
    for nights_in_segment in nights[:-1]:
        cursor = cursor + timedelta(days=nights_in_segment)
        transfer_dates.append(cursor.isoformat())
    return transfer_dates


def _evidence_by_date(
    rows: list[TransferEvidence | dict[str, object]],
) -> dict[str, TransferEvidence]:
    result: dict[str, TransferEvidence] = {}
    for row in rows:
        evidence = row if isinstance(row, TransferEvidence) else TransferEvidence.model_validate(row)
        result[evidence.date] = evidence
    return result


def _score_candidate(
    *,
    evidence_count: int,
    total_boundaries: int,
    total_cost: float | None,
    average_friction: float | None,
    nights: list[int],
) -> float:
    score = 50.0
    if total_boundaries:
        score += 25.0 * (evidence_count / total_boundaries)
    if total_cost is not None:
        score -= min(30.0, total_cost / 100.0)
    if average_friction is not None:
        score -= average_friction / 4.0
    score -= _imbalance_penalty(nights)
    return round(max(0.0, min(100.0, score)), 2)


def _imbalance_penalty(nights: list[int]) -> float:
    if not nights:
        return 0.0
    average = sum(nights) / len(nights)
    return sum(abs(value - average) for value in nights) / len(nights)


def _recommendation(score: float, missing_dates: list[str]) -> str:
    if missing_dates:
        return "research_required"
    if score >= 75:
        return "strong"
    if score >= 60:
        return "good"
    if score >= 40:
        return "conditional"
    return "weak"
