"""Runtime configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


def _expand(key: str, default: str) -> Path:
    raw = os.environ.get(key, default)
    return Path(raw).expanduser()


def _bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mode(key: str, default: str = "advisory") -> str:
    value = os.environ.get(key, default).strip().lower()
    return value if value in VALID_LLM_MODES else default


# Core storage paths
DB_PATH: Path = _expand("TRIPPY_DB_PATH", "~/.trippy/state.db")
MEMORY_PATH: Path = _expand("TRIPPY_MEMORY_PATH", "~/.trippy/memory.json")
TRIPS_PATH: Path = _expand("TRIPPY_TRIPS_PATH", "~/.trippy/trips")
INTAKES_PATH: Path = _expand("TRIPPY_INTAKES_PATH", "~/.trippy/intakes")
PLANS_PATH: Path = _expand("TRIPPY_PLANS_PATH", "~/.trippy/plans")
WORKSPACES_PATH: Path = _expand("TRIPPY_WORKSPACES_PATH", "~/.trippy/workspaces")
SHORTLISTS_PATH: Path = _expand("TRIPPY_SHORTLISTS_PATH", "~/.trippy/shortlists")
RESEARCH_PATH: Path = _expand("TRIPPY_RESEARCH_PATH", "~/.trippy/research")
VAULT_PATH: Path = _expand("TRIPPY_VAULT_PATH", "~/.trippy/vault")
EXPORT_PATH: Path = _expand("TRIPPY_EXPORT_PATH", "~/.trippy/export")
LEARNING_PATH: Path = _expand("TRIPPY_LEARNING_PATH", "~/.trippy/learning")
LLM_CACHE_PATH: Path = _expand("TRIPPY_LLM_CACHE_PATH", "~/.trippy/llm_cache")
LLM_ACCOUNTING_PATH: Path = _expand("TRIPPY_LLM_ACCOUNTING_PATH", "~/.trippy/llm_accounting")

# Google OAuth
GMAIL_CREDENTIALS_PATH: Path = _expand("GMAIL_CREDENTIALS_PATH", "~/.trippy/gmail_credentials.json")
GMAIL_TOKEN_PATH: Path = _expand("GMAIL_TOKEN_PATH", "~/.trippy/gmail_token.json")
GOOGLE_TOKEN_PATH: Path = _expand("GOOGLE_TOKEN_PATH", "~/.trippy/google_token.json")

# API keys
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_SHEETS_API_KEY: str = os.environ.get("GOOGLE_SHEETS_API_KEY", "")
SHERPA_API_KEY: str = os.environ.get("SHERPA_API_KEY", "")
DUFFEL_ACCESS_TOKEN: str = os.environ.get("DUFFEL_ACCESS_TOKEN", "")
FIRECRAWL_API_KEY: str = os.environ.get("FIRECRAWL_API_KEY", "")
SERPAPI_KEY: str = os.environ.get("SERPAPI_KEY", "")

# LLM routing
VALID_LLM_MODES = {"off", "test", "advisory", "required"}
LLM_MODE: str = _mode("TRIPPY_LLM_MODE", "advisory")
PLANNING_LLM_MODE: str = _mode("TRIPPY_PLANNING_LLM_MODE", LLM_MODE)

LLM_MODEL_FAST: str = os.environ.get("TRIPPY_LLM_MODEL_FAST", "claude-sonnet-4-6")
LLM_MODEL_DEEP: str = os.environ.get("TRIPPY_LLM_MODEL_DEEP", "claude-opus-4-7")
LLM_MODEL_CHEAP: str = os.environ.get("TRIPPY_LLM_MODEL_CHEAP", "claude-haiku-4-5")

AGENT_LLM_MODEL: str = os.environ.get("TRIPPY_AGENT_LLM_MODEL", LLM_MODEL_FAST)
TRIP_IDEATION_MODEL: str = os.environ.get("TRIPPY_TRIP_IDEATION_MODEL", LLM_MODEL_FAST)
TRIP_IDEATION_DEEP_MODEL: str = os.environ.get("TRIPPY_TRIP_IDEATION_DEEP_MODEL", LLM_MODEL_DEEP)
TRIP_PLANNER_MODEL: str = os.environ.get("TRIPPY_TRIP_PLANNER_MODEL", LLM_MODEL_FAST)
TRIP_PLANNER_DEEP_MODEL: str = os.environ.get("TRIPPY_TRIP_PLANNER_DEEP_MODEL", LLM_MODEL_DEEP)
PLANNING_ADVISOR_MODEL: str = os.environ.get(
    "TRIPPY_PLANNING_ADVISOR_MODEL",
    os.environ.get("TRIPPY_PLANNING_LLM_MODEL", LLM_MODEL_FAST),
)
PLANNING_ADVISOR_DEEP_MODEL: str = os.environ.get(
    "TRIPPY_PLANNING_ADVISOR_DEEP_MODEL", LLM_MODEL_DEEP
)
GEOGRAPHY_RESOLVER_MODEL: str = os.environ.get("TRIPPY_GEOGRAPHY_RESOLVER_MODEL", LLM_MODEL_FAST)
CONFIRMATION_PARSER_MODEL: str = os.environ.get("TRIPPY_CONFIRMATION_PARSER_MODEL", LLM_MODEL_FAST)
SOURCE_RESEARCH_EXTRACTOR_MODEL: str = os.environ.get(
    "TRIPPY_SOURCE_RESEARCH_EXTRACTOR_MODEL", LLM_MODEL_FAST
)
FRICTION_LLM_MODEL: str = os.environ.get("TRIPPY_FRICTION_LLM_MODEL", LLM_MODEL_CHEAP)

PLANNING_LLM_ENABLED: bool = _bool(
    "TRIPPY_PLANNING_LLM_ENABLED",
    bool(ANTHROPIC_API_KEY) and PLANNING_LLM_MODE not in {"off", "test"},
)
IDEATION_LLM_ENABLED: bool = _bool(
    "TRIPPY_IDEATION_LLM_ENABLED",
    PLANNING_LLM_ENABLED,
)
TRIP_PLANNER_LLM_ENABLED: bool = _bool(
    "TRIPPY_TRIP_PLANNER_LLM_ENABLED",
    PLANNING_LLM_ENABLED,
)
LODGING_LLM_ENABLED: bool = _bool("TRIPPY_LODGING_LLM_ENABLED", PLANNING_LLM_ENABLED)
GEOGRAPHY_LLM_ENABLED: bool = _bool("TRIPPY_GEOGRAPHY_LLM_ENABLED", PLANNING_LLM_ENABLED)
SOURCE_RESEARCH_LLM_ENABLED: bool = _bool(
    "TRIPPY_SOURCE_RESEARCH_LLM_ENABLED", PLANNING_LLM_ENABLED
)
FRICTION_LLM_ENABLED: bool = _bool("TRIPPY_FRICTION_LLM_ENABLED", False)

FAST_IDEATION_ENABLED: bool = _bool("TRIPPY_FAST_IDEATION_ENABLED", True)
DEEP_IDEATION_ON_SELECTION: bool = _bool("TRIPPY_DEEP_IDEATION_ON_SELECTION", True)
LLM_CACHE_ENABLED: bool = _bool("TRIPPY_LLM_CACHE_ENABLED", True)
LLM_CACHE_TTL_SECONDS: int = int(os.environ.get("TRIPPY_LLM_CACHE_TTL_SECONDS", "86400"))
LLM_ACCOUNTING_ENABLED: bool = _bool("TRIPPY_LLM_ACCOUNTING_ENABLED", True)

# Backward-compatible aliases
PLANNING_LLM_MODEL: str = PLANNING_ADVISOR_MODEL
EXTRACTION_LLM_MODEL: str = os.environ.get("TRIPPY_EXTRACTION_LLM_MODEL", CONFIRMATION_PARSER_MODEL)

# External source/search config
FIRECRAWL_BASE_URL: str = os.environ.get("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev")
FIRECRAWL_ENABLED: bool = _bool("FIRECRAWL_ENABLED", True)
FIRECRAWL_CACHE_TTL_SECONDS: int = int(os.environ.get("FIRECRAWL_CACHE_TTL_SECONDS", "900"))
FIRECRAWL_MAX_RESULTS: int = int(os.environ.get("FIRECRAWL_MAX_RESULTS", "5"))
SERPAPI_TIMEOUT_SECONDS: float = float(os.environ.get("TRIPPY_SERPAPI_TIMEOUT_SECONDS", "12"))

# Google Sheet template
SHEET_TEMPLATE_ID: str = os.environ.get("TRIPPY_SHEET_TEMPLATE_ID", "")
LIVE_VALIDATION_ENABLED: bool = _bool("TRIPPY_LIVE_VALIDATION_ENABLED", False)
LIVE_VALIDATION_TIMEOUT_SECONDS: float = float(
    os.environ.get("TRIPPY_LIVE_VALIDATION_TIMEOUT_SECONDS", "4")
)
SOURCE_RESEARCH_TIMEOUT_SECONDS: float = float(
    os.environ.get("TRIPPY_SOURCE_RESEARCH_TIMEOUT_SECONDS", "12")
)
SOURCE_RESEARCH_PLAYWRIGHT_ENABLED: bool = _bool("TRIPPY_SOURCE_RESEARCH_PLAYWRIGHT_ENABLED", False)
SOURCE_RESEARCH_OPENCLAW_ENABLED: bool = _bool("TRIPPY_SOURCE_RESEARCH_OPENCLAW_ENABLED", False)
OPENCLAW_GATEWAY_URL: str = os.environ.get("TRIPPY_OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
OPENCLAW_COMMAND: str = os.environ.get("TRIPPY_OPENCLAW_COMMAND", "openclaw")
OPENCLAW_AGENT_ID: str = os.environ.get("TRIPPY_OPENCLAW_AGENT_ID", "main")

DATABASE_URL: str = f"sqlite:///{DB_PATH}"

# Legacy compat aliases (some tests reference old paths)
HERMES_DB_PATH = DB_PATH
HERMES_VAULT_PATH = VAULT_PATH
HERMES_EXPORT_PATH = EXPORT_PATH
