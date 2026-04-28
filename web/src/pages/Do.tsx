import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { ShortlistHero } from "@/components/ShortlistHero";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { Button } from "@/components/ui/button";
import {
  Loader2, Sparkles, Check, ExternalLink, ArrowRight, RefreshCcw,
  AlertCircle, AlertTriangle, MapPin, Calendar, Clock,
} from "lucide-react";
import { api, type ActivityOption, type TripIntake } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import {
  Chip,
  LiveProvidersBanner,
  RowHeaderStrip,
  deriveLiveBanner,
  deriveLivePill,
  deriveRowLabel,
} from "@/components/ShortlistRow";

type SortKey = "best" | "rating" | "duration";

const Do = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("best");
  const [groupByDay, setGroupByDay] = useState(true);
  const [openWhyId, setOpenWhyId] = useState<string | null>(null);

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "activities", { validate_live: true, deep_research: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const selectMutation = useMutation({
    mutationFn: (id: string) => api.selectActivity(tripId!, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const trip = tripQuery.data;
  const shortlist = shortlistOptions(trip, "activities");
  const options: ActivityOption[] = shortlist?.activity_options ?? [];
  const stages = buildStages(trip, "do");
  const recommendedId = shortlist?.recommended_option_id;
  const flagCount = options.reduce((s, o) => s + o.friction_flags.length, 0);
  const hasSelection = options.some((o) => o.row_status === "approved");

  const banner = useMemo(
    () => deriveLiveBanner(shortlist?.warnings ?? [], options, "activities"),
    [shortlist?.warnings, options],
  );
  const sorted = useMemo(() => sortActivities(options, sortKey), [options, sortKey]);

  const groupedByDay = sorted.reduce<Record<string, ActivityOption[]>>((acc, opt) => {
    const day = opt.scheduled_day ?? opt.suggested_day;
    const key = day != null ? `Day ${day}` : "Unscheduled";
    if (!acc[key]) acc[key] = [];
    acc[key].push(opt);
    return acc;
  }, {});
  const dayKeys = Object.keys(groupedByDay).sort((a, b) => {
    if (a === "Unscheduled") return 1;
    if (b === "Unscheduled") return -1;
    return parseInt(a.replace("Day ", "")) - parseInt(b.replace("Day ", ""));
  });

  return (
    <AppShell>
      <ShortlistHero intake={trip?.intake} stageLabel="Do" stageNumber={6} flagCount={flagCount} />
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 6 · Activities
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">Pick what you'll do.</h2>
          </div>
          {options.length > 0 && (
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
            title="No activities yet"
            description="Hermes will research age-appropriate activities and tours, score for family fit and crowd risk, and propose a per-day schedule."
            ctaLabel="Build activity shortlist"
            onBuild={() => buildMutation.mutate()}
            isLoading={buildMutation.isPending}
            isError={buildMutation.isError}
            errorMessage={(buildMutation.error as Error)?.message}
          />
        )}

        {options.length > 0 && (
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="flex flex-wrap gap-2">
              <Chip>✦ Safety &gt; family pace &gt; price</Chip>
              <Chip>{partyChip(trip?.intake)}</Chip>
              <button
                onClick={() => setGroupByDay((v) => !v)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/10 text-xs font-bold text-foreground/80 hover:border-foreground/30"
              >
                {groupByDay ? "Grouped by day" : "Flat list"}
              </button>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Sort:</span>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className="h-9 rounded-xl border-2 border-foreground/15 bg-card px-3 font-bold text-sm focus:outline-none focus:border-foreground/40"
              >
                <option value="best">Best overall</option>
                <option value="rating">Rating</option>
                <option value="duration">Duration</option>
              </select>
            </div>
          </div>
        )}

        {options.length > 0 && (
          groupByDay ? (
            <div className="space-y-8">
              {dayKeys.map((dayKey) => (
                <div key={dayKey}>
                  <h3 className="font-[Fredoka] text-xl font-bold mb-3 flex items-center gap-2">
                    <Calendar className="h-5 w-5 text-primary" /> {dayKey}
                  </h3>
                  <div className="flex flex-col gap-4">
                    {groupedByDay[dayKey].map((o) => (
                      <ActivityRow
                        key={o.option_id}
                        option={o}
                        isRecommended={o.option_id === recommendedId}
                        isSelected={o.row_status === "approved"}
                        onSelect={() => selectMutation.mutate(o.option_id)}
                        isSelecting={selectMutation.isPending}
                        tripId={tripId!}
                        onScheduled={() => queryClient.invalidateQueries({ queryKey: ["trip", tripId] })}
                        whyOpen={openWhyId === o.option_id}
                        onToggleWhy={() => setOpenWhyId(openWhyId === o.option_id ? null : o.option_id)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {sorted.map((o) => (
                <ActivityRow
                  key={o.option_id}
                  option={o}
                  isRecommended={o.option_id === recommendedId}
                  isSelected={o.row_status === "approved"}
                  onSelect={() => selectMutation.mutate(o.option_id)}
                  isSelecting={selectMutation.isPending}
                  tripId={tripId!}
                  onScheduled={() => queryClient.invalidateQueries({ queryKey: ["trip", tripId] })}
                  whyOpen={openWhyId === o.option_id}
                  onToggleWhy={() => setOpenWhyId(openWhyId === o.option_id ? null : o.option_id)}
                />
              ))}
            </div>
          )
        )}

        <div className="mt-8 flex items-center justify-end gap-3">
          {!hasSelection && (
            <span className="text-sm text-muted-foreground">
              No activities selected — that's OK, you can still build the timeline.
            </span>
          )}
          <Button
            onClick={() => navigate(`/trip/${tripId}/timeline`)}
            className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
          >
            Continue to Timeline <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </AppShell>
  );
};

function partyChip(intake: TripIntake | undefined): string {
  if (!intake) return "Party";
  const total = intake.travelers || (intake.party.adults + intake.party.children);
  return `Party of ${total}`;
}

function sortActivities(options: ActivityOption[], key: SortKey): ActivityOption[] {
  const arr = [...options];
  if (key === "rating") {
    arr.sort((a, b) => extractRating(b.review_safety_signal) - extractRating(a.review_safety_signal));
  } else if (key === "duration") {
    arr.sort((a, b) => durationMinutes(a.duration) - durationMinutes(b.duration));
  } else {
    arr.sort((a, b) => a.rank - b.rank);
  }
  return arr;
}

function extractRating(value: string): number {
  const m = (value || "").match(/(\d+(?:\.\d+)?)\s*★/);
  return m ? parseFloat(m[1]) : 0;
}

function durationMinutes(value: string): number {
  const m = (value || "").match(/(\d+)\s*h(?:ours?)?/i);
  return m ? parseInt(m[1]) * 60 : Number.POSITIVE_INFINITY;
}

function ActivityRow({
  option,
  isRecommended,
  isSelected,
  onSelect,
  isSelecting,
  tripId,
  onScheduled,
  whyOpen,
  onToggleWhy,
}: {
  option: ActivityOption;
  isRecommended: boolean;
  isSelected: boolean;
  onSelect: () => void;
  isSelecting: boolean;
  tripId: string;
  onScheduled: () => void;
  whyOpen: boolean;
  onToggleWhy: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [day, setDay] = useState(String(option.scheduled_day ?? option.suggested_day ?? ""));
  const [start, setStart] = useState(option.scheduled_start_time || option.suggested_start_time);
  const [end, setEnd] = useState(option.scheduled_end_time || option.suggested_end_time);

  const scheduleMutation = useMutation({
    mutationFn: () =>
      api.scheduleActivity({
        trip_id: tripId,
        option_id: option.option_id,
        day: day ? parseInt(day) : undefined,
        start_time: start,
        end_time: end,
      }),
    onSuccess: () => {
      onScheduled();
      setEditing(false);
    },
  });

  const label = deriveRowLabel("", isRecommended, option.recommendation_grade);
  const pill = deriveLivePill(option);
  const scheduledDay = option.scheduled_day ?? option.suggested_day;
  const scheduledStart = option.scheduled_start_time || option.suggested_start_time;
  const scheduledEnd = option.scheduled_end_time || option.suggested_end_time;

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
            <Sparkles className="h-4 w-4 text-foreground/60" />
            <span className="font-bold truncate">{option.activity_name}</span>
          </>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-[1fr_minmax(220px,_auto)] gap-5 px-5 py-5">
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-sm font-medium text-foreground/85">
            <MapPin className="h-4 w-4 text-foreground/50" />
            {option.island_location}
          </div>
          <div className="flex flex-wrap gap-1.5 text-xs">
            {option.duration && (
              <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-bold">{option.duration}</span>
            )}
            {option.review_safety_signal && (
              <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">{option.review_safety_signal}</span>
            )}
            {option.age_family_fit && (
              <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">{option.age_family_fit}</span>
            )}
          </div>
        </div>
        <div className="md:text-right">
          <div className="font-[Fredoka] text-2xl font-bold leading-none break-words">{option.price_band || "—"}</div>
        </div>
      </div>

      {/* Schedule row */}
      <div className="px-5 pb-3">
        {editing ? (
          <div className="rounded-xl border-2 border-foreground/15 bg-muted/30 p-3 space-y-2">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <label className="flex flex-col">
                <span className="font-bold uppercase tracking-wider text-muted-foreground mb-1">Day</span>
                <input value={day} onChange={(e) => setDay(e.target.value)} placeholder="3" className="h-9 rounded-lg border border-foreground/15 bg-card px-2 font-medium focus:outline-none focus:border-primary" />
              </label>
              <label className="flex flex-col">
                <span className="font-bold uppercase tracking-wider text-muted-foreground mb-1">Start</span>
                <input value={start} onChange={(e) => setStart(e.target.value)} placeholder="09:00" className="h-9 rounded-lg border border-foreground/15 bg-card px-2 font-medium focus:outline-none focus:border-primary" />
              </label>
              <label className="flex flex-col">
                <span className="font-bold uppercase tracking-wider text-muted-foreground mb-1">End</span>
                <input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="12:00" className="h-9 rounded-lg border border-foreground/15 bg-card px-2 font-medium focus:outline-none focus:border-primary" />
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditing(false)} className="text-xs font-bold text-muted-foreground hover:text-foreground">Cancel</button>
              <Button onClick={() => scheduleMutation.mutate()} disabled={scheduleMutation.isPending} className="h-8 rounded-lg bg-foreground text-background font-bold px-3 text-xs">
                {scheduleMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save schedule"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-xs text-foreground/80 font-medium">
            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
            <span>
              {scheduledDay != null ? `Day ${scheduledDay}` : "Not scheduled"}
              {scheduledStart && ` · ${scheduledStart}–${scheduledEnd}`}
            </span>
            <button onClick={() => setEditing(true)} className="ml-auto text-xs font-bold text-primary hover:underline">Edit</button>
          </div>
        )}
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
          {isSelecting ? <Loader2 className="h-4 w-4 animate-spin" /> : isSelected ? <><Check className="h-4 w-4" /> Selected</> : "Select"}
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
          {option.group_size_signal && <p className="leading-snug">Group size: {option.group_size_signal}</p>}
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground pt-1">
            <span>Pace {option.family_pace_fit_score}</span>
            <span>Safety {option.safety_confidence_score}</span>
            <span>Crowd {option.crowd_fit_score}</span>
            <span>Friction {option.total_friction_score}</span>
            {option.validation?.adapter_used && <span>Source: {option.validation.adapter_used}</span>}
          </div>
        </div>
      )}
    </article>
  );
}

export default Do;
