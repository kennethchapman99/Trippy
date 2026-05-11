# Trippy Lodging Structure Planner

## When to use

Use this skill when deciding single-stay vs split-stay structure, lodging neighborhoods, hotel/villa tradeoffs, or date allocation across multiple trip locations.

## Required inputs

- `trip_id`
- Confirmed or provisional trip boundaries
- Selected plan option or destination shape
- Traveler count and sleeping/privacy needs
- Current lodging shortlist if available
- Current inter-location travel assumptions if multi-location

## Procedure

1. Load canonical trip state and intake.
2. Check date boundary confidence with the Trip Date Guardian skill.
3. Identify whether the trip is single-location or multi-location.
4. For multi-location trips, allocate nights by experience value and travel friction.
5. Consider inter-location travel cost/time before recommending final split.
6. Build or refresh lodging shortlist only within valid date constraints.
7. Recommend a structure call: single stay, split stay, hub-and-spoke, or staged route.
8. Label any dates as provisional if flights or inter-location travel are not selected.
9. Run friction audit after lodging structure changes.

## Allowed tools

- Trippy MCP trip read tools.
- Trippy MCP lodging shortlist tools.
- Trippy MCP date/timeline tools.
- Read-only source research tools.
- Friction audit tools.
- Learning proposal tools.

## Human approval gates

Human approval is required before:
- selecting final lodging.
- changing booked lodging.
- locking multi-location night allocation when inter-location travel evidence is missing.
- booking non-refundable stays.

## What not to infer

Do not infer:
- exact bed layout without source evidence.
- total lodging price without taxes/fees evidence.
- cancellation terms without source evidence.
- checkout feasibility without return/inter-location transport timing.
- that cheapest stay is best if friction is high.

## Evidence requirements

Each lodging recommendation should include:
- location/neighborhood.
- date range and whether it is provisional.
- room/villa capacity evidence.
- cancellation/price confidence.
- family fit notes.
- travel friction notes.
- source link or evidence status.

## Verification checklist

- Trip boundary confidence is known.
- Multi-location night split has inter-location timing considered.
- Lodging check-in/check-out aligns with flights or transfers.
- Family sleeping fit is checked.
- Source evidence status is visible.
- Friction audit was run after structure changes.

## Failure modes

- Lodging is finalized before return date is known.
- Night split ignores expensive or awkward inter-location travel.
- Hotel choice looks good but causes daily transit burden.
- Bed fit is guessed.
- Cancellation terms are missing but not flagged.

## Learning capture rules

Create a proposal when:
- Ken consistently prefers a lodging structure in a destination type.
- split-stay friction changes the recommended trip shape.
- a lodging source is consistently unreliable or useful.
- a family comfort rule should become durable memory.

Do not silently update lodging preferences.