# Skill: trippy-gmail-reconciler

## Purpose
Search Gmail for booking confirmation emails, parse them into structured data, match
each confirmation to the correct trip, update canonical trip state with confirmation
codes, and push changes to the Google Sheet. Flag ambiguous or unmatched confirmations.

## Trigger Conditions
- User says "check my email for booking confirmations"
- User says "reconcile [trip name] confirmations"
- After booking a flight or hotel ("I just booked the flights — check Gmail")
- Periodic reconciliation run (weekly during active trip planning)

## Inputs
```json
{
  "trip_id": "japan-2026 (optional — reconcile all active trips if omitted)",
  "since_date": "2026-01-01 (optional — only look at emails since this date)",
  "max_emails": 50
}
```

## Process
1. Call `gmail_search_bookings(max_emails)` to find candidate emails
2. If trip_id specified, narrow query to that trip's date range
3. For each email, call `gmail_get_email(message_id)` to get full content
4. For PDF attachments, call `gmail_get_attachment` and extract text with PyPDF
5. Pass email body + attachments to ConfirmationParser (Claude)
6. Match each parsed confirmation to a trip using TripLinker (fuzzy matching)
7. For matched confirmations:
   - Update canonical trip state: fill in confirmation_code on segment/stay
   - Write Confirmation object to trip record
   - Trigger sheet sync to update Google Sheet
8. For unmatched: store as unlinked, surface in output with suggested matches
9. Detect conflicts (two confirmations for same segment with different codes)

## Outputs
```json
{
  "emails_scanned": 23,
  "confirmations_parsed": 8,
  "confirmations_linked": 6,
  "confirmations_unlinked": 2,
  "conflicts": [],
  "updates": [
    {"trip": "japan-2026", "field": "segments[0].confirmation_code", "value": "ABC123"},
    {"trip": "japan-2026", "field": "stays[0].confirmation_code", "value": "BOOKING-XYZ"}
  ],
  "unlinked": [
    {"vendor": "Marriott", "code": "RES789", "dates": "Mar 15-18", "reason": "No matching trip found"}
  ]
}
```

## Persistence After Success
- Updated canonical Trip JSON for all affected trips
- Updated SQLite DB confirmations table
- Updated Google Sheets (via sheet_sync)
- If recurring pattern found (e.g., Airbnb confirmations often unlinked): write skill_hint to memory
