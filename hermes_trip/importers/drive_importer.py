"""Google Drive folder importer — lists Sheets in a folder and imports each one."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from hermes_trip.importers.sheet_importer import ImportResult, SheetImporter

logger = logging.getLogger(__name__)

SHEETS_MIME = "application/vnd.google-apps.spreadsheet"


# ---------------------------------------------------------------------------
# URL / ID helpers
# ---------------------------------------------------------------------------


def _folder_id_from_url_or_id(url_or_id: str) -> str:
    """Extract Drive folder ID from a URL or return a bare ID unchanged."""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]+", url_or_id):
        return url_or_id
    raise ValueError(f"Cannot extract folder ID from: {url_or_id!r}")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DriveFolderResult:
    folder_id: str
    files_found: int = 0
    results: list[ImportResult] = field(default_factory=list)

    @property
    def total_created(self) -> int:
        return sum(r.trips_created for r in self.results)

    @property
    def total_updated(self) -> int:
        return sum(r.trips_updated for r in self.results)

    @property
    def errors(self) -> list[str]:
        return [e for r in self.results for e in r.errors]


# ---------------------------------------------------------------------------
# DriveFolderImporter
# ---------------------------------------------------------------------------


class DriveFolderImporter:
    """Lists Google Sheets in a Drive folder and imports each one.

    Pass ``drive_service`` and ``sheets_service`` to inject mocks in tests.
    """

    def __init__(
        self,
        auth_manager: Any | None = None,
        drive_service: Any | None = None,
        sheets_service: Any | None = None,
        db_url: str | None = None,
        anthropic_client: Any | None = None,
    ) -> None:
        self._auth_manager = auth_manager
        self._drive_service = drive_service
        self._sheets_service = sheets_service
        self._db_url = db_url
        self._anthropic_client = anthropic_client

    # ------------------------------------------------------------------

    def import_folder(self, folder_url_or_id: str) -> DriveFolderResult:
        """Import all Google Sheets found in the given Drive folder."""
        folder_id = _folder_id_from_url_or_id(folder_url_or_id)
        result = DriveFolderResult(folder_id=folder_id)

        files = self._list_sheets_in_folder(folder_id)
        result.files_found = len(files)

        for f in files:
            sheet_id = f["id"]
            name = f.get("name", sheet_id)
            logger.info("Importing sheet '%s' (%s)", name, sheet_id)
            importer = SheetImporter(
                db_url=self._db_url,
                anthropic_client=self._anthropic_client,
                auth_manager=self._auth_manager,
                sheets_service=self._get_sheets_service(),
            )
            r = importer.import_file(sheet_id)
            # Use the sheet name as source label for nicer CLI output
            r.source = name
            result.results.append(r)

        return result

    def list_files(self, folder_url_or_id: str) -> list[dict[str, str]]:
        """Return [{id, name}] for all Sheets in the folder (dry-run helper)."""
        folder_id = _folder_id_from_url_or_id(folder_url_or_id)
        return self._list_sheets_in_folder(folder_id)

    # ------------------------------------------------------------------

    def _list_sheets_in_folder(self, folder_id: str) -> list[dict[str, str]]:
        service = self._get_drive_service()
        files: list[dict[str, str]] = []
        page_token: str | None = None

        while True:
            kwargs: dict[str, Any] = {
                "q": f"'{folder_id}' in parents and mimeType='{SHEETS_MIME}' and trashed=false",
                "fields": "nextPageToken, files(id, name)",
                "pageSize": 100,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    def _get_drive_service(self) -> Any:
        if self._drive_service is not None:
            return self._drive_service
        return self._get_auth_manager().build_service("drive", "v3")

    def _get_sheets_service(self) -> Any:
        if self._sheets_service is not None:
            return self._sheets_service
        return self._get_auth_manager().build_service("sheets", "v4")

    def _get_auth_manager(self) -> Any:
        if self._auth_manager is not None:
            return self._auth_manager
        from hermes_trip.ingest.google_auth import GoogleAuthManager

        self._auth_manager = GoogleAuthManager()
        return self._auth_manager
