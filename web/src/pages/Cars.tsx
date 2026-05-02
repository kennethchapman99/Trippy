import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { ShortlistHero } from "@/components/ShortlistHero";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { Button } from "@/components/ui/button";
import {
  Loader2, Car, Check, ExternalLink, ArrowRight, RefreshCcw,
  AlertCircle, AlertTriangle, Users, Luggage, Camera,
} from "lucide-react";
import { api, mergeShortlistIntoTrip, type CarOption, type TripIntake, type TripState } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import {
  Chip,
  LiveProvidersBanner,
  RowHeaderStrip,
  deriveLiveBanner,
  deriveLivePill,
  deriveRowLabel,
} from "@/components/ShortlistRow";

type SortKey = "best" | "price" | "comfort";

const Cars = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("best");
  const [openWhyId, setOpenWhyId] = useState<string | null>(null);

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "cars", { validate_live: true, deep_research: true }),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });

  const selectMutation = useMutation({
    mutationFn: (id: string) => api.selectCar(tripId!, id),
    onSuccess: (response) => {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist),
      );
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });

  const trip = tripQuery.data;
  const shortlist = shortlistOptions(trip, "cars");
  const options: CarOption[] = shortlist?.car_options ?? [];
  const stages = buildStages(trip, "cars");
  const recommendedId = shortlist?.recommended_option_id;
  const flagCount = options.reduce((s, o) => s + o.friction_flags.length, 0);
  const hasSelection = options.some((o) => o.row_status === "approved");
  const hasShortlist = Boolean(shortlist);

  const sorted = useMemo(() => sortCars(options, sortKey), [options, sortKey]);
  const banner = useMemo(
    () => deriveLiveBanner(shortlist?.warnings ?? [], options, "cars"),
    [shortlist?.warnings, options],
  );

  return (
    <AppShell>
      <ShortlistHero
        intake={trip?.intake}
        shortlists={trip?.shortlists}
        stageLabel="Cars"
        stageNumber={5}
        flagCount={flagCount}
      />
      <div className="px-4 md:px-6 lg:px-8 py-4 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-4 md:px-6 lg:px-8 py-6">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 5 · Cars
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">Pick your wheels.</h2>
          </div>
          {hasShortlist && (
            <button
              onClick={() => buildMutation.mutate()}
              disabled={buildMutation.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors"
            >
              {buildMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              Re-research
            </button>
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
            <div className="text-sm text-muted-foreground">{(tripQuery.error as Error)?.message}</div>
          </div>
        )}

        {!tripQuery.isLoading && !shortlist && (
          <EmptyShortlist
            title="No car options yet"
            description="Trippy will research rentals at your pickup location, score for passenger/luggage fit, parking practicality, and pickup simplicity."
            ctaLabel="Build car shortlist"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {!tripQuery.isLoading && shortlist && options.length === 0 && (
          <EmptyShortlist
            title="No car rows returned"
            description="The shortlist exists, but it did not produce any car rows. Re-run car research after connecting live providers."
            ctaLabel="Re-research cars"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {options.length > 0 && (
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="flex flex-wrap gap-2">
              <Chip>✦ Luggage fit &gt; pickup ease &gt; price</Chip>
              <Chip>{partyChip(trip?.intake)}</Chip>
              <Chip>{pickupChip(options)}</Chip>
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
              <CarRow
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

        <div className="mt-8 flex items-center justify-end gap-3">
          {!hasSelection && (
            <span className="text-sm text-muted-foreground">No car selected — that's OK, you can still continue.</span>
          )}
          <Button
            onClick={() => navigate(`/trip/${tripId}/do`)}
            className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
          >
            Continue to Activities <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </AppShell>
  );
};

function partyChip(intake: TripIntake | undefined): string {
  if (!intake) return "Party";
  const total = intake.travelers || (intake.party.adults + intake.party.children);
  return `Party of ${total} · checked bags`;
}

function pickupChip(options: CarOption[]): string {
  return options[0]?.pickup_location ? `Pickup ${options[0].pickup_location}` : "Pickup TBD";
}

function sortCars(options: CarOption[], key: SortKey): CarOption[] {
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

function displayCarFare(value: string): string {
  const text = (value || "").trim();
  if (!text) return "not live-quoted yet";
  const price = text.match(/(?:CAD\s*)?(?:CA\$|C\$|\$)\s*[\d,]+(?:\.\d{1,2})?(?:\s*\/\s*(?:day|week|rental))?/i);
  if (price) return price[0].replace(/\s+/g, " ");
  if (/not\s+live|live\s+price|required|quote|verify/i.test(text)) return "not live-quoted yet";
  if (text.length > 42 || /compare|deals|available|search|find|book/i.test(text)) return "live price required";
  return text;
}

function CarRow({
  option,
  isRecommended,
  isSelected,
  onSelect,
  isSelecting,
  whyOpen,
  onToggleWhy,
}: {
  option: CarOption;
  isRecommended: boolean;
  isSelected: boolean;
  onSelect: () => void;
  isSelecting: boolean;
  whyOpen: boolean;
  onToggleWhy: () => void;
}) {
  const label = deriveRowLabel("", isRecommended, option.recommendation_grade);
  const pill = deriveLivePill(option);
  const fare = displayCarFare(option.current_price_signal || option.price_band);
  const seatsLabel = option.seating_capacity ? `${option.seating_capacity} seats` : "Verify seats";

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
            <Car className="h-4 w-4 text-foreground/60" />
            <span className="font-bold truncate">{option.vehicle_class}</span>
            <span className="text-xs text-muted-foreground ml-1 truncate">{option.booking_source}</span>
          </>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(340px,38%)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(180px,_auto)] gap-4 px-4 py-4 md:px-5 md:py-5">
        <CarImage option={option} />
        <div className="flex items-start gap-2">
          <Users className="h-5 w-5 text-foreground/50 mt-0.5" />
          <div>
            <div className="font-[Fredoka] text-2xl font-bold leading-none">{seatsLabel}</div>
            <div className="text-xs text-muted-foreground mt-1.5">{option.passenger_fit}</div>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <Luggage className="h-5 w-5 text-foreground/50 mt-0.5" />
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Luggage</div>
            <div className="text-sm text-foreground/85 mt-1">{option.luggage_fit}</div>
          </div>
        </div>
        <div className="md:text-right">
          <div className="font-[Fredoka] text-2xl font-bold leading-none break-words">{fare}</div>
          <div className="text-xs text-muted-foreground mt-1.5">{option.pickup_location}</div>
        </div>
      </div>

      <div className="px-5 pb-4 grid md:grid-cols-2 gap-4">
        <ul className="space-y-1.5 text-sm">
          {option.tradeoffs.slice(0, 3).map((t) => (
            <li key={t} className="flex items-start gap-2">
              <Check className="h-4 w-4 text-palm shrink-0 mt-0.5" />
              <span className="text-foreground/85">{t}</span>
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
          {isSelecting ? <Loader2 className="h-4 w-4 animate-spin" /> : isSelected ? <><Check className="h-4 w-4" /> Using this car</> : "Use this car"}
        </Button>
        {option.deep_link && (
          <a href={option.deep_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-bold text-foreground/80 hover:text-foreground">
            <ArrowRight className="h-4 w-4" /> Open listing
          </a>
        )}
        <SourcePill option={option} />
        {Object.entries(option.comparison_links ?? {}).slice(0, 2).map(([source, link]) => (
          <a key={source} href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground">
            <ExternalLink className="h-3.5 w-3.5" /> {source}
          </a>
        ))}
        <button type="button" onClick={onToggleWhy} className="ml-auto text-sm font-medium text-muted-foreground hover:text-foreground">
          {whyOpen ? "Hide details" : "Why not this?"}
        </button>
      </div>

      {whyOpen && (
        <div className="px-5 pb-5 pt-1 text-sm text-foreground/80 space-y-2 border-t border-foreground/10">
          {option.fees_caution && <p className="leading-snug">⚠ {option.fees_caution}</p>}
          {option.cancellation_notes && <p className="text-xs">Cancellation: {option.cancellation_notes}</p>}
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground pt-1">
            <span>Comfort {option.family_comfort_score}</span>
            <span>Pickup {option.pickup_dropoff_simplicity_score}</span>
            <span>Luggage {option.luggage_practicality_score}</span>
            <span>Parking {option.driving_parking_suitability_score}</span>
            {option.validation?.adapter_used && <span>Source: {option.validation.adapter_used}</span>}
          </div>
        </div>
      )}
    </article>
  );
}

function CarImage({ option }: { option: CarOption }) {
  const [imgFailed, setImgFailed] = useState(false);
  const imageUrl = option.photo_urls?.find((url) => url.startsWith("http"));
  if (!imageUrl || imgFailed) {
    return (
      <div className="h-72 lg:h-full min-h-72 rounded-2xl border-2 border-foreground/10 bg-muted/60 flex items-center justify-center text-muted-foreground">
        <Camera className="h-7 w-7" />
      </div>
    );
  }
  return (
    <div className="h-72 lg:h-full min-h-72 rounded-2xl overflow-hidden border-2 border-foreground/10 bg-muted">
      <img
        src={imageUrl}
        alt={option.vehicle_class}
        loading="lazy"
        className="h-full w-full object-cover"
        onError={() => setImgFailed(true)}
      />
    </div>
  );
}

function SourcePill({ option }: { option: CarOption }) {
  const source = option.validation?.source_name || option.booking_source;
  const adapter = option.validation?.adapter_used;
  const label = adapter ? `${source} · ${adapter}` : source;
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-foreground/15 bg-muted/50 px-2.5 py-1 text-xs font-bold text-foreground/70">
      From {label}
    </span>
  );
}

export default Cars;
