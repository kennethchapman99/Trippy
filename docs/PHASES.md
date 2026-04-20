# Trippy Delivery Phases (Execution Plan)

This document expands the roadmap into concrete, testable phases with a clear
"ready to test by creating a new trip" gate.

## Phase 2 — Live Google credentials

**Goal:** Trippy can authenticate safely to Gmail, Drive, and Sheets.

**Definition of done:**
- OAuth credentials and token are present and loadable.
- MCP tools can run read + write operations without manual patching.

## Phase 3 — Historical mining + durable preferences

**Goal:** Build family intelligence from real prior trips.

**Definition of done:**
- Past trip sheets imported into canonical trip JSON.
- Preference object exists in memory and is evidence-backed.
- Global family defaults are available for planning sessions.

## Phase 4 — New trip creation and human-readable sheet

**Goal:** Turn a rough idea into canonical state + Google Sheet.

**Definition of done:**
- New trip can be created from a text idea.
- Google Sheet is linked in sync metadata.
- Checklist and baseline structure are pre-populated.

## Phase 5 — Gmail reconciliation in production

**Goal:** Keep bookings continuously reconciled.

**Definition of done:**
- Booking confirmations are parsed from Gmail.
- Confirmations are linked to segments/stays.
- Canonical trip and sheet are both updated.

## Phase 6 — Friction audit and safety loop

**Goal:** Catch trip risks before they hurt the family.

**Definition of done:**
- Risk flags are persisted on trips.
- High/critical findings generate reusable skill hints.
- Passport and timing constraints are audited on active trips.

## Phase 7 — Choice intelligence (flights + stays)

**Goal:** Make highly specific recommendations that match family taste.

**Definition of done:**
- Global preference keys exist for flight choice criteria.
- Global preference keys exist for stay choice criteria (Airbnb + boutique + hotels).
- At least one trip captures trip-specific overrides without mutating global defaults.

## Phase 8 — Dual-surface concierge output

**Goal:** Keep both machine state and human-facing views excellent.

**Definition of done:**
- Agent answers can reference canonical trip and preference state.
- Google Sheet remains an up-to-date human-readable mirror.
- Context includes both global preferences and trip-specific nuances.

## New trip testing gate

Trippy is considered **ready to test by building a new trip** when all are true:
1. Phase 2 complete
2. Phase 3 complete
3. Phase 4 complete
4. Phase 7 complete
5. Phase 8 complete

This ensures we are not only able to create a trip, but able to make high-quality,
detailed recommendations and keep state usable for both humans and the concierge.
