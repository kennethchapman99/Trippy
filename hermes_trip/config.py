"""Runtime configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


def _expand(key: str, default: str) -> Path:
    raw = os.environ.get(key, default)
    return Path(raw).expanduser()


DB_PATH: Path = _expand("HERMES_DB_PATH", "~/.hermes_trip/state.db")
VAULT_PATH: Path = _expand("HERMES_VAULT_PATH", "~/.hermes_trip/vault")
EXPORT_PATH: Path = _expand("HERMES_EXPORT_PATH", "~/.hermes_trip/export")

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_CREDENTIALS_PATH: Path = _expand(
    "GMAIL_CREDENTIALS_PATH", "~/.hermes_trip/gmail_credentials.json"
)
GMAIL_TOKEN_PATH: Path = _expand("GMAIL_TOKEN_PATH", "~/.hermes_trip/gmail_token.json")
GOOGLE_TOKEN_PATH: Path = _expand("GOOGLE_TOKEN_PATH", "~/.hermes_trip/google_token.json")
SHERPA_API_KEY: str = os.environ.get("SHERPA_API_KEY", "")
DUFFEL_ACCESS_TOKEN: str = os.environ.get("DUFFEL_ACCESS_TOKEN", "")
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GOOGLE_SHEETS_API_KEY: str = os.environ.get("GOOGLE_SHEETS_API_KEY", "")

DATABASE_URL: str = f"sqlite:///{DB_PATH}"
