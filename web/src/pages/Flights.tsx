import { useEffect, useMemo, useState } from "react";
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
type FlightPhase = "departure" | "return";

const Flights = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAddCandidate, setShowAddCandidate] = useState(false);
  const [candidateLink, setCandidateLink] = useState("");
  const [candidateName, setCandidateName] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("best");
  const [openWhyId, setOpenWhyId] = useState<string | null>(null);
  const [returnSearchStartedFor, setReturnSearchStartedFor] = useState<string>("");

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: ({ phase }: { phase: FlightPhase }) =>
      api.buildShortlist(tripId!, "flights", {
        flight_phase: phase,
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

  function changeDeparture() {
    setReturnSearchStartedFor("");
    queryClient.setQueryData<TripState>(["trip", tripId], (current) => {
      if (!current) return current;
      const shortlists = (current.shortlists ?? []).map((item) => {
        if (item.category !== "flights") return item;
        const artifacts = { ...(item.artifacts ?? {}) };
        const selection = { ...(artifacts.flight_selection ?? {}) };
        delete selection.selected_outbound_option_id;
        delete selection.selected_return_option_id;
        artifacts.flight_selection = selection;
        return {
          ...item,
          recommended_option_id: null,
          artifacts,
          flight_options: item.flight_options.map((option) => ({
            ...option,
            row_status: option.row_status === "approved" ? "researched" : option.row_status,
            recommendation_label: option.recommendation_label?.includes("selected")
              ? ""
              : option.recommendation_label,
          })),
        };
      });
      return { ...current, shortlists };
    });
  }

  const selectMutation = useMutation({
    mutationFn: ({ optionId, phase }: { optionId: string; phase: FlightPhase }) =>
      api.selectFlight(tripId!, optionId, phase === "departure" ? "outbound" : "return"),
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
  const allOptions: FlightOption[] = (shortlist?.flight_options ?? []).filter(
    (option) => !isSyntheticDuffelFlight(option) && !hasImpossibleFlightDateSpan(option),
  );

  const stages = buildStages(trip, "flights");
  const recommendedId = shortlist?.recommended_option_id;
  const flightSelection = shortlist?.artifacts?.flight_selection;

  const departureOptions = allOptions.filter((option) => flightPhase(option) === "departure");
  const returnOptions = allOptions.filter((option) => flightPhase(option) === "return");

  const selectedOutboundId = flightSelection?.selected_outbound_option_id || "";
  const selectedReturnId = flightSelection?.selected_return_option_id || "";

  const selectedOutbound = departureOptions.find((option) => option.option_id === selectedOutboundId);
  const selectedReturn = returnOptions.find((option) => option.option_id === selectedReturnId);

  const showDepartureOptions = !selectedOutboundId || !selectedOutbound;
  const hasDepartureSelection = Boolean(selectedOutbound);
  const hasReturnSelection = Boolean(selectedReturn);
  const hasSelection = hasDepartureSelection && hasReturnSelection;
  const activePhase: FlightPhase = hasDepartureSelection && !hasReturnSelection ? "return" : "departure";
  const visibleOptions = activePhase === "departure" ? departureOptions : returnOptions;
  const sorted = useMemo(() => sortOptions(visibleOptions, sortKey), [visibleOptions, sortKey]);
  const flagCount = visibleOptions.reduce((sum, o) => sum + o.friction_flags.length, 0);
  const hasShortlist = Boolean(shortlist);

  useEffect(() => {
    if (!tripId || !hasDepartureSelection || hasReturnSelection) return;
    if (returnOptions.length > 0) return;
    if (returnSearchStartedFor === selectedOutboundId) return;
    setReturnSearchStartedFor(selectedOutboundId);
    buildMutation.mutate({ phase: "return" });
  }, [
    tripId,
    hasDepartureSelection,
    hasReturnSelection,
    returnOptions.length,
    returnSearchStartedFor,
    selectedOutboundId,
  ]);

  const liveBanner = useMemo(
    () => (shortlist ? deriveLiveBanner(shortlist.warnings ?? [], visibleOptions, "flights") : null),
    [shortlist?.warnings, visibleOptions],
  );

  const title = hasSelection
    ? "Flights selected."
    : activePhase === "return"
      ? "Pick your return flight."
      : "Pick your departure flight.";

  return (
    <AppShell>
      <ShortlistHero
        intake={trip?.intake}
        shortlists={trip?.shortlists}
        stageLabel="Flights"
        stageNumber={3}
        flagCount={flagCount}
      />
      <div className="px-4 md:px-6 lg:px-8 py-4 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-4 md:px-6 lg:px-8 py-6">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 3 · Flights
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              {title}
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
                onClick={() => buildMutation.mutate({ phase: activePhase })}
                disabled={buildMutation.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors"
              >
                {buildMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCcw className="h-4 w-4" />
                )}
                {activePhase === "return" ? "Research returns" : "Research departures"}
              </button>
            </div>
          )}
        </div>

        <LiveProvidersBanner banner={liveBanner} />

        {selectedOutbound && (
          <div className="mb-4">
            <SelectedFlightSummary
              label="Departure selected"
              option={selectedOutbound}
            />
            {!hasReturnSelection && (
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={changeDeparture}
                  className="rounded-xl border-2 font-bold"
                >
                  Change departure
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={buildMutation.isPending}
                  onClick={() => {
                    setReturnSearchStartedFor("");
                    buildMutation.mutate({ phase: "return" });
                  }}
                  className="rounded-xl border-2 font-bold"
                >
                  {buildMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" />
                  )}
                  Re-research returns
                </Button>
              </div>
            )}
          </div>
        )}

        {selectedReturn && (
          <SelectedFlightSummary
            label="Return selected"
            option={selectedReturn}
          />
        )}

        {activePhase === "return" && !hasReturnSelection && (
          <div className="rounded-2xl border-2 border-foreground/10 bg-card p-4 mb-4 text-sm font-bold text-muted-foreground">
            Searching return options from {selectedOutbound?.arrival_airport || "destination"} back to {selectedOutbound?.departure_airport || "home"}…
            Flexible trip windows may produce options across multiple return dates.
          </div>
        )}

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
            title="No departure options yet"
            description="Trippy will research outbound flight options first. Return options come only after you choose the departure flight."
            ctaLabel="Build departure shortlist"
            onBuild={() => buildMutation.mutate({ phase: "departure" })}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {!tripQuery.isLoading && shortlist && visibleOptions.length === 0 && (
          <EmptyShortlist
            title={activePhase === "return" ? "No return rows yet" : "No departure rows yet"}
            description={
              activePhase === "return"
                ? "The departure is selected, but no return rows are available yet. Re-research return options, or change the departure and try again."
                : "The shortlist exists, but it did not produce any departure rows. Re-run flight research or paste a specific flight link to compare."
            }
            ctaLabel={activePhase === "return" ? "Research return flights" : "Research departure flights"}
            onBuild={() => buildMutation.mutate({ phase: activePhase })}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

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

        {visibleOptions.length > 0 && (
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="flex flex-wrap gap-2">
              <Chip>{activePhase === "return" ? "Step 2 of 2 · Return" : "Step 1 of 2 · Departure"}</Chip>
              <Chip>✦ Preference applied: comfort &gt; schedule &gt; price</Chip>
              <Chip>{partyChip(trip?.intake)}</Chip>
              <Chip>{originChip(visibleOptions)}</Chip>
              <Chip>{hasDepartureSelection ? "Departure picked" : "Pick departure"}</Chip>
              <Chip>{hasReturnSelection ? "Return picked" : "Return pending"}</Chip>
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

        {sorted.length > 0 && (
          <div id="friction-review" className="flex scroll-mt-32 flex-col gap-4">
            {sorted.map((o) => (
              <FlightRow
                key={o.option_id}
                option={o}
                activePhase={activePhase}
                isRecommended={o.option_id === recommendedId}
                isSelectedForActivePhase={
                  activePhase === "departure"
                    ? o.option_id === selectedOutboundId
                    : o.option_id === selectedReturnId
                }
                onSelect={() => selectMutation.mutate({ optionId: o.option_id, phase: activePhase })}
                isSelecting={selectMutation.isPending}
                whyOpen={openWhyId === o.option_id}
                onToggleWhy={() => setOpenWhyId(openWhyId === o.option_id ? null : o.option_id)}
              />
            ))}
          </div>
        )}

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
            {activePhase === "departure"
              ? "Choose a departure flight first. Trippy will then search return options."
              : "Choose a return flight to lock the trip envelope before finalizing stays, cars, activities, and timeline."}
          </div>
        )}
      </div>
    </AppShell>
  );
};

function flightPhase(option: FlightOption): FlightPhase {
  return option.flight_phase === "return" ? "return" : "departure";
}

function SelectedFlightSummary({ label, option }: { label: string; option: FlightOption }) {
  return (
    <div className="rounded-2xl border-2 border-foreground/10 bg-card p-4 mb-4 text-sm">
      <div className="font-bold text-foreground">{label}</div>
      <div className="text-muted-foreground mt-1">
        {option.departure_airport} → {option.arrival_airport} · arrives {formatFlightSubline(option.arrival_date)} {shortFlightText(option.arrival_time)} · {option.airline}
      </div>
    </div>
  );
}

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
  activePhase,
  isRecommended,
  isSelectedForActivePhase,
  onSelect,
  isSelecting,
  whyOpen,
  onToggleWhy,
}: {
  option: FlightOption;
  activePhase: FlightPhase;
  isRecommended: boolean;
  isSelectedForActivePhase: boolean;
  onSelect: () => void;
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
  const actionLabel = activePhase === "return" ? "Select return" : "Select departure";
  const selectedLabel = activePhase === "return" ? "Return selected" : "Departure selected";

  return (
    <article
      className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce ${
        isSelectedForActivePhase
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

      <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_minmax(220px,_auto)] gap-5 px-5 py-5">
        <TimeBlock
          time={option.departure_time}
          subline={`${option.departure_date || ""} · ${option.departure_airport}`.trim()}
        />
        <div>
          <TimeBlock
            time={option.arrival_time}
            subline={`${option.arrival_date || ""} · ${option.arrival_airport}`.trim()}
            dayOffset={arrivalDayOffset}
          />
        </div>
        <div className="md:text-right">
          <FlightPrice option={option} />
        </div>
      </div>

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

      <div className="px-5 py-3 border-t-2 border-foreground/10 flex items-center gap-3 flex-wrap">
        <Button
          onClick={onSelect}
          disabled={isSelecting}
          className={`h-10 rounded-xl font-bold border-2 px-5 ${
            isSelectedForActivePhase
              ? "bg-primary text-primary-foreground border-foreground shadow-card"
              : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isSelectedForActivePhase ? (
            <><Check className="h-4 w-4" /> {selectedLabel}</>
          ) : (
            actionLabel
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
      <div className="absolute left-0 top-full mt-1 text-[10px] font-bold text-muted-foreground">
        {origin}
      </div>
      <div className="absolute right-0 top-full mt-1 text-[10px] font-bold text-muted-foreground">
        {destination}
      </div>
    </div>
  );
}

function derivePros(option: FlightOption): string[] {
  const pros: string[] = [];
  if (option.stops === 0) pros.push("Nonstop — protects the first day and avoids layover risk");
  if (option.recommendation_grade === "strong") pros.push("Strong comfort-to-friction balance");
  if (option.timing_fit) pros.push(option.timing_fit);
  if (option.baggage_cabin_notes) pros.push(option.baggage_cabin_notes);
  if (!pros.length && option.recommendation_rationale) pros.push(option.recommendation_rationale);
  return pros;
}

export default Flights;
