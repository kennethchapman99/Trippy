# Trippy Tool Architecture

## Boundary model

Trippy uses three separate layers. Keep them separate.

| Layer | Owns | Does not own |
|---|---|---|
| Hermes-compatible orchestration | Planning, reasoning, skill selection, memory context, review-gated learning proposals | Provider-specific scraping/API logic, canonical trip persistence, ranking algorithms |
| Trippy app/domain layer | Canonical trip state, saved trips, ranking, UX/API behavior, shortlist scoring, review gates, business/domain rules | External tool mechanics, permanent learning without review |
| Printing Press-style tools | External-world data access, compact JSON, typed failures, dry-run, fixture/cache/live modes, source/timestamp/confidence/freshness metadata | Trip ranking, UX decisions, memory mutation, booking/payment actions |

## Registry location

```text
trippy/tool_registry/
  registry.json
  registry.py
  gateway.py
  adapters.py
  schemas.py
  schema_definitions/manifest.json
```

`registry.json` is the source of truth for tools. Do not create a second registry in prompts, skills, or services.

## Registered tool categories

Current first-pass tools are fixture-backed and use the final interface:

- `flight_search` -> `flight_option.v1`
- `lodging_search` -> `lodging_option.v1`
- `restaurant_search` -> `restaurant_option.v1`
- `activity_discovery` -> `activity_option.v1`
- `weather_check` -> `weather_result.v1`
- `route_check` -> `route_result.v1`
- `travel_advisory_check` -> `travel_advisory_result.v1`
- `itinerary_validation` -> `itinerary_validation_result.v1`

Every tool result uses the same envelope:

```json
{
  "tool_id": "flight_search",
  "source": "trippy-flights search",
  "mode": "live | cache | fixture | dry_run",
  "type": "flight_option",
  "schema_version": "flight_option.v1",
  "confidence": 0.62,
  "last_checked_at": "2026-05-10T00:00:00Z",
  "stale_after_minutes": 30,
  "summary": "Fixture flight search for YYZ to SCL.",
  "data": {},
  "warnings": [],
  "risk_flags": [],
  "source_urls": []
}
```

## How Hermes calls tools

Hermes-compatible orchestration uses:

```python
from trippy.hermes.orchestrator import HermesCompatibilityOrchestrator

orchestrator = HermesCompatibilityOrchestrator()
result = orchestrator.call_external_tool(
    "flight_search",
    {"origin": "YYZ", "destination": "SCL", "departure_date": "2026-06-08"},
    dry_run=True,
)
```

Internally this routes through:

```text
HermesCompatibilityOrchestrator
  -> HermesToolClient
    -> TrippyToolGateway
      -> ToolRegistry
        -> ToolAdapter
```

## How to add a new generated tool

1. Add a stable schema if needed in `trippy/tool_registry/schemas.py` and `schema_definitions/manifest.json`.
2. Add an entry to `trippy/tool_registry/registry.json`.
3. Implement or register an adapter in `trippy/tool_registry/adapters.py`.
4. Start with `status: "fixture"` unless a real provider path is tested.
5. Make `dry_run(input)` return the same envelope without network access.
6. Make `healthcheck()` return provider readiness without booking/log-in/payment actions.
7. Add tests proving:
   - registry loads
   - schema is known
   - dry-run works
   - fixture/live output validates
   - typed failure output validates
   - freshness/source/confidence metadata is present

## Health checks

```bash
python scripts/trippy_tool_gateway.py healthcheck
python scripts/trippy_tool_gateway.py healthcheck flight_search
```

## Fixture mode

Fixture mode validates the final interface without pretending to be live.

```bash
python scripts/trippy_tool_gateway.py run flight_search '{"origin":"YYZ","destination":"SCL","departure_date":"2026-06-08"}'
python scripts/trippy_tool_gateway.py run lodging_search '{"destination":"Valparaiso","start_date":"2026-06-11","end_date":"2026-06-14"}'
python scripts/trippy_tool_gateway.py run activity_discovery '{"destination":"Santiago","interests":["food","culture"]}'
```

## Dry-run mode

Dry-run mode shows what would be called and performs no external provider work.

```bash
python scripts/trippy_tool_gateway.py dry-run flight_search '{"origin":"YYZ","destination":"SCL"}'
python scripts/trippy_tool_gateway.py dry-run lodging_search '{"destination":"Valparaiso"}'
python scripts/trippy_tool_gateway.py dry-run activity_discovery '{"destination":"Santiago"}'
```

## Promote fixture/mock tool to live

1. Implement the live provider command behind the adapter interface.
2. Keep the `tool_id`, schema, and output envelope stable.
3. Add typed provider failures using `tool_error.v1`.
4. Add cache if useful and set `supports_cache` truthfully.
5. Add live healthcheck coverage.
6. Only then change `status` from `fixture` to `live` in `registry.json`.

## Scouty inspection

```bash
python scripts/scouty_describe.py
```

The output includes:

- app name
- registry path
- registered tools
- schemas
- detected LLM calls
- detected external API references
- memory/learning files
- healthcheck command
- fixture/dry-run commands
- test command

## Tests

```bash
uv run pytest tests/unit/test_tool_registry_gateway.py tests/unit/test_hermes_orchestration.py
```

## Current migration status

The new registry/gateway/Hermes-compatible boundary is implemented. Legacy shortlist services still contain some direct provider integrations. Do not expand those direct integrations. Migrate them behind registered adapters one vertical at a time, starting with flights because flight selection defines trip start/end-date guardrails.
