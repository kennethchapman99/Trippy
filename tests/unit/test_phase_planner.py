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
