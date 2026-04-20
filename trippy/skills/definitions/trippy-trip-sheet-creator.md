# Skill: trippy-trip-sheet-creator

## Purpose
Given a rough trip idea ("Japan next March", "Costa Rica in January for 10 days"),
create a new canonical trip record and a Google Sheet using the Trippy template.
Pre-fill the sheet with known family info, suggested structure, and preference-aware
recommendations.

## Trigger Conditions
- User says "start a new trip" or "plan [destination] in [timeframe]"
- User provides a rough travel idea to develop
- A trip record exists in DB but no Google Sheet has been created

## Inputs
```json
{
  "trip_idea": "Japan, March 2027, roughly 2 weeks",
  "folder_id": "Drive folder ID to create the sheet in (optional)",
  "template_sheet_id": "Override the default template (optional)"
}
```

## Process
1. Parse the trip idea: destination(s), dates, duration, party (assume all 5 travelers)
2. Create a canonical Trip record with trip_id, name, status=planned
3. Pre-populate travelers from the family profile in memory
4. Suggest itinerary structure: key cities, recommended nights per city, logical order
5. Suggest departure time targets based on preference memory
6. Flag known requirements (JR Pass for Japan, ETA for Canada→Japan, etc.)
7. Call `sheets_from_template(title, template_sheet_id)` to create the Google Sheet
8. Write the canonical data to the sheet:
   - Trip overview tab: name, dates, travelers, status
   - Flights tab: placeholder rows for outbound + return
   - Hotels tab: placeholder rows per city
   - Checklist tab: pre-populated with standard + destination-specific items
9. Write canonical Trip JSON to `~/.trippy/trips/{trip_id}.json`
10. Write trip to SQLite DB
11. Return trip_id, sheet_id, and sheet URL

## Outputs
```json
{
  "trip_id": "japan-2027",
  "sheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
  "sheet_url": "https://docs.google.com/spreadsheets/d/...",
  "suggestion_summary": "Suggest: Tokyo 4n → Kyoto 3n → Osaka 2n → Tokyo 2n",
  "flags": ["Add JR Pass to checklist", "Check ETA requirement for Canadian passports"]
}
```

## Persistence After Success
- Canonical Trip JSON written to `~/.trippy/trips/{trip_id}.json`
- Trip written to SQLite DB (status: planned)
- SyncMetadata updated with sheet_id and sheet_url
- Memory: write skill_hint "New trip {trip_id} created on {date}"
