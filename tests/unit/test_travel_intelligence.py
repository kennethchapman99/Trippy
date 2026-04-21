"""Tests for extracting reusable travel intelligence from trip history."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from trippy.memory.store import MemoryStore
from trippy.models.trip import RiskFlag, RiskSeverity, Stay, StayType, Traveler, Trip, TripStatus
from trippy.services.learning import LearningEventStore, ProposalType
from trippy.services.travel_intelligence import TravelIntelligenceService


def test_extracts_family_lodging_and_pacing_signals() -> None:
    trip = Trip(
        trip_id="tokyo-2026",
        name="Tokyo 2026",
        status=TripStatus.LIVED,
        destination_summary="Tokyo",
        travelers=[Traveler(name=f"Traveler {i}") for i in range(5)],
        stays=[
            Stay(
                stay_id="stay-1",
                stay_type=StayType.HOTEL,
                property_name="Central Boutique Hotel",
                city="Tokyo",
                country="Japan",
                check_in=date(2026, 3, 10),
                check_out=date(2026, 3, 14),
                room_type="king suite with 3 beds",
                notes="central walkable near transit",
            )
        ],
    )

    report = TravelIntelligenceService().analyze([trip])

    keys = {signal.key for signal in report.all_signals}
    assert "family_requires_three_bed_validation" in keys
    assert "city_core_hotel_pattern" in keys
    assert "average_nights_per_stop" in keys


def test_proposes_memory_without_applying_until_approved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trippy import config

    memory_path = tmp_path / "memory.json"
    monkeypatch.setattr(config, "MEMORY_PATH", memory_path)
    trip = Trip(
        trip_id="rome-2026",
        name="Rome 2026",
        status=TripStatus.LIVED,
        travelers=[Traveler(name=f"Traveler {i}") for i in range(5)],
        risk_flags=[
            RiskFlag(
                risk_id="risk-1",
                severity=RiskSeverity.MEDIUM,
                category="pacing",
                description="Too many stops",
            )
        ],
    )
    service = TravelIntelligenceService()
    report = service.analyze([trip])

    proposals = service.propose_memory_updates(report, learning_dir=tmp_path / "learning")

    assert proposals
    assert all(proposal.proposal_type == ProposalType.MEMORY for proposal in proposals)
    assert not memory_path.exists()
    LearningEventStore(tmp_path / "learning").approve(proposals[0].id)
    assert MemoryStore(memory_path).all_entries()
