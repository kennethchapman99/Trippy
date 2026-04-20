"""Roadmap phase status checks + orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PhaseStatus:
    phase: int
    title: str
    complete: bool
    blockers: list[str]
    next_step: str


class PhasePlannerService:
    """Determines readiness/completion of roadmap phases 2-6.

    The checks are intentionally deterministic and lightweight, so teams can
    quickly see what to do next without running a full agent session.
    """

    def __init__(self, memory_path: Path | None = None, trips_dir: Path | None = None) -> None:
        from trippy import config

        self._memory_path = memory_path or config.MEMORY_PATH
        self._trips_dir = trips_dir or config.TRIPS_PATH

    def status(self) -> list[PhaseStatus]:
        from trippy import config
        from trippy.memory.store import MemoryStore
        from trippy.services.trip_state import TripStateService

        memory = MemoryStore(self._memory_path)
        trip_svc = TripStateService(self._trips_dir)
        trips = trip_svc.load_all()

        has_google_creds = (
            config.GMAIL_CREDENTIALS_PATH.exists()
            and (config.GMAIL_TOKEN_PATH.exists() or config.GOOGLE_TOKEN_PATH.exists())
        )
        has_trips = len(trips) > 0
        has_preferences = memory.get_value("pref:preferences_object") is not None
        has_sheeted_trip = any(bool(t.sync.google_sheet_id) for t in trips)
        has_confirmation = any(bool(t.confirmations) for t in trips)
        has_risks = any(bool(t.risk_flags) for t in trips)

        phases: list[PhaseStatus] = []
        phases.append(
            PhaseStatus(
                phase=2,
                title="Live Google credentials",
                complete=has_google_creds,
                blockers=[] if has_google_creds else ["Missing Google credentials/token files"],
                next_step="Run: trippy phase-run 2",
            )
        )
        phases.append(
            PhaseStatus(
                phase=3,
                title="Past trip mining + preference extraction",
                complete=has_trips and has_preferences,
                blockers=[
                    *([] if has_trips else ["No canonical trips found in ~/.trippy/trips"]),
                    *([] if has_preferences else ["No extracted preferences in memory store"]),
                ],
                next_step="Run: trippy phase-run 3 --folder-id <drive_folder_id>",
            )
        )
        phases.append(
            PhaseStatus(
                phase=4,
                title="New trip sheet generation",
                complete=has_sheeted_trip,
                blockers=[] if has_sheeted_trip else ["No trip linked to a Google Sheet yet"],
                next_step='Run: trippy phase-run 4 --trip-idea "Japan March 2027"',
            )
        )
        phases.append(
            PhaseStatus(
                phase=5,
                title="Gmail reconciliation in production",
                complete=has_confirmation,
                blockers=[] if has_confirmation else ["No parsed confirmations linked to trips yet"],
                next_step="Run: trippy phase-run 5 --max-emails 50",
            )
        )
        phases.append(
            PhaseStatus(
                phase=6,
                title="Friction audit + self-improving loop",
                complete=has_risks,
                blockers=[] if has_risks else ["No persisted friction/risk flags on trips yet"],
                next_step="Run: trippy phase-run 6 --trip-id <trip_id>",
            )
        )
        return phases

    def run_phase(self, phase: int, **kwargs: Any) -> dict[str, Any]:
        """Execute the main workflow for one roadmap phase."""
        if phase == 2:
            return self._run_phase_2()
        if phase == 3:
            return self._run_phase_3(**kwargs)
        if phase == 4:
            return self._run_phase_4(**kwargs)
        if phase == 5:
            return self._run_phase_5(**kwargs)
        if phase == 6:
            return self._run_phase_6(**kwargs)
        return {"error": f"Unsupported phase: {phase}"}

    def _run_phase_2(self) -> dict[str, Any]:
        from trippy import config

        return {
            "phase": 2,
            "credentials_path": str(config.GMAIL_CREDENTIALS_PATH),
            "token_path": str(config.GMAIL_TOKEN_PATH),
            "google_token_path": str(config.GOOGLE_TOKEN_PATH),
            "credentials_exist": config.GMAIL_CREDENTIALS_PATH.exists(),
            "token_exists": config.GMAIL_TOKEN_PATH.exists() or config.GOOGLE_TOKEN_PATH.exists(),
        }

    def _run_phase_3(self, **kwargs: Any) -> dict[str, Any]:
        from trippy.skills.runners.past_trip_miner import PastTripMinerRunner
        from trippy.skills.runners.preference_extractor import PreferenceExtractorRunner

        miner = PastTripMinerRunner()
        mined = miner.run(
            {
                "folder_id": kwargs.get("folder_id"),
                "query": kwargs.get("query", "trip"),
                "max_sheets": kwargs.get("max_sheets", 50),
            }
        )
        extractor = PreferenceExtractorRunner()
        extracted = extractor.run(
            {
                "trip_ids": mined.get("trip_ids") or None,
                "min_evidence_trips": kwargs.get("min_evidence_trips", 2),
            }
        )
        return {"phase": 3, "mined": mined, "extracted": extracted}

    def _run_phase_4(self, **kwargs: Any) -> dict[str, Any]:
        from trippy.skills.runners.trip_sheet_creator import TripSheetCreatorRunner

        runner = TripSheetCreatorRunner()
        result = runner.run(
            {
                "trip_idea": kwargs.get("trip_idea", ""),
                "folder_id": kwargs.get("folder_id"),
                "template_sheet_id": kwargs.get("template_sheet_id"),
            }
        )
        return {"phase": 4, "created": result}

    def _run_phase_5(self, **kwargs: Any) -> dict[str, Any]:
        from trippy.skills.runners.gmail_reconciler import GmailReconcilerRunner

        runner = GmailReconcilerRunner()
        result = runner.run({"max_emails": kwargs.get("max_emails", 50)})
        return {"phase": 5, "reconciled": result}

    def _run_phase_6(self, **kwargs: Any) -> dict[str, Any]:
        from trippy import config
        from trippy.memory.store import MemoryStore
        from trippy.services.trip_state import TripStateService
        from trippy.skills.runners.friction_audit import FrictionAuditRunner

        trip_id = kwargs.get("trip_id")
        if not trip_id:
            trip_svc = TripStateService(self._trips_dir)
            active = trip_svc.find_active()
            trip_id = active[0].trip_id if active else ""
            if not trip_id:
                return {"phase": 6, "error": "No active trips found to audit"}

        runner = FrictionAuditRunner()
        audit_result = runner.run({"trip_id": trip_id, "check_preferences": True})

        # Minimal self-improvement loop: store a reusable hint when high/critical
        critical = int(audit_result.get("critical", 0))
        high = int(audit_result.get("high", 0))
        if critical > 0 or high > 0:
            memory = MemoryStore(config.MEMORY_PATH)
            memory.set(
                key="hint:always-run-friction-audit-after-reconcile",
                value=True,
                category="skill_hint",
                confidence=0.8,
                source="phase-runner",
                notes="High/critical risk found; enforce post-reconcile friction audit.",
            )

        return {"phase": 6, "audit": audit_result}
