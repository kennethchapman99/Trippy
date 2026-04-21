# Trippy Next-Phase Architecture

## Goal

Trippy should become a family-specific travel intelligence system, not a generic destination
recommender. The next build should strengthen three foundations before deeper booking
automation:

1. Past-trip evidence becomes structured planning intelligence.
2. Comfort and convenience risks are deterministic checks, not vibes.
3. Trip ideas are compared as actual family-fit concepts, with clear tradeoffs.
4. Source routing is explicit, inspectable, and learnable.
5. Maps and dashboard artifacts make trip state usable by the family, not just the agent.

## Recommended Path

### Phase 1: Memory Mining And Preference Intelligence

Use existing Google Sheet, Gmail, and canonical trip import flows as evidence collectors. Convert
the imported trips into durable, reviewable memory signals:

- lodging fit by context: city hotel, city rental, rural rental, bed setup
- country-level priors from historical ratings and notes
- travel burden: total travel time, directness, connection tolerance
- pacing: nights per stop, transitions per week, activity/chill balance
- vendor and loyalty patterns: airlines, hotel groups, platforms, Aeroplan usage
- friction lessons: missed risks, avoided risks, user corrections

Implementation rule: the extractor may propose and summarize memory, but memory writes remain
review-gated through the existing learning proposal flow.

Country priors are a first planning layer, not a rule engine. Strong countries still need
sub-region, season, logistics, and trip-style checks. Weak or mixed countries can still be
recommended when the exact concept resolves the historical friction.

### Phase 2: Comfort/Friction Engine

Keep this deterministic. The engine should run before recommendations, before booking, after
Gmail reconciliation, and during concierge mode.

Core checks:

- layover length, airport mismatches, terminal/airport changes
- arrival/check-in friction and prior-night lodging needs
- family-of-5 sleeping fit and minimum 3-bed validation
- king-bed preference and queen-bed compromise warnings
- city lodging location burden and city rental suitability
- rental access, parking, safety, and late-arrival complexity
- overcompressed trip pacing and risky same-day transitions
- missing cash, visa, entry, health, and vaccination research
- country-prior cautions such as historical crowd, safety, food, sickness, road, cost, or travel-burden friction
- mass-market/crowded/weak-safety tour signals when activity data exists

Implementation rule: if data is missing for a reliability-critical check, flag the missing data
explicitly rather than pretending the option is safe.

### Phase 3: Trip Ideation And Comparison

Start with a small deterministic concept scorer. It should accept loose constraints and produce
2-5 trip concepts ranked by family fit.

Required concept output:

- estimated cost band
- estimated travel burden
- direct-flight friendliness
- family-fit score
- comfort/convenience score
- food score
- crowd risk
- rationale grounded in family preferences and memory
- fit based on past country-level history
- why it might not fit
- research required before booking

Implementation rule: do not claim live prices, current entry rules, or current availability unless
the workflow explicitly uses live research tools.

### Phase 4: Planning Workspace

Once a concept is selected, create or update a Google Sheet as the operational workspace:

- canonical itinerary
- flight, lodging, car, and activity options considered
- recommendation rationale and rejected alternatives
- day-by-day plan
- booking status and confirmations
- costs and loyalty details
- transport, buffers, map links, risk notes, and entry/health/cash checklist

Implementation rule: the canonical JSON remains source of truth; the sheet is the family-facing
workspace and should be syncable.

### Phase 5: Source Registry And Booking Copilot

Before live automation, every booking/research workflow should ask the source registry for a route:

- flights: Google Flights first, Kayak.ca/Expedia/Flighthub cross-check
- city lodging: Booking.com first, Tripadvisor/Trivago/Expedia validation
- private lodging: Airbnb/VRBO first, Booking.com/Tripadvisor validation
- tours: GetYourGuide first, Airbnb Experiences secondary, Tripadvisor validation
- cars: Booking.com first, Expedia/Kayak.ca comparison
- deals: Travelzoo for inspiration only

Source records include platform, categories, strengths, weaknesses, confidence, access modes,
prefer/avoid rules, and whether the site is currently better for discovery, validation, browser
automation, or manual handoff.

Implementation rule: source effectiveness is a learning target, but source ranking changes remain
review-gated like other memory/rule changes.

### Phase 6: Maps Output Layer

Maps are operational artifacts, not decoration. Generate:

- master trip map pins for airports, lodging, transfers, food, activities, and logistics
- airport-to-lodging and stay-to-stay direction links
- day-grouped map references
- JSON, GeoJSON, and KML-style exports for My Maps or future geocoding

Implementation rule: do not guess coordinates. Until geocoding is explicit, use address/search
queries and Google Maps links.

### Phase 7: Timeline Dashboard

The dashboard should expose:

- Past Trips timeline
- Planned Trips timeline
- Ideas Bucket
- quick links to sheets, maps, confirmations, and notes
- family-fit score, comfort score, completeness, budget band, risks, and next actions

Implementation rule: start with generated static HTML + JSON. Move to a richer app only after the
data model stabilizes.

### Phase 8: Booking Copilot

Stage this deliberately:

1. structured comparison of exact fares/listings
2. ready-to-click navigation and context handoff
3. human-reviewed booking assist
4. deeper automation only after repeated reliable runs

Implementation rule: avoid brittle site automation until the recommendation and friction checks are
solid enough to make automation worth trusting.

### Phase 9: Concierge Mode

Concierge mode should answer exact operational questions quickly from canonical state and attached
evidence. It should prioritize retrieval and risk awareness over creative planning.

Required behavior:

- confirmation numbers, addresses, check-in times, access instructions
- what is paid/unpaid, booked/unbooked, confirmed/unconfirmed
- tomorrow's logistics and backup plans
- transfer timing and luggage/kids burden
- proactive warnings as risk windows approach

### Phase 10: Post-Trip Retrospective

After each trip, capture:

- what worked
- what was worth the money
- what created friction
- hard rules for next time
- never-repeat items
- favorite food, hotel, activity, and place moments
- whether pace and destination fit expectations

Implementation rule: retrospective output creates workflow records and pending learning proposals.
It does not directly write memory.

## Risks

- **Overbroad live automation too early:** defer autonomous booking until exact-comparison workflows
  are reliable.
- **Unreviewed learning drift:** keep all memory and skill changes behind proposals.
- **Generic recommendation leakage:** score all ideas against Chapman-specific preferences and
  friction rules.
- **False certainty on current rules:** visa, entry, vaccine, and live fare/listing details require
  explicit current-source research before final recommendation.
- **Map false precision:** do not create fake coordinates or route certainty; use explicit links and
  unresolved map data until geocoded.
- **Dashboard as vanity UI:** keep the dashboard focused on operational readiness, risks, links, and
  decisions.
