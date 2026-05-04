import { Link } from "react-router-dom";
import { ArrowLeft, AlertTriangle, ChevronDown } from "lucide-react";
import type { FlightOption, ShortlistState, TripIntake } from "@/lib/api";
import { TripMap } from "@/components/TripMap";
import { useGeocodes } from "@/lib/geocode";
import { buildSeedPins, makeGeocodeLookup } from "@/lib/pinBuilders";

export function ShortlistHero({
  intake,
  shortlists,
  stageLabel,
  stageNumber,
  flagCount,
  flagHref = "#friction-review",
  showMap = true,
}: {
  intake: TripIntake | null | undefined;
  shortlists?: ShortlistState[];
  stageLabel: string;
  stageNumber: number;
  flagCount?: number;
  flagHref?: string;
  showMap?: boolean;
}) {
  const tripName = intake?.trip_name ?? "Your trip";
  const seeds = intake?.destination_seeds ?? [];
  const destination = seeds.join(" · ");
  const dateRange = deriveTripDateRangeLabel(intake, shortlists);

  const geocodeResults = useGeocodes(seeds);
  const lookup = makeGeocodeLookup(
    seeds.map((q, i) => ({ query: q, coords: geocodeResults[i]?.data ?? null }))
  );
  const pins = buildSeedPins(seeds, lookup);

  return (
    <div className="bg-gradient-hero border-b-2 border-foreground/10 px-4 md:px-6 lg:px-8 pt-6 pb-7 relative">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground/70 hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="h-4 w-4" /> Back to trips
      </Link>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="px-3 py-1 rounded-full bg-card border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
          Planning · Stage {stageNumber} of 8 — {stageLabel}
        </span>
        {dateRange ? (
          <span className="px-4 py-1.5 rounded-full bg-sunshine/45 border-2 border-foreground/15 text-base md:text-lg font-bold leading-none">
            {dateRange}
          </span>
        ) : (
          intake?.duration_days && (
            <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">
              {intake.duration_days} days
            </span>
          )
        )}
        {intake?.party && (
          <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">
            {intake.party.adults + intake.party.children} travelers
          </span>
        )}
        {flagCount !== undefined && flagCount > 0 && (
          <a
            href={flagHref}
            className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background transition-bounce"
            aria-label={`Review ${flagCount} friction flag${flagCount !== 1 ? "s" : ""}`}
          >
            <AlertTriangle className="h-4 w-4 text-sunshine" />
            <div className="text-xs leading-tight">
              <div className="font-bold">{flagCount} friction flag{flagCount !== 1 ? "s" : ""}</div>
              <div className="opacity-70">Review friction</div>
            </div>
            <ChevronDown className="h-3.5 w-3.5 opacity-70" />
          </a>
        )}
      </div>
      <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">
        {tripName}
      </h1>
      {destination && (
        <p className="text-foreground/70 italic mt-2 font-medium">{destination}</p>
      )}
      {showMap && pins.length > 0 && (
        <div className="mt-5 max-w-5xl">
          <TripMap
            pins={pins}
            variant="compact"
            showScrubber={false}
            height="260px"
            zoom={5}
          />
        </div>
      )}
    </div>
  );
}

export function deriveTripDateRangeLabel(
  intake: TripIntake | null | undefined,
  shortlists?: ShortlistState[],
): string {
  const selectedFlight = findSelectedFlight(shortlists);
  const selectedReturnFlight = findSelectedReturnFlight(shortlists);
  const lockedEnvelope = findLockedTripEnvelope(shortlists);

  if (lockedEnvelope) {
    const envelopeStart = parseDatePrefix(lockedEnvelope.trip_start_datetime);
    const envelopeEnd = parseDatePrefix(lockedEnvelope.trip_end_datetime);
    if (envelopeStart && envelopeEnd) {
      if (envelopeEnd.getTime() >= envelopeStart.getTime()) {
        return formatDateRange(envelopeStart, envelopeEnd);
      }
      return "Flight dates invalid · reselect return";
    }
  }

  if (selectedFlight && !selectedReturnFlight) {
    const arrival = parseIsoDateOnly(selectedFlight.arrival_date);
    return arrival ? `Departure selected · return pending after ${formatSingleDate(arrival)}` : "Departure selected · return pending";
  }

  if (selectedFlight && selectedReturnFlight) {
    const flightStart = parseIsoDateOnly(selectedFlight.arrival_date) ?? parseIsoDateOnly(selectedFlight.departure_date);
    const flightEnd = findExplicitReturnDate(selectedReturnFlight, flightStart ?? new Date(0));
    if (flightStart && flightEnd) return formatDateRange(flightStart, flightEnd);
  }

  const intakeStart = parseIsoDateOnly(intake?.travel_window?.start_date);
  const intakeEnd = parseIsoDateOnly(intake?.travel_window?.end_date);
  if (intakeStart && intakeEnd) return `Target window · ${formatDateRange(intakeStart, intakeEnd)}`;
  if (intakeStart) return `Target window · ${formatSingleDate(intakeStart)}`;
  return "";
}

function findLockedTripEnvelope(shortlists?: ShortlistState[]): { trip_start_datetime?: string; trip_end_datetime?: string } | null {
  const flights = shortlists?.find((shortlist) => shortlist.category === "flights");
  const envelope = flights?.artifacts?.trip_envelope;
  if (!envelope || typeof envelope !== "object") return null;
  const data = envelope as Record<string, unknown>;
  if (data.status !== "locked") return null;
  if (typeof data.trip_start_datetime !== "string" || typeof data.trip_end_datetime !== "string") {
    return null;
  }
  return {
    trip_start_datetime: data.trip_start_datetime,
    trip_end_datetime: data.trip_end_datetime,
  };
}

function findSelectedFlight(shortlists?: ShortlistState[]): FlightOption | null {
  const flights = shortlists?.find((shortlist) => shortlist.category === "flights");
  if (!flights) return null;
  const outboundId = flights.artifacts?.flight_selection?.selected_outbound_option_id;
  const outbound = flights.flight_options.find((option) => option.option_id === outboundId && option.flight_phase !== "return");
  if (outbound) return outbound;
  const selectedStatuses = new Set(["approved", "booked", "confirmed"]);
  const recommended = flights.flight_options.find((option) => option.option_id === flights.recommended_option_id);
  if (recommended && selectedStatuses.has(recommended.row_status) && recommended.flight_phase !== "return") return recommended;
  return (
    flights.flight_options.find((option) => selectedStatuses.has(option.row_status) && option.flight_phase !== "return") ??
    null
  );
}

function findSelectedReturnFlight(shortlists?: ShortlistState[]): FlightOption | null {
  const flights = shortlists?.find((shortlist) => shortlist.category === "flights");
  if (!flights) return null;
  const returnId = flights.artifacts?.flight_selection?.selected_return_option_id;
  return flights.flight_options.find((option) => option.option_id === returnId && option.flight_phase === "return") ?? null;
}

function findExplicitReturnDate(option: FlightOption | null, start: Date): Date | null {
  if (!option) return null;
  const candidates = [option.departure_date, option.arrival_date]
    .map(parseIsoDateOnly)
    .filter((date): date is Date => Boolean(date))
    .filter((date) => date.getTime() >= start.getTime());
  if (candidates.length === 0) return null;
  return candidates.sort((a, b) => b.getTime() - a.getTime())[0];
}

function parseDatePrefix(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  return parseIsoDateOnly(value.slice(0, 10));
}

function parseIsoDateOnly(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function formatDateRange(start: Date, end: Date): string {
  if (start.getUTCFullYear() === end.getUTCFullYear()) {
    return `${formatDatePart(start)} - ${formatDatePart(end)}, ${end.getUTCFullYear()}`;
  }
  return `${formatSingleDate(start)} - ${formatSingleDate(end)}`;
}

function formatSingleDate(date: Date): string {
  return `${formatDatePart(date)}, ${date.getUTCFullYear()}`;
}

function formatDatePart(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
