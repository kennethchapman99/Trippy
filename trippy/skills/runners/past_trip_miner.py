"""trippy-past-trip-miner skill runner.

Scans Google Drive for prior trip sheets, imports them into canonical trip records,
and stores results in JSON + SQLite.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class PastTripMinerRunner:
    skill_name = "trippy-past-trip-miner"

    def __init__(
        self,
        trips_dir: Path | None = None,
        auth_manager: Any | None = None,
        anthropic_client: Any | None = None,
    ) -> None:
        from trippy import config

        self._trips_dir = trips_dir or config.TRIPS_PATH
        self._auth_manager = auth_manager
        self._anthropic_client = anthropic_client

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        folder_id: str | None = inputs.get("folder_id")
        query: str = inputs.get("query", "trip")
        max_sheets: int = inputs.get("max_sheets", 50)
        dry_run: bool = inputs.get("dry_run", False)

        sheets = self._discover_sheets(folder_id, query, max_sheets)

        if dry_run:
            return {
                "sheets_found": len(sheets),
                "sheets": [{"name": s["name"], "id": s["id"]} for s in sheets],
                "dry_run": True,
            }

        imported = 0
        updated = 0
        failed = 0
        trip_ids: list[str] = []

        for sheet in sheets:
            try:
                result = self._import_sheet(sheet)
                if result.get("ok"):
                    if result.get("created"):
                        imported += 1
                    else:
                        updated += 1
                    tid = result.get("trip_id", "")
                    if tid:
                        trip_ids.append(tid)
                else:
                    failed += 1
                    logger.warning(
                        "Failed to import sheet %r: %s", sheet["name"], result.get("error")
                    )
            except Exception as exc:
                failed += 1
                logger.error("Unhandled error importing %r: %s", sheet["name"], exc)

        logger.info("PastTripMiner: %d imported, %d updated, %d failed", imported, updated, failed)

        return {
            "sheets_scanned": len(sheets),
            "trips_imported": imported,
            "trips_updated": updated,
            "trips_failed": failed,
            "trip_ids": trip_ids,
            "summary": (
                f"Found {len(sheets)} sheets. "
                f"{imported} new trips, {updated} updated, {failed} failed."
            ),
        }

    def _discover_sheets(
        self, folder_id: str | None, query: str, max_sheets: int
    ) -> list[dict[str, Any]]:
        from trippy.ingest.google_auth import GoogleAuthManager

        auth = self._auth_manager or GoogleAuthManager()

        if folder_id:
            from trippy.importers.drive_importer import DriveFolderImporter

            importer = DriveFolderImporter(auth_manager=auth)
            return importer.list_files(folder_id)[:max_sheets]

        # Search Drive
        drive = auth.build_service("drive", "v3")
        resp = (
            drive.files()
            .list(
                q=(
                    f"name contains '{query}' "
                    "and mimeType = 'application/vnd.google-apps.spreadsheet' "
                    "and trashed = false"
                ),
                fields="files(id,name)",
                pageSize=min(max_sheets, 100),
            )
            .execute()
        )
        return cast(list[dict[str, Any]], resp.get("files", []))

    def _import_sheet(self, sheet: dict[str, Any]) -> dict[str, Any]:
        from trippy.db import make_session_factory
        from trippy.db.models import Trip as DbTrip
        from trippy.importers.sheet_importer import SheetImporter
        from trippy.ingest.google_auth import GoogleAuthManager
        from trippy.services.trip_state import TripStateService

        auth = self._auth_manager or GoogleAuthManager()
        importer = SheetImporter(auth_manager=auth, anthropic_client=self._anthropic_client)

        result = importer.import_file(sheet["id"])
        if not result.ok:
            return {"ok": False, "error": str(result.errors)}

        # Persist imported DB trips as canonical JSON
        state_svc = TripStateService(trips_dir=self._trips_dir)
        trip_ids: list[str] = []
        factory = make_session_factory()
        with factory() as session:
            for db_trip_id in result.db_trip_ids:
                db_trip = session.get(DbTrip, db_trip_id)
                if db_trip is None:
                    logger.warning(
                        "Sheet import reported db trip id %s but it was not found",
                        db_trip_id,
                    )
                    continue
                canonical_trip = state_svc.from_db_trip(db_trip)
                state_svc.save(canonical_trip)
                trip_ids.append(canonical_trip.trip_id)

        created = result.trips_created > 0
        return {
            "ok": True,
            "created": created,
            "trip_id": trip_ids[0] if trip_ids else "",
            "trip_ids": trip_ids,
        }
