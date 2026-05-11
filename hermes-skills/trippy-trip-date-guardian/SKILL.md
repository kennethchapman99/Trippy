# Trippy Trip Date Guardian

## When to use

Use this skill whenever trip boundaries, flights, lodging dates, car rental dates, or activity dates are being created, selected, changed, or questioned.

## Required inputs

- `trip_id`
- Current canonical trip state
- Any selected departure flight
- Any selected return flight
- Any lodging/car/activity date ranges involved in the change

## Procedure

1. Load canonical trip state through Trippy MCP.
2. Identify whether the departure flight is selected.
3. Identify whether the return flight is selected.
4. Treat the departure flight as the outbound timing anchor.
5. Treat the return flight as the end-date anchor.
6. If the return flight is missing, do not finalize hard trip end dates unless Ken explicitly confirms them.
7. Validate lodging, cars, and activities against selected flight boundaries.
8. Run a friction audit after any boundary change.
9. Return a concise status: confirmed dates, provisional dates, missing anchors, and risks.

## Allowed tools

- Trippy MCP read trip tools.
- Trippy MCP flight selection/date tools.
- Trippy MCP timeline tools.
- Trippy MCP friction audit tools.
- Learning proposal tools.

## Human approval gates

Human approval is required before:
- finalizing a trip end date without a selected return flight.
- changing existing booked lodging/car/activity dates.
- overwriting a previously confirmed date boundary.

## What not to infer

Do not infer:
- a return date from the lodging checkout alone.
- a final trip end date from the destination stay plan.
- car rental dates from a rough trip duration.
- activity dates before the master timeline has stable boundaries.

## Evidence requirements

A confirmed boundary needs one of:
- selected flight evidence.
- explicit human confirmation.
- confirmed booking evidence.

Otherwise label it provisional.

## Verification checklist

- Departure and return are represented as separate steps.
- Return flight is required before final trip end date is locked.
- Lodging checkout does not conflict with return flight.
- Car pickup/dropoff matches flight timing.
- Activities are not scheduled outside the confirmed window.
- Friction audit has been run after changes.

## Failure modes

- UI collapses departure and return into one impossible pill.
- Destination string is mistakenly treated as an airport route.
- Return date is missing but downstream planning acts as if it is known.
- Lodging or car dates are generated before flights are selected.
- Date changes do not trigger friction re-checks.

## Learning capture rules

Create a proposal when:
- a date ambiguity recurs.
- a source creates bad airport/city parsing.
- a user correction reveals a durable date-handling rule.

Do not silently change core date rules without review.