"""Tests for roadmap phase status/orchestration service."""

from __future__ import annotations

from datetime import date

from trippy.memory.store import MemoryStore
from trippy.models.trip import Trip, TripStatus
from trippy.services.phase_planner import PhasePlannerService
from trippy.services.trip_state import TripStateService


def test_status_shows_phase_2_complete_when_google_files_exist(tmp_path, monkeypatch) -> None:
    from trippy import config

    creds = tmp_path / "gmail_credentials.json"
    token = tmp_path / "gmail_token.json"
    creds.write_text("{}", encoding="utf-8")
    token.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", creds)
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", token)
    monkeypatch.setattr(config, "GOOGLE_TOKEN_PATH", tmp_path / "google_token.json")

    planner = PhasePlannerService(memory_path=tmp_path / "memory.json", trips_dir=tmp_path / "trips")
    phases = planner.status()
    phase2 = next(p for p in phases if p.phase == 2)
    assert phase2.complete
    assert not phase2.blockers


def test_status_marks_phase_3_complete_with_trips_and_preferences(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.json")
    memory.set(
        key="pref:preferences_object",
        value={"comfort_over_price": True},
        category="preference",
        confidence=0.9,
        source="test",
    )

    trip_svc = TripStateService(tmp_path / "trips")
    trip_svc.save(
        Trip(
            trip_id="japan-2027",
            name="Japan 2027",
            status=TripStatus.BOOKED,
            start_date=date(2027, 3, 10),
            end_date=date(2027, 3, 24),
        )
    )

    planner = PhasePlannerService(memory_path=tmp_path / "memory.json", trips_dir=tmp_path / "trips")
    phases = planner.status()
    phase3 = next(p for p in phases if p.phase == 3)
    assert phase3.complete


def test_run_phase_2_reports_file_existence(tmp_path, monkeypatch) -> None:
    from trippy import config

    creds = tmp_path / "gmail_credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", creds)
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", tmp_path / "gmail_token.json")
    monkeypatch.setattr(config, "GOOGLE_TOKEN_PATH", tmp_path / "google_token.json")

    planner = PhasePlannerService(memory_path=tmp_path / "memory.json", trips_dir=tmp_path / "trips")
    result = planner.run_phase(2)
    assert result["phase"] == 2
    assert result["credentials_exist"] is True
    assert result["token_exists"] is False


def test_run_phase_unsupported_returns_error(tmp_path) -> None:
    planner = PhasePlannerService(memory_path=tmp_path / "memory.json", trips_dir=tmp_path / "trips")
    result = planner.run_phase(99)
    assert "error" in result


def test_phase_7_seeds_choice_criteria_and_trip_override(tmp_path) -> None:
    trip_svc = TripStateService(tmp_path / "trips")
    trip_svc.save(
        Trip(
            trip_id="japan-2027",
            name="Japan 2027",
            status=TripStatus.PLANNED,
            start_date=date(2027, 3, 10),
            end_date=date(2027, 3, 24),
        )
    )

    planner = PhasePlannerService(memory_path=tmp_path / "memory.json", trips_dir=tmp_path / "trips")
    result = planner.run_phase(7, trip_id="japan-2027")
    assert result["phase"] == 7

    memory = MemoryStore(tmp_path / "memory.json")
    assert memory.get_value("pref:flight_choice_criteria") is not None
    assert memory.get_value("pref:stay_choice_criteria") is not None
    assert memory.get_value("trip_pref:japan-2027:stay") is not None


def test_new_trip_readiness_requires_phases_2_3_4_7_8(tmp_path, monkeypatch) -> None:
    from trippy import config

    # Satisfy phase 2
    creds = tmp_path / "gmail_credentials.json"
    token = tmp_path / "gmail_token.json"
    creds.write_text("{}", encoding="utf-8")
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", creds)
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", token)
    monkeypatch.setattr(config, "GOOGLE_TOKEN_PATH", tmp_path / "google_token.json")

    # Satisfy phases 3/4/8 baseline with trip + preferences + sheet id
    trip_svc = TripStateService(tmp_path / "trips")
    trip = Trip(
        trip_id="japan-2027",
        name="Japan 2027",
        status=TripStatus.BOOKED,
        start_date=date(2027, 3, 10),
        end_date=date(2027, 3, 24),
    )
    trip.sync.google_sheet_id = "sheet-123"
    trip_svc.save(trip)

    memory = MemoryStore(tmp_path / "memory.json")
    memory.set(
        key="pref:preferences_object",
        value={"comfort_over_price": True},
        category="preference",
        confidence=0.9,
        source="test",
    )

    # Satisfy phase 7 requirements
    memory.set(
        key="pref:flight_choice_criteria",
        value={"prefer_nonstop": True},
        category="preference",
        source="test",
    )
    memory.set(
        key="pref:stay_choice_criteria",
        value={"allow_stay_types": ["hotel", "airbnb"]},
        category="preference",
        source="test",
    )
    memory.set(
        key="trip_pref:japan-2027:stay",
        value={"vibe": "walkable"},
        category="trip_insight",
        source="test",
    )

    planner = PhasePlannerService(memory_path=tmp_path / "memory.json", trips_dir=tmp_path / "trips")
    readiness = planner.new_trip_test_readiness()

    assert readiness["ready"] is True
    assert readiness["failing"] == []
