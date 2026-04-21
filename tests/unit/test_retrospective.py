"""Tests for post-trip retrospective learning proposals."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from trippy.memory.store import MemoryStore
from trippy.models.retrospective import TripRetrospectiveInput
from trippy.models.trip import Trip, TripStatus
from trippy.services.learning import LearningEventStore
from trippy.services.retrospective import RetrospectiveService
from trippy.services.trip_state import TripStateService


def test_retrospective_creates_reviewable_proposals_without_mutating_memory(
    tmp_path: Path,
) -> None:
    memory_path = tmp_path / "memory.json"
    learning = LearningEventStore(tmp_path / "learning", memory_path=memory_path)
    trip_state = TripStateService(trips_dir=tmp_path / "trips")
    trip_state.save(
        Trip(
            trip_id="japan-2026",
            name="Japan 2026",
            status=TripStatus.LIVED,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1) + timedelta(days=14),
        )
    )

    result = RetrospectiveService(trip_state=trip_state, learning_store=learning).record(
        TripRetrospectiveInput(
            trip_id="japan-2026",
            worked=["Central hotels near rail stations were worth it."],
            friction=["One transfer day was too compressed."],
            hard_rules=["Never book a family city stay without explicit 3-bed confirmation."],
            never_repeat=["Do not schedule luggage-heavy transfers before breakfast."],
            favorites=["Small ramen tour was a highlight."],
            pace="Two major activities per day was the upper limit.",
        )
    )

    assert result.workflow_id
    assert len(result.proposal_ids) == 5
    assert not memory_path.exists()

    approved = learning.approve(result.proposal_ids[0])
    assert approved.status.value == "approved"
    assert MemoryStore(memory_path).all_entries()
