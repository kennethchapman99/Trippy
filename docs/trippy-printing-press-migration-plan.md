# Trippy Printing Press Tool-Layer Migration Plan

## Goal

Move Trippy away from scattered agent-owned external-world calls and toward one stable external tool boundary:

- **Hermes-compatible orchestration** owns planning, reasoning, skill selection, memory context, and review-gated learning proposals.
- **Trippy** owns canonical trip state, ranking, saved trips, UX/API behavior, and business/domain rules.
- **Printing Press-style tools** own external-world data access, compact JSON outputs, health checks, dry-run support, schemas, fixture/live mode, freshness, source, and confidence metadata.

## Current repo observations

- `trippy/agent.py` currently behaves as a custom LLM tool loop with direct internal tool execution.
- Some external travel evidence paths are still implemented inside shortlist/services code, including flight/live-source research and web-intelligence enrichment.
- Existing service behavior is valuable and should not be ripped out without preserving trip creation, itinerary generation, UI routes, saved trips, and CLI commands.
- The safest first migration step is to introduce a real registry/gateway boundary and route new Hermes-facing external tools through it.

## Implemented in this branch

1. Added `trippy/tool_registry/`:
   - `registry.json`
   - `registry.py`
   - `gateway.py`
   - `adapters.py`
   - `schemas.py`
   - schema manifest under `schema_definitions/manifest.json`

2. Added a Hermes compatibility boundary:
   - `trippy/hermes/orchestrator.py`
   - `trippy/hermes/tool_client.py`

3. Added fixture-backed external-world tools:
   - `flight_search`
   - `lodging_search`
   - `restaurant_search`
   - `activity_discovery`
   - `weather_check`
   - `route_check`
   - `travel_advisory_check`
   - `itinerary_validation`

4. Added utility scripts:
   - `scripts/trippy_tool_gateway.py`
   - `scripts/scouty_describe.py`

5. Added tests for:
   - registry load
   - known schemas
   - dry-run output
   - fixture output
   - freshness metadata
   - gateway health checks
   - Hermes-compatible orchestrator using the tool gateway
   - learning proposals remaining pending review

## Migration sequence from here

### Phase 1 — boundary in place

Status: implemented in this branch.

- Registry is machine-readable.
- Tool outputs are normalized and validated.
- Fixture/dry-run mode is explicit.
- Hermes compatibility layer delegates external-world tools through the gateway.

### Phase 2 — refactor legacy shortlist services

Next work:

- Move provider-specific external calls out of shortlist services and into registered adapters.
- Start with flight providers:
  - Duffel search
  - SerpAPI flight fallback
  - scanner fallback trigger
- Then lodging/activity/car/web-intelligence adapters.
- Keep Trippy scoring/ranking in services, but feed them normalized tool results.

Target dependency direction:

```text
Hermes orchestrator
  -> TrippyToolGateway
    -> registered Printing Press-style adapter
      -> live/cache/fixture provider command
  -> Trippy service/ranker
    -> canonical trip state / shortlist state
```

Not this:

```text
Hermes agent prompt/tool loop
  -> random service helper
    -> direct API/scraper/provider call
```

### Phase 3 — promote fixture adapters to live

For each live adapter:

1. Implement provider-specific command behind the common adapter interface.
2. Keep the registry entry stable.
3. Set `status` to `live` only after tests prove:
   - schema validation
   - dry-run behavior
   - healthcheck behavior
   - typed failures
   - no booking/payment/login actions
   - source/timestamp/confidence/freshness metadata
4. Add cache support when provider cost/rate limits justify it.

### Phase 4 — remove legacy direct calls

Once a category has a live adapter:

- Replace direct service calls with `TrippyToolGateway.call(...)`.
- Keep backward-compatible CLI/API wrappers.
- Add tests proving the service calls the gateway and not provider helpers directly.
- Delete or quarantine obsolete provider-specific helpers.

## Guardrails

- Do not put provider calls inside prompts.
- Do not let generated tools rank trips.
- Do not let generated tools mutate memory or trip state.
- Do not silently add permanent preferences.
- Do not mark mock/fixture output as live.
- Do not create a second registry.
- Do not remove working UI/API routes without explicit migration tests.

## Known remaining gap

This branch establishes the new architecture and Hermes-facing external tool boundary, but it does not fully migrate every legacy shortlist/provider service. Existing services still contain some direct provider logic. The next PR should focus on one vertical at a time, beginning with flight search, because dates and trip envelope constraints depend heavily on accurate departure/return flight selection.
