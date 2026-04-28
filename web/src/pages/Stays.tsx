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
  Loader2, Hotel, Check, ExternalLink, ArrowRight, Plus, RefreshCcw,
  AlertCircle, MapPin, Bed,
} from "lucide-react";
import { api, type LodgingOption } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import { TripMap } from "@/components/TripMap";
import { useGeocodes } from "@/lib/geocode";
import { buildLodgingPins, makeGeocodeLookup } from "@/lib/pinBuilders";

const GROUP_COLORS = [
  "hsl(18 95% 55%)",
  "hsl(205 88% 48%)",
  "hsl(178 70% 45%)",
  "hsl(145 55% 38%)",
  "hsl(45 100% 60%)",
];

const Stays = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [link, setLink] = useState("");
  const [name, setName] = useState("");

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "lodging"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const selectMutation = useMutation({
    mutationFn: (id: string) => api.selectLodging(tripId!, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const candidateMutation = useMutation({
    mutationFn: () => api.addLodgingCandidate({ trip_id: tripId!, link, name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
      setLink("");
      setName("");
      setShowAdd(false);
    },
  });

  const trip = tripQuery.data;
  const shortlist = shortlistOptions(trip, "lodging");
  const options: LodgingOption[] = shortlist?.lodging_options ?? [];
  const stages = buildStages(trip, "stays");
  const recommendedId = shortlist?.recommended_option_id;
  const flagCount = options.reduce((s, o) => s + o.friction_flags.length, 0);
  const hasSelection = options.some((o) => o.row_status === "approved");

  const lodgingQueries = options.map((o) =>
    [o.location_area, o.island_or_region].filter(Boolean).join(", ")
  );
  const lodgingGeocodes = useGeocodes(lodgingQueries);
  const lodgingLookup = makeGeocodeLookup(
    lodgingQueries.map((q, i) => ({ query: q, coords: lodgingGeocodes[i]?.data ?? null }))
  );
  const lodgingPins = buildLodgingPins(options, lodgingLookup);
  const regionGroups = (() => {
    const byRegion = new Map<string, string[]>();
    for (const o of options) {
      const region = o.island_or_region || o.location_area || "Other";
      const list = byRegion.get(region) ?? [];
      list.push(`lodging-${o.option_id}`);
      byRegion.set(region, list);
    }
    return Array.from(byRegion.entries()).map(([label, pinIds], i) => ({
      id: `region-${i}`,
      label,
      color: GROUP_COLORS[i % GROUP_COLORS.length],
      pinIds,
    }));
  })();

  return (
    <AppShell>
      <ShortlistHero
        intake={trip?.intake}
        stageLabel="Stays"
        stageNumber={4}
        flagCount={flagCount}
      />
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 4 · Stays
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Pick where you sleep.
            </h2>
            {shortlist?.recommendation_summary && (
              <p className="text-muted-foreground mt-1 max-w-2xl">{shortlist.recommendation_summary}</p>
            )}
          </div>
          {options.length > 0 && (
            <div className="flex gap-2">
              <button
                onClick={() => setShowAdd((v) => !v)}
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
            <div className="text-sm">
              <div className="font-bold text-destructive">Couldn't load trip</div>
              <div className="text-muted-foreground mt-1">
                {(tripQuery.error as Error)?.message}
              </div>
            </div>
          </div>
        )}

        {!tripQuery.isLoading && !shortlist && (
          <EmptyShortlist
            title="No lodging options yet"
            description="Hermes will research family-friendly stays in the right neighborhoods, score them on friction (bed layout, walkability, parking), and propose a recommendation."
            ctaLabel="Build lodging shortlist"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {showAdd && (
          <div className="rounded-3xl border-2 border-foreground/15 bg-card shadow-card p-5 mb-6">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Add your own lodging to compare
            </div>
            <div className="grid md:grid-cols-[1fr_220px_auto] gap-3">
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="Paste an Airbnb / Booking / hotel URL"
                className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
              />
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Label"
                className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
              />
              <Button
                onClick={() => candidateMutation.mutate()}
                disabled={!link || candidateMutation.isPending}
                className="h-11 rounded-xl bg-foreground text-background font-bold px-5"
              >
                {candidateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Research it"}
              </Button>
            </div>
          </div>
        )}

        {lodgingPins.length > 0 && regionGroups.length > 0 && (
          <div className="mb-6 space-y-2">
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Where these stays sit · Split-stay decision view
            </div>
            <TripMap
              pins={lodgingPins}
              height="380px"
              showScrubber={false}
              groups={regionGroups.length > 1 ? regionGroups : undefined}
            />
          </div>
        )}

        {options.length > 0 && (
          <div className="grid lg:grid-cols-2 gap-5">
            {options.map((o) => (
              <LodgingCard
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

        {hasSelection && (
          <div className="mt-6 flex justify-end">
            <Button
              onClick={() => navigate(`/trip/${tripId}/cars`)}
              className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
            >
              Continue to Cars <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        )}

        {shortlist && shortlist.warnings.length > 0 && (
          <div className="mt-6 rounded-3xl border-2 border-coral/30 bg-coral/5 p-5">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
              Friction warnings
            </div>
            <ul className="space-y-1 text-sm">
              {shortlist.warnings.map((w) => <li key={w}>· {w}</li>)}
            </ul>
          </div>
        )}
      </div>
    </AppShell>
  );
};

function LodgingCard({
  option, isRecommended, isSelected, onSelect, isSelecting,
}: {
  option: LodgingOption;
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
            <Hotel className="h-5 w-5 text-secondary" />
            <span className="font-[Fredoka] text-xl font-bold leading-tight">{option.name}</span>
          </div>
          <div className="text-xs text-muted-foreground font-semibold mt-1 flex items-center gap-1">
            <MapPin className="h-3 w-3" /> {option.location_area}{option.island_or_region && ` · ${option.island_or_region}`}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">{option.lodging_type}</div>
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

      <div className="px-5 pt-3 flex items-start gap-2 text-sm">
        <Bed className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
        <span className="text-foreground/85 leading-snug">{option.bed_layout || "bed layout not confirmed"}</span>
      </div>

      <div className="px-5 pt-3 flex flex-wrap gap-1.5 text-xs">
        <span className="px-2 py-0.5 rounded-full bg-sunshine/30 border border-foreground/10 font-bold">
          {option.current_price_signal || option.price_band}
        </span>
        {option.occupancy_fit && (
          <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">{option.occupancy_fit}</span>
        )}
        {option.parking_practicality && (
          <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">parking: {option.parking_practicality}</span>
        )}
        {option.walkability && (
          <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">walk: {option.walkability}</span>
        )}
      </div>

      {option.comfort_fit && (
        <p className="px-5 pt-3 text-sm text-foreground/85 leading-snug">{option.comfort_fit}</p>
      )}

      <div className="px-5 pt-3 grid grid-cols-2 gap-3">
        <ScoreBar label="Comfort" value={option.family_comfort_score} color="hsl(18 95% 55%)" />
        <ScoreBar label="Friction" value={option.friction_score} color="hsl(0 70% 60%)" />
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

      {option.cancellation_notes && (
        <div className="px-5 pt-3 text-xs text-muted-foreground">
          Cancellation: {option.cancellation_notes}
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
            <ExternalLink className="h-3 w-3" /> {option.source || "open"}
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
          {isSelecting ? <Loader2 className="h-4 w-4 animate-spin" /> :
            isSelected ? <><Check className="h-4 w-4" /> Selected</> : "Select"}
        </Button>
      </div>
    </article>
  );
}

function ScoreBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
        <span>{label}</span>
        <span className="text-foreground">{value}</span>
      </div>
      <div className="h-2 rounded-full bg-muted border border-foreground/10 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value}%`, background: color }} />
      </div>
    </div>
  );
}

export default Stays;
