"""Extract reusable family travel intelligence from canonical trip history."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from trippy.models.intelligence import (
    EvidenceRef,
    EvidenceSourceType,
    IntelligenceCategory,
    PreferenceSignal,
    TravelIntelligenceReport,
)
from trippy.models.trip import StayType, Trip, TripStatus
from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType

_CENTRALITY_HINTS = {
    "central",
    "downtown",
    "urban core",
    "walkable",
    "old town",
    "city centre",
    "city center",
    "shinjuku",
    "ginza",
    "near transit",
}


class TravelIntelligenceService:
    """Turns past trips into structured, reviewable planning intelligence."""

    def analyze(self, trips: list[Trip], *, min_support: int = 1) -> TravelIntelligenceReport:
        lived = [trip for trip in trips if trip.status == TripStatus.LIVED]
        evidence_trips = lived or trips
        signals: list[PreferenceSignal] = []
        friction_patterns: list[PreferenceSignal] = []
        destination_affinities: list[PreferenceSignal] = []
        vendor_patterns: list[PreferenceSignal] = []

        if not evidence_trips:
            return TravelIntelligenceReport(
                trips_analyzed=0,
                lived_trips_analyzed=0,
                summary="No canonical trips available for intelligence extraction.",
            )

        signals.extend(self._family_fit_signals(evidence_trips, min_support=min_support))
        signals.extend(self._lodging_signals(evidence_trips, min_support=min_support))
        signals.extend(self._pacing_signals(evidence_trips, min_support=min_support))
        vendor_patterns.extend(self._vendor_signals(evidence_trips, min_support=min_support))
        destination_affinities.extend(self._destination_signals(evidence_trips))
        friction_patterns.extend(self._friction_signals(evidence_trips, min_support=min_support))

        total = (
            len(signals)
            + len(friction_patterns)
            + len(destination_affinities)
            + len(vendor_patterns)
        )
        return TravelIntelligenceReport(
            trips_analyzed=len(trips),
            lived_trips_analyzed=len(lived),
            signals=signals,
            friction_patterns=friction_patterns,
            destination_affinities=destination_affinities,
            vendor_patterns=vendor_patterns,
            summary=f"Extracted {total} travel intelligence signal(s) from {len(evidence_trips)} evidence trip(s).",
        )

    def propose_memory_updates(
        self,
        report: TravelIntelligenceReport,
        *,
        learning_dir: Path | None = None,
        memory_path: Path | None = None,
        source_workflow_id: str | None = None,
        min_confidence: float = 0.5,
    ) -> list[LearningProposal]:
        """Create review-gated memory proposals for extracted intelligence."""
        proposals: list[LearningProposal] = []
        for signal in report.all_signals:
            if signal.confidence < min_confidence:
                continue
            category = (
                "skill_hint"
                if signal.category in {IntelligenceCategory.FRICTION, IntelligenceCategory.VENDOR}
                else "preference"
            )
            after = {
                "key": f"intel:{signal.key}",
                "value": {
                    "category": signal.category.value,
                    "value": signal.value,
                    "rationale": signal.rationale,
                    "support_count": signal.support_count,
                    "evidence": [item.model_dump(mode="json") for item in signal.evidence],
                },
                "category": category,
                "confidence": signal.confidence,
                "source": "travel-intelligence",
                "notes": signal.rationale,
            }
            proposals.append(
                LearningProposal(
                    proposal_type=ProposalType.MEMORY,
                    summary=f"Remember travel intelligence: {signal.rationale[:140]}",
                    source_workflow_id=source_workflow_id,
                    before=None,
                    after=after,
                )
            )
        return LearningEventStore(learning_dir, memory_path=memory_path).add_proposals(proposals)

    def _family_fit_signals(self, trips: list[Trip], *, min_support: int) -> list[PreferenceSignal]:
        family_trips = [trip for trip in trips if len(trip.travelers) >= 5]
        if len(family_trips) < min_support:
            return []
        return [
            PreferenceSignal(
                key="family_requires_three_bed_validation",
                category=IntelligenceCategory.LODGING,
                value={"travelers": 5, "minimum_beds": 3},
                confidence=_confidence(len(family_trips), len(trips)),
                support_count=len(family_trips),
                evidence=[
                    _trip_evidence(
                        trip,
                        "Trip includes at least five travelers; lodging must validate bed fit.",
                    )
                    for trip in family_trips
                ],
                rationale="Family trips require explicit sleeping-fit validation for at least 3 beds.",
            )
        ]

    def _lodging_signals(self, trips: list[Trip], *, min_support: int) -> list[PreferenceSignal]:
        signals: list[PreferenceSignal] = []
        central_hotels = [
            (trip, stay)
            for trip in trips
            for stay in trip.stays
            if stay.stay_type == StayType.HOTEL
            and _has_any_hint(stay.notes, stay.address, stay.property_name)
        ]
        rentals = [
            (trip, stay)
            for trip in trips
            for stay in trip.stays
            if stay.stay_type in {StayType.AIRBNB, StayType.VRBO, StayType.HOUSE}
        ]
        if len(central_hotels) >= min_support:
            signals.append(
                PreferenceSignal(
                    key="city_core_hotel_pattern",
                    category=IntelligenceCategory.LODGING,
                    value={"preferred_context": "central walkable city hotel"},
                    confidence=_confidence(
                        len(central_hotels), max(1, sum(len(t.stays) for t in trips))
                    ),
                    support_count=len(central_hotels),
                    evidence=[
                        _trip_evidence(
                            trip, f"{stay.property_name} has central/walkable location signals."
                        )
                        for trip, stay in central_hotels
                    ],
                    rationale="Past stays show value in central, walkable city lodging.",
                )
            )
        if len(rentals) >= min_support:
            signals.append(
                PreferenceSignal(
                    key="private_rental_pattern",
                    category=IntelligenceCategory.LODGING,
                    value={
                        "successful_stay_types": sorted(
                            {stay.stay_type.value for _, stay in rentals}
                        )
                    },
                    confidence=_confidence(len(rentals), max(1, sum(len(t.stays) for t in trips))),
                    support_count=len(rentals),
                    evidence=[
                        _trip_evidence(trip, f"{stay.property_name} used as private lodging.")
                        for trip, stay in rentals
                    ],
                    rationale="Private rentals are part of the family's successful lodging pattern when context fits.",
                )
            )
        return signals

    def _pacing_signals(self, trips: list[Trip], *, min_support: int) -> list[PreferenceSignal]:
        stays = [stay for trip in trips for stay in trip.stays if stay.nights]
        if len(stays) < min_support:
            return []
        avg_nights = sum(stay.nights or 0 for stay in stays) / len(stays)
        return [
            PreferenceSignal(
                key="average_nights_per_stop",
                category=IntelligenceCategory.PACING,
                value={
                    "average_nights": round(avg_nights, 1),
                    "minimum_recommended": max(2, int(avg_nights)),
                },
                confidence=_confidence(len(stays), len(stays) + 2),
                support_count=len(stays),
                evidence=[
                    _trip_evidence(trip, f"{stay.property_name}: {stay.nights} night(s).")
                    for trip in trips
                    for stay in trip.stays
                    if stay.nights
                ],
                rationale=f"Historical stays average {avg_nights:.1f} nights per stop; avoid overcompressed pacing.",
            )
        ]

    def _vendor_signals(self, trips: list[Trip], *, min_support: int) -> list[PreferenceSignal]:
        carrier_counts: Counter[str] = Counter(
            segment.carrier for trip in trips for segment in trip.segments if segment.carrier
        )
        signals: list[PreferenceSignal] = []
        for carrier, count in carrier_counts.most_common():
            if count < min_support:
                continue
            signals.append(
                PreferenceSignal(
                    key=f"carrier_pattern_{_slug(carrier)}",
                    category=IntelligenceCategory.VENDOR,
                    value={"carrier": carrier, "segments": count},
                    confidence=_confidence(count, sum(carrier_counts.values())),
                    support_count=count,
                    evidence=[
                        _trip_evidence(trip, f"{carrier} segment found in trip history.")
                        for trip in trips
                        if any(segment.carrier == carrier for segment in trip.segments)
                    ],
                    rationale=f"{carrier} appears repeatedly in family flight history; check loyalty and comfort fit.",
                )
            )
        return signals

    def _destination_signals(self, trips: list[Trip]) -> list[PreferenceSignal]:
        signals: list[PreferenceSignal] = []
        for trip in trips:
            if not trip.destination_summary:
                continue
            signals.append(
                PreferenceSignal(
                    key=f"destination_history_{trip.trip_id}",
                    category=IntelligenceCategory.DESTINATION,
                    value={"destination_summary": trip.destination_summary, "trip_name": trip.name},
                    confidence=0.6 if trip.status == TripStatus.LIVED else 0.4,
                    support_count=1,
                    evidence=[
                        _trip_evidence(trip, f"Destination history: {trip.destination_summary}")
                    ],
                    rationale=f"{trip.destination_summary} is known family trip context for future comparisons.",
                )
            )
        return signals

    def _friction_signals(self, trips: list[Trip], *, min_support: int) -> list[PreferenceSignal]:
        risks = [risk for trip in trips for risk in trip.risk_flags]
        counts: Counter[str] = Counter(risk.category for risk in risks)
        signals: list[PreferenceSignal] = []
        for category, count in counts.items():
            if count < min_support:
                continue
            signals.append(
                PreferenceSignal(
                    key=f"recurring_friction_{_slug(category)}",
                    category=IntelligenceCategory.FRICTION,
                    value={"risk_category": category, "count": count},
                    confidence=_confidence(count, max(1, len(risks))),
                    support_count=count,
                    evidence=[
                        _trip_evidence(trip, f"Risk category {category} appeared in trip audit.")
                        for trip in trips
                        if any(risk.category == category for risk in trip.risk_flags)
                    ],
                    rationale=f"Recurring friction category '{category}' should be checked early in future planning.",
                )
            )
        return signals


def _trip_evidence(trip: Trip, description: str) -> EvidenceRef:
    return EvidenceRef(
        source_type=EvidenceSourceType.TRIP,
        source_id=trip.trip_id,
        trip_id=trip.trip_id,
        description=description,
    )


def _confidence(support: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(0.95, max(0.45, support / total))


def _has_any_hint(*values: str | None) -> bool:
    text = " ".join(value or "" for value in values).lower()
    return any(hint in text for hint in _CENTRALITY_HINTS)


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
