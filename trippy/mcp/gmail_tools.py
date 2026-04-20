"""Gmail MCP tools — search, read, and extract attachments from Gmail.

All tools accept an optional ``auth_manager`` for dependency injection in tests.
In production, auth is loaded from the environment (GOOGLE_TOKEN_PATH).
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from trippy.ingest.google_auth import GoogleAuthManager

logger = logging.getLogger(__name__)

_BOOKING_KEYWORDS = [
    "confirmation",
    "booking",
    "reservation",
    "itinerary",
    "e-ticket",
    "receipt",
    "check-in",
    "your trip",
]


def _get_auth() -> GoogleAuthManager:
    from trippy.ingest.google_auth import GoogleAuthManager

    return GoogleAuthManager()


def _gmail_service(auth: GoogleAuthManager | None = None) -> Any:
    mgr = auth or _get_auth()
    return mgr.build_service("gmail", "v1")


def _decode_body(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_parts(payload: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """Recursively extract text, html, and attachment metadata from a MIME payload."""
    body_text = ""
    body_html = ""
    attachments: list[dict[str, Any]] = []

    mime = payload.get("mimeType", "")
    parts = payload.get("parts", [])

    if mime == "text/plain" and not parts:
        data = payload.get("body", {}).get("data", "")
        body_text = _decode_body(data)
    elif mime == "text/html" and not parts:
        data = payload.get("body", {}).get("data", "")
        body_html = _decode_body(data)
    elif payload.get("filename"):
        # Attachment
        body_obj = payload.get("body", {})
        attachments.append(
            {
                "filename": payload["filename"],
                "mime_type": mime,
                "attachment_id": body_obj.get("attachmentId"),
                "size": body_obj.get("size", 0),
            }
        )
    else:
        for part in parts:
            t, h, a = _extract_parts(part)
            body_text = body_text or t
            body_html = body_html or h
            attachments.extend(a)

    return body_text, body_html, attachments


def register_gmail_tools(mcp: FastMCP) -> None:
    """Register all Gmail tools onto the given FastMCP instance."""

    @mcp.tool()
    def gmail_search(
        query: str,
        max_results: int = 20,
        label: str = "INBOX",
    ) -> list[dict[str, Any]]:
        """Search Gmail for emails matching the query.

        Returns a list of message summaries: id, subject, from, date, snippet.
        Use gmail_get_email to fetch the full content of a specific message.

        Args:
            query: Gmail search query (e.g. "from:aircanada.com confirmation")
            max_results: Maximum number of results (default 20, max 100)
            label: Gmail label to search within (default "INBOX")
        """
        service = _gmail_service()
        try:
            resp = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    labelIds=[label],
                    maxResults=min(max_results, 100),
                )
                .execute()
            )
        except Exception as exc:
            logger.error("gmail_search failed: %s", exc)
            return []

        messages = resp.get("messages", [])
        if not messages:
            return []

        results: list[dict[str, Any]] = []
        for msg in messages:
            try:
                detail = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in detail.get("payload", {}).get("headers", [])
                }
                results.append(
                    {
                        "id": msg["id"],
                        "subject": headers.get("subject", "(no subject)"),
                        "from": headers.get("from", ""),
                        "date": headers.get("date", ""),
                        "snippet": detail.get("snippet", ""),
                    }
                )
            except Exception as exc:
                logger.warning("Failed to fetch message %s metadata: %s", msg["id"], exc)

        return results

    @mcp.tool()
    def gmail_search_bookings(max_results: int = 50) -> list[dict[str, Any]]:
        """Search Gmail for booking confirmation emails from common travel vendors.

        Uses a pre-built query targeting flight, hotel, and rental car confirmations.
        Returns message summaries. Use gmail_get_email to read full content.
        """
        keyword_query = " OR ".join(f'"{kw}"' for kw in _BOOKING_KEYWORDS)
        return gmail_search(keyword_query, max_results=max_results)  # type: ignore[no-any-return]

    @mcp.tool()
    def gmail_get_email(message_id: str) -> dict[str, Any]:
        """Get the full content of a Gmail message including body text and attachments.

        Returns: subject, from, date, body_text, body_html, attachments (list of
        attachment metadata). Use gmail_get_attachment to download attachment bytes.

        Args:
            message_id: Gmail message ID from gmail_search results
        """
        service = _gmail_service()
        try:
            detail = (
                service.users().messages().get(userId="me", id=message_id, format="full").execute()
            )
        except Exception as exc:
            logger.error("gmail_get_email(%s) failed: %s", message_id, exc)
            return {"error": str(exc)}

        payload = detail.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        body_text, body_html, attachments = _extract_parts(payload)

        return {
            "id": message_id,
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "date": headers.get("date", ""),
            "body_text": body_text[:12_000],
            "body_html": body_html[:12_000],
            "attachments": attachments,
        }

    @mcp.tool()
    def gmail_get_attachment(message_id: str, attachment_id: str) -> dict[str, Any]:
        """Download an email attachment and return its decoded content.

        For PDF attachments, this returns the raw bytes encoded as base64.
        Use the confirmation parser to extract structured data from PDF content.

        Args:
            message_id: Gmail message ID
            attachment_id: Attachment ID from gmail_get_email response
        """
        service = _gmail_service()
        try:
            resp = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            data = resp.get("data", "")
            return {
                "attachment_id": attachment_id,
                "data_base64": data,
                "size": resp.get("size", 0),
            }
        except Exception as exc:
            logger.error("gmail_get_attachment failed: %s", exc)
            return {"error": str(exc)}
