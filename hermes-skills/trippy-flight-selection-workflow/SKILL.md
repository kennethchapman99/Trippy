# Trippy Flight Selection Workflow

## When to use

Use this skill when searching, comparing, selecting, or validating flight options for a trip.

## Required inputs

- Origin airport or city.
- Destination airport or city.
- Departure date or window.
- Return date or window for round trips.
- Traveler count.
- Cabin/stop/airline preferences if provided.
- Current `trip_id` when the search belongs to an existing trip.

## Procedure

1. Load trip intake and canonical state if `trip_id` exists.
2. Normalize origin and destination to airport/city concepts; do not pass itinerary neighborhoods as IATA codes.
3. Split the workflow into two explicit steps:
   - departure flight options and selection.
   - return flight options and selection.
4. Build or request departure options first.
5. After departure selection, update outbound timing constraints.
6. Build or request return options second.
7. After return selection, update trip end constraints.
8. Run a friction audit after either selection.
9. Summarize timeline impact, not just price.

## Allowed tools

- Trippy MCP trip read/update tools.
- Trippy MCP flight shortlist tools.
- Trippy MCP date guardian tools.
- Read-only source research tools.
- Friction audit tools.

## Human approval gates

Human approval is required before:
- booking or purchasing flights.
- changing selected flights.
- accepting risky layovers.
- choosing separate-ticket or multi-airline itineraries.

## What not to infer

Do not infer:
- live availability without source evidence.
- baggage terms without source evidence.
- fare class rules without source evidence.
- IATA codes from neighborhood strings.
- trip end date before return flight selection or explicit confirmation.

## Evidence requirements

Each flight option should include:
- airline/carrier.
- flight numbers if available.
- departure and arrival airports.
- departure and arrival times.
- stops and layover duration.
- source link or provider evidence.
- price status: live, observed, estimated, or missing.
- recommendation grade and friction warnings.

## Verification checklist

- Origin and destination are valid airport/city values.
- Departure and return are visibly separate steps.
- Return selection updates final trip boundary.
- Tight layovers are flagged.
- Overnight/next-day arrivals are clear.
- Multi-airline/separate-ticket risk is flagged.
- Downstream lodging/car/activity dates are rechecked.

## Failure modes

- A destination neighborhood list gets sent as a flight destination.
- UI displays one pill for both departure and return.
- No way to navigate between departure and return options.
- Return not selected but trip end date appears final.
- Price is shown as certain without source evidence.

## Learning capture rules

Create a proposal when:
- Ken rejects a flight pattern repeatedly.
- a carrier/route preference becomes durable.
- a common route parsing issue appears.
- a friction pattern should become a rule.

Do not silently mutate flight preference memory.