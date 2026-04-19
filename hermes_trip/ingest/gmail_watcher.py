"""Gmail API watcher — fetches booking confirmation emails."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hermes_trip import config

logger = logging.getLogger(__name__)

# Sender domains whose mail we trust as potential confirmations.
# Easy to extend: add to SENDER_ALLOWLIST in .env as a comma-separated list,
# or extend this set in code.
SENDER_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Airlines
        "aircanada.com",
        "united.com",
        "delta.com",
        "westjet.com",
        "lufthansa.com",
        "klm.com",
        "airfrance.com",
        "britishairways.com",
        "aa.com",
        "southwest.com",
        "jetblue.com",
        "porter.com",
        "flyporter.com",
        "airtransat.com",
        "transat.com",
        "sunwing.com",
        "flair.ca",
        "flyflair.com",
        "cathaypacific.com",
        "airindia.com",
        "emirates.com",
        "etihad.com",
        "turkishairlines.com",
        "singaporeair.com",
        "qatarairways.com",
        # Accommodation platforms
        "booking.com",
        "airbnb.com",
        "vrbo.com",
        "homeaway.com",
        # Hotel chains
        "marriott.com",
        "hilton.com",
        "hyatt.com",
        "ihg.com",
        "fourseasons.com",
        "bestwestern.com",
        "accor.com",
        "wyndham.com",
        # OTAs
        "expedia.com",
        "hotels.com",
        "priceline.com",
        "kayak.com",
        "travelocity.com",
        # Activities & car rentals
        "viator.com",
        "getyourguide.com",
        "hertz.com",
        "avis.com",
        "budget.com",
        "enterprise.com",
        "nationalcar.com",
        "turo.com",
    }
)


@dataclass
class EmailAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class EmailContent:
    message_id: str
    sender: str
    subject: str
    date: datetime
    body_text: str
    body_html: str
    attachments: list[EmailAttachment] = field(default_factory=list)
    raw_bytes: bytes = field(default_factory=bytes)

    @property
    def sender_domain(self) -> str:
        addr = self.sender.lower()
        if "@" in addr:
            addr = addr.split("@")[-1].strip(">").strip()
        return addr


def _is_allowed_sender(email_content: EmailContent) -> bool:
    domain = email_content.sender_domain
    # Exact match or subdomain match
    return domain in SENDER_ALLOWLIST or any(
        domain.endswith("." + allowed) for allowed in SENDER_ALLOWLIST
    )


def _parse_gmail_message(raw_msg: dict[str, Any]) -> EmailContent | None:
    """Convert a Gmail API message dict to EmailContent."""
    try:
        payload = raw_msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        sender = headers.get("from", "")
        subject = headers.get("subject", "")
        date_str = headers.get("date", "")

        from email.utils import parsedate_to_datetime

        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            date = datetime.utcnow()

        body_text = ""
        body_html = ""
        attachments: list[EmailAttachment] = []

        def _walk(part: dict[str, Any]) -> None:
            nonlocal body_text, body_html
            mime_type = part.get("mimeType", "")
            body = part.get("body", {})
            data_b64 = body.get("data", "")

            if data_b64:
                decoded = base64.urlsafe_b64decode(data_b64 + "==").decode(
                    "utf-8", errors="replace"
                )
                if mime_type == "text/plain":
                    body_text += decoded
                elif mime_type == "text/html":
                    body_html += decoded
                elif mime_type.startswith("application/") or mime_type.startswith("image/"):
                    filename = part.get("filename") or f"attachment.{mime_type.split('/')[-1]}"
                    attachments.append(
                        EmailAttachment(
                            filename=filename,
                            content_type=mime_type,
                            data=base64.urlsafe_b64decode(data_b64 + "=="),
                        )
                    )

            for sub in part.get("parts", []):
                _walk(sub)

        _walk(payload)

        raw_bytes = base64.urlsafe_b64decode(
            raw_msg.get("raw", "") + "=="
        ) if "raw" in raw_msg else b""

        return EmailContent(
            message_id=raw_msg.get("id", ""),
            sender=sender,
            subject=subject,
            date=date,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            raw_bytes=raw_bytes,
        )
    except Exception as exc:
        logger.warning("Failed to parse Gmail message: %s", exc)
        return None


class GmailWatcher:
    """Polls Gmail for new booking confirmation emails.

    Pass ``gmail_service`` in tests to inject a mock; omit it in production
    and it will authenticate with the credentials on disk.
    """

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
        gmail_service: Any | None = None,
        auth_manager: Any | None = None,
    ) -> None:
        self._creds_path = credentials_path or config.GMAIL_CREDENTIALS_PATH
        self._token_path = token_path or config.GMAIL_TOKEN_PATH
        self._service = gmail_service  # injected for tests
        self._auth_manager = auth_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """Build the Gmail API service using OAuth2 credentials."""
        if self._service is not None:
            return  # already injected

        if self._auth_manager is not None:
            self._service = self._auth_manager.build_service("gmail", "v1")
            return

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
        from googleapiclient.discovery import build  # type: ignore[import-untyped]

        SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
        creds = None

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)  # type: ignore[no-untyped-call]

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self._creds_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {self._creds_path}. "
                        "Download OAuth client secrets from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._creds_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)

    def fetch_new_messages(
        self, label: str = "INBOX", max_results: int = 50
    ) -> list[EmailContent]:
        """Fetch recent messages from Gmail, filtered to allowed senders."""
        if self._service is None:
            self.authenticate()
        service: Any = self._service

        # Narrow to booking-confirmation-like emails to avoid wasting fetch budget
        query = (
            "subject:(confirmation OR booking OR reservation OR itinerary OR "
            "\"your trip\" OR \"order confirmed\" OR \"e-ticket\")"
        )
        results: dict[str, Any] = (
            service.users()
            .messages()
            .list(userId="me", labelIds=[label], maxResults=max_results, q=query)
            .execute()
        )
        messages_meta = results.get("messages", [])
        emails: list[EmailContent] = []

        for meta in messages_meta:
            msg_id: str = meta["id"]
            raw_msg: dict[str, Any] = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            content = _parse_gmail_message(raw_msg)
            if content and _is_allowed_sender(content):
                emails.append(content)
            else:
                logger.debug(
                    "Skipped message %s (sender not in allowlist or parse failed)", msg_id
                )

        return emails

    def save_to_vault(
        self,
        content: EmailContent,
        vault_path: Path,
        trip_id: int | None = None,
    ) -> Path:
        """Save raw email bytes to vault. Returns path to saved file."""
        folder = vault_path / (str(trip_id) if trip_id else "unlinked")
        folder.mkdir(parents=True, exist_ok=True)
        eml_path = folder / f"{content.message_id}.eml"
        if content.raw_bytes:
            eml_path.write_bytes(content.raw_bytes)
        else:
            # Write a minimal .eml from parsed parts
            eml_path.write_text(
                f"From: {content.sender}\nSubject: {content.subject}\nDate: {content.date}\n\n"
                + (content.body_text or content.body_html),
                encoding="utf-8",
            )
        for att in content.attachments:
            att_path = folder / f"{content.message_id}_{att.filename}"
            att_path.write_bytes(att.data)
        return eml_path
