# Trippy — Chapman Family Travel Concierge

Trippy is a persistent, self-improving family travel agent for Ken Chapman and his family.
It is not a generic AI travel assistant. It is a dedicated travel intelligence system that
learns from real trips, applies family preferences automatically, and gets progressively
better at planning, organizing, and friction-proofing each journey.

Built on the **Hermes agent architecture** — structured memory, callable skills, MCP tool
access, and a learning loop that persists lessons across trips.

---

## What It Does

| Capability | Description |
|---|---|
| **Mine past trips** | Scans Google Drive for prior travel sheets, parses them into canonical trip records, extracts durable family preferences |
| **Plan new trips** | Turns a rough idea ("Japan next March") into a structured trip record + Google Sheet, pre-filled with itinerary structure and known preferences |
| **Reconcile Gmail** | Reads booking confirmations, matches them to the correct trip, updates canonical state, pushes to Google Sheets |
| **Audit for friction** | Proactively flags tight layovers, hotel check-in mismatches, missing confirmations, passport expiry, missing seats/bags |
| **Self-improve** | Persists durable lessons to memory after successful workflows; updates Hermes skills so future planning is sharper |

---

## Architecture

```
trippy/
  agent.py              Hermes agent — streaming, tool-calling, memory-aware
  config.py             Environment config (paths, API keys)
  models/               Canonical Pydantic schemas (source of truth)
    trip.py             Trip, Segment, Stay, Confirmation, RiskFlag, ...
    preferences.py      FamilyTravelPreferences
    profile.py          FamilyProfile, TravelerProfile
  memory/               Hermes memory management
    store.py            JSON-backed MemoryStore (versioned, categorized)
    preference_writer.py  Extract + write durable preferences from trip evidence
    profile_manager.py  Family profile CRUD
  mcp/                  MCP server — Google API boundary
    server.py           FastMCP entry point
    gmail_tools.py      Gmail search/read/attachment tools
    sheets_tools.py     Sheets create/read/write/template tools
    drive_tools.py      Drive search/list tools
  skills/               Hermes skills (self-improvement surface)
    definitions/        Skill .md specs (one per skill)
    runners/            Python skill execution modules
  services/             Core business logic
    trip_state.py       Canonical trip CRUD + JSON persistence
    sheet_sync.py       Trip state ↔ Google Sheets bidirectional sync
    friction_detector.py  Deterministic rule-based risk auditing
  db/                   SQLite persistence (SQLAlchemy 2.x + Alembic)
  ingest/               Email ingestion pipeline (Gmail → confirmation → trip)
  importers/            Sheet importing pipeline (Drive → parse → canonical)
  cli.py                Typer CLI (command: trippy)
  thin_slice.py         End-to-end demo of the full flow (no real credentials needed)
```

**Key design rules:**
- Canonical state lives in `~/.trippy/trips/{trip_id}.json` + SQLite. The LLM reasons about state; it does not store it.
- All Google API calls go through the MCP server in `trippy/mcp/`. Services never call Google directly.
- Memory holds durable truths (preferences, profile). Trip-specific facts stay in trip state.
- Skills are the self-improvement surface — the agent patches them after successful workflows.

---

## Quick Start

```bash
# Install dependencies
uv sync

# Run the end-to-end demo (no credentials required)
uv run python -m trippy.thin_slice

# Start the agent
uv run trippy agent

# Start the MCP server (for tool access from the agent)
uv run python -m trippy.mcp.server

# Initialize the database
uv run trippy db-init
```

---

## Skills

Six Hermes skills are registered and callable by the agent:

| Skill | Purpose |
|---|---|
| `trippy-past-trip-miner` | Scan Drive, import prior trip sheets into canonical records |
| `trippy-preference-extractor` | Extract durable preferences from lived trip history |
| `trippy-trip-sheet-creator` | Create a new Google Sheet from a trip idea |
| `trippy-gmail-reconciler` | Fetch Gmail confirmations and link them to trips |
| `trippy-flight-friction-audit` | Audit a trip for risks (layovers, passports, timing) |
| `trippy-family-itinerary-builder` | Build a day-by-day draft itinerary |

---

## Development

```bash
uv run pytest            # 186 tests
uv run mypy trippy/      # type checking
uv run ruff check .      # lint
uv run ruff format .     # format
```

CI runs all four checks on every push (GitHub Actions).

---

## Roadmap execution commands

You can inspect and run roadmap phases directly from the CLI:

```bash
# Show phase 2-6 completion, blockers, and the next suggested action
uv run trippy phase-status

# Run a specific phase workflow
uv run trippy phase-run 2
uv run trippy phase-run 3 --folder-id <drive_folder_id>
uv run trippy phase-run 4 --trip-idea "Japan next March"
uv run trippy phase-run 5 --max-emails 50
uv run trippy phase-run 6 --trip-id japan-2027
```

---

## Current Status

**Phase 1 — Hermes-native foundation: complete.**

The full architecture is in place and all CI checks pass:

- [x] Canonical Pydantic models (`Trip`, `Segment`, `Stay`, `Confirmation`, `RiskFlag`, ...)
- [x] JSON-backed MemoryStore with versioning, categories, and confidence scoring
- [x] Deterministic `FrictionDetector` (passport expiry, tight connections, missing confirmations, check-in gaps)
- [x] All 6 Hermes skills defined and runnable
- [x] MCP server with Gmail, Sheets, and Drive tools
- [x] Hermes agent loop (streaming, tool-calling, memory-injection)
- [x] Full Typer CLI (`trippy agent`, `trippy db-init`, `trippy import-drive`, ...)
- [x] SQLite persistence with Alembic migrations
- [x] 186 passing tests, mypy clean, ruff clean

---

## Roadmap

### Phase 2 — Live Google credentials
Connect real OAuth2 credentials and exercise the MCP tools against Ken's actual Gmail and
Drive. Validate the Gmail → confirmation → trip linking pipeline end-to-end with real data.

### Phase 3 — Past trip mining
Run `trippy-past-trip-miner` against the family's Google Drive to import all historical
trip sheets into canonical records. Extract durable preferences from that history and
write them into the MemoryStore.

### Phase 4 — New trip sheet creation
Wire up `trippy-trip-sheet-creator` to create real Google Sheets from the template,
populated with trip structure, itinerary draft, and known preferences pre-filled.

### Phase 5 — Gmail reconciliation in production
Run `trippy-gmail-reconciler` live: fetch new booking confirmations from Gmail, parse
them with Claude, link them to the correct trip, update both JSON state and the Sheet.

### Phase 6 — Self-improving skills
After each successful workflow, have the agent assess whether a skill definition should
be updated based on what it learned. Persist the updated `.md` and track skill versions.

---

## Family Context

- **Travelers**: Ken, Sue, and three kids — party of 5
- **Home airport**: Toronto Pearson (YYZ), occasionally Hamilton (YHM)
- **Passports**: Canadian
- **Costs**: CAD unless stated otherwise
- **Optimization priority**: Comfort > schedule > price
