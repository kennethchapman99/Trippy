# JSON-First Destination-Agnostic Audit

Date: 2026-04-30
Branch: `codex/json-first-qa-hardening`

## Executive Summary

Trippy is mostly aligned around canonical `TripIntake.geography` and `DestinationProfile`, but the audit found production paths that could still move planning away from explicit JSON state:

- Flight shortlists created canned Google Flights/Kayak candidate rows when live providers returned nothing.
- User-supplied flight candidates could build route links from raw destination text when no destination IATA was resolved.
- Workspace logistics contained Portugal/Schengen/euro defaults.
- Selected-destination planning used country priors by scanning raw destination text.

Those P0/P1 production issues were fixed in this branch. Flights now fail closed without live provider rows or user-supplied itinerary evidence, and flight route links require IATA origin and destination codes.

## Files Inspected

- `trippy/models/trip_planning.py`
- `trippy/services/destination_profiles.py`
- `trippy/services/geography_resolver.py`
- `trippy/services/flight_shortlist.py`
- `trippy/services/lodging_shortlist.py`
- `trippy/services/car_shortlist.py`
- `trippy/services/activity_shortlist.py`
- `trippy/services/trip_planner.py`
- `trippy/services/trip_workspace.py`
- `trippy/services/trip_ideation.py`
- `trippy/services/country_priors.py`
- `trippy/services/shortlist_store.py`
- `trippy/ui/server.py`
- `trippy/ui/static/app.js`
- `tests/unit/test_trip_geography.py`
- `tests/unit/test_trip_planning_pipeline.py`
- `README.md`, `AGENTS.md`, `pyproject.toml`

## Commands Run

```bash
grep -RIn "Chile\|Santiago\|Grand Cayman\|Azores\|Cayman\|Providencia\|Bellavista\|Barrio Italia\|Maipo\|SCL\|GCM\|PDL\|Ponta Delgada\|Seven Mile\|Rum Point\|Stingray\|Tokyo\|Bangkok\|Costa Rica\|Lisbon\|Paris\|London\|Rome\|New York" trippy tests README.md docs .env.example pyproject.toml
grep -RIn "golden path\|demo\|sample\|fixture\|fallback\|hardcoded\|static\|canned\|template\|mock\|stub\|fake\|placeholder\|known destination\|profile_for\|destination_profile\|if .*destination\|if .*trip_name\|if .*seed" trippy tests README.md docs
grep -RIn "IATA\|airport_catalog\|AIRPORT_CATALOG\|primary_gateway\|gateway_airport\|destination_airports\|iata_code" trippy tests
rg -n "weather|beach|island|city scoring|family friendly|best areas|avoid this region|gateway|neighborhood|destination contains|contains\(.*destination|if .* in .*destination|Google Flights|Booking|Expedia|Hotels|rental|maps\.google|deep link|deeplink" trippy tests
rg -n "country=\"Portugal\"|Schengen|euros|Duffel Airways|flight-direct-route|one-stop same-ticket candidate|price sanity-check candidate|DESTINATION_AIRPORT_REQUIRED|fit_for_text\(seed\)|destination_seeds\).*flight|destination_seeds.*gateway" trippy tests
uv run pytest tests/unit/test_trip_geography.py
uv run pytest tests/unit/test_trip_planning_pipeline.py
uv run pytest
uv run mypy trippy/
uv run ruff check .
```

## Findings

### P0 Fixed

- `trippy/services/flight_shortlist.py`: provider failure generated three canned flight options with airline labels, Google Flights/Kayak links, fare language, comfort scores, and recommendation grades. Fixed by removing fallback flight option generation. The shortlist now records warnings and zero flight rows unless live providers or user evidence supply rows.
- `trippy/services/flight_shortlist.py`: user flight candidates without resolved gateway could use raw `destination_seeds` as the arrival airport and build comparison links. Fixed by returning `DESTINATION_AIRPORT_REQUIRED` and suppressing route links unless both origin and destination are valid IATA codes.

### P1 Fixed

- `trippy/services/trip_workspace.py`: workspace logistics rows included Portugal/Schengen/euro defaults. Replaced with destination-agnostic entry/currency/local-movement language.
- `trippy/services/trip_workspace.py`: placeholder stay country was hardcoded to Portugal. Replaced with `intake.geography.country` when explicitly present, otherwise blank.
- `trippy/services/trip_planner.py`: selected-destination drafts used country priors by matching raw seeds/destination text. Restricted country-prior lookup to explicit `geography.country`.
- `tests/unit/test_trip_planning_pipeline.py`: tests expected canned flight fallback rows. Updated to assert fail-closed behavior and to use user-supplied candidates where candidate workflow behavior is under test.

### P1 Remaining

- `trippy/services/trip_ideation.py`: idea-stage trip generation is still based on destination-specific templates such as Cayman, Lisbon/Portugal, Japan, Costa Rica, and Italy. This is acceptable only for explicit idea inspiration, not selected-destination planning. Recommended next PR: replace templates with provider/scanner-backed idea sources or clearly mark the module as inspiration-only and keep it out of downstream trip execution.
- `trippy/services/country_priors.py`: country prior data contains destination facts. Selected-destination planning no longer scans raw seeds for these priors, but idea ranking still uses them. Recommended next PR: require explicit user-approved country field or past-trip evidence scope before applying priors.
- `trippy/skills/runners/itinerary_builder.py`: skill runner can synthesize itinerary city rows from destination summaries. It appears skill-scoped rather than connector/bookable output, but should be hardened to require canonical trip state and mark unresolved rows.

### P2 Accepted

- Named destinations in docs, fixtures, importer/parser tests, friction tests, and OpenClaw/Firecrawl tests are mostly sample strings or isolated fixture evidence.
- `trippy/thin_slice.py` is an explicit demo path and does not appear to be default runtime state.
- UI placeholder copy and docs examples mention destinations but do not directly drive scanner/provider behavior.
- `shortlist_store.py` retains Duffel sandbox filtering strings for "Duffel Airways"; this is provider-sandbox defense, not destination steering.

## JSON-First Verification

- Intake canonicalization only accepts explicit three-letter airport strings as airport refs; non-airport destination chunks become unresolved `TripMapLocation` values.
- `DestinationProfile` exposes flight gateways only from `TripGeography.destination_airports`.
- Lodging/activity/car targets can still use unresolved user-entered place text for scanner/search handoff.
- Flight live providers require IATA route codes; no raw destination string is used as a flight route after this patch.
- Workspace reads selected plan, canonical geography, and shortlist state. Remaining placeholders are marked unconfirmed/seeded, not live/bookable.
- UI/API exposes `/api/state`, `/api/trip`, intake creation, shortlist, workspace, and map endpoints. A dedicated JSON import/export editing path and resolver evidence editor are not yet first-class UI flows.

## Tests Added or Changed

- Added/updated `tests/unit/test_trip_geography.py` coverage for:
  - arbitrary brain dump remains unresolved
  - explicit IATA accepted without invented city/country
  - enriched JSON drives gateway/lodging/activity/car targets
  - concatenated raw destination cannot become a route
  - provider failure creates no fake flight rows
  - user flight candidate without destination IATA gets no route links
- Updated `tests/unit/test_trip_planning_pipeline.py` to stop expecting generated fallback flight rows and to use explicit user candidates for candidate selection/research tests.

## Fixes Made

- Removed canned fallback flight row creation.
- Added IATA guard to flight deep-link builders.
- Blocked raw destination text from becoming user-candidate arrival airport/routes.
- Removed Portugal/Schengen/euro workspace defaults.
- Restricted selected-destination country-prior lookup to explicit enriched geography.

## Remaining Risks

- Idea generation still uses hardcoded concept templates and can return named destinations as suggestions.
- UI does not yet provide a dedicated enriched JSON import/export editor or resolver evidence confirmation workflow.
- Some skill definitions and runners still contain example destination itinerary structures and should be reviewed before being used as production planning paths.

## Check Results

- `uv run pytest tests/unit/test_trip_geography.py`: 6 passed.
- `uv run pytest tests/unit/test_trip_planning_pipeline.py`: 28 passed.
- `uv run pytest`: 345 passed, 5 skipped.
- `uv run mypy trippy/`: success, no issues in 91 source files.
- `uv run ruff check .`: all checks passed.

## Recommended Next PRs

1. Replace or quarantine `trip_ideation.py` templates behind an explicit "inspiration examples" mode.
2. Add a UI/API path for importing, viewing, editing, and exporting enriched `TripIntake` JSON, including resolver evidence and user confirmation status.
3. Harden itinerary-builder skill runner so it can only create itinerary rows from canonical trip JSON or explicit user-supplied rows.
4. Add CI grep checks for destination-specific production code and generated fallback flight/lodging/car/activity rows.
