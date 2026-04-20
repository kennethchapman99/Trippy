"""Unit tests for Trippy agent orchestration and intent routing."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from trippy.agent import TrIppyAgent
from trippy.models.trip import Trip, TripStatus


def _mock_anthropic_client(response_text: str = "ok") -> MagicMock:
    block = SimpleNamespace(type="text", text=response_text)
    message = SimpleNamespace(content=[block], stop_reason="end_turn")
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _seed_trip(
    agent: TrIppyAgent,
    *,
    trip_id: str,
    name: str,
    status: TripStatus,
    start_offset_days: int,
    with_sheet: bool = False,
) -> Trip:
    start = date.today() + timedelta(days=start_offset_days)
    trip = Trip(
        trip_id=trip_id,
        name=name,
        status=status,
        start_date=start,
        end_date=start + timedelta(days=7),
    )
    if with_sheet:
        trip.sync.google_sheet_id = "sheet-123"
    agent._trip_svc.save(trip)
    return trip


def test_reconcile_intent_auto_runs_gmail_reconciler(monkeypatch, tmp_path: Path) -> None:
    client = _mock_anthropic_client("reconciled")
    agent = TrIppyAgent(
        anthropic_client=client,
        memory_path=tmp_path / "memory.json",
        trips_dir=tmp_path / "trips",
    )
    trip = _seed_trip(
        agent,
        trip_id="tokyo-2026",
        name="Tokyo 2026",
        status=TripStatus.BOOKED,
        start_offset_days=10,
    )

    captured: dict[str, object] = {}

    def _fake_run_skill(skill_name: str, inputs: dict[str, object]) -> str:
        captured["skill_name"] = skill_name
        captured["inputs"] = inputs
        return '{"ok": true}'

    monkeypatch.setattr("trippy.agent._run_skill", _fake_run_skill)

    result = agent.chat("Please reconcile Gmail confirmations for this trip.")

    assert result == "reconciled"
    assert captured["skill_name"] == "trippy-gmail-reconciler"
    assert captured["inputs"] == {"trip_id": trip.trip_id}
    assert client.messages.create.called


def test_trip_selection_prefers_explicit_trip(monkeypatch, tmp_path: Path) -> None:
    client = _mock_anthropic_client("done")
    agent = TrIppyAgent(
        anthropic_client=client,
        memory_path=tmp_path / "memory.json",
        trips_dir=tmp_path / "trips",
    )
    _seed_trip(
        agent,
        trip_id="iceland-2026",
        name="Iceland 2026",
        status=TripStatus.BOOKED,
        start_offset_days=3,
    )
    explicit = _seed_trip(
        agent,
        trip_id="japan-2026",
        name="Japan 2026",
        status=TripStatus.BOOKED,
        start_offset_days=30,
    )

    captured: dict[str, object] = {}

    def _fake_run_skill(skill_name: str, inputs: dict[str, object]) -> str:
        captured["trip_id"] = inputs.get("trip_id")
        return '{"ok": true}'

    monkeypatch.setattr("trippy.agent._run_skill", _fake_run_skill)

    agent.chat("Reconcile bookings for Japan 2026 please.")
    assert captured["trip_id"] == explicit.trip_id


def test_trip_scoped_intent_without_available_trip_asks_clarifying_question(tmp_path: Path) -> None:
    client = _mock_anthropic_client("should-not-run")
    agent = TrIppyAgent(
        anthropic_client=client,
        memory_path=tmp_path / "memory.json",
        trips_dir=tmp_path / "trips",
    )

    result = agent.chat("Can you audit friction for our trip?")

    assert "Which trip should I use" in result
    client.messages.create.assert_not_called()


def test_operations_intent_runs_deterministic_preflight(monkeypatch, tmp_path: Path) -> None:
    client = _mock_anthropic_client("ops response")
    agent = TrIppyAgent(
        anthropic_client=client,
        memory_path=tmp_path / "memory.json",
        trips_dir=tmp_path / "trips",
    )
    trip = _seed_trip(
        agent,
        trip_id="rome-2026",
        name="Rome 2026",
        status=TripStatus.BOOKED,
        start_offset_days=1,
        with_sheet=True,
    )

    def _fake_execute_tool(name: str, *_args, **_kwargs) -> str:
        if name == "run_friction_audit":
            return '{"ok": true, "risks": []}'
        return '{"ok": true}'

    monkeypatch.setattr("trippy.agent._execute_tool", _fake_execute_tool)
    monkeypatch.setattr(agent, "_refresh_sheet_sync", lambda _trip: {"ok": True})

    result = agent.chat("We landed. Need transfer and gate instructions now.")

    assert result == "ops response"
    called_system_prompt = client.messages.create.call_args.kwargs["system"]
    assert "Operations Mode (During-Trip)" in called_system_prompt
    assert trip.trip_id in called_system_prompt
    assert "run_friction_audit" in called_system_prompt
    assert "sheet_sync_refresh" in called_system_prompt
