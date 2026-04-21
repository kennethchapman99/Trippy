"""Tests that learning paths create proposals instead of mutating memory."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from trippy.agent import _execute_tool
from trippy.memory.preference_writer import PreferenceWriter
from trippy.memory.store import MemoryStore
from trippy.models.trip import Segment, Stay, StayType, Traveler, Trip, TripStatus
from trippy.services.learning import LearningEventStore
from trippy.services.trip_state import TripStateService
from trippy.skills.runners.preference_extractor import PreferenceExtractorRunner


def test_preference_extractor_proposes_without_mutating_memory(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.json")
    trips_dir = tmp_path / "trips"
    learning_dir = tmp_path / "learning"
    trip_svc = TripStateService(trips_dir=trips_dir)
    trip_svc.save(_lived_trip("portugal-2025", date(2025, 3, 1)))

    result = PreferenceExtractorRunner(memory_store=memory, trips_dir=trips_dir).run(
        {
            "min_evidence_trips": 1,
            "learning_dir": learning_dir,
        }
    )

    assert result["preferences_written"] == {}
    assert result["preferences_proposed"]
    assert result["learning_proposals"]
    assert memory.all_entries() == []

    store = LearningEventStore(learning_dir, memory_path=memory.path)
    proposal = store.approve(result["learning_proposals"][0])
    assert proposal.status.value == "approved"
    assert MemoryStore(memory.path).all_entries()


def test_agent_memory_tool_creates_reviewable_proposal(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.json")
    trip_svc = TripStateService(trips_dir=tmp_path / "trips")
    learning_dir = tmp_path / "learning"

    result = _execute_tool(
        "update_memory",
        {
            "key": "pref:test",
            "value": "Prefer central boutique hotels in cities.",
            "category": "preference",
            "confidence": 0.8,
        },
        memory,
        trip_svc,
        learning_dir,
    )

    assert '"review_required": true' in result
    assert memory.all_entries() == []
    assert LearningEventStore(learning_dir, memory_path=memory.path).list_proposals()


def test_preference_writer_direct_write_requires_approval(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.json")

    with pytest.raises(PermissionError):
        PreferenceWriter(memory).extract_and_write(
            [_lived_trip("italy-2025", date(2025, 5, 1))],
            min_trips=1,
        )

    assert memory.all_entries() == []


def _lived_trip(trip_id: str, start: date) -> Trip:
    depart = datetime.combine(start, datetime.min.time()).replace(hour=9)
    arrive = depart + timedelta(hours=7)
    return Trip(
        trip_id=trip_id,
        name="Portugal 2025",
        status=TripStatus.LIVED,
        destination_summary="Lisbon and Porto",
        start_date=start,
        end_date=start + timedelta(days=8),
        travelers=[
            Traveler(name="Ken", passport_country="CAN"),
            Traveler(name="Traveler 2"),
            Traveler(name="Traveler 3"),
            Traveler(name="Traveler 4"),
            Traveler(name="Traveler 5"),
        ],
        segments=[
            Segment(
                segment_id="flight-1",
                carrier="Air Canada",
                origin="YYZ",
                destination="LIS",
                depart_at=depart,
                arrive_at=arrive,
            )
        ],
        stays=[
            Stay(
                stay_id="stay-1",
                stay_type=StayType.HOTEL,
                property_name="Central Lisbon Hotel",
                city="Lisbon",
                country="Portugal",
                check_in=start,
                check_out=start + timedelta(days=4),
                notes="central walkable boutique hotel; king bed plus 2 twins",
            )
        ],
    )
