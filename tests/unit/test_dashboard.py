"""Tests for static dashboard generation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from trippy.models.trip import RiskFlag, RiskSeverity, Trip, TripStatus
from trippy.services.dashboard import DashboardService
from trippy.services.trip_state import TripStateService


def test_dashboard_builds_past_planned_and_idea_tiles(tmp_path: Path) -> None:
    trip_state = TripStateService(trips_dir=tmp_path / "trips")
    trip_state.save(
        Trip(
            trip_id="japan-2026",
            name="Japan 2026",
            status=TripStatus.LIVED,
            destination_summary="Tokyo and Kyoto",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 14),
            notes="Food and rail pacing worked well.",
        )
    )
    trip_state.save(
        Trip(
            trip_id="portugal-2027",
            name="Portugal 2027",
            status=TripStatus.PLANNED,
            destination_summary="Lisbon and Porto",
            start_date=date(2027, 4, 1),
            end_date=date(2027, 4, 10),
            risk_flags=[
                RiskFlag(
                    risk_id="risk-1",
                    severity=RiskSeverity.HIGH,
                    category="lodging",
                    description="Bed setup missing for family of 5.",
                )
            ],
        )
    )

    dashboard = DashboardService(trip_state=trip_state).write_dashboard(tmp_path / "dashboard")

    assert len(dashboard.past_trips) == 1
    assert len(dashboard.planned_trips) == 1
    assert dashboard.ideas
    assert Path(dashboard.exports["html"]).exists()
    assert "Trippy" in Path(dashboard.exports["html"]).read_text(encoding="utf-8")
    assert json.loads(Path(dashboard.exports["json"]).read_text(encoding="utf-8"))["planned_trips"][
        0
    ]["key_risks"]
