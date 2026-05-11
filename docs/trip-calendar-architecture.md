# Trippy Trip Calendar Architecture

## Purpose

Trip dates are booking guardrails, not display text. Trippy must have one canonical date model that downstream workflows obey.

The canonical owner is:

```text
trippy.services.trip_calendar.TripCalendarService
trippy.models.trip_calendar.TripCalendarState
```

## Core principle

- Intake dates are rough planning signals.
- Selected departure and return flights define the outer trip envelope.
- Stay segments define the inside of the trip.
- Transfer segments test whether the stay boundaries are sane.
- Booking-sensitive shortlist rows must be bound to the current calendar version/hash.

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

For example:

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

## Binding shortlists to the calendar

All booking-sensitive rows now support:

- `calendar_version`
- `date_dependency_hash`
- `valid_for_start_date`
- `valid_for_end_date`
- `valid_for_segment_id`
- `dependency_status`
- `booking_safe`
- `booking_blockers`

`CalendarBindingService` deterministically marks rows as current/provisional/stale.

Rows are not booking-safe when:

- the trip envelope is not locked
- the row was generated for a stale calendar hash
- the row is a scanner handoff
- the row is search-link only
- the row lacks exact live evidence
- the row does not match a current stay segment/date

## Flight flow integration

`FlightFlowService` now synchronizes `TripCalendarState` from the current flight shortlist state.

The flight flow payload includes:

- `trip_calendar`
- `trip_calendar_status`
- `calendar_version`
- `date_dependency_hash`
- `calendar_blocking_issues`

The UI should render these fields instead of inferring trip dates from pills, loose fields, or shortlist rows.

## Current implementation slice

Implemented in this branch:

- canonical calendar models
- calendar persistence service
- envelope synchronization from selected flights
- stay segment generation from selected plan options
- transfer boundary creation from stay segments
- invariant validation
- calendar version/hash metadata
- calendar dependency fields on all shortlist option rows
- deterministic calendar binding service
- unit tests for calendar and binding behavior

## Remaining work

The next slices should add:

1. UI endpoints for `GET /api/trips/{trip_id}/calendar` and stay-structure updates.
2. Frontend Calendar Integrity panel.
3. Lodging/car/activity services calling `CalendarBindingService` before saving.
4. Boundary optimizer that compares alternate stay splits against transfer cost/friction.
5. Workspace timeline generation directly from `TripCalendarState`.
6. Full integration tests for single-location and multi-location flows.
