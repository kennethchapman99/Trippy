"""Google Drive MCP tools — search and list files for past-trip mining."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

_SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _drive_service() -> Any:
    from trippy.ingest.google_auth import GoogleAuthManager

    return GoogleAuthManager().build_service("drive", "v3")


def _folder_id_from(url_or_id: str) -> str:
    """Extract folder ID from a Drive URL or return as-is."""
    if "/folders/" in url_or_id:
        part = url_or_id.split("/folders/")[1]
        return part.split("?")[0].split("/")[0]
    return url_or_id.strip()


def register_drive_tools(mcp: FastMCP) -> None:
    """Register all Drive tools onto the given FastMCP instance."""

    @mcp.tool()
    def drive_search(
        query: str,
        folder_id: str | None = None,
        file_type: str = "spreadsheet",
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Search Google Drive for files matching the query.

        Args:
            query: Search terms (e.g. "japan trip 2026")
            folder_id: Optional folder ID/URL to restrict search
            file_type: "spreadsheet" (default) | "any"
            max_results: Maximum results (default 50)

        Returns:
            List of {"id", "name", "modified_time", "url"} dicts
        """
        service = _drive_service()
        q_parts = [f"name contains '{query}'", "trashed = false"]
        if file_type == "spreadsheet":
            q_parts.append(f"mimeType = '{_SHEET_MIME}'")
        if folder_id:
            fid = _folder_id_from(folder_id)
            q_parts.append(f"'{fid}' in parents")

        full_query = " and ".join(q_parts)
        try:
            resp = (
                service.files()
                .list(
                    q=full_query,
                    fields="files(id,name,modifiedTime,webViewLink)",
                    pageSize=min(max_results, 100),
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            return [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "modified_time": f.get("modifiedTime", ""),
                    "url": f.get(
                        "webViewLink", f"https://docs.google.com/spreadsheets/d/{f['id']}"
                    ),
                }
                for f in resp.get("files", [])
            ]
        except Exception as exc:
            logger.error("drive_search(%r) failed: %s", query, exc)
            return []

    @mcp.tool()
    def drive_list_folder(
        folder_id: str,
        file_type: str = "spreadsheet",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """List all files in a Google Drive folder.

        Args:
            folder_id: Google Drive folder ID or URL
            file_type: "spreadsheet" (default) | "any"
            max_results: Maximum results (default 100)

        Returns:
            List of {"id", "name", "modified_time", "url"} dicts, sorted by name
        """
        fid = _folder_id_from(folder_id)
        service = _drive_service()

        q_parts = [f"'{fid}' in parents", "trashed = false"]
        if file_type == "spreadsheet":
            q_parts.append(f"mimeType = '{_SHEET_MIME}'")

        all_files: list[dict[str, Any]] = []
        page_token = None

        while True:
            try:
                kwargs: dict[str, Any] = {
                    "q": " and ".join(q_parts),
                    "fields": "nextPageToken,files(id,name,modifiedTime,webViewLink)",
                    "pageSize": min(max_results, 100),
                    "orderBy": "name",
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                resp = service.files().list(**kwargs).execute()
                for f in resp.get("files", []):
                    all_files.append(
                        {
                            "id": f["id"],
                            "name": f["name"],
                            "modified_time": f.get("modifiedTime", ""),
                            "url": f.get("webViewLink", ""),
                        }
                    )
                    if len(all_files) >= max_results:
                        return all_files

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            except Exception as exc:
                logger.error("drive_list_folder(%s) failed: %s", fid, exc)
                break

        return all_files

    @mcp.tool()
    def drive_get_file_metadata(file_id: str) -> dict[str, Any]:
        """Get metadata for a specific Drive file.

        Args:
            file_id: Drive file ID or Google Sheets URL

        Returns:
            {"id", "name", "mime_type", "modified_time", "url", "owners"}
        """
        if "/" in file_id:
            # Could be a Sheets URL
            if "/spreadsheets/d/" in file_id:
                file_id = file_id.split("/spreadsheets/d/")[1].split("/")[0]
            elif "/folders/" in file_id:
                file_id = _folder_id_from(file_id)

        service = _drive_service()
        try:
            f = (
                service.files()
                .get(
                    fileId=file_id,
                    fields="id,name,mimeType,modifiedTime,webViewLink,owners",
                )
                .execute()
            )
            return {
                "id": f["id"],
                "name": f.get("name", ""),
                "mime_type": f.get("mimeType", ""),
                "modified_time": f.get("modifiedTime", ""),
                "url": f.get("webViewLink", ""),
                "owners": [o.get("emailAddress", "") for o in f.get("owners", [])],
            }
        except Exception as exc:
            logger.error("drive_get_file_metadata(%s) failed: %s", file_id, exc)
            return {"error": str(exc)}
