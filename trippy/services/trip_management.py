"""Trip lifecycle helpers used by UI and future dashboard controls."""

from __future__ import annotations

import shutil
from pathlib import Path

from trippy import config
from trippy.models.shortlists import ShortlistCategory
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.trip_execution import TripExecutionService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService
from trippy.services.trip_state import TripStateService
from trippy.services.trip_workspace import TripWorkspaceService


class TripManagementService:
    """Delete local trip artifacts consistently.

    This intentionally does not rewrite the append-only learning/event log. Deletion is a
    state-management action, while the log remains the audit trail of what happened.
    """

    def __init__(
        self,
        *,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        workspace_service: TripWorkspaceService | None = None,
        trip_state: TripStateService | None = None,
        shortlist_store: ShortlistStore | None = None,
        execution_service: TripExecutionService | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._workspace = workspace_service or TripWorkspaceService(self._intakes, self._planner)
        self._trip_state = trip_state or TripStateService()
        self._shortlists = shortlist_store or ShortlistStore()
        self._execution = execution_service or TripExecutionService(
            shortlist_store=self._shortlists
        )

    def delete_trip(self, trip_id: str) -> dict[str, object]:
        """Delete local planning state for a trip and return a diagnostic summary."""
        deleted: list[str] = []
        missing: list[str] = []

        self._delete_path(self._intakes.path_for(trip_id), deleted, missing)
        self._delete_path(self._planner.path_for(trip_id), deleted, missing)
        self._delete_path(self._workspace.path_for(trip_id), deleted, missing)
        self._delete_path(self._execution.path_for(trip_id), deleted, missing_if_absent=False)

        canonical_path = config.TRIPS_PATH / f"{trip_id}.json"
        if self._trip_state.delete(trip_id):
            deleted.append(str(canonical_path))
        else:
            missing.append(str(canonical_path))

        for category in ShortlistCategory:
            self._delete_path(self._shortlists.path_for(trip_id, category), deleted, missing)

        self._delete_path(config.RESEARCH_PATH / trip_id, deleted, missing_if_absent=False)

        for path in self._export_paths(trip_id):
            self._delete_path(path, deleted, missing_if_absent=False)

        return {
            "trip_id": trip_id,
            "deleted_paths": deleted,
            "missing_paths": missing,
            "deleted_count": len(deleted),
            "audit_note": "Learning/event logs were preserved as an append-only audit trail.",
        }

    def _delete_path(
        self,
        path: Path,
        deleted: list[str],
        missing: list[str] | None = None,
        *,
        missing_if_absent: bool = True,
    ) -> None:
        if path.exists() and path.is_file():
            path.unlink()
            deleted.append(str(path))
        elif path.exists() and path.is_dir():
            shutil.rmtree(path)
            deleted.append(str(path))
        elif missing is not None and missing_if_absent:
            missing.append(str(path))

    def _export_paths(self, trip_id: str) -> list[Path]:
        export_root = config.EXPORT_PATH
        if not export_root.exists():
            return []
        resolved_root = export_root.resolve()
        return [
            path
            for path in export_root.rglob(f"*{trip_id}*")
            if path.is_file() and resolved_root in path.resolve().parents
        ]
