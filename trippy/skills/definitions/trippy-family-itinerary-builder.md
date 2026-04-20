# Skill: trippy-family-itinerary-builder

## Purpose
Build a day-by-day draft itinerary for a trip, applying family travel preferences
automatically. Output is both a structured itinerary and a suggested Google Sheet
population for the trip.

This skill handles: city ordering, recommended nights per destination, activity
pacing for a family with kids, buffer days, and logistics between cities.

## Trigger Conditions
- User says "build an itinerary for [trip]"
- User says "how should we structure [destination]?"
- After `trippy-trip-sheet-creator` creates a trip (suggest as next step)

## Inputs
```json
{
  "trip_id": "japan-2027",
  "destinations": ["Tokyo", "Kyoto", "Osaka"],
  "total_days": 14,
  "interests": ["food", "culture", "nature"],
  "avoid": ["very early mornings", "packed schedules"]
}
```

## Process
1. Load family preferences from memory (pacing, stay length, arrival time preferences)
2. Load family profile (5 travelers including minors — pace accordingly)
3. Research destination logistics: city order, transport between cities, distances
4. Apply preference constraints:
   - min_nights_per_destination (≥2, prefer 3)
   - prefer_slow_travel (no more than 3 destinations per week)
   - airport buffer and transit time from arrival airport to first hotel
5. Build day-by-day structure:
   - Day 1: arrival + settle-in (no packed first day)
   - Intermediate days: activities with reasonable daily count for family
   - Last day: pack + depart (no full-day activities before a long flight)
6. For each city: suggest 2–3 neighbourhoods to focus on
7. Flag family-specific considerations (stroller access, kid-friendly options, etc.)
8. Return as both structured JSON and human-readable day-by-day text

## Outputs
```json
{
  "trip_id": "japan-2027",
  "total_days": 14,
  "itinerary": [
    {"day": 1, "date": "2027-03-10", "city": "Tokyo", "notes": "Arrive NRT (~14:00), transfer to hotel (Shinjuku). Easy evening — jet lag day."},
    {"day": 2, "date": "2027-03-11", "city": "Tokyo", "notes": "Shibuya + Harajuku. Afternoon: teamLab if kids are up for it."},
    "..."
  ],
  "city_summary": {
    "Tokyo": "4 nights (days 1-4)",
    "Kyoto": "3 nights (days 5-7)",
    "Osaka": "3 nights (days 8-10)",
    "Tokyo": "3 nights (days 11-13)",
    "Departure": "day 14"
  },
  "warnings": ["Day 5 Kyoto shinkansen early (07:00 preferred) — check family preference"],
  "suggested_sheet_updates": [...]
}
```

## Persistence After Success
- Day-by-day itinerary written into canonical trip notes
- Sheet sync: populate itinerary tab in Google Sheet
- No memory writes (trip-specific data, not durable preferences)
