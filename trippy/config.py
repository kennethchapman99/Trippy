"""Runtime configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


def _expand(key: str, default: str) -> Path:
    raw = os.environ.get(key, default)
    return Path(raw).expanduser()


# Core storage paths
DB_PATH: Path = _expand("TRIPPY_DB_PATH", "~/.trippy/state.db")
MEMORY_PATH: Path = _expand("TRIPPY_MEMORY_PATH", "~/.trippy/memory.json")
TRIPS_PATH: Path = _expand("TRIPPY_TRIPS_PATH", "~/.trippy/trips")
VAULT_PATH: Path = _expand("TRIPPY_VAULT_PATH", "~/.trippy/vault")
EXPORT_PATH: Path = _expand("TRIPPY_EXPORT_PATH", "~/.trippy/export")

# Google OAuth
GMAIL_CREDENTIALS_PATH: Path = _expand("GMAIL_CREDENTIALS_PATH", "~/.trippy/gmail_credentials.json")
GMAIL_TOKEN_PATH: Path = _expand("GMAIL_TOKEN_PATH", "~/.trippy/gmail_token.json")
GOOGLE_TOKEN_PATH: Path = _expand("GOOGLE_TOKEN_PATH", "~/.trippy/google_token.json")

# API keys
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_SHEETS_API_KEY: str = os.environ.get("GOOGLE_SHEETS_API_KEY", "")
SHERPA_API_KEY: str = os.environ.get("SHERPA_API_KEY", "")
DUFFEL_ACCESS_TOKEN: str = os.environ.get("DUFFEL_ACCESS_TOKEN", "")

# Google Sheet template
SHEET_TEMPLATE_ID: str = os.environ.get("TRIPPY_SHEET_TEMPLATE_ID", "")

DATABASE_URL: str = f"sqlite:///{DB_PATH}"

# Legacy compat aliases (some tests reference old paths)
HERMES_DB_PATH = DB_PATH
HERMES_VAULT_PATH = VAULT_PATH
HERMES_EXPORT_PATH = EXPORT_PATH
