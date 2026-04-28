import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { ShortlistHero } from "@/components/ShortlistHero";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { Button } from "@/components/ui/button";
import {
  Loader2, Hotel, Check, ExternalLink, ArrowRight, Plus, RefreshCcw,
  AlertCircle, AlertTriangle, MapPin, Bed,
} from "lucide-react";
import { api, type LodgingOption, type TripIntake } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import { TripMap } from "@/components/TripMap";
import { useGeocodes } from "@/lib/geocode";
import { buildLodgingPins, makeGeocodeLookup } from "@/lib/pinBuilders";
import {
  Chip,
  LiveProvidersBanner,
  RowHeaderStrip,
  deriveLiveBanner,
  deriveLivePill,
  deriveRowLabel,
} from "@/components/ShortlistRow";

const GROUP_COLORS = [
  "hsl(18 95% 55%)",
  "hsl(205 88% 48%)",
  "hsl(178 70% 45%)",
  "hsl(145 55% 38%)",
  "hsl(45 100% 60%)",
];

type SortKey = "best" | "price" | "comfort";

const Stays = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [link, setLink] = useState("");
  const [name, setName] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("best");
  const [openWhyId, setOpenWhyId] = useState<string | null>(null);

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "lodging", { validate_live: true, deep_research: true }),
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

  const sorted = useMemo(() => sortLodging(options, sortKey), [options, sortKey]);
  const banner = useMemo(
    () => deriveLiveBanner(shortlist?.warnings ?? [], options, "lodging"),
    [shortlist?.warnings, options],
  );

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
      <ShortlistHero intake={trip?.intake} stageLabel="Stays" stageNumber={4} flagCount={flagCount} />
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 4 · Stays
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">Pick where you sleep.</h2>
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
                {buildMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                Re-research
              </button>
            </div>
          )}
        </div>

        <LiveProvidersBanner banner={banner} />

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
              <div className="text-muted-foreground mt-1">{(tripQuery.error as Error)?.message}</div>
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
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="flex flex-wrap gap-2">
              <Chip>✦ Comfort &gt; location &gt; price</Chip>
              <Chip>{partyChip(trip?.intake)}</Chip>
              <Chip>{regionsChip(options)}</Chip>
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
                <option value="comfort">Comfort</option>
              </select>
            </div>
          </div>
        )}

        {sorted.length > 0 && (
          <div className="flex flex-col gap-4">
            {sorted.map((o) => (
              <LodgingRow
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
      </div>
    </AppShell>
  );
};

function partyChip(intake: TripIntake | undefined): string {
  if (!intake) return "Party · checked bags";
  const total = intake.travelers || (intake.party.adults + intake.party.children);
  return `Party of ${total}`;
}

function regionsChip(options: LodgingOption[]): string {
  const region = options[0]?.island_or_region || options[0]?.location_area || "region";
  return `${region}`;
}

function sortLodging(options: LodgingOption[], key: SortKey): LodgingOption[] {
  const arr = [...options];
  if (key === "price") {
    arr.sort((a, b) => priceAmount(a.price_band || a.current_price_signal) - priceAmount(b.price_band || b.current_price_signal));
  } else if (key === "comfort") {
    arr.sort((a, b) => b.family_comfort_score - a.family_comfort_score);
  } else {
    arr.sort((a, b) => a.rank - b.rank);
  }
  return arr;
}

function priceAmount(value: string): number {
  const m = (value || "").match(/([\d][\d,]*(?:\.\d{2})?)/);
  return m ? parseFloat(m[1].replace(/,/g, "")) : Number.POSITIVE_INFINITY;
}

function LodgingRow({
  option,
  isRecommended,
  isSelected,
  onSelect,
  isSelecting,
  whyOpen,
  onToggleWhy,
}: {
  option: LodgingOption;
  isRecommended: boolean;
  isSelected: boolean;
  onSelect: () => void;
  isSelecting: boolean;
  whyOpen: boolean;
  onToggleWhy: () => void;
}) {
  const label = deriveRowLabel("", isRecommended, option.recommendation_grade);
  const pill = deriveLivePill(option);

  return (
    <article
      className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce ${
        isSelected ? "border-foreground shadow-sticker" : "border-foreground/10 shadow-card hover:-translate-y-0.5"
      }`}
    >
      <RowHeaderStrip
        label={label}
        pill={pill}
        left={
          <>
            <Hotel className="h-4 w-4 text-foreground/60" />
            <span className="font-bold truncate">{option.name}</span>
            <span className="text-xs text-muted-foreground ml-1 truncate">{option.lodging_type}</span>
          </>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-[1fr_minmax(220px,_auto)] gap-5 px-5 py-5">
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-sm font-medium text-foreground/85">
            <MapPin className="h-4 w-4 text-foreground/50" />
            {option.location_area}
            {option.island_or_region && <span className="text-muted-foreground">· {option.island_or_region}</span>}
          </div>
          <div className="flex items-start gap-1.5 text-sm">
            <Bed className="h-4 w-4 text-foreground/50 shrink-0 mt-0.5" />
            <span className="text-foreground/85">{option.bed_layout || "bed layout not confirmed"}</span>
          </div>
        </div>
        <div className="md:text-right">
          <div className="font-[Fredoka] text-3xl font-bold leading-none">
            {option.current_price_signal || option.price_band}
          </div>
          {option.price_band && option.price_band !== option.current_price_signal && (
            <div className="text-xs text-muted-foreground mt-1.5 font-mono uppercase tracking-wider">
              Total {option.price_band}
            </div>
          )}
        </div>
      </div>

      <div className="px-5 pb-4 grid md:grid-cols-2 gap-4">
        <ul className="space-y-1.5 text-sm">
          {derivePros(option).slice(0, 3).map((p) => (
            <li key={p} className="flex items-start gap-2">
              <Check className="h-4 w-4 text-palm shrink-0 mt-0.5" />
              <span className="text-foreground/85">{p}</span>
            </li>
          ))}
        </ul>
        {option.friction_flags.length > 0 && (
          <div className="rounded-xl border border-coral/40 bg-coral/5 px-3 py-2 space-y-1">
            {option.friction_flags.slice(0, 3).map((f) => (
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
            isSelected ? "bg-primary text-primary-foreground border-foreground shadow-card" : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? <Loader2 className="h-4 w-4 animate-spin" /> : isSelected ? <><Check className="h-4 w-4" /> Using this stay</> : "Use this stay"}
        </Button>
        {option.deep_link && (
          <a href={option.deep_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-bold text-foreground/80 hover:text-foreground">
            <ArrowRight className="h-4 w-4" /> Open listing
          </a>
        )}
        {option.deep_link && (
          <a href={option.deep_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground">
            <ExternalLink className="h-3.5 w-3.5" /> Book / confirm
          </a>
        )}
        <button type="button" onClick={onToggleWhy} className="ml-auto text-sm font-medium text-muted-foreground hover:text-foreground">
          {whyOpen ? "Hide details" : "Why not this?"}
        </button>
      </div>

      {whyOpen && (
        <div className="px-5 pb-5 pt-1 text-sm text-foreground/80 space-y-2 border-t border-foreground/10">
          {option.comfort_fit && <p className="leading-snug">{option.comfort_fit}</p>}
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
            {option.parking_practicality && <span>Parking: {option.parking_practicality}</span>}
            {option.walkability && <span>Walk: {option.walkability}</span>}
            {option.cancellation_notes && <span>Cancel: {option.cancellation_notes}</span>}
            {option.validation?.adapter_used && <span>Source: {option.validation.adapter_used}</span>}
          </div>
        </div>
      )}
    </article>
  );
}

function derivePros(option: LodgingOption): string[] {
  const pros: string[] = [];
  if (option.comfort_fit) pros.push(option.comfort_fit);
  for (const t of option.tradeoffs) {
    if (pros.length >= 3) break;
    if (!pros.includes(t)) pros.push(t);
  }
  if (pros.length === 0 && option.bed_layout) pros.push(option.bed_layout);
  return pros;
}

export default Stays;
