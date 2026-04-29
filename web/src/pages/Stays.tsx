import { useEffect, useMemo, useState, type DragEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { ShortlistHero } from "@/components/ShortlistHero";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { Button } from "@/components/ui/button";
import {
  Loader2, Hotel, Check, ExternalLink, ArrowRight, Plus, RefreshCcw,
  AlertCircle, AlertTriangle, MapPin, Bed, ChevronLeft, ChevronRight, Save,
  GripVertical, X,
} from "lucide-react";
import { api, mergeShortlistIntoTrip, type LodgingOption, type TripIntake, type TripState } from "@/lib/api";
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

interface NightTarget {
  key: string;
  label: string;
  nights: number;
  allocated: number;
}

const Stays = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [link, setLink] = useState("");
  const [name, setName] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("best");
  const [openWhyId, setOpenWhyId] = useState<string | null>(null);
  const [nightDraft, setNightDraft] = useState<Record<string, number>>({});
  const [localSelectedIds, setLocalSelectedIds] = useState<string[]>([]);
  const [draggedStayId, setDraggedStayId] = useState<string | null>(null);

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "lodging", { validate_live: true, deep_research: true }),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });

  const selectMutation = useMutation({
    mutationFn: ({ id, selected }: { id: string; selected: boolean }) =>
      selected ? api.deselectLodging(tripId!, id) : api.selectLodging(tripId!, id),
    onMutate: async ({ id, selected }) => {
      await queryClient.cancelQueries({ queryKey: ["trip", tripId] });
      setLocalSelectedIds((current) =>
        selected ? current.filter((value) => value !== id) : current.includes(id) ? current : [...current, id],
      );
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        current ? {
          ...current,
          shortlists: (current.shortlists ?? []).map((item) =>
            item.category === "lodging"
              ? {
                  ...item,
                  lodging_options: item.lodging_options.map((option) =>
                    option.option_id === id
                      ? { ...option, row_status: selected ? "researched" : "approved" }
                      : option,
                  ),
                }
              : item,
          ),
        } : current,
      );
    },
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
    },
  });

  const structureMutation = useMutation({
    mutationFn: (nightPlan: Array<{ region: string; nights: number; lodging_option_id: string; notes: string }>) =>
      api.updateLodgingStructure({
        trip_id: tripId!,
        strategy: nightPlan.length > 1 ? "split_stay" : "single_stay",
        night_plan: nightPlan,
        notes: "Saved from lodging selection night allocation.",
      }),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });

  const candidateMutation = useMutation({
    mutationFn: () => api.addLodgingCandidate({ trip_id: tripId!, link, name }),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
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
  const serverSelectedIds = useMemo(
    () => options.filter((o) => o.row_status === "approved").map((o) => o.option_id),
    [options],
  );
  const selectedIds = useMemo(
    () => mergeIds(localSelectedIds, serverSelectedIds).filter((id) =>
      options.some((option) => option.option_id === id),
    ),
    [localSelectedIds, serverSelectedIds, options],
  );
  const hasSelection = selectedIds.length > 0;
  const hasShortlist = Boolean(shortlist);
  const selectedOptions = selectedIds
    .map((id) => options.find((option) => option.option_id === id))
    .filter((option): option is LodgingOption => Boolean(option));
  const nightTargets = useMemo(
    () => buildNightTargets(trip, selectedOptions, nightDraft),
    [trip, selectedOptions, nightDraft],
  );
  const expectedNights = nightTargets.reduce((sum, target) => sum + target.nights, 0) || expectedTripNights(trip);
  const allocatedNights = selectedOptions.reduce((sum, option) => sum + (nightDraft[option.option_id] || 0), 0);
  const targetMismatches = nightTargets.filter((target) => target.allocated !== target.nights);
  const nightConstraintOk = selectedOptions.length === 0 || targetMismatches.length === 0;

  const sorted = useMemo(() => sortLodging(options, sortKey), [options, sortKey]);
  const banner = useMemo(
    () => deriveLiveBanner(shortlist?.warnings ?? [], options, "lodging"),
    [shortlist?.warnings, options],
  );

  useEffect(() => {
    if (selectedOptions.length === 0) return;
    setNightDraft((current) => {
      const next = { ...current };
      for (const target of nightTargets) {
        const group = selectedOptions.filter((option) => optionRegionKey(option) === target.key);
        const split = splitNights(target.nights, group.length);
        group.forEach((option, index) => {
          next[option.option_id] = split[index] ?? 1;
        });
      }
      for (const key of Object.keys(next)) {
        if (!selectedOptions.some((option) => option.option_id === key)) delete next[key];
      }
      return next;
    });
  }, [selectedOptions.map((option) => option.option_id).join("|"), nightTargets.map((target) => `${target.key}:${target.nights}`).join("|")]);

  useEffect(() => {
    setLocalSelectedIds((current) => mergeIds(current, serverSelectedIds));
  }, [serverSelectedIds.join("|")]);

  const moveSelectedStay = (draggedId: string, targetId: string) => {
    if (draggedId === targetId) return;
    setLocalSelectedIds((current) => {
      const ordered = mergeIds(current, serverSelectedIds).filter((id) =>
        options.some((option) => option.option_id === id),
      );
      return moveIdBefore(ordered, draggedId, targetId);
    });
  };

  const onStayDragStart = (event: DragEvent, optionId: string) => {
    setDraggedStayId(optionId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", optionId);
  };

  const onStayDrop = (event: DragEvent, targetId: string) => {
    event.preventDefault();
    const sourceId = event.dataTransfer.getData("text/plain") || draggedStayId;
    if (sourceId) moveSelectedStay(sourceId, targetId);
    setDraggedStayId(null);
  };

  const destinationContext = trip?.intake?.destination_seeds?.join(", ") ?? "";
  const lodgingQueries = options.map((o) =>
    [o.location_area, o.island_or_region].filter(Boolean).join(", ")
  );
  const lodgingSearchQueries = lodgingQueries.map((query) =>
    destinationContext && !query.toLowerCase().includes(destinationContext.toLowerCase())
      ? [query, destinationContext].filter(Boolean).join(", ")
      : query
  );
  const lodgingGeocodes = useGeocodes(lodgingSearchQueries);
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

  const allocationPanel = selectedOptions.length > 0 && (
    <div className={`mt-6 rounded-2xl border-2 p-4 ${nightConstraintOk ? "border-foreground/15 bg-card" : "border-coral/50 bg-coral/5"}`}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
            Stay allocation constraint
          </div>
          <div className="font-bold mt-1">
            Put the selected stays in trip order, then assign nights to cover each selected location.
          </div>
          <div className="text-sm text-muted-foreground mt-1">
            Trip length is constrained by the selected departure and return flights when available, with the intake travel window as fallback.
          </div>
        </div>
        <Button
          onClick={() => structureMutation.mutate(selectedOptions.map((option) => ({
            region: option.location_area || option.island_or_region || option.name,
            nights: Math.max(1, nightDraft[option.option_id] || 1),
            lodging_option_id: option.option_id,
            notes: `Selected stay from ${option.source || "source listing"}`,
          })))}
          disabled={!nightConstraintOk || structureMutation.isPending}
          className="h-10 rounded-xl bg-foreground text-background font-bold"
        >
          {structureMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save nights
        </Button>
      </div>
      <div className="mt-4 grid md:grid-cols-2 gap-3">
        {selectedOptions.map((option, index) => (
          <div
            key={option.option_id}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => onStayDrop(event, option.option_id)}
            className={`flex items-center justify-between gap-3 rounded-xl border bg-background px-3 py-2 transition-colors ${
              draggedStayId === option.option_id ? "border-primary/60" : "border-foreground/10"
            }`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <button
                type="button"
                draggable
                onDragStart={(event) => onStayDragStart(event, option.option_id)}
                onDragEnd={() => setDraggedStayId(null)}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-foreground/10 bg-card text-muted-foreground hover:text-foreground hover:border-foreground/30"
                aria-label={`Drag ${option.name} to reorder selected stays`}
                title="Drag to reorder"
              >
                <GripVertical className="h-4 w-4" />
              </button>
              <span className="shrink-0 text-xs font-bold text-muted-foreground tabular-nums">
                {index + 1}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-bold truncate">{option.name}</span>
                <span className="block text-xs text-muted-foreground truncate">{option.location_area}</span>
              </span>
            </div>
            <label className="shrink-0">
              <span className="sr-only">Nights for {option.name}</span>
              <input
                type="number"
                min={1}
                value={nightDraft[option.option_id] || 1}
                onChange={(e) => setNightDraft((current) => ({
                  ...current,
                  [option.option_id]: Math.max(1, Number(e.target.value) || 1),
                }))}
                className="h-9 w-20 rounded-lg border-2 border-foreground/10 bg-card px-2 text-right font-bold focus:outline-none focus:border-primary"
              />
            </label>
          </div>
        ))}
      </div>
      {expectedNights && (
        <div className={`mt-3 text-sm font-bold ${nightConstraintOk ? "text-palm" : "text-coral"}`}>
          {nightConstraintOk
            ? `${allocatedNights} night${allocatedNights === 1 ? "" : "s"} allocated`
            : targetMismatches.map((target) => `${target.label}: ${target.allocated}/${target.nights}`).join(" · ")}
        </div>
      )}
    </div>
  );

  return (
    <AppShell>
      <ShortlistHero
        intake={trip?.intake}
        shortlists={trip?.shortlists}
        stageLabel="Stays"
        stageNumber={4}
        flagCount={flagCount}
        showMap={false}
      />
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
          {hasShortlist && (
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
            description="Trippy will research family-friendly stays in the right neighborhoods, score them on friction (bed layout, walkability, parking), and propose a recommendation."
            ctaLabel="Build lodging shortlist"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {!tripQuery.isLoading && shortlist && options.length === 0 && (
          <EmptyShortlist
            title="No lodging rows returned"
            description="The shortlist exists, but it did not produce any lodging rows. Re-run lodging research after connecting SERPAPI_KEY, or paste a specific lodging link to compare."
            ctaLabel="Re-research lodging"
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
          <div id="friction-review" className="flex scroll-mt-32 flex-col gap-4">
            {sorted.map((o) => (
              <LodgingRow
                key={o.option_id}
                option={o}
                isRecommended={o.option_id === recommendedId}
                isSelected={selectedIds.includes(o.option_id)}
                onSelect={() => selectMutation.mutate({ id: o.option_id, selected: selectedIds.includes(o.option_id) })}
                isSelecting={selectMutation.isPending}
                whyOpen={openWhyId === o.option_id}
                onToggleWhy={() => setOpenWhyId(openWhyId === o.option_id ? null : o.option_id)}
              />
            ))}
          </div>
        )}

        {allocationPanel}

        {hasSelection && (
          <div className="mt-6 flex justify-end">
            <Button
              onClick={() => navigate(`/trip/${tripId}/cars`)}
              disabled={!nightConstraintOk}
              className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
            >
              {nightConstraintOk ? "Continue to Cars" : "Allocate all nights"} <ArrowRight className="h-4 w-4" />
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

function mergeIds(...groups: string[][]): string[] {
  return Array.from(new Set(groups.flat().filter(Boolean)));
}

function moveIdBefore(ids: string[], draggedId: string, targetId: string): string[] {
  const from = ids.indexOf(draggedId);
  const to = ids.indexOf(targetId);
  if (from < 0 || to < 0 || from === to) return ids;
  const next = [...ids];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function expectedTripNights(trip: TripState | undefined): number | null {
  const intake = trip?.intake;
  if (!intake) return null;
  const flightNights = selectedFlightNights(trip);
  if (flightNights) return flightNights;
  const start = intake.travel_window.start_date ? new Date(`${intake.travel_window.start_date}T00:00:00`) : null;
  const end = intake.travel_window.end_date ? new Date(`${intake.travel_window.end_date}T00:00:00`) : null;
  if (start && end && end > start) {
    return Math.round((end.getTime() - start.getTime()) / 86_400_000);
  }
  return intake.duration_days || null;
}

function buildNightTargets(
  trip: TripState | undefined,
  selectedOptions: LodgingOption[],
  nightDraft: Record<string, number>,
): NightTarget[] {
  if (selectedOptions.length === 0) return [];
  const selectedPlan = trip?.draft?.options.find(
    (option) => option.option_id === trip.draft?.selected_option_id,
  );
  const planNights = selectedPlan?.nights_by_region ?? {};
  const fallback = expectedTripNights(trip) || selectedOptions.length;
  const targets = new Map<string, NightTarget>();

  for (const option of selectedOptions) {
    const key = optionRegionKey(option);
    if (targets.has(key)) continue;
    const label = option.island_or_region || option.location_area || option.name;
    targets.set(key, {
      key,
      label,
      nights: targetNightsForOption(option, planNights, fallback),
      allocated: 0,
    });
  }
  for (const option of selectedOptions) {
    const target = targets.get(optionRegionKey(option));
    if (target) target.allocated += nightDraft[option.option_id] || 0;
  }
  return Array.from(targets.values());
}

function selectedFlightNights(trip: TripState | undefined): number | null {
  const flights = trip?.shortlists.find((shortlist) => shortlist.category === "flights");
  const selection = flights?.artifacts?.flight_selection;
  const outbound = flights?.flight_options.find((option) => option.option_id === selection?.selected_outbound_option_id);
  const returnFlight = flights?.flight_options.find((option) => option.option_id === selection?.selected_return_option_id);
  const start = parseIsoDate(outbound?.departure_date);
  const end = latestFlightDate(returnFlight, start);
  if (!start || !end || end <= start) return null;
  return Math.round((end.getTime() - start.getTime()) / 86_400_000);
}

function latestFlightDate(option: { departure_date?: string; arrival_date?: string } | undefined, start: Date | null): Date | null {
  if (!option || !start) return null;
  const dates = [parseIsoDate(option.departure_date), parseIsoDate(option.arrival_date)]
    .filter((date): date is Date => Boolean(date))
    .filter((date) => date >= start);
  if (dates.length === 0) return null;
  return dates.sort((a, b) => b.getTime() - a.getTime())[0];
}

function parseIsoDate(value: string | undefined): Date | null {
  return value ? new Date(`${value}T00:00:00`) : null;
}

function targetNightsForOption(
  option: LodgingOption,
  planNights: Record<string, number>,
  fallback: number,
): number {
  const labels = [option.island_or_region, option.location_area].filter(Boolean);
  for (const [region, nights] of Object.entries(planNights)) {
    if (labels.some((label) => regionMatches(label, region))) {
      return Math.max(1, Number(nights) || fallback);
    }
  }
  return fallback;
}

function optionRegionKey(option: LodgingOption): string {
  return normalizeRegion(option.island_or_region || option.location_area || option.name);
}

function regionMatches(left: string, right: string): boolean {
  const a = normalizeRegion(left);
  const b = normalizeRegion(right);
  return Boolean(a && b && (a.includes(b) || b.includes(a)));
}

function normalizeRegion(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function splitNights(total: number, count: number): number[] {
  if (count <= 0) return [];
  const safeTotal = Math.max(count, total || count);
  const base = Math.floor(safeTotal / count);
  const remainder = safeTotal % count;
  return Array.from({ length: count }, (_, index) => base + (index < remainder ? 1 : 0));
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
            <span className="rounded-full bg-background/80 border border-foreground/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-foreground/70">
              {option.source || "Source"}
            </span>
          </>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr_minmax(220px,_auto)] gap-5 px-5 py-5">
        <LodgingImage option={option} />
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-sm font-medium text-foreground/85">
            <MapPin className="h-4 w-4 text-foreground/50" />
            {option.location_area}
            {option.island_or_region && <span className="text-muted-foreground">· {option.island_or_region}</span>}
          </div>
          <div className="flex items-start gap-1.5 text-sm">
            <Bed className="h-4 w-4 text-foreground/50 shrink-0 mt-0.5" />
            <span className="text-foreground/85">{displayBedLayout(option.bed_layout)}</span>
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
          aria-pressed={isSelected}
          className={`h-10 rounded-xl font-bold border-2 px-5 ${
            isSelected ? "bg-primary text-primary-foreground border-foreground shadow-card" : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
          }`}
        >
          {isSelecting ? <Loader2 className="h-4 w-4 animate-spin" /> : isSelected ? <><X className="h-4 w-4" /> Remove stay</> : "Use this stay"}
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

function LodgingImage({ option }: { option: LodgingOption }) {
  const [imgFailed, setImgFailed] = useState(false);
  const [index, setIndex] = useState(0);
  const photos = lodgingPhotoUrls(option);
  const active = photos[index % Math.max(photos.length, 1)];

  const move = (delta: number) => {
    if (photos.length <= 1) return;
    setImgFailed(false);
    setIndex((current) => (current + delta + photos.length) % photos.length);
  };

  return (
    <div className="group relative h-56 lg:h-full min-h-52 rounded-2xl overflow-hidden bg-muted border-2 border-foreground/10">
      {active && !imgFailed && (
        <img
          src={active}
          alt={[option.name, option.location_area, option.island_or_region].filter(Boolean).join(", ")}
          loading="lazy"
          onError={() => setImgFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      {(!active || imgFailed) && (
        <div className="absolute inset-0 grid place-items-center bg-muted text-muted-foreground">
          <div className="flex flex-col items-center gap-2 text-xs font-semibold uppercase tracking-wider">
            <Hotel className="h-8 w-8" />
            <span>Open listing for photos</span>
          </div>
        </div>
      )}
      {active && !imgFailed && <div className="absolute inset-0 bg-gradient-to-t from-black/35 via-transparent to-transparent" />}
      {photos.length > 1 && (
        <>
          <button
            type="button"
            onClick={() => move(-1)}
            className="absolute left-2 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-background/95 border border-foreground/15 shadow-sm transition-transform hover:scale-105 grid place-items-center"
            aria-label="Previous lodging photo"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => move(1)}
            className="absolute right-2 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-background/95 border border-foreground/15 shadow-sm transition-transform hover:scale-105 grid place-items-center"
            aria-label="Next lodging photo"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </>
      )}
      <span className="absolute left-2.5 bottom-2.5 rounded-full bg-background/90 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-foreground/15">
        {photos.length > 1 ? `${index + 1}/${photos.length}` : "Property photos only"}
      </span>
      {photos.length > 1 && (
        <div className="absolute bottom-2.5 right-2.5 flex max-w-[55%] gap-1 overflow-hidden rounded-full bg-background/85 px-2 py-1 border border-foreground/15">
          {photos.slice(0, 10).map((photo, photoIndex) => (
            <button
              key={photo}
              type="button"
              onClick={() => {
                setImgFailed(false);
                setIndex(photoIndex);
              }}
              aria-label={`Show lodging photo ${photoIndex + 1}`}
              className={`h-1.5 rounded-full transition-all ${
                photoIndex === index ? "w-5 bg-foreground" : "w-1.5 bg-foreground/35 hover:bg-foreground/60"
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function lodgingPhotoUrls(option: Pick<LodgingOption, "photo_urls">): string[] {
  return Array.from(new Set((option.photo_urls || []).filter((url) => url.startsWith("http"))));
}

function derivePros(option: LodgingOption): string[] {
  const pros: string[] = [];
  if (option.comfort_fit) pros.push(option.comfort_fit);
  for (const t of option.tradeoffs) {
    if (pros.length >= 3) break;
    if (!pros.includes(t)) pros.push(t);
  }
  if (pros.length === 0) pros.push(displayBedLayout(option.bed_layout));
  return pros;
}

export function displayBedLayout(value: string | undefined): string {
  const text = (value || "").trim();
  if (!text) return "Bed layout not confirmed yet";
  if (/serpapi|king bed strongly preferred|queen compromise|exact layout must be verified/i.test(text)) {
    return "Bed layout pending OpenClaw/FireCrawl verification";
  }
  return text;
}

export default Stays;
