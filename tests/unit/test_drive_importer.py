"""Unit tests for DriveFolderImporter — Drive and Sheets API calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trippy.importers.drive_importer import (
    DriveFolderImporter,
    DriveFolderResult,
    _folder_id_from_url_or_id,
)
from trippy.importers.sheet_importer import ImportResult

# ---------------------------------------------------------------------------
# URL / ID parsing
# ---------------------------------------------------------------------------


class TestFolderIdFromUrl:
    def test_full_drive_url(self) -> None:
        url = "https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjg"
        assert _folder_id_from_url_or_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjg"

    def test_url_with_query_params(self) -> None:
        url = "https://drive.google.com/drive/folders/ABC123XYZ?usp=sharing"
        assert _folder_id_from_url_or_id(url) == "ABC123XYZ"

    def test_bare_id_passthrough(self) -> None:
        assert _folder_id_from_url_or_id("ABC123def456") == "ABC123def456"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract folder ID"):
            _folder_id_from_url_or_id("not a valid id!")

    def test_invalid_url_with_spaces_raises(self) -> None:
        with pytest.raises(ValueError):
            _folder_id_from_url_or_id("https://example.com/no folder here")


# ---------------------------------------------------------------------------
# DriveFolderResult
# ---------------------------------------------------------------------------


class TestDriveFolderResult:
    def test_total_created(self) -> None:
        r1 = ImportResult(source="a")
        r1.trips_created = 2
        r2 = ImportResult(source="b")
        r2.trips_created = 1
        result = DriveFolderResult(folder_id="X", results=[r1, r2])
        assert result.total_created == 3

    def test_total_updated(self) -> None:
        r1 = ImportResult(source="a")
        r1.trips_updated = 1
        result = DriveFolderResult(folder_id="X", results=[r1])
        assert result.total_updated == 1

    def test_errors_aggregated(self) -> None:
        r1 = ImportResult(source="a")
        r1.errors.append("oops")
        r2 = ImportResult(source="b")
        r2.errors.append("bang")
        result = DriveFolderResult(folder_id="X", results=[r1, r2])
        assert len(result.errors) == 2

    def test_empty_folder(self) -> None:
        result = DriveFolderResult(folder_id="X")
        assert result.total_created == 0
        assert result.total_updated == 0
        assert result.errors == []


# ---------------------------------------------------------------------------
# DriveFolderImporter
# ---------------------------------------------------------------------------


def _make_drive_service(files: list[dict[str, str]], next_token: str | None = None) -> MagicMock:
    """Return a mock Drive service that yields ``files`` on list()."""
    service = MagicMock()
    response: dict[str, object] = {"files": files}
    if next_token:
        response["nextPageToken"] = next_token
    service.files().list().execute.return_value = response
    return service


def _make_import_result(created: int = 1) -> ImportResult:
    r = ImportResult(source="fake")
    r.trips_created = created
    return r


class TestListSheetsInFolder:
    def test_returns_files_list(self) -> None:
        files = [{"id": "id1", "name": "Japan 2026"}, {"id": "id2", "name": "Costa Rica"}]
        drive_service = _make_drive_service(files)
        importer = DriveFolderImporter(drive_service=drive_service, sheets_service=MagicMock())
        result = importer._list_sheets_in_folder("FOLDER_ID")
        assert len(result) == 2
        assert result[0]["name"] == "Japan 2026"

    def test_empty_folder_returns_empty_list(self) -> None:
        drive_service = _make_drive_service([])
        importer = DriveFolderImporter(drive_service=drive_service, sheets_service=MagicMock())
        result = importer._list_sheets_in_folder("FOLDER_ID")
        assert result == []

    def test_handles_pagination(self) -> None:
        page1_files = [{"id": "id1", "name": "Sheet1"}]
        page2_files = [{"id": "id2", "name": "Sheet2"}]

        drive_service = MagicMock()
        # First call returns nextPageToken, second call returns empty token
        drive_service.files().list().execute.side_effect = [
            {"files": page1_files, "nextPageToken": "tok123"},
            {"files": page2_files},
        ]

        importer = DriveFolderImporter(drive_service=drive_service, sheets_service=MagicMock())
        result = importer._list_sheets_in_folder("FOLDER_ID")
        assert len(result) == 2


class TestImportFolder:
    def test_calls_import_for_each_sheet(self) -> None:
        files = [{"id": "id1", "name": "Japan"}, {"id": "id2", "name": "CR"}]
        drive_service = _make_drive_service(files)
        sheets_service = MagicMock()

        with patch(
            "trippy.importers.drive_importer.SheetImporter.import_file",
            return_value=_make_import_result(1),
        ):
            importer = DriveFolderImporter(
                drive_service=drive_service, sheets_service=sheets_service
            )
            result = importer.import_folder("FOLDER_ID")

        assert result.files_found == 2
        assert result.total_created == 2

    def test_empty_folder_returns_zero_files(self) -> None:
        drive_service = _make_drive_service([])
        importer = DriveFolderImporter(drive_service=drive_service, sheets_service=MagicMock())
        result = importer.import_folder("FOLDER_ID")
        assert result.files_found == 0
        assert result.results == []

    def test_list_files_dry_run(self) -> None:
        files = [{"id": "id1", "name": "Japan 2026"}]
        drive_service = _make_drive_service(files)
        importer = DriveFolderImporter(drive_service=drive_service, sheets_service=MagicMock())
        listed = importer.list_files("FOLDER_ID")
        assert listed == files
