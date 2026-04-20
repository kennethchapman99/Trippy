# Skill: trippy-past-trip-miner

## Purpose
Search Ken's Google Drive for prior trip spreadsheets, import each one into canonical
trip records, and store them. This is the foundational data-gathering step before
preference extraction.

## Trigger Conditions
- User asks "mine my past trips" or "scan my Drive for trips"
- User asks to refresh travel history
- First-time setup
- A new Drive folder of trip sheets has been shared

## Inputs
```json
{
  "folder_id": "Google Drive folder ID or URL (optional — searches all Drive if omitted)",
  "query": "Search terms to narrow the Drive search (default: 'trip')",
  "max_sheets": "Maximum sheets to import (default: 50)",
  "dry_run": "If true, list sheets found without importing (default: false)"
}
```

## Process
1. Call `drive_list_folder(folder_id)` or `drive_search(query)` to find candidate sheets
2. Filter to sheets that look like travel records (by name or contents)
3. For each sheet, call `sheets_read(spreadsheet_id)` to get raw data
4. Pass raw data to SheetImporter which uses Claude to extract structured trip data
5. Write each trip as a canonical Trip model to `~/.trippy/trips/{trip_id}.json`
6. Write each trip to SQLite DB for query/linking
7. Return a summary: trips found, imported, failed

## Outputs
```json
{
  "sheets_scanned": 12,
  "trips_imported": 10,
  "trips_updated": 2,
  "trips_failed": 0,
  "trip_ids": ["japan-2026", "costa-rica-2025", "..."],
  "summary": "Found 10 past trips. 5 are 'lived', 2 are 'booked'."
}
```

## Persistence After Success
- All canonical trip JSON files written to `~/.trippy/trips/`
- All trips written/updated in SQLite DB
- Trigger `trippy-preference-extractor` if ≥2 lived trips were found
- Write skill_hint to memory: "Last Drive scan found N trips on {date}"

## Error Handling
- Sheets that fail to parse are logged and skipped (not fatal)
- If Google auth fails, surface clear error message with re-auth instructions
- Report partial results if some sheets succeed and some fail
