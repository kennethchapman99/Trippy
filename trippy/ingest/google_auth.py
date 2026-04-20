"""Shared Google OAuth2 credential manager — Gmail, Sheets, and Drive."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from trippy import config

logger = logging.getLogger(__name__)

GMAIL_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/gmail.readonly",)
SHEETS_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
DRIVE_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/drive.readonly",)
ALL_SCOPES: tuple[str, ...] = GMAIL_SCOPES + SHEETS_SCOPES + DRIVE_SCOPES


class GoogleAuthManager:
    """Manages a single OAuth2 token covering Gmail, Sheets, and Drive read scopes.

    Pass ``credentials`` directly in tests to skip all disk I/O and browser flows.
    """

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
        scopes: Sequence[str] | None = None,
        credentials: Any | None = None,
    ) -> None:
        self._creds_path = credentials_path or config.GMAIL_CREDENTIALS_PATH
        self._token_path = token_path or config.GOOGLE_TOKEN_PATH
        self._scopes: tuple[str, ...] = tuple(scopes) if scopes is not None else ALL_SCOPES
        self._credentials = credentials  # pre-built creds for tests

    # ------------------------------------------------------------------

    def get_credentials(self) -> Any:
        """Return valid credentials, refreshing or re-running the OAuth flow as needed."""
        if self._credentials is not None:
            return self._credentials
        return self._load_or_refresh()

    def build_service(self, service_name: str, version: str) -> Any:
        """Return a googleapiclient resource (e.g. build_service('sheets', 'v4'))."""
        from googleapiclient.discovery import build  # type: ignore[import-untyped]

        return build(service_name, version, credentials=self.get_credentials())

    # ------------------------------------------------------------------

    def _load_or_refresh(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

        creds = None
        scopes_list = list(self._scopes)

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                str(self._token_path), scopes_list
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self._creds_path.exists():
                    raise FileNotFoundError(
                        f"Google credentials not found at {self._creds_path}. "
                        "Download OAuth client secrets (Desktop app type) from "
                        "Google Cloud Console and save to that path."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self._creds_path), scopes_list)
                creds = flow.run_local_server(port=0)
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json())
            logger.info("Google token saved to %s", self._token_path)

        return creds
