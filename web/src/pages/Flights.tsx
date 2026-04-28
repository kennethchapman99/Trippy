import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { ShortlistHero } from "@/components/ShortlistHero";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { FrictionFlags, GradeBadge } from "@/components/FrictionFlags";
import { Button } from "@/components/ui/button";
import {
  Loader2, Plane, Check, ExternalLink, ArrowRight, Plus, RefreshCcw,
  AlertCircle, Clock,
} from "lucide-react";
import { api, type FlightOption } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";

const Flights = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAddCandidate, setShowAddCandidate] = useState(false);
  const [candidateLink, setCandidateLink] = useState("");
  const [candidateName, setCandidateName] = useState("");

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "flights"),
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
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 3 · Flights
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Pick your flights.
            </h2>
            {shortlist?.recommendation_summary && (
              <p className="text-muted-foreground mt-1 max-w-2xl">{shortlist.recommendation_summary}</p>
            )}
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

        {/* Options grid */}
        {options.length > 0 && (
          <div className="grid lg:grid-cols-2 gap-5">
            {options.map((o) => (
              <FlightCard
                key={o.option_id}
                option={o}
                isRecommended={o.option_id === recommendedId}
                isSelected={o.row_status === "approved"}
                onSelect={() => selectMutation.mutate(o.option_id)}
                isSelecting={selectMutation.isPending}
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

        {/* Warnings */}
        {shortlist && shortlist.warnings.length > 0 && (
          <div className="mt-6 rounded-3xl border-2 border-coral/30 bg-coral/5 p-5">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
              Friction warnings
            </div>
            <ul className="space-y-1 text-sm">
              {shortlist.warnings.map((w) => (
                <li key={w}>· {w}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </AppShell>
  );
};

function FlightCard({
  option,
  isRecommended,
  isSelected,
  onSelect,
  isSelecting,
}: {
  option: FlightOption;
  isRecommended: boolean;
  isSelected: boolean;
  onSelect: () => void;
  isSelecting: boolean;
}) {
  return (
    <article
      className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce flex flex-col ${
        isSelected
          ? "border-foreground shadow-sticker -translate-y-1"
          : "border-foreground/10 shadow-card hover:-translate-y-0.5"
      }`}
    >
      <div className="px-5 pt-5 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Plane className="h-5 w-5 text-secondary" />
            <span className="font-[Fredoka] text-xl font-bold">{option.airline}</span>
            <span className="text-sm text-muted-foreground font-mono">
              {option.flight_numbers.join(" / ")}
            </span>
          </div>
          <div className="text-sm font-semibold mt-1 text-foreground/80">
            {option.departure_airport} → {option.arrival_airport}
            {option.stops > 0 && (
              <span className="text-muted-foreground">
                {" "}· {option.stops} stop{option.stops !== 1 ? "s" : ""}
                {option.layover_airports.length > 0 && ` (${option.layover_airports.join(", ")})`}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <GradeBadge grade={option.recommendation_grade} />
          {isRecommended && (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-foreground text-background text-[10px] font-bold uppercase tracking-wider">
              Hermes' pick
            </span>
          )}
        </div>
      </div>

      <div className="px-5 pt-3 grid grid-cols-2 gap-3 text-sm">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-muted-foreground" />
          <div>
            <div className="font-bold tabular-nums">{option.departure_time || "—"}</div>
            <div className="text-xs text-muted-foreground">{option.departure_date}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-muted-foreground" />
          <div>
            <div className="font-bold tabular-nums">{option.arrival_time || "—"}</div>
            <div className="text-xs text-muted-foreground">{option.arrival_date}</div>
          </div>
        </div>
      </div>

      <div className="px-5 pt-3 flex flex-wrap gap-1.5 text-xs">
        <span className="px-2 py-0.5 rounded-full bg-muted border border-foreground/10 font-bold">
          {option.total_travel_duration || "duration unknown"}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-sunshine/30 border border-foreground/10 font-bold">
          {option.fare_estimate_cad || option.price_band}
        </span>
        {option.timing_fit && (
          <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">
            {option.timing_fit}
          </span>
        )}
      </div>

      {option.recommendation_rationale && (
        <p className="px-5 pt-3 text-sm text-foreground/85 leading-snug">
          {option.recommendation_rationale}
        </p>
      )}

      <div className="px-5 pt-3 grid grid-cols-2 gap-3">
        <ScoreBar label="Comfort" value={option.family_comfort_score} color="hsl(18 95% 55%)" />
        <ScoreBar label="Friction" value={option.friction_score} color="hsl(0 70% 60%)" inverted />
      </div>

      {option.tradeoffs.length > 0 && (
        <ul className="px-5 pt-3 space-y-1">
          {option.tradeoffs.slice(0, 3).map((t) => (
            <li key={t} className="text-xs text-foreground/75 leading-snug">· {t}</li>
          ))}
        </ul>
      )}

      {option.friction_flags.length > 0 && (
        <div className="px-5 pt-3">
          <FrictionFlags flags={option.friction_flags} />
        </div>
      )}

      <div className="mt-auto p-5 pt-4 flex items-center gap-2 border-t-2 border-foreground/10 mt-4">
        {option.deep_link && (
          <a
            href={option.deep_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" /> {option.booking_source || "open"}
          </a>
        )}
        <Button
          onClick={onSelect}
          disabled={isSelecting}
          className={`ml-auto h-10 rounded-xl font-bold border-2 px-5 ${
            isSelected
              ? "bg-palm text-primary-foreground border-foreground shadow-card hover:bg-palm/90"
              : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isSelected ? (
            <><Check className="h-4 w-4" /> Selected</>
          ) : (
            "Select"
          )}
        </Button>
      </div>
    </article>
  );
}

function ScoreBar({
  label, value, color, inverted = false,
}: { label: string; value: number; color: string; inverted?: boolean }) {
  const display = inverted ? `${value}` : `${value}`;
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
        <span>{label}</span>
        <span className="text-foreground">{display}</span>
      </div>
      <div className="h-2 rounded-full bg-muted border border-foreground/10 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value}%`, background: color }} />
      </div>
    </div>
  );
}

export default Flights;
