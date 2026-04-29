import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { ShortlistHero } from "@/components/ShortlistHero";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { Button } from "@/components/ui/button";
import {
  Loader2, Check, ExternalLink, ArrowRight, Plus, RefreshCcw,
  AlertCircle, AlertTriangle, Plane,
} from "lucide-react";
import {
  api,
  mergeShortlistIntoTrip,
  type FlightOption,
  type TripIntake,
  type TripState,
} from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import {
  Chip,
  LiveProvidersBanner,
  RowHeaderStrip,
  deriveLiveBanner,
  deriveLivePill,
  deriveRowLabel,
} from "@/components/ShortlistRow";

type SortKey = "best" | "price" | "duration";
type FlightSelectionKind = "outbound" | "return";

const Flights = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAddCandidate, setShowAddCandidate] = useState(false);
  const [candidateLink, setCandidateLink] = useState("");
  const [candidateName, setCandidateName] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("best");
  const [openWhyId, setOpenWhyId] = useState<string | null>(null);

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () =>
      api.buildShortlist(tripId!, "flights", {
        validate_live: true,
        deep_research: true,
      }),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });

  const selectMutation = useMutation({
    mutationFn: ({ optionId, kind }: { optionId: string; kind: FlightSelectionKind }) =>
      api.selectFlight(tripId!, optionId, kind),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });

  const candidateMutation = useMutation({
    mutationFn: () =>
      api.addFlightCandidate({
        trip_id: tripId!,
        link: candidateLink,
        name: candidateName,
      }),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
      setCandidateLink("");
      setCandidateName("");
      setShowAddCandidate(false);
    },
  });

  const trip = tripQuery.data;
  const shortlist = shortlistOptions(trip, "flights");
  const options: FlightOption[] = (shortlist?.flight_options ?? []).filter(
    (option) => !isSyntheticDuffelFlight(option) && !hasImpossibleFlightDateSpan(option),
  );
  const stages = buildStages(trip, "flights");
  const recommendedId = shortlist?.recommended_option_id;
  const flightSelection = shortlist?.artifacts?.flight_selection;
  const legacySelectedOutboundId =
    options.find((o) => o.option_id === recommendedId && o.row_status === "approved")?.option_id ||
    options.find((o) => o.row_status === "approved")?.option_id ||
    "";
  const selectedOutboundId = flightSelection?.selected_outbound_option_id || legacySelectedOutboundId;
  const selectedReturnId = flightSelection?.selected_return_option_id || "";
  const flagCount = options.reduce((sum, o) => sum + o.friction_flags.length, 0);
  const hasDepartureSelection = Boolean(selectedOutboundId && options.some((o) => o.option_id === selectedOutboundId));
  const hasReturnSelection = Boolean(selectedReturnId && options.some((o) => o.option_id === selectedReturnId));
  const hasSelection = hasDepartureSelection && hasReturnSelection;
  const hasShortlist = Boolean(shortlist);

  const sorted = useMemo(() => sortOptions(options, sortKey), [options, sortKey]);

  const liveBanner = useMemo(
    () => (shortlist ? deriveLiveBanner(shortlist.warnings ?? [], options, "flights") : null),
    [shortlist?.warnings, options],
  );

  return (
    <AppShell>
      <ShortlistHero
        intake={trip?.intake}
        shortlists={trip?.shortlists}
        stageLabel="Flights"
        stageNumber={3}
        flagCount={flagCount}
      />
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 3 · Flights
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Pick your flights.
            </h2>
          </div>
          {hasShortlist && (
            <div className="flex gap-2">
              <button
                onClick={() => setShowAddCandidate((v) => !v)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors"
              >
                <Plus className="h-4 w-4" /> Paste a link
              </button>
              <button
                onClick={() => buildMutation.mutate()}
                disabled={buildMutation.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors"
              >
                {buildMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCcw className="h-4 w-4" />
                )}
                Re-research
              </button>
            </div>
          )}
        </div>

        <LiveProvidersBanner banner={liveBanner} />

        {tripQuery.isLoading && (
          <div className="flex items-center justify-center py-24 text-muted-foreground gap-3">
            <Loader2 className="h-6 w-6 animate-spin" />
            <span className="font-bold">Loading…</span>
          </div>
        )}

        {tripQuery.isError && (
          <div className="rounded-3xl border-2 border-destructive/30 bg-destructive/5 p-6 flex items-start gap-4 mb-6">
            <AlertCircle className="h-6 w-6 text-destructive shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-destructive">Couldn't load trip</div>
              <div className="text-sm text-muted-foreground mt-1">
                {(tripQuery.error as Error)?.message}
              </div>
            </div>
          </div>
        )}

        {!tripQuery.isLoading && !shortlist && (
          <EmptyShortlist
            title="No flight options yet"
            description="Trippy will research direct and one-stop options from your departure airports, score each on friction, and propose a recommendation."
            ctaLabel="Build flight shortlist"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {!tripQuery.isLoading && shortlist && options.length === 0 && (
          <EmptyShortlist
            title="No flight rows returned"
            description="The shortlist exists, but it did not produce any flight rows. Re-run flight research after connecting live providers, or paste a specific flight link to compare."
            ctaLabel="Re-research flights"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {/* Add candidate */}
        {showAddCandidate && (
          <div className="rounded-3xl border-2 border-foreground/15 bg-card shadow-card p-5 mb-6">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Add your own flight to compare
            </div>
            <div className="grid md:grid-cols-[1fr_220px_auto] gap-3">
              <input
                value={candidateLink}
                onChange={(e) => setCandidateLink(e.target.value)}
                placeholder="Paste a Google Flights / airline URL"
                className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
              />
              <input
                value={candidateName}
                onChange={(e) => setCandidateName(e.target.value)}
                placeholder="Label (e.g. AC1726)"
                className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
              />
              <Button
                onClick={() => candidateMutation.mutate()}
                disabled={!candidateLink || candidateMutation.isPending}
                className="h-11 rounded-xl bg-foreground text-background font-bold px-5"
              >
                {candidateMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Research it"
                )}
              </Button>
            </div>
          </div>
        )}

        {/* Filter / sort strip */}
        {options.length > 0 && (
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="flex flex-wrap gap-2">
              <Chip>✦ Preference applied: comfort &gt; schedule &gt; price</Chip>
              <Chip>{partyChip(trip?.intake)}</Chip>
              <Chip>{originChip(options)}</Chip>
              <Chip>{hasDepartureSelection ? "Departure picked" : "Pick departure"}</Chip>
              <Chip>{hasReturnSelection ? "Return picked" : "Pick return"}</Chip>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Sort:</span>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className="h-9 rounded-xl border-2 border-foreground/15 bg-card px-3 font-bold text-sm focus:outline-none focus:border-foreground/40"
              >
                <option value="best">Best overall</option>
                <option value="price">Price</option>
                <option value="duration">Duration</option>
              </select>
            </div>
          </div>
        )}

        {/* Rows */}
        {sorted.length > 0 && (
          <div id="friction-review" className="flex scroll-mt-32 flex-col gap-4">
            {sorted.map((o) => (
              <FlightRow
                key={o.option_id}
                option={o}
                isRecommended={o.option_id === recommendedId}
                isSelectedOutbound={o.option_id === selectedOutboundId}
                isSelectedReturn={o.option_id === selectedReturnId}
                onSelect={(kind) => selectMutation.mutate({ optionId: o.option_id, kind })}
                isSelecting={selectMutation.isPending}
                whyOpen={openWhyId === o.option_id}
                onToggleWhy={() => setOpenWhyId(openWhyId === o.option_id ? null : o.option_id)}
              />
            ))}
          </div>
        )}

        {/* Continue */}
        {hasSelection && (
          <div className="mt-6 flex justify-end">
            <Button
              onClick={() => navigate(`/trip/${tripId}/stays`)}
              className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
            >
              Continue to Stays <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        )}
        {!hasSelection && sorted.length > 0 && (
          <div className="mt-6 rounded-2xl border-2 border-foreground/10 bg-card p-4 text-sm font-bold text-muted-foreground">
            Pick both a departure flight and a return flight before continuing. Trippy will use that pair as timing context for stays, cars, activities, and the Master Timeline.
          </div>
        )}
      </div>
    </AppShell>
  );
};

function partyChip(intake: TripIntake | undefined): string {
  if (!intake) return "Party · checked bags";
  const total = intake.travelers || (intake.party.adults + intake.party.children);
  return `Party of ${total} · checked bags`;
}

function originChip(options: FlightOption[]): string {
  const origin = options[0]?.departure_airport || "origin";
  return `${origin} origin locked`;
}

function sortOptions(options: FlightOption[], key: SortKey): FlightOption[] {
  const arr = [...options];
  if (key === "price") {
    arr.sort((a, b) => priceAmount(a) - priceAmount(b));
  } else if (key === "duration") {
    arr.sort((a, b) => durationHours(a.total_travel_duration) - durationHours(b.total_travel_duration));
  } else {
    arr.sort((a, b) => a.rank - b.rank);
  }
  return arr;
}

function isSyntheticDuffelFlight(option: FlightOption): boolean {
  if (/duffel airways/i.test(option.airline || "")) return true;
  return (option.flight_numbers || []).some((number) => /^ZZ/i.test(number));
}

function hasImpossibleFlightDateSpan(option: FlightOption): boolean {
  const offset = dayOffset(option.departure_date, option.arrival_date);
  if (offset <= 2) return false;
  const hours = durationHours(option.total_travel_duration);
  if (!Number.isFinite(hours)) return false;
  return hours + 12 < offset * 24;
}

function priceAmount(o: FlightOption): number {
  return parseFlightPrice(o.fare_estimate_cad || o.price_band, o.traveler_count || 1)?.total ?? Number.POSITIVE_INFINITY;
}

function FlightPrice({ option }: { option: FlightOption }) {
  const price = parseFlightPrice(option.fare_estimate_cad || option.price_band, option.traveler_count || 1);
  if (!price) {
    return <div className="font-[Fredoka] text-3xl font-bold leading-none text-muted-foreground">—</div>;
  }
  return (
    <div className="leading-none">
      <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-1.5">
        Total
      </div>
      <div className="font-[Fredoka] text-3xl md:text-4xl font-bold">
        <span className="text-palm">{formatCad(price.total)}</span>
        <span className="text-base md:text-lg font-bold text-muted-foreground"> (</span>
        <span className="text-palm text-2xl md:text-3xl">{formatCad(price.perPerson)}</span>
        <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
          {" "}per person)
        </span>
      </div>
    </div>
  );
}

function parseFlightPrice(value: string, travelerCount: number): { total: number; perPerson: number } | null {
  const text = value || "";
  const cadAmounts = [...text.matchAll(/CAD\s*\$?\s*([\d,]+(?:\.\d{1,2})?)/gi)].map((match) =>
    Number(match[1].replace(/,/g, "")),
  );
  if (cadAmounts.length >= 2) {
    return { total: cadAmounts[0], perPerson: cadAmounts[1] };
  }
  const loose = text.match(/(?:CA\$|C\$|\$)\s*([\d,]+(?:\.\d{1,2})?)/i);
  if (!loose) return null;
  const amount = Number(loose[1].replace(/,/g, ""));
  const count = Math.max(1, travelerCount || 1);
  if (/per\s*(?:person|traveler|passenger|pp)/i.test(text)) {
    return { total: amount * count, perPerson: amount };
  }
  return { total: amount, perPerson: amount / count };
}

function formatCad(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

function durationHours(value: string): number {
  const m = (value || "").match(/(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(?:(\d+)\s*m)?/i);
  if (!m) return Number.POSITIVE_INFINITY;
  return parseFloat(m[1]) + (parseFloat(m[2] || "0") || 0) / 60;
}

function FlightRow({
  option,
  isRecommended,
  isSelectedOutbound,
  isSelectedReturn,
  onSelect,
  isSelecting,
  whyOpen,
  onToggleWhy,
}: {
  option: FlightOption;
  isRecommended: boolean;
  isSelectedOutbound: boolean;
  isSelectedReturn: boolean;
  onSelect: (kind: FlightSelectionKind) => void;
  isSelecting: boolean;
  whyOpen: boolean;
  onToggleWhy: () => void;
}) {
  const label = deriveRowLabel(option.recommendation_label, isRecommended, option.recommendation_grade);
  const pill = deriveLivePill(option);
  const stopText =
    option.stops === 0
      ? "Nonstop"
      : `${option.stops} stop${option.stops > 1 ? "s" : ""}${option.layover_airports.length ? ` (${option.layover_airports.join(", ")})` : ""}`;
  const pros = derivePros(option);
  const cons = option.friction_flags;
  const arrivalDayOffset = dayOffset(option.departure_date, option.arrival_date);

  return (
    <article
      className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce ${
        isSelectedOutbound || isSelectedReturn
          ? "border-foreground shadow-sticker"
          : "border-foreground/10 shadow-card hover:-translate-y-0.5"
      }`}
    >
      <RowHeaderStrip
        label={label}
        pill={pill}
        left={
          <>
            <AirlineLogo option={option} />
            <span className="font-bold truncate">{option.airline}</span>
            {option.flight_numbers.length > 0 && (
              <span className="text-xs text-muted-foreground font-mono ml-1 truncate">
                {option.flight_numbers.join(" → ")}
              </span>
            )}
          </>
        }
      />

      {/* Body */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_minmax(220px,_auto)] gap-5 px-5 py-5">
        {/* Departure */}
        <TimeBlock
          time={option.departure_time}
          subline={`${option.departure_date || ""} · ${option.departure_airport}`.trim()}
        />
        {/* Arrival + route timeline below */}
        <div>
          <TimeBlock
            time={option.arrival_time}
            subline={`${option.arrival_date || ""} · ${option.arrival_airport}`.trim()}
            dayOffset={arrivalDayOffset}
          />
        </div>
        {/* Price */}
        <div className="md:text-right">
          <FlightPrice option={option} />
        </div>
      </div>

      {/* Route timeline + stop info */}
      <div className="px-5 pb-3">
        <RouteTimeline
          origin={option.departure_airport}
          destination={option.arrival_airport}
          layovers={option.layover_airports}
        />
        <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-[Fredoka] text-2xl md:text-3xl font-bold text-foreground">
            {option.total_travel_duration || "duration unknown"}
          </span>
          <span className="text-sm font-bold text-muted-foreground">· {stopText}</span>
        </div>
      </div>

      {/* Pros / cons */}
      <div className="px-5 pb-4 grid md:grid-cols-2 gap-4">
        <ul className="space-y-1.5 text-sm">
          {pros.slice(0, 3).map((p) => (
            <li key={p} className="flex items-start gap-2">
              <Check className="h-4 w-4 text-palm shrink-0 mt-0.5" />
              <span className="text-foreground/85">{p}</span>
            </li>
          ))}
        </ul>
        {cons.length > 0 && (
          <div className="rounded-xl border border-coral/40 bg-coral/5 px-3 py-2 space-y-1">
            {cons.slice(0, 3).map((f) => (
              <div key={f} className="flex items-start gap-2 text-xs text-foreground/80">
                <AlertTriangle className="h-3.5 w-3.5 text-coral shrink-0 mt-0.5" />
                <span>{f}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action bar */}
      <div className="px-5 py-3 border-t-2 border-foreground/10 flex items-center gap-3 flex-wrap">
        <Button
          onClick={() => onSelect("outbound")}
          disabled={isSelecting}
          className={`h-10 rounded-xl font-bold border-2 px-5 ${
            isSelectedOutbound
              ? "bg-primary text-primary-foreground border-foreground shadow-card"
              : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isSelectedOutbound ? (
            <><Check className="h-4 w-4" /> Departure</>
          ) : (
            "Use as departure"
          )}
        </Button>
        <Button
          onClick={() => onSelect("return")}
          disabled={isSelecting}
          className={`h-10 rounded-xl font-bold border-2 px-5 ${
            isSelectedReturn
              ? "bg-primary text-primary-foreground border-foreground shadow-card"
              : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isSelectedReturn ? (
            <><Check className="h-4 w-4" /> Return</>
          ) : (
            "Use as return"
          )}
        </Button>
        {option.deep_link && (
          <a
            href={option.deep_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm font-bold text-foreground/80 hover:text-foreground"
          >
            <ArrowRight className="h-4 w-4" /> Open search
          </a>
        )}
        {option.deep_link && (
          <a
            href={option.deep_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Book / confirm
          </a>
        )}
        <button
          type="button"
          onClick={onToggleWhy}
          className="ml-auto text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          {whyOpen ? "Hide details" : "Why not this?"}
        </button>
      </div>

      {whyOpen && (
        <div className="px-5 pb-5 pt-1 text-sm text-foreground/80 space-y-2 border-t border-foreground/10">
          {option.recommendation_rationale && (
            <p className="leading-snug">{option.recommendation_rationale}</p>
          )}
          {option.tradeoffs.length > 0 && (
            <ul className="space-y-1">
              {option.tradeoffs.map((t) => (
                <li key={t} className="text-xs">· {t}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground pt-1">
            <span>Comfort {option.family_comfort_score}</span>
            <span>Friction {option.friction_score}</span>
            {option.validation?.adapter_used && (
              <span>Source: {option.validation.adapter_used}</span>
            )}
            {option.validation?.confidence !== undefined && (
              <span>Confidence {Math.round((option.validation.confidence ?? 0) * 100)}%</span>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

function TimeBlock({
  time,
  subline,
  dayOffset = 0,
}: {
  time: string;
  subline: string;
  dayOffset?: number;
}) {
  const display = shortFlightText(time);
  const isLong = display.length > 12;
  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-2 min-w-0">
        <div
          className={`font-bold leading-tight tabular-nums break-words ${
            isLong
              ? "text-xl md:text-2xl text-foreground/90"
              : "font-[Fredoka] text-3xl md:text-4xl"
          }`}
        >
          {display}
        </div>
        {dayOffset > 0 && (
          <span className="font-[Fredoka] text-2xl md:text-3xl font-bold leading-none text-red-600">
            +{dayOffset}
          </span>
        )}
      </div>
      <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mt-1.5">
        {formatFlightSubline(subline)}
      </div>
    </div>
  );
}

function AirlineLogo({ option }: { option: FlightOption }) {
  const logoUrl = option.airline_logo_url || airlineLogoFromFlightNumbers(option.flight_numbers);
  if (!logoUrl) return <Plane className="h-4 w-4 text-foreground/60 shrink-0" />;
  return (
    <img
      src={logoUrl}
      alt={`${option.airline} logo`}
      className="h-7 w-7 rounded-full border border-foreground/10 bg-white object-contain p-0.5 shrink-0"
      onError={(event) => {
        event.currentTarget.style.display = "none";
      }}
    />
  );
}

function airlineLogoFromFlightNumbers(flightNumbers: string[]): string {
  const first = flightNumbers.find(Boolean) || "";
  const match = first.match(/^([A-Z0-9]{2})\d/i);
  if (!match) return "";
  const domain = AIRLINE_DOMAINS[match[1].toUpperCase()];
  return domain ? `https://www.google.com/s2/favicons?sz=64&domain=${domain}` : "";
}

const AIRLINE_DOMAINS: Record<string, string> = {
  AA: "aa.com",
  AC: "aircanada.com",
  AF: "airfrance.com",
  BA: "britishairways.com",
  DL: "delta.com",
  IB: "iberia.com",
  LH: "lufthansa.com",
  S4: "azoresairlines.pt",
  TP: "flytap.com",
  UA: "united.com",
  WS: "westjet.com",
};

function dayOffset(departureDate: string, arrivalDate: string): number {
  const departure = parseDateOnly(departureDate);
  const arrival = parseDateOnly(arrivalDate);
  if (!departure || !arrival) return 0;
  const msPerDay = 24 * 60 * 60 * 1000;
  return Math.max(0, Math.round((arrival.getTime() - departure.getTime()) / msPerDay));
}

function parseDateOnly(value: string): Date | null {
  const match = (value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function shortFlightText(value: string): string {
  const cleaned = (value || "").trim();
  if (!cleaned) return "—";
  if (/^open search$/i.test(cleaned)) return "Open search";
  if (/^verify time$/i.test(cleaned)) return "Verify time";
  if (/target|verify|variable|not supplied|unavailable/i.test(cleaned)) return "Verify time";
  return cleaned;
}

function formatFlightSubline(value: string): string {
  return value.replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (_, y, m, d) => {
    const date = new Date(Number(y), Number(m) - 1, Number(d));
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "2-digit",
      year: "numeric",
    });
  });
}

function RouteTimeline({
  origin,
  destination,
  layovers,
}: {
  origin: string;
  destination: string;
  layovers: string[];
}) {
  const stops = layovers.length;
  return (
    <div className="relative h-6">
      <div className="absolute left-2 right-2 top-1/2 -translate-y-1/2 h-[2px] bg-foreground/30 rounded-full" />
      <div className="absolute left-0 top-1/2 -translate-y-1/2 h-3 w-3 rounded-full bg-foreground border-2 border-foreground" />
      <div className="absolute right-0 top-1/2 -translate-y-1/2 h-3 w-3 rounded-full bg-foreground border-2 border-foreground" />
      {stops > 0 &&
        layovers.map((code, idx) => {
          const pct = ((idx + 1) / (stops + 1)) * 100;
          return (
            <div
              key={`${code}-${idx}`}
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 flex flex-col items-center"
              style={{ left: `${pct}%` }}
            >
              <span className="text-[10px] font-bold text-foreground/70 -translate-y-3 absolute">
                {code}
              </span>
              <div className="h-3 w-3 rounded-full bg-coral border-2 border-foreground" />
            </div>
          );
        })}
      <span className="absolute -bottom-4 left-0 text-[10px] font-bold text-muted-foreground">
        {origin}
      </span>
      <span className="absolute -bottom-4 right-0 text-[10px] font-bold text-muted-foreground">
        {destination}
      </span>
    </div>
  );
}

function derivePros(option: FlightOption): string[] {
  const pros: string[] = [];
  if (option.stops === 0) pros.push("Nonstop — protects the first day and avoids layover risk");
  if (option.recommendation_rationale) {
    const first = option.recommendation_rationale.split(". ").slice(0, 1)[0];
    if (first && !pros.some((p) => p.includes(first))) pros.push(first.replace(/\.$/, ""));
  }
  if (option.timing_fit) pros.push(option.timing_fit);
  for (const t of option.tradeoffs) {
    if (pros.length >= 3) break;
    if (!pros.includes(t)) pros.push(t);
  }
  return pros;
}

export default Flights;
