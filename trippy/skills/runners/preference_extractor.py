"""trippy-preference-extractor skill runner."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from trippy.memory.store import MemoryStore
from trippy.models.profile import FamilyProfile, TravelerProfile
from trippy.models.trip import Traveler, Trip
from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType

logger = logging.getLogger(__name__)


class PreferenceExtractorRunner:
    skill_name = "trippy-preference-extractor"

    def __init__(
        self,
        memory_store: Any | None = None,
        trips_dir: Path | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._trips_dir = trips_dir

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from trippy import config
        from trippy.memory.preference_writer import PreferenceWriter
        from trippy.services.trip_state import TripStateService

        memory = self._memory_store or MemoryStore(config.MEMORY_PATH)
        trips_dir = self._trips_dir or config.TRIPS_PATH
        state_svc = TripStateService(trips_dir=trips_dir)

        # Load trips to analyse
        trip_ids: list[str] | None = inputs.get("trip_ids")
        min_evidence = inputs.get("min_evidence_trips", 2)
        propose_learning: bool = inputs.get("propose_learning", True)
        learning_dir = inputs.get("learning_dir")

        if trip_ids:
            trips = [t for tid in trip_ids if (t := state_svc.load(tid)) is not None]
        else:
            trips = state_svc.load_all()

        if not trips:
            return {"skip_reason": "No trips found to analyse", "preferences_written": {}}

        writer = PreferenceWriter(memory=memory)
        candidates = writer.extract_candidates(trips, min_trips=min_evidence)
        learning_store = LearningEventStore(
            _as_path(learning_dir),
            memory_path=memory.path,
        )
        proposals: list[LearningProposal] = []
        preferences_proposed: dict[str, str] = {}
        profile_updates: list[str] = []

        if propose_learning:
            for name, candidate in candidates.items():
                proposals.append(_candidate_to_proposal(candidate, memory))
                preferences_proposed[name] = str(candidate["reason"])

            profile_proposal, profile_updates = _profile_update_proposal(memory, trips)
            if profile_proposal is not None:
                proposals.append(profile_proposal)

            proposals = learning_store.add_proposals(proposals)

        from trippy.services.travel_intelligence import TravelIntelligenceService

        intelligence = TravelIntelligenceService().analyze(trips, min_support=min_evidence)
        intelligence_proposals: list[LearningProposal] = []
        if propose_learning:
            intelligence_proposals = TravelIntelligenceService().propose_memory_updates(
                intelligence,
                learning_dir=_as_path(learning_dir),
                memory_path=memory.path,
                min_confidence=0.5,
            )
            proposals.extend(intelligence_proposals)

        logger.info(
            "PreferenceExtractor: proposed %d preferences, %d profile updates",
            len(preferences_proposed),
            len(profile_updates),
        )

        return {
            "trips_analysed": len(trips),
            "lived_trips": len([t for t in trips if t.status.value == "lived"]),
            "preferences_written": {},
            "preferences_proposed": preferences_proposed,
            "intelligence_summary": intelligence.summary,
            "intelligence_signals": len(intelligence.all_signals),
            "learning_proposals": [proposal.id for proposal in proposals],
            "profile_updates": profile_updates,
            "review_required": True,
            "skip_reason": None,
        }


def _as_path(path: Any) -> Path | None:
    return Path(path) if path else None


def _candidate_to_proposal(
    candidate: dict[str, Any],
    memory: MemoryStore,
) -> LearningProposal:
    key = str(candidate["key"])
    existing = memory.get(key)
    return LearningProposal(
        proposal_type=ProposalType.MEMORY,
        summary=f"Review extracted family preference: {candidate['reason']}",
        before=existing.model_dump(mode="json") if existing else None,
        after={
            "key": key,
            "value": candidate["value"],
            "category": candidate["category"],
            "confidence": candidate["confidence"],
            "source": candidate["source"],
            "notes": candidate.get("notes"),
        },
    )


def _profile_update_proposal(
    memory: MemoryStore,
    trips: list[Trip],
) -> tuple[LearningProposal | None, list[str]]:
    from trippy.memory.profile_manager import ProfileManager

    current = ProfileManager(memory=memory).load()
    updated = FamilyProfile.model_validate(current.model_dump(mode="json"))
    updates: list[str] = []

    for trip in trips:
        for traveler in trip.travelers:
            updates.extend(_merge_traveler(updated, traveler, source_trip_id=trip.trip_id))

    if updated.model_dump(mode="json") == current.model_dump(mode="json"):
        return None, []

    return (
        LearningProposal(
            proposal_type=ProposalType.MEMORY,
            summary=f"Review family profile updates from trip history ({len(updates)} change(s))",
            before={
                "key": "profile:family",
                "value": current.model_dump(mode="json"),
                "category": "profile",
            },
            after={
                "key": "profile:family",
                "value": updated.model_dump(mode="json"),
                "category": "profile",
                "confidence": 1.0,
                "source": "preference-extractor",
                "notes": "; ".join(updates[:8]),
            },
        ),
        updates,
    )


def _merge_traveler(
    profile: FamilyProfile,
    traveler: Traveler,
    *,
    source_trip_id: str,
) -> list[str]:
    existing = profile.get_traveler(traveler.name)
    if existing is None:
        profile.travelers.append(
            TravelerProfile(
                name=traveler.name,
                passport_country=traveler.passport_country,
                passport_expiry=traveler.passport_expiry,
                date_of_birth=traveler.date_of_birth,
                is_minor=traveler.is_minor,
            )
        )
        return [f"Add traveler {traveler.name} from {source_trip_id}"]

    updates: list[str] = []
    if traveler.passport_expiry and (
        existing.passport_expiry is None or traveler.passport_expiry > existing.passport_expiry
    ):
        existing.passport_expiry = traveler.passport_expiry
        updates.append(f"Update {traveler.name} passport expiry from {source_trip_id}")
    if traveler.passport_country and not existing.passport_country:
        existing.passport_country = traveler.passport_country
        updates.append(f"Update {traveler.name} passport country from {source_trip_id}")
    return updates
