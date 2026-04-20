# Skill: trippy-flight-friction-audit

## Purpose
Audit a trip's flight plan (and connected logistics) for timing risks, friction points,
and family-specific issues. Produce a ranked risk report with severity and recommended fixes.

This skill runs deterministic rule-based checks, not LLM guessing. Rules are calibrated
for a family of 5 (Ken, Sue, 3 kids) with checked luggage from Toronto.

## Trigger Conditions
- User says "audit [trip name] for issues"
- User asks "is this itinerary ok?" after building a flight plan
- Automatically after `trippy-gmail-reconciler` links a new flight confirmation
- Before finalizing a trip (pre-departure check)

## Inputs
```json
{
  "trip_id": "japan-2026",
  "check_preferences": true
}
```

## Process
Run all of the following checks against the canonical trip state:

### Flight Timing Checks
1. **Departure time** — flag segments departing before earliest_acceptable from preferences
2. **Connection time** — flag connections below min_connection_minutes (domestic/international)
3. **Layover duration** — flag layovers > max_layover_hours_no_hotel (>4h needs hotel plan)
4. **Airport change** — flag connections that require changing airports
5. **Total travel time** — flag outbound or return journeys >18h with no premium cabin

### Alignment Checks
6. **Hotel check-in timing** — if arrival is before 15:00, flag need for early check-in
7. **Rental car desk hours** — if arrival is after 23:00 or before 06:00, flag desk hours issue
8. **Red-eye + no rest** — if overnight flight arrives and first activity is < 4h later
9. **Same-day city transfers** — arriving city A, hotel is city B, no transfer segment found

### Booking Completeness Checks
10. **Unconfirmed segments** — any flight without a confirmation code
11. **Unconfirmed stays** — any hotel/airbnb without a confirmation code
12. **Missing seat assignments** — flights > 90 days away but no seats selected
13. **Baggage** — segments where baggage_included is null or false for family of 5

### Document & Logistics Checks
14. **Passport expiry** — any traveler whose passport expires < 6 months after trip end
15. **Visa / entry requirements** — flag destinations that typically require visa for CAN
16. **Check-in deadline** — if departure < 24h and no check-in recorded

## Risk Severity
- **CRITICAL**: Trip-blocking issue (passport expired, no confirmed flights)
- **HIGH**: Likely to cause significant disruption (90-min connection for family, no hotel night 1)
- **MEDIUM**: Friction that should be resolved (early departure, no seats selected)
- **LOW**: Minor inconvenience or housekeeping item

## Outputs
```json
{
  "trip_id": "japan-2026",
  "total_risks": 3,
  "critical": 0,
  "high": 1,
  "medium": 2,
  "low": 0,
  "risks": [
    {
      "risk_id": "risk-1",
      "severity": "high",
      "category": "layover",
      "description": "AC001 → NRT connection in YVR is 85 min (international). Minimum for family of 5 with bags: 110 min.",
      "affected": ["leg-1"],
      "fix": "Rebook onto AC005 (14:30 YYZ) which gives 155 min in YVR."
    }
  ]
}
```

## Persistence After Success
- Risk flags written to canonical trip state (risk_flags list)
- If a risk type appears in ≥3 trips: write to memory as a planning pattern
  (e.g., "hint:japan-yvr-connection — YYZ→NRT via YVR often has tight connections")
