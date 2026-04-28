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
import { api, type FlightOption, type TripIntake } from "@/lib/api";
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const selectMutation = useMutation({
    mutationFn: (optionId: string) => api.selectFlight(tripId!, optionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const candidateMutation = useMutation({
    mutationFn: () =>
      api.addFlightCandidate({
        trip_id: tripId!,
        link: candidateLink,
        name: candidateName,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
      setCandidateLink("");
      setCandidateName("");
      setShowAddCandidate(false);
    },
  });

  const trip = tripQuery.data;
  const shortlist = shortlistOptions(trip, "flights");
  const options: FlightOption[] = shortlist?.flight_options ?? [];
  const stages = buildStages(trip, "flights");
  const recommendedId = shortlist?.recommended_option_id;
  const flagCount = options.reduce((sum, o) => sum + o.friction_flags.length, 0);
  const hasSelection = options.some((o) => o.row_status === "approved");

  const sorted = useMemo(() => sortOptions(options, sortKey), [options, sortKey]);

  const liveBanner = useMemo(
    () => deriveLiveBanner(shortlist?.warnings ?? [], options, "flights"),
    [shortlist?.warnings, options],
  );

  return (
    <AppShell>
      <ShortlistHero
        intake={trip?.intake}
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
          {options.length > 0 && (
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
            description="Hermes will research direct and one-stop options from your departure airports, score each on friction, and propose a recommendation."
            ctaLabel="Build flight shortlist"
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
          <div className="flex flex-col gap-4">
            {sorted.map((o) => (
              <FlightRow
                key={o.option_id}
                option={o}
                isRecommended={o.option_id === recommendedId}
                isSelected={o.row_status === "approved"}
                onSelect={() => selectMutation.mutate(o.option_id)}
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

function priceAmount(o: FlightOption): number {
  const m = (o.fare_estimate_cad || o.price_band || "").match(/([\d][\d,]*(?:\.\d{2})?)/);
  return m ? parseFloat(m[1].replace(/,/g, "")) : Number.POSITIVE_INFINITY;
}

function durationHours(value: string): number {
  const m = (value || "").match(/(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(?:(\d+)\s*m)?/i);
  if (!m) return Number.POSITIVE_INFINITY;
  return parseFloat(m[1]) + (parseFloat(m[2] || "0") || 0) / 60;
}

function FlightRow({
  option,
  isRecommended,
  isSelected,
  onSelect,
  isSelecting,
  whyOpen,
  onToggleWhy,
}: {
  option: FlightOption;
  isRecommended: boolean;
  isSelected: boolean;
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
  const fare = option.fare_estimate_cad || option.price_band;
  const band = option.price_band && option.price_band !== fare ? option.price_band : null;
  const pros = derivePros(option);
  const cons = option.friction_flags;

  return (
    <article
      className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce ${
        isSelected
          ? "border-foreground shadow-sticker"
          : "border-foreground/10 shadow-card hover:-translate-y-0.5"
      }`}
    >
      <RowHeaderStrip
        label={label}
        pill={pill}
        left={
          <>
            <Plane className="h-4 w-4 text-foreground/60" />
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
          />
        </div>
        {/* Price */}
        <div className="md:text-right">
          <div className="font-[Fredoka] text-3xl font-bold leading-none">
            {fare || "—"}{" "}
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              per person
            </span>
          </div>
          {band && (
            <div className="text-xs text-muted-foreground mt-1.5 font-mono uppercase tracking-wider">
              Band {band}
            </div>
          )}
        </div>
      </div>

      {/* Route timeline + stop info */}
      <div className="px-5 pb-3">
        <RouteTimeline
          origin={option.departure_airport}
          destination={option.arrival_airport}
          layovers={option.layover_airports}
        />
        <div className="text-xs font-bold text-muted-foreground mt-2">
          {option.total_travel_duration || "duration unknown"} · {stopText}
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
          onClick={onSelect}
          disabled={isSelecting}
          className={`h-10 rounded-xl font-bold border-2 px-5 ${
            isSelected
              ? "bg-primary text-primary-foreground border-foreground shadow-card"
              : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isSelected ? (
            <><Check className="h-4 w-4" /> Using this flight</>
          ) : (
            "Use this flight"
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

function TimeBlock({ time, subline }: { time: string; subline: string }) {
  return (
    <div>
      <div className="font-[Fredoka] text-3xl md:text-4xl font-bold leading-none tabular-nums">
        {time || "—"}
      </div>
      <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mt-1.5">
        {subline}
      </div>
    </div>
  );
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
