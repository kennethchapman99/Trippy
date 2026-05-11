# Hermes-Native Trippy Architecture

## Diagnosis

Trippy has the right intent but is still mostly Hermes-inspired rather than Hermes-native.

Current state:
- `trippy/agent.py` manually builds a system prompt, injects memory, exposes tools, routes skills, and calls deterministic services.
- Hermes concepts exist in the repo: memory, skills, MCP, review-gated learning, and canonical state.
- The orchestration layer is still mostly custom Trippy code.

Target state:
- Hermes owns the agent brain, profile, memory, skill discovery, tool use, session history, and review-gated self-improvement.
- Trippy owns deterministic travel product logic, canonical state, UI, Google Sheets sync, source evidence, and friction scoring.
- MCP is the boundary between them.

## Responsibility split

| Layer | Owns | Should not own |
|---|---|---|
| Hermes profile `trippy` | orchestration, durable memory, skills, tool permissions, reviewable learning, trip-ops conversation flow | canonical trip database, date math, source-of-truth booking state |
| Trippy app | canonical JSON/SQLite state, trip UI, timeline model, shortlist models, sheet sync, Gmail parsing, friction detector | open-ended agent reasoning or hidden memory mutations |
| Trippy MCP | narrow, safe tools for Hermes to call | broad arbitrary Python execution |
| OpenClaw / Firecrawl | read-only evidence gathering | booking, checkout, payment, login-only actions |

## Canonical rule

The LLM may reason about trip state, but it does not store trip state.

- Durable family truths: Hermes memory.
- Trip-specific facts: Trippy canonical state.
- External evidence: Trippy source evidence records.
- Workflow lessons: review-gated learning proposals.
- Skill changes: proposed by Hermes, reviewed by Ken, then versioned.

## Target MCP tool boundary

Expose narrow domain tools instead of one broad router:

- `trippy_list_trips`
- `trippy_get_trip`
- `trippy_create_intake`
- `trippy_build_flight_shortlist`
- `trippy_build_lodging_shortlist`
- `trippy_build_car_shortlist`
- `trippy_build_activity_shortlist`
- `trippy_run_friction_audit`
- `trippy_sync_trip_sheet`
- `trippy_record_learning_event`
- `trippy_propose_skill_update`

Future high-value tools:

- `trippy_select_departure_flight`
- `trippy_select_return_flight`
- `trippy_update_trip_dates_from_flights`
- `trippy_build_master_timeline`
- `trippy_validate_trip_date_constraints`

## Date guardrail

A trip does not have a confirmed end date until the return flight is selected or a human explicitly confirms the end date.

Required behavior:
- Departure flight selection can set arrival/start constraints.
- Return flight selection sets final trip end constraints.
- Lodging/cars/activities must not finalize hard dates without both boundary anchors.
- Any mismatch between selected flights and lodging/cars/activities triggers a friction audit.

## Skill migration plan

Source-controlled Hermes skill templates live in `hermes-skills/`.

Initial skills:
- `trippy-gmail-confirmation-reconciler`
- `trippy-trip-date-guardian`
- `trippy-flight-selection-workflow`
- `trippy-lodging-structure-planner`
- `trippy-friction-auditor`

These should be copied or synced into the Hermes `trippy` profile skill directory. The repo remains the editable source of truth; the Hermes profile is the runtime deployment target.

## Learning loop

Every meaningful workflow should produce one of four outcomes:

1. No reusable learning.
2. Durable memory proposal.
3. Skill improvement proposal.
4. Product/code improvement issue.

No memory or skill update should apply silently. Trippy already has the right review-gated philosophy; the next step is to make Hermes the primary place where skill/memory proposals are generated and curated.

## Curator strategy

Hermes Curator should be used carefully:
- Pin core Trippy skills.
- Run dry-runs before applying changes.
- Keep backups and rollback points.
- Avoid over-merging skills that represent distinct workflows.
- Prefer pruning stale references and examples over rewriting core procedures.

## Migration order

1. Keep `trippy/agent.py` as transitional.
2. Add Trippy domain MCP tools.
3. Create Hermes profile documentation.
4. Move current skill definitions into Hermes-native skill templates.
5. Use one real workflow as the first Hermes-native thin slice: Gmail confirmation → canonical trip update → sheet sync → friction audit → learning proposal.
6. Only after the thin slice works, migrate flight/lodging/activity planning orchestration.

## Non-goals

Do not move deterministic logic into prompts.

Keep these in code:
- date math
- flight departure/return constraints
- trip segment boundaries
- booking state machine
- canonical models
- source evidence records
- friction scoring
- sheet sync
- live-source confidence rules

## Success criteria

Trippy is Hermes-native when:
- A Hermes `trippy` profile can plan, reconcile, audit, and improve through MCP tools.
- Skills are discoverable and editable by Hermes, not hard-coded only inside `trippy/agent.py`.
- Memory updates are review-gated and durable.
- Trip state remains canonical in Trippy.
- Tool calls are narrow, auditable, and safe.
