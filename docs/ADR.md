# Architecture Decision Record — Trippy Hermes-Native Refactor

## 1. Current Repo Shape

### What exists
The repo (`hermes_trip` Python package, CLI command `hermes-trip`) is a standalone data
ingestion CLI. Its phases are:

- **Phase 1 (done):** Import trip sheets (xlsx/csv/Google Sheets) via Claude structured
  output → upsert into SQLite via SQLAlchemy.
- **Phase 2 (done):** Fetch Gmail confirmation emails → parse via Claude → fuzzy-link to
  trips in DB.
- **Phases 3–7 (planned as CLI stubs):** Visa checks, preference extraction, flight search,
  HTML export, Telegram notifications.

### Current component inventory

| Component | File(s) | Quality |
|-----------|---------|---------|
| SQLAlchemy ORM models | `hermes_trip/db/models.py` | Good — keep |
| Alembic migrations | `hermes_trip/db/migrations/` | Good — keep |
| Google OAuth2 manager | `hermes_trip/ingest/google_auth.py` | Good — keep |
| Gmail watcher | `hermes_trip/ingest/gmail_watcher.py` | Good — keep |
| Confirmation parser (Claude) | `hermes_trip/ingest/parser.py` | Good — keep |
| Confirmation linker | `hermes_trip/ingest/linker.py` | Good — keep |
| Sheet importer (Claude) | `hermes_trip/importers/sheet_importer.py` | Good — keep |
| Drive folder importer | `hermes_trip/importers/drive_importer.py` | Good — keep |
| Typer CLI | `hermes_trip/cli.py` | Keep, extend |
| Config | `hermes_trip/config.py` | Keep, extend |

### What is missing

| Missing Component | Impact |
|------------------|--------|
| Hermes agent runtime / entrypoint | Agent cannot plan or reason — it only ingests |
| AGENTS.md / SOUL.md / .hermes.md | No Hermes-native identity or behavioral config |
| Canonical Pydantic trip model | No structured state separate from ORM models |
| MCP server for Google tools | Hermes cannot call Google APIs as tools |
| Hermes skill definitions | No reusable, self-improving travel workflows |
| Memory store | No durable preference persistence |
| Friction detector | No proactive risk identification |
| Sheet sync service | No bidirectional Sheet ↔ canonical state |
| Family preference model | Preferences not modeled — only planned as Phase 5 |
| New-trip creation workflow | Cannot start a trip from an idea |

---

## 2. Why It Diverges From Hermes-Native Design

### Root cause
The project was designed as a **data pipeline** ("get trip data into a database") rather
than an **agent system** ("reason about, plan, and improve family travel").

Specific divergences:

**No agent layer.** The CLI directly calls importer and parser classes. There is no agent
that reasons, plans, or decides. All logic is imperative, not agentic.

**No Hermes concepts.** AGENTS.md, SOUL.md, skills, and memory are entirely absent. The
"Hermes" in the old project name referred to the project name, not the framework.

**No canonical Pydantic state model.** The ORM models are the only schema. There is no
JSON-serializable trip model suitable for agent context injection or round-tripping.

**No MCP tool layer.** Google APIs are called directly from importers and ingest code.
The Hermes agent cannot call Google as tools — it would need to shell out to the CLI.

**No learning loop.** Preferences are planned (DB table exists) but nothing writes to them.
Nothing reads from them either. The system does not improve over time.

**Google Sheets are import-only.** The importer reads sheets but nothing writes back to
them. There is no sheet sync service, no template creation, no new-trip sheet generation.

**Planning is absent.** The system can ingest existing trips but cannot help plan a new
one — no itinerary building, no flight option reasoning, no friction auditing.

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: AGENT CORE                                             │
│  AGENTS.md + SOUL.md + .hermes.md                               │
│  trippy/agent.py — Hermes agent runtime (Anthropic API)         │
│  trippy/memory/ — Durable preference + profile memory           │
│  trippy/skills/ — Reusable travel workflows                     │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2: TOOL ACCESS (MCP)                                      │
│  trippy/mcp/server.py — FastMCP server                          │
│  trippy/mcp/gmail_tools.py — Gmail search/read/attach           │
│  trippy/mcp/sheets_tools.py — Sheets create/read/write          │
│  trippy/mcp/drive_tools.py — Drive search/list                  │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 3: CANONICAL TRIP STATE                                   │
│  trippy/models/trip.py — Pydantic canonical model               │
│  trippy/models/preferences.py — Family preference model         │
│  trippy/models/profile.py — Traveler/family profile             │
│  trippy/services/trip_state.py — Trip CRUD + JSON persistence   │
│  trippy/services/sheet_sync.py — Trip ↔ Sheet sync              │
│  trippy/services/friction_detector.py — Risk auditing           │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 4: LEARNING LOOP                                          │
│  trippy/memory/store.py — JSON memory store                     │
│  trippy/memory/preference_writer.py — Evidence-based writes     │
│  trippy/skills/runners/ — Skill execution + post-run updates    │
└─────────────────────────────────────────────────────────────────┘
         │                         │
   SQLite DB                  ~/.trippy/trips/
  (persistence)            (canonical JSON state)
```

---

## 4. What Gets Kept, Wrapped, Replaced, or Deleted

### Keep as-is (migrate to `trippy/` package, update imports)
- `db/models.py` — SQLAlchemy models are good; extend with new tables
- `db/migrations/` — Alembic history preserved
- `ingest/parser.py` — Claude-based confirmation extractor is well-designed
- `ingest/gmail_watcher.py` — Gmail API client with EmailContent dataclass
- `ingest/google_auth.py` — Unified OAuth2 manager
- `ingest/linker.py` — Fuzzy confirmation-to-trip matching
- `importers/sheet_importer.py` — Claude-based sheet parser
- `importers/drive_importer.py` — Drive folder bulk importer
- `cli.py` — Extend with new commands; CLI stays useful for direct invocation

### Wrap / promote
- Sheet importer → becomes input to `trippy-past-trip-miner` skill runner
- Confirmation parser + linker → becomes core of `trippy-gmail-reconciler` skill runner
- Drive importer → becomes input to `trippy-past-trip-miner` skill runner
- `ParsedTrip` / `ParsedConfirmation` Pydantic models → feed into canonical models

### Replace
- `hermes_trip/` package → `trippy/` package (complete rename)
- Standalone CLI-only flows → Agent-orchestrated skill invocations
- Phase 3–7 stubs → Proper services + skills implementation

### Add (new)
- `trippy/models/` — Canonical Pydantic schemas
- `trippy/memory/` — Memory store and preference/profile management
- `trippy/mcp/` — FastMCP server with Google tools
- `trippy/skills/` — Hermes skill definitions and runners
- `trippy/services/` — Trip state, sheet sync, friction detector
- `trippy/agent.py` — Main Hermes agent entrypoint
- `trippy/thin_slice.py` — End-to-end demo flow
- AGENTS.md, SOUL.md, CLAUDE.md, .hermes.md — Hermes context files

### Delete
- `hermes_trip/` directory entirely (replaced by `trippy/`)
- Phase 2–7 stubs in cli.py that do nothing (replaced by proper implementations)

---

## 5. Migration Path

### Phase 1 — Hermes skeleton + canonical model (this PR)
**Acceptance criteria:**
- [ ] AGENTS.md, SOUL.md, .hermes.md present and complete
- [ ] `trippy/` package exists with all migrated code
- [ ] Canonical Pydantic models fully defined and tested
- [ ] Memory store implemented and tested
- [ ] MCP server skeleton with all Google tools defined (mockable)
- [ ] All 6 skill definitions written as markdown
- [ ] Friction detector implemented and tested
- [ ] Sheet sync service skeleton
- [ ] `hermes_trip/` package removed, all tests pass with `trippy/` imports
- [ ] `trippy agent` CLI command launches interactive agent

### Phase 2 — Google tooling / MCP integration
**Acceptance criteria:**
- [ ] MCP server runs: `python -m trippy.mcp.server`
- [ ] Gmail tools tested against live Gmail (with credentials)
- [ ] Sheets tools: create sheet, write cells, read cells, copy template
- [ ] Drive tools: search files, list folder
- [ ] Agent can call all MCP tools in an interactive session

### Phase 3 — Past-trip mining and preference extraction
**Acceptance criteria:**
- [ ] `trippy-past-trip-miner` skill: scans Drive folder, imports all sheets
- [ ] `trippy-preference-extractor` skill: derives ≥5 preferences from mined trips
- [ ] Preferences written to memory with confidence scores
- [ ] Family profile populated from traveler data

### Phase 4 — New-trip sheet generation
**Acceptance criteria:**
- [ ] `trippy agent` can start from "Japan next March"
- [ ] Creates canonical trip record
- [ ] Creates Google Sheet from template
- [ ] Sheet populated with destinations, dates, traveler names
- [ ] Preference-aware suggestions (departure times, hotel type)

### Phase 5 — Gmail confirmation reconciliation
**Acceptance criteria:**
- [ ] `trippy-gmail-reconciler` skill: searches Gmail for booking emails
- [ ] Parses confirmations and matches to correct trip
- [ ] Updates canonical trip state (confirmation codes filled in)
- [ ] Pushes changes to Google Sheet
- [ ] Flags ambiguous or unmatched confirmations

### Phase 6 — Friction audit + self-improving skills
**Acceptance criteria:**
- [ ] `trippy-flight-friction-audit` catches ≥5 risk categories
- [ ] Risk report produced with severity and fix recommendations
- [ ] After reconciliation workflow, agent updates relevant skill if pattern found
- [ ] Memory updated with new preference evidence from completed trips

---

## 6. Key Design Decisions

### D1: JSON + SQLite dual storage
**Decision:** Canonical trip state is in `~/.trippy/trips/{trip_id}.json`; SQLite is for
query and indexing.
**Rationale:** JSON files are inspectable, diffable, Git-friendly, and easy to inject into
agent context. SQLite enables efficient fuzzy matching and linking. Both are needed.

### D2: FastMCP for Google tool exposure
**Decision:** Use the `mcp` Python SDK with FastMCP to expose Google tools.
**Rationale:** Clean separation between agent reasoning and tool implementation. The agent
calls `gmail_search()` as a tool, not as a Python import. This enables future swapping of
the Google backend without touching agent logic.

### D3: Skill runners are Python, skill definitions are Markdown
**Decision:** Skills have two parts: a `.md` definition (what the skill does, inputs,
outputs, persistence) and a `.py` runner (how it does it).
**Rationale:** The markdown is what the agent reads to decide whether to invoke a skill.
The Python runner is the actual execution. This separation enables the agent to reason
about skills without running them.

### D4: Memory store is JSON, not a vector DB
**Decision:** Use a JSON file at `~/.trippy/memory.json` with structured categories.
**Rationale:** For a family of 5 with dozens of preferences, a vector DB is overkill.
A structured JSON file with categories is inspectable, testable, and trivially portable.
It can be upgraded to a vector store if/when semantic search becomes valuable.

### D5: Package rename from `hermes_trip` to `trippy`
**Decision:** Complete rename; no backward-compat shim.
**Rationale:** The old name was confusing ("hermes" referred to the project name, not the
Hermes agent framework). A clean rename eliminates the ambiguity and aligns with the
product name ("Trippy").

### D6: Friction detector is deterministic Python, not LLM
**Decision:** `FrictionDetector` uses rule-based logic for most checks.
**Rationale:** Rules like "connection < 90 min is HIGH risk" are deterministic and testable.
Using an LLM for this would add latency, cost, and non-determinism where it's not needed.
The agent uses friction detector output as context for its reasoning, not the other way around.
