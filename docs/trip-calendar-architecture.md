# Trippy Trip Calendar Architecture

## Purpose

Trip dates are booking guardrails, not display text. Trippy needs one canonical date model that downstream workflows obey.

The canonical owner introduced by this branch is:

```text
trippy.services.trip_calendar.TripCalendarService
trippy.models.trip_calendar.TripCalendarState
```

## Core principle

- Intake dates are rough planning signals.
- Selected departure and return flights define the outer trip envelope.
- Stay segments define the inside of the trip.
- Transfer segments test whether the stay boundaries are sane.
- Booking-sensitive shortlist rows must be bound to the current calendar version/hash before they can be booking-safe.

## State progression

```text
idea_window
  -> target_window
  -> outbound_selected
  -> envelope_locked
  -> stay_plan_proposed
  -> transfers_priced
  -> calendar_committed
  -> booking_safe
```

## Canonical objects

### Rough window

Comes from `TripIntake.travel_window` and duration fields.

This is useful for ideation and search, but it is not booking-safe.

### Trip envelope

Comes from the selected departure and return flights.

A trip envelope is locked only when both exist:

- selected outbound flight
- selected return flight

The envelope owns:

- trip start datetime/date
- trip end datetime/date
- home return datetime
- origin airport
- destination airport
- return airport
- home arrival airport
- trip nights

### Stay segments

Stay segments are contiguous inside the locked envelope.

Rules:

- first stay starts on trip start date
- last stay ends on trip end date
- sum of stay nights equals trip nights
- transfer dates are stay boundaries

### Transfer segments

A transfer segment is created between adjacent stay segments.

Inter-location flights, ferries, trains, cars, or private transfers are downstream of the envelope. They must never redefine trip start/end.

## Days vs nights

This is a hard rule:

- `duration_days` is a rough intake/planning signal
- `trip_nights` is authoritative after the flight envelope is locked
- lodging/stay structures must sum to `trip_nights`, not `duration_days`

Example:

```text
arrival: 2027-06-16
return departure: 2027-06-22
trip_nights: 6
stay segments must total 6 nights
```

## Calendar versioning

`TripCalendarState` carries:

- `calendar_version`
- `date_dependency_hash`

Every date-driving change should produce a new hash and, after the initial build, a new calendar version.

Date-driving changes include:

- selected departure change
- selected return change
- envelope lock/unlock
- stay split change
- stay order/region change
- transfer boundary change
- manual calendar override

## Flight flow integration

`FlightFlowService` now synchronizes `TripCalendarState` from the current flight shortlist state.

The flight flow payload includes:

- `trip_calendar`
- `trip_calendar_status`
- `calendar_version`
- `date_dependency_hash`
- `calendar_blocking_issues`

The UI should render these fields instead of inferring trip dates from pills, loose fields, or shortlist rows.

## Shortlist calendar binding

All booking-sensitive shortlist option models now carry calendar dependency metadata:

- `calendar_version`
- `date_dependency_hash`
- `valid_for_start_date`
- `valid_for_end_date`
- `valid_for_segment_id`
- `dependency_status`
- `booking_safe`
- `booking_blockers`

`CalendarBindingService` deterministically marks rows as:

- `current`
- `provisional_no_envelope`
- `stale_calendar_changed`
- `missing_dates`
- `invalid_region`
- `unknown`

Rows must not be booking-safe when:

- the trip envelope is not locked
- the row was generated for a stale calendar hash
- the row is a scanner handoff
- the row is search-link only
- the row lacks exact live evidence
- the row does not match a current stay segment/date

## Current implementation slice

Implemented in this branch:

- canonical calendar models
- calendar persistence service
- provisional calendar creation from intake
- selected outbound state without falsely locking end date
- envelope synchronization from selected departure + return flights
- stay segment generation from selected plan options
- transfer boundary creation from stay segments
- invariant validation
- calendar version/hash metadata
- flight-flow payload synchronization
- calendar dependency fields on shortlist option models
- deterministic calendar binding service
- frontend flight-flow type updates for calendar fields
- unit tests for calendar and binding behavior

## Required next slices

### P1 — Wire binding into shortlist save/build paths

Call `CalendarBindingService` before saving:

- flights
- lodging
- cars
- activities

Persist the resulting dependency status, blockers, and booking-safe labels.

### P2 — Lodging integration

- Make lodging searches segment-aware.
- Bind each lodging option to a stay segment.
- Validate check-in/check-out dates against canonical calendar.
- Fix any remaining `duration_days` vs `trip_nights` comparisons.

### P3 — Transfer boundary optimizer

Add `trip_boundary_optimizer.py` to compare alternate stay splits.

It should evaluate:

- transfer date
- transfer cost evidence
- transfer timing
- duration
- family friction
- lodging impact
- activity impact

It must never invent prices or availability.

### P4 — Cars and activities

- Cars must bind to envelope or stay segment dates.
- Activities must bind to region/date windows.
- Arrival days and transfer days should carry friction warnings.

### P5 — UI

Add a Calendar Integrity panel showing:

- current calendar phase
- start/end dates
- trip nights
- selected departure/return
- stay split
- transfer boundaries
- stale options
- blocking issues
- next action

Flight UI must show two separate required steps:

1. Departure flight options
2. Return flight options

Return must remain disabled until departure is selected.

## Acceptance bar

Trippy is not booking-safe until it can prove that the selected booking options match the current canonical calendar version.
