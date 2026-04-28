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
| **Mine past trips** | Scans Google Drive for prior travel sheets, parses them into canonical trip records, and proposes durable planning intelligence |
| **Use country priors** | Applies historical country ratings and notes as directional priors for destination fit, cautions, and ranking |
| **Compare trip ideas** | Turns loose constraints into ranked family-fit concepts with comfort, food, crowd, travel-burden, and friction tradeoffs |
| **Plan new trips** | Turns a selected trip idea into a structured trip record + Google Sheet, pre-filled with itinerary structure and known preferences |
| **Capture trip party** | Records who is actually coming, adult/child counts, roster, child ages, sleeping/privacy needs, and fuzzy duration ranges |
| **Route travel sources** | Uses an explicit source registry for flights, lodging, tours, cars, validation, and deal inspiration |
| **Validate shortlists** | Adds provenance, freshness, confidence, availability, and verification status to shortlist rows, with optional live source-link checks |
| **Generate maps** | Creates practical Google Maps links plus JSON, GeoJSON, and KML artifacts for trip navigation |
| **Show dashboard** | Builds a static Past Trips / Planned Trips / Ideas dashboard from canonical state |
| **Use local UI** | Runs a bright local planning dashboard and trip wizard with stage-by-stage feedback, run logs, and review-gated learning proposals |
| **Reconcile Gmail** | Reads booking confirmations, matches them to the correct trip, updates canonical state, pushes to Google Sheets |
| **Audit for friction** | Proactively flags tight layovers, hotel check-in mismatches, family bed fit, city lodging burden, crowded tours, pacing issues, and missing entry/health/cash research |
| **Self-improve** | Records workflow outcomes, retrospectives, and user feedback, then creates review-gated memory and skill proposals |

---

## Architecture

```
trippy/
  agent.py              Hermes agent — streaming, tool-calling, memory-aware
  config.py             Environment config (paths, API keys)
  models/               Canonical Pydantic schemas (source of truth)
    trip.py             Trip, Segment, Stay, Confirmation, RiskFlag, ...
    preferences.py      FamilyTravelPreferences
    country_priors.py   Historical country-level planning priors
    intelligence.py     Extracted travel intelligence signals
    ideas.py            Trip idea requests, concepts, comparisons
    trip_planning.py    New-trip intake, party/roster, fuzzy duration, plan drafts, and workspace state
    maps.py             Map pins, routes, and trip map artifacts
    sources.py          Travel source registry models
    dashboard.py        Dashboard tiles and export models
    retrospective.py    Post-trip retrospective models
    profile.py          FamilyProfile, TravelerProfile
  memory/               Hermes memory management
    store.py            JSON-backed MemoryStore (versioned, categorized)
    preference_writer.py  Extract durable preference candidates from trip evidence
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
    learning.py         Workflow outcomes, feedback, review-gated proposals
    country_priors.py   Country prior lookup, scoring, and learning proposals
    travel_intelligence.py Past-trip intelligence extraction
    trip_ideation.py    Family-fit trip concept scoring
    trip_intake.py      New-trip intake persistence
    trip_planner.py     Deterministic trip planning drafts, including Azores golden path
    trip_workspace.py   Canonical trip + hydrated planning workspace + Master Timeline creation
    trip_map_builder.py Planning map artifacts from selected plan options
    flight_shortlist.py Source-linked flight recommendation shortlists
    lodging_shortlist.py Family-fit lodging recommendation shortlists
    car_shortlist.py   Car rental recommendation shortlists
    activity_shortlist.py Activity/tour recommendation shortlists
    live_validation.py Conservative live-source link validation for shortlist rows
    source_registry.py  Deterministic travel source routing
    map_outputs.py      Google Maps links + JSON/GeoJSON/KML artifacts
    dashboard.py        Static dashboard JSON + HTML generation
    retrospective.py    Post-trip retrospective proposal workflow
    sheet_sync.py       Trip state ↔ Google Sheets bidirectional sync
    friction_detector.py  Deterministic rule-based risk auditing
  ui/                   Local browser UI, wizard, assets, and service-backed API
  db/                   SQLite persistence (SQLAlchemy 2.x + Alembic)
  ingest/               Email ingestion pipeline (Gmail → confirmation → trip)
  importers/            Sheet importing pipeline (Drive → parse → canonical)
  cli.py                Typer CLI (command: trippy)
  thin_slice.py         End-to-end demo of the full flow (no real credentials needed)
```

**Key design rules:**
- Canonical state lives in `~/.trippy/trips/{trip_id}.json` + SQLite. The LLM reasons about state; it does not store it.
- Google API calls live behind the MCP tools or dedicated sync/workspace service boundaries.
- Memory holds durable truths (preferences, profile). Trip-specific facts stay in trip state.
- Learning is review-gated: workflows and feedback create proposals; only `trippy learn approve` mutates memory or skill files.
- Skills are the self-improvement surface, but skill edits remain human-approved.

---

## Quick Start

```bash
# Install dependencies
uv sync

# Check local/live readiness
uv run trippy doctor

# Run Google OAuth and validate Gmail, Sheets write, and Drive access
uv run trippy auth-google

# Mine past trip intelligence and review proposed learning
uv run trippy mine-intelligence
uv run trippy learn review

# Generate ranked family-fit trip concepts
uv run trippy trip-ideas --time "March break" --days 9 --goal food --goal culture --avoid crowds

# Plan a selected destination with the Azores golden path
uv run trippy trip-intake wizard --no-prompt --trip-name "Azores 2027" --destination Azores --travel-window "summer 2027" --days "9 to 11 days" --party-type whole_family --adults 2 --children 3 --child-age 15 --child-age 12 --child-age 10 --goal nature --goal food
uv run trippy trip-plan draft --trip-id azores-2027
uv run trippy trip-plan select --trip-id azores-2027 --option-id azores-two-island-balanced
uv run trippy trip-plan workspace --trip-id azores-2027
uv run trippy trip-map build --trip-id azores-2027
uv run trippy trip-plan flights --trip-id azores-2027
uv run trippy trip-plan lodging --trip-id azores-2027 --deep-research --adapter auto
uv run trippy trip-plan cars --trip-id azores-2027
uv run trippy trip-plan activities --trip-id azores-2027
uv run trippy trip-plan propose-learning --trip-id azores-2027

# Duration accepts exact or fuzzy values: --days 10, --days "6 to 8 days", --duration "about a week"
# Named rosters are repeatable: --traveler "Ken|adult" --traveler "Child 1|12"
# trip-plan workspace hydrates Flights, Lodging, Cars, Activities, Maps, Risks, Overview, and Master Timeline tabs.
# Add --validate-live to shortlist or workspace commands to attempt conservative source-link validation.
# A verified_live row means the live source page was reachable, not that final inventory/payment terms are proven.
# Add --deep-research --adapter auto on lodging to extract read-only source observations and evidence artifacts.

# Inspect country-level historical priors
uv run trippy country-priors Japan

# Inspect source routing, generate maps, and build the dashboard
uv run trippy sources --category flights
uv run trippy maps <trip-id>
uv run trippy dashboard

# Start the local browser UI
uv run trippy ui
uv run trippy ui --port 8788 --no-open
# UI logs are visible in the Run Log panel and as JSON at /api/logs.
# The backend source of truth is ~/.trippy/learning/events.jsonl.

# Capture post-trip lessons as review-gated proposals
uv run trippy retro <trip-id> --worked "..." --friction "..." --hard-rule "..."

# Run the end-to-end demo (no credentials required)
uv run python -m trippy.thin_slice

# Start the agent
uv run trippy agent

# Start the MCP server (for tool access from the agent)
uv run python -m trippy.mcp.server

# Initialize the database
uv run trippy db-init
```

Copy `.env.example` to `.env` for live use. Trippy stores runtime state under
`~/.trippy` by default:

```bash
TRIPPY_DB_PATH=~/.trippy/state.db
TRIPPY_MEMORY_PATH=~/.trippy/memory.json
TRIPPY_TRIPS_PATH=~/.trippy/trips
TRIPPY_INTAKES_PATH=~/.trippy/intakes
TRIPPY_PLANS_PATH=~/.trippy/plans
TRIPPY_WORKSPACES_PATH=~/.trippy/workspaces
TRIPPY_SHORTLISTS_PATH=~/.trippy/shortlists
TRIPPY_RESEARCH_PATH=~/.trippy/research
TRIPPY_VAULT_PATH=~/.trippy/vault
TRIPPY_EXPORT_PATH=~/.trippy/export
TRIPPY_LEARNING_PATH=~/.trippy/learning
TRIPPY_LIVE_VALIDATION_ENABLED=false
TRIPPY_LIVE_VALIDATION_TIMEOUT_SECONDS=4
TRIPPY_SOURCE_RESEARCH_TIMEOUT_SECONDS=12
TRIPPY_SOURCE_RESEARCH_PLAYWRIGHT_ENABLED=false
TRIPPY_SOURCE_RESEARCH_OPENCLAW_ENABLED=false
TRIPPY_OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
TRIPPY_OPENCLAW_COMMAND=openclaw
GMAIL_CREDENTIALS_PATH=~/.trippy/gmail_credentials.json
GOOGLE_TOKEN_PATH=~/.trippy/google_token.json
```

### Live source research with OpenClaw (optional, read-only)

Set the three OpenClaw env vars above and run an OpenClaw gateway on the configured
URL. Then any of the four shortlists can be enriched with read-only browser-agent
observations:

```bash
uv run trippy trip-plan flights    --trip-id <id> --deep-research --adapter openclaw
uv run trippy trip-plan lodging    --trip-id <id> --deep-research --adapter openclaw
uv run trippy trip-plan cars       --trip-id <id> --deep-research --adapter openclaw
uv run trippy trip-plan activities --trip-id <id> --deep-research --adapter openclaw
```

OpenClaw is invoked **read-only**: search and inspect, never log in, never book,
never add to cart, never check out, never take payment actions. Trippy never
claims live availability, exact price, room layout, cancellation terms, baggage,
or schedule unless an OpenClaw observation directly evidences it. Rows without
evidence stay `HANDOFF_REQUIRED`. After observations are applied, a
deterministic anti-friction post-processor flags risky candidates (late arrivals
vs. lodging check-in, tight layovers, multi-airline tickets, undersized cars,
missing total price or cancellation terms) and downgrades their recommendation
grade and live-data status accordingly.

---

## Skills

Six Hermes skills are registered and callable by the agent:

| Skill | Purpose |
|---|---|
| `trippy-past-trip-miner` | Scan Drive, import prior trip sheets into canonical records |
| `trippy-preference-extractor` | Propose durable preferences from lived trip history |
| `trippy-trip-sheet-creator` | Create a new Google Sheet from a trip idea |
| `trippy-gmail-reconciler` | Fetch Gmail confirmations and link them to trips |
| `trippy-flight-friction-audit` | Audit a trip for risks (layovers, passports, timing) |
| `trippy-family-itinerary-builder` | Build a day-by-day draft itinerary |

---

## Development

```bash
uv run pytest            # 248 passing tests, 5 skipped
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
uv run trippy phase-run 5 --max-emails 50 --dry-run
uv run trippy phase-run 6 --trip-id japan-2027
```

Every meaningful CLI workflow records a workflow ID under
`~/.trippy/learning/events.jsonl`. Attach explicit feedback and review learning proposals:

```bash
uv run trippy feedback <workflow-id> --rating needs-work --notes "..." --correction "..." --future-learning
uv run trippy learn review
uv run trippy learn approve <proposal-id>
uv run trippy learn reject <proposal-id>
```

No preference, profile, memory, or skill learning is applied silently. Past-trip mining,
agent memory updates, user feedback, and friction-derived hints all create pending proposals
first.

---

## Current Status

**Phase 1 — Hermes-native foundation: complete.**

The full architecture is in place and all CI checks pass:

- [x] Canonical Pydantic models (`Trip`, `Segment`, `Stay`, `Confirmation`, `RiskFlag`, ...)
- [x] JSON-backed MemoryStore with versioning, categories, and confidence scoring
- [x] Deterministic `FrictionDetector` (passport expiry, tight connections, missing confirmations, check-in gaps, family bed fit, city/rental fit, pacing, tours, entry/health/cash readiness)
- [x] All 6 Hermes skills defined and runnable
- [x] MCP server with Gmail, Sheets, and Drive tools
- [x] Hermes agent loop (streaming, tool-calling, memory-injection)
- [x] Full Typer CLI (`trippy agent`, `trippy db-init`, `trippy import-drive`, ...)
- [x] SQLite persistence with Alembic migrations
- [x] Setup doctor and Google OAuth validator
- [x] Review-gated workflow feedback and learning proposals
- [x] Country-level priors from historical ratings and notes
- [x] Past-trip intelligence mining and trip idea comparison
- [x] Source registry, map artifact generation, dashboard export, and retrospective proposals
- [x] 248 passing tests, 5 skipped, mypy clean, ruff clean

---

## Roadmap

### Phase 2 — Live Google credentials
Connect real OAuth2 credentials and exercise the MCP tools against Ken's actual Gmail and
Drive. Validate the Gmail → confirmation → trip linking pipeline end-to-end with real data.

### Phase 3 — Past trip mining
Run `trippy-past-trip-miner` against the family's Google Drive to import all historical
trip sheets into canonical records. Extract durable preferences from that history and
review the proposed MemoryStore updates before approving them.

### Phase 4 — New trip sheet creation
Wire up `trippy-trip-sheet-creator` to create real Google Sheets from the template,
populated with trip structure, itinerary draft, and known preferences pre-filled.

### Phase 5 — Gmail reconciliation in production
Run `trippy-gmail-reconciler` live: fetch new booking confirmations from Gmail, parse
them with Claude, link them to the correct trip, update both JSON state and the Sheet.

### Phase 6 — Self-improving skills
After each successful workflow, have the agent assess whether a skill definition should
be updated based on what it learned. Persist the updated `.md` only after review approval
and track skill versions.

---

## Family Context

- **Travelers**: Ken, Sue, and three kids — party of 5
- **Home airport**: Toronto Pearson (YYZ), occasionally Hamilton (YHM)
- **Passports**: Canadian
- **Costs**: CAD unless stated otherwise
- **Optimization priority**: Comfort > schedule > price
