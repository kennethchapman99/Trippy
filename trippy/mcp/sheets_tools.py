"""Google Sheets MCP tools — create, read, write, and template trip sheets."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _sheets_service() -> Any:
    from trippy.ingest.google_auth import GoogleAuthManager

    return GoogleAuthManager().build_service("sheets", "v4")


def _drive_service() -> Any:
    from trippy.ingest.google_auth import GoogleAuthManager

    return GoogleAuthManager().build_service("drive", "v3")


def register_sheets_tools(mcp: FastMCP) -> None:
    """Register all Sheets tools onto the given FastMCP instance."""

    @mcp.tool()
    def sheets_read(spreadsheet_id: str, cell_range: str = "A1:Z500") -> dict[str, Any]:
        """Read cells from a Google Sheet.

        Args:
            spreadsheet_id: The Google Sheets spreadsheet ID or full URL
            cell_range: A1 notation range (e.g. "Sheet1!A1:Z100"). Default reads first 500 rows.

        Returns:
            {"values": [[row1col1, row1col2, ...], ...], "spreadsheet_id": "...", "range": "..."}
        """
        # Extract ID from URL if needed
        sid = _extract_sheet_id(spreadsheet_id)
        service = _sheets_service()
        try:
            resp = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=sid,
                    range=cell_range,
                    valueRenderOption="UNFORMATTED_VALUE",
                )
                .execute()
            )
            return {
                "spreadsheet_id": sid,
                "range": resp.get("range", cell_range),
                "values": resp.get("values", []),
            }
        except Exception as exc:
            logger.error("sheets_read(%s, %s) failed: %s", sid, cell_range, exc)
            return {"error": str(exc), "spreadsheet_id": sid}

    @mcp.tool()
    def sheets_write(
        spreadsheet_id: str,
        cell_range: str,
        values: list[list[Any]],
    ) -> dict[str, Any]:
        """Write values to a Google Sheet range.

        Args:
            spreadsheet_id: Spreadsheet ID or URL
            cell_range: A1 notation (e.g. "Sheet1!A2:D10")
            values: List of rows, each row is a list of cell values

        Returns:
            {"updated_range": "...", "updated_rows": N, "updated_cells": N}
        """
        sid = _extract_sheet_id(spreadsheet_id)
        service = _sheets_service()
        try:
            resp = (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=sid,
                    range=cell_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": values},
                )
                .execute()
            )
            return {
                "spreadsheet_id": sid,
                "updated_range": resp.get("updatedRange", cell_range),
                "updated_rows": resp.get("updatedRows", 0),
                "updated_cells": resp.get("updatedCells", 0),
            }
        except Exception as exc:
            logger.error("sheets_write(%s) failed: %s", sid, exc)
            return {"error": str(exc), "spreadsheet_id": sid}

    @mcp.tool()
    def sheets_append(
        spreadsheet_id: str,
        cell_range: str,
        values: list[list[Any]],
    ) -> dict[str, Any]:
        """Append rows to a Google Sheet (adds after last row with data).

        Args:
            spreadsheet_id: Spreadsheet ID or URL
            cell_range: Range indicating the table to append to (e.g. "Flights!A:Z")
            values: List of rows to append

        Returns:
            {"updates": {"updated_range": "...", "updated_rows": N}}
        """
        sid = _extract_sheet_id(spreadsheet_id)
        service = _sheets_service()
        try:
            resp = (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sid,
                    range=cell_range,
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                )
                .execute()
            )
            updates = resp.get("updates", {})
            return {
                "spreadsheet_id": sid,
                "updated_range": updates.get("updatedRange", ""),
                "updated_rows": updates.get("updatedRows", 0),
            }
        except Exception as exc:
            logger.error("sheets_append(%s) failed: %s", sid, exc)
            return {"error": str(exc)}

    @mcp.tool()
    def sheets_create(title: str, folder_id: str | None = None) -> dict[str, Any]:
        """Create a new Google Spreadsheet.

        Args:
            title: Name of the new spreadsheet
            folder_id: Optional Google Drive folder ID to place the sheet in

        Returns:
            {"spreadsheet_id": "...", "url": "https://docs.google.com/spreadsheets/d/..."}
        """
        service = _sheets_service()
        try:
            resp = service.spreadsheets().create(body={"properties": {"title": title}}).execute()
            sid = resp["spreadsheetId"]
            url = resp.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sid}")

            if folder_id:
                drive = _drive_service()
                # Move to folder
                file_meta = drive.files().get(fileId=sid, fields="parents").execute()
                previous_parents = ",".join(file_meta.get("parents", []))
                drive.files().update(
                    fileId=sid,
                    addParents=folder_id,
                    removeParents=previous_parents,
                    fields="id, parents",
                ).execute()

            return {"spreadsheet_id": sid, "url": url, "title": title}
        except Exception as exc:
            logger.error("sheets_create(%r) failed: %s", title, exc)
            return {"error": str(exc)}

    @mcp.tool()
    def sheets_from_template(
        title: str,
        template_spreadsheet_id: str,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new spreadsheet by copying a template.

        This copies the entire template (all tabs, formatting, formulas) and
        renames it. Use this to create a new trip sheet from the Trippy template.

        Args:
            title: Name of the new spreadsheet
            template_spreadsheet_id: ID of the template spreadsheet to copy
            folder_id: Optional Drive folder to move the new sheet into

        Returns:
            {"spreadsheet_id": "...", "url": "..."}
        """
        drive = _drive_service()
        try:
            copy = (
                drive.files()
                .copy(
                    fileId=template_spreadsheet_id,
                    body={"name": title},
                )
                .execute()
            )
            new_id = copy["id"]
            url = f"https://docs.google.com/spreadsheets/d/{new_id}"

            if folder_id:
                file_meta = drive.files().get(fileId=new_id, fields="parents").execute()
                previous_parents = ",".join(file_meta.get("parents", []))
                drive.files().update(
                    fileId=new_id,
                    addParents=folder_id,
                    removeParents=previous_parents,
                    fields="id, parents",
                ).execute()

            return {"spreadsheet_id": new_id, "url": url, "title": title}
        except Exception as exc:
            logger.error("sheets_from_template failed: %s", exc)
            return {"error": str(exc)}

    @mcp.tool()
    def sheets_get_metadata(spreadsheet_id: str) -> dict[str, Any]:
        """Get spreadsheet metadata including title and list of sheet (tab) names.

        Args:
            spreadsheet_id: Spreadsheet ID or URL

        Returns:
            {"title": "...", "sheets": ["Sheet1", "Flights", ...]}
        """
        sid = _extract_sheet_id(spreadsheet_id)
        service = _sheets_service()
        try:
            resp = (
                service.spreadsheets()
                .get(spreadsheetId=sid, fields="properties.title,sheets.properties.title")
                .execute()
            )
            return {
                "spreadsheet_id": sid,
                "title": resp.get("properties", {}).get("title", ""),
                "sheets": [s["properties"]["title"] for s in resp.get("sheets", [])],
            }
        except Exception as exc:
            logger.error("sheets_get_metadata(%s) failed: %s", sid, exc)
            return {"error": str(exc)}


def _extract_sheet_id(url_or_id: str) -> str:
    """Extract spreadsheet ID from a URL or return the ID as-is."""
    if "/spreadsheets/d/" in url_or_id:
        part = url_or_id.split("/spreadsheets/d/")[1]
        return part.split("/")[0].split("?")[0]
    return url_or_id.strip()
