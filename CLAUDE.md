# CLAUDE.md — Trippy Development Guide

## Project Overview

Trippy is a Hermes-native family travel concierge for Ken Chapman. It is built as a
Hermes agent system with four layers:

1. **Agent Core** — Hermes agent + AGENTS.md + SOUL.md + memory + skills
2. **Tool Access** — MCP server exposing Gmail, Sheets, Drive to the agent
3. **Canonical Trip State** — Pydantic models + JSON files + SQLite persistence
4. **Learning Loop** — Memory writes + skill updates after successful workflows

## Package Structure

```
trippy/                     Main Python package
  agent.py                  Hermes agent entrypoint (streaming, tool-calling)
  thin_slice.py             Demo: complete end-to-end flow
  config.py                 Environment config
  models/                   Canonical Pydantic schemas (source of truth)
    trip.py                 Trip, Segment, Stay, Confirmation, RiskFlag, ...
    preferences.py          FamilyTravelPreferences
    profile.py              FamilyProfile, TravelerProfile
  memory/                   Hermes memory management
    store.py                JSON-backed MemoryStore
    preference_writer.py    Write preferences from evidence
    profile_manager.py      Family profile CRUD
  mcp/                      MCP server for Google tool access
    server.py               FastMCP entry point (run: python -m trippy.mcp.server)
    gmail_tools.py          Gmail search/read/attachment tools
    sheets_tools.py         Sheets create/read/write/template tools
    drive_tools.py          Drive search/list tools
  skills/                   Hermes skills
    definitions/            Skill .md specs (one per skill)
    runners/                Python skill execution modules
  services/                 Core business logic
    trip_state.py           Canonical trip CRUD + JSON persistence
    sheet_sync.py           Trip state ↔ Google Sheets bidirectional sync
    friction_detector.py    Proactive risk/friction detection
  db/                       SQLite persistence (SQLAlchemy 2.x)
    models.py               ORM models
    migrations/             Alembic migrations
  ingest/                   Email ingestion pipeline
    parser.py               Claude-based confirmation extractor
    gmail_watcher.py        Gmail API client
    google_auth.py          Unified OAuth2 manager
    linker.py               Fuzzy confirmation-to-trip matching
  importers/                Sheet importing pipeline
    sheet_importer.py       Claude-based sheet parser
    drive_importer.py       Drive folder bulk importer
  cli.py                    Typer CLI (command: trippy)
```

## Development Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Type check
uv run mypy trippy/

# Lint + format
uv run ruff check trippy/ tests/
uv run ruff format trippy/ tests/

# Initialize database
uv run trippy db-init

# Start MCP server (for testing tool access)
uv run python -m trippy.mcp.server

# Run thin slice demo
uv run python -m trippy.thin_slice

# Start agent
uv run trippy agent
```

## Key Architectural Rules

1. **Never bypass Hermes.** The agent must orchestrate all workflows. Do not write scripts
   that skip the agent layer for production flows (thin_slice.py is only a demo).

2. **Canonical state is JSON + SQLite, not prompt text.** Facts go in
   `~/.trippy/trips/{trip_id}.json` and the DB. The LLM reasons about state; it does not
   store it.

3. **Memory is for durable truths, not trip specifics.** A preference like "avoid 6 AM
   departures" belongs in memory. A specific confirmation code belongs in trip state.

4. **MCP tools are the Google boundary.** All Google API calls go through
   `trippy/mcp/`. Do not call Google APIs directly from services or skills.

5. **Skills are the self-improvement surface.** After a non-trivial workflow, the agent
   should assess whether a skill needs updating. Skills live in `trippy/skills/`.

## Adding a New Skill

1. Create `trippy/skills/definitions/trippy-{name}.md` following the existing template
2. Create `trippy/skills/runners/{name}.py` with a `SkillRunner` implementing `run(inputs)`
3. Register the skill in `trippy/skills/__init__.py`
4. Update `AGENTS.md` skill table

## Adding a New MCP Tool

1. Add the tool function to the appropriate file in `trippy/mcp/`
2. The function must use `@mcp.tool()` decorator with type annotations
3. All inputs/outputs must be JSON-serializable
4. Add a test in `tests/unit/test_mcp_tools.py`

## Testing

- Unit tests use in-memory SQLite and mocked Claude/Google clients
- All Claude API calls are injectable: `ConfirmationParser(anthropic_client=mock)`
- All Google API calls are injectable: `GoogleAuthManager(credentials=mock)`
- MCP tools tested with mock Google clients
- New canonical model tests in `tests/unit/test_canonical_models.py`
- Friction detector tests in `tests/unit/test_friction_detector.py`
- Memory store tests in `tests/unit/test_memory_store.py`

## Environment Variables

```
ANTHROPIC_API_KEY          Required for Claude API
TRIPPY_DB_PATH             SQLite path (default: ~/.trippy/state.db)
TRIPPY_MEMORY_PATH         Memory store (default: ~/.trippy/memory.json)
TRIPPY_TRIPS_PATH          Trip JSON files (default: ~/.trippy/trips/)
TRIPPY_VAULT_PATH          Email archive (default: ~/.trippy/vault/)
GMAIL_CREDENTIALS_PATH     OAuth2 client credentials JSON
GOOGLE_TOKEN_PATH          OAuth2 token (default: ~/.trippy/google_token.json)
TRIPPY_SHEET_TEMPLATE_ID   Google Sheet template spreadsheet ID (optional)
```

## Important: What NOT to Do

- Do not add new standalone ingestion scripts outside the Hermes agent flow
- Do not write trip-specific facts into Hermes memory
- Do not call Google APIs directly from services — use MCP tools
- Do not treat Google Sheets as the canonical state — they are a view
- Do not keep `hermes_trip/` references — the package is `trippy`
