# Trippy Friction Auditor

## When to use

Use this skill after any change to flights, lodging, cars, activities, traveler roster, dates, destination structure, or booking confirmations.

## Required inputs

- `trip_id`
- Current canonical trip state
- Recent change summary if available
- Current shortlists and selected options if relevant

## Procedure

1. Load canonical trip state through Trippy MCP.
2. Run the deterministic Trippy friction audit.
3. Review risks by severity and booking impact.
4. Identify whether risks are caused by missing data, provisional dates, bad sequencing, or selected options.
5. Recommend concrete next actions.
6. Do not invent fixes that require unsupported source facts.
7. Create learning proposals only for reusable patterns.

## Allowed tools

- Trippy MCP read trip tools.
- Trippy MCP friction audit tools.
- Trippy MCP shortlist tools.
- Trippy MCP sheet sync tools when audit output needs to be reflected.
- Learning proposal tools.

## Human approval gates

Human approval is required before:
- changing bookings.
- accepting high-risk timing.
- cancelling or rebooking anything.
- applying a learned hard rule.

## What not to infer

Do not infer:
- passport/visa readiness without stored evidence.
- exact drive/transfer time without source support.
- late check-in permission without source support.
- baggage or cancellation terms without evidence.
- that a missing confirmation means a booking does not exist.

## Evidence requirements

Each friction flag should include:
- severity.
- affected trip object.
- source of the concern.
- what evidence is missing if any.
- recommended next action.
- whether booking is blocked or just cautioned.

## Verification checklist

- Date boundary risks are checked.
- Flight arrival/departure vs lodging check-in/out is checked.
- Car pickup/dropoff timing is checked.
- Family bed/space fit is checked.
- Activity pacing and travel burden are checked.
- Missing confirmations are flagged without overclaiming.
- Output is written back only when explicitly routed through Trippy tools.

## Failure modes

- Audit runs before canonical state is updated.
- Audit output is treated as a booking decision instead of a risk signal.
- Missing source evidence is presented as confirmed risk.
- Low-severity warnings drown out hard blockers.
- Audit is skipped after a date change.

## Learning capture rules

Create a proposal when:
- a risk pattern repeats across trips.
- Ken overrides a warning and the result teaches a preference.
- a new hard-blocking rule should be added.
- the audit creates noise and should be tuned.

Do not silently change friction scoring or durable rules.