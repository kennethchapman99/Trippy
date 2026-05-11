# Trippy Gmail Confirmation Reconciler

## When to use

Use this skill when Ken asks Trippy to check Gmail for booking confirmations, reconcile bookings, update trip records, or verify that recent flight/lodging/car/activity bookings landed in the trip sheet.

## Required inputs

- Optional `trip_id` if reconciling one trip.
- Optional `since_date` to limit Gmail search.
- Optional `max_emails`; default to a conservative recent batch.

## Procedure

1. Read active trips through Trippy MCP.
2. Search Gmail for booking-related messages.
3. Read full email bodies and attachments when needed.
4. Parse vendor, traveler names, dates, location, confirmation number, price, cancellation terms, and source evidence.
5. Match confirmations to a canonical trip using dates, destination, traveler party, and vendor clues.
6. Update canonical Trippy state only through Trippy MCP tools.
7. Sync the trip sheet after state changes.
8. Run a friction audit after any booking or date change.
9. Summarize matched, unmatched, conflicting, and missing data.
10. Create a learning proposal only for reusable parsing or planning lessons.

## Allowed tools

- Gmail search/read tools.
- Trippy MCP trip state tools.
- Trippy MCP sheet sync tools.
- Trippy MCP friction audit tools.
- Learning proposal tools.

## Human approval gates

Ask for approval before:
- deleting, archiving, or labelling Gmail messages.
- changing or cancelling bookings.
- sending vendor messages.
- sharing traveler information externally.

## What not to infer

Do not infer:
- final price if taxes/fees are unclear.
- cancellation terms unless explicitly present.
- room bedding or capacity unless explicitly present.
- flight baggage allowance unless source evidence supports it.
- which trip owns a confirmation when the match is ambiguous.

## Evidence requirements

Every linked confirmation should include:
- email subject/sender/date reference.
- parsed confirmation number.
- vendor name.
- travel dates.
- confidence score.
- fields that require human verification.

## Verification checklist

- Confirmation dates fall within the trip window.
- Destination/vendor matches the planned trip.
- Traveler names and party size make sense.
- Duplicates and conflicts are flagged.
- Sheet sync completed or failed with a visible reason.
- Friction audit was run after updates.

## Failure modes

- Email is a marketing offer, not a confirmation.
- PDF/attachment cannot be parsed.
- Same confirmation appears in multiple emails.
- Vendor uses unclear date format.
- Booking belongs to a different trip.
- Sheet sync fails due to missing Google credentials.

## Learning capture rules

Create a proposal when:
- a vendor-specific parsing pattern is discovered.
- a recurring false positive appears in Gmail searches.
- a common missing field causes manual work.
- a friction issue should become a durable rule.

Do not silently mutate memory or skill files.