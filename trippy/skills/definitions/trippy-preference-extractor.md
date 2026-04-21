# Skill: trippy-preference-extractor

## Purpose
Analyse a set of canonical trip records and derive durable family travel preferences.
Create review-gated Hermes learning proposals with confidence scores based on evidence strength.
Do not mutate durable memory until a human approves the proposal.

This skill distinguishes durable preferences ("we consistently avoid 6 AM departures")
from one-off exceptions ("took a 5 AM flight once for a very cheap deal").

## Trigger Conditions
- After `trippy-past-trip-miner` completes with ≥2 lived trips
- User says "learn from our past trips"
- When confidence of existing preferences drops below 0.5 (needs refresh)
- After completing a major trip (add new evidence)

## Inputs
```json
{
  "trip_ids": ["japan-2026", "costa-rica-2025"],
  "min_evidence_trips": 2
}
```
If `trip_ids` omitted, loads all lived trips from `~/.trippy/trips/`.

## Process
1. Load canonical Trip models for all specified (or all lived) trips
2. Analyse departure time patterns across all segments
3. Analyse connection time patterns (identify min tolerated)
4. Analyse stay patterns (average nights/destination, hotel types chosen)
5. Analyse pacing (number of destinations per week)
6. Identify what changed: did they upgrade cabin? book direct more often?
7. Distinguish patterns (seen in ≥min_evidence_trips) from outliers
8. Propose durable preferences with source_trips reference
9. Propose family profile updates (passport expiry from traveler data)
10. Wait for `trippy learn approve <proposal-id>` before memory changes

## Outputs
```json
{
  "preferences_proposed": {
    "departure_time": "Earliest acceptable 07:30 (conf=75%, 4 trips)",
    "min_connection_international": "110 min (conf=80%, 3 trips)",
    "nights_per_destination": "3+ preferred (conf=70%, 5 stays)"
  },
  "learning_proposals": ["lp-..."],
  "profile_updates": ["Ken passport expiry updated"],
  "skip_reason": null
}
```

## Persistence After Success
- All inferred preferences become pending proposals under category: "preference"
- Family profile updates become pending proposals under category: "profile"
- Approval through `trippy learn approve <proposal-id>` is required before persistence

## Do NOT Write to Memory
- Any inferred preference before explicit review approval
- Trip-specific confirmation codes or booking details
- Costs for specific trips (averages only, if relevant)
- One-off decisions that don't generalize
