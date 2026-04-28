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
  Loader2, Sparkles, Check, ExternalLink, ArrowRight, RefreshCcw,
  AlertCircle, MapPin, Calendar, Clock,
} from "lucide-react";
import { api, type ActivityOption } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";

const Do = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildShortlist(tripId!, "activities"),
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

  // Group activities by suggested day
  const groupedByDay = options.reduce<Record<string, ActivityOption[]>>((acc, opt) => {
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
      <ShortlistHero
        intake={trip?.intake}
        stageLabel="Do"
        stageNumber={6}
        flagCount={flagCount}
      />
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 6 · Activities
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Pick what you'll do.
            </h2>
            {shortlist?.recommendation_summary && (
              <p className="text-muted-foreground mt-1 max-w-2xl">{shortlist.recommendation_summary}</p>
            )}
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

        {tripQuery.isLoading && (
          <div className="flex items-center justify-center py-24 text-muted-foreground gap-3">
            <Loader2 className="h-6 w-6 animate-spin" />
            <span className="font-bold">Loading…</span>
          </div>
        )}

        {tripQuery.isError && (
          <div className="rounded-3xl border-2 border-destructive/30 bg-destructive/5 p-6 flex items-start gap-4 mb-6">
            <AlertCircle className="h-6 w-6 text-destructive shrink-0 mt-0.5" />
            <div className="text-sm text-muted-foreground">
              {(tripQuery.error as Error)?.message}
            </div>
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
          <div className="space-y-8">
            {dayKeys.map((dayKey) => (
              <div key={dayKey}>
                <h3 className="font-[Fredoka] text-xl font-bold mb-3 flex items-center gap-2">
                  <Calendar className="h-5 w-5 text-primary" /> {dayKey}
                </h3>
                <div className="grid lg:grid-cols-2 gap-5">
                  {groupedByDay[dayKey].map((o) => (
                    <ActivityCard
                      key={o.option_id}
                      option={o}
                      isRecommended={o.option_id === recommendedId}
                      isSelected={o.row_status === "approved"}
                      onSelect={() => selectMutation.mutate(o.option_id)}
                      isSelecting={selectMutation.isPending}
                      tripId={tripId!}
                      onScheduled={() => queryClient.invalidateQueries({ queryKey: ["trip", tripId] })}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {hasSelection && (
          <div className="mt-8 flex justify-end">
            <Button
              onClick={() => navigate(`/trip/${tripId}/timeline`)}
              className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
            >
              Continue to Timeline <ArrowRight className="h-4 w-4" />
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

function ActivityCard({
  option, isRecommended, isSelected, onSelect, isSelecting, tripId, onScheduled,
}: {
  option: ActivityOption;
  isRecommended: boolean;
  isSelected: boolean;
  onSelect: () => void;
  isSelecting: boolean;
  tripId: string;
  onScheduled: () => void;
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
            <Sparkles className="h-5 w-5 text-secondary" />
            <span className="font-[Fredoka] text-xl font-bold leading-tight">{option.activity_name}</span>
          </div>
          <div className="text-xs text-muted-foreground font-semibold mt-1 flex items-center gap-1">
            <MapPin className="h-3 w-3" /> {option.island_location}
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

      <div className="px-5 pt-3 flex flex-wrap gap-1.5 text-xs">
        <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-bold">
          {option.duration || "duration unknown"}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-sunshine/30 border border-foreground/10 font-bold">
          {option.price_band}
        </span>
        {option.age_family_fit && (
          <span className="px-2 py-0.5 rounded-full bg-card border border-foreground/15 font-medium">{option.age_family_fit}</span>
        )}
      </div>

      {/* Schedule */}
      <div className="px-5 pt-3">
        {editing ? (
          <div className="rounded-xl border-2 border-foreground/15 bg-muted/30 p-3 space-y-2">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <label className="flex flex-col">
                <span className="font-bold uppercase tracking-wider text-muted-foreground mb-1">Day</span>
                <input
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                  placeholder="3"
                  className="h-9 rounded-lg border border-foreground/15 bg-card px-2 font-medium focus:outline-none focus:border-primary"
                />
              </label>
              <label className="flex flex-col">
                <span className="font-bold uppercase tracking-wider text-muted-foreground mb-1">Start</span>
                <input
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  placeholder="09:00"
                  className="h-9 rounded-lg border border-foreground/15 bg-card px-2 font-medium focus:outline-none focus:border-primary"
                />
              </label>
              <label className="flex flex-col">
                <span className="font-bold uppercase tracking-wider text-muted-foreground mb-1">End</span>
                <input
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  placeholder="12:00"
                  className="h-9 rounded-lg border border-foreground/15 bg-card px-2 font-medium focus:outline-none focus:border-primary"
                />
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditing(false)} className="text-xs font-bold text-muted-foreground hover:text-foreground">
                Cancel
              </button>
              <Button
                onClick={() => scheduleMutation.mutate()}
                disabled={scheduleMutation.isPending}
                className="h-8 rounded-lg bg-foreground text-background font-bold px-3 text-xs"
              >
                {scheduleMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save schedule"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-xs text-foreground/80 font-medium">
            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
            <span>
              {option.scheduled_day || option.suggested_day
                ? `Day ${option.scheduled_day ?? option.suggested_day}`
                : "Not scheduled"}
              {(option.scheduled_start_time || option.suggested_start_time) &&
                ` · ${option.scheduled_start_time || option.suggested_start_time}–${option.scheduled_end_time || option.suggested_end_time}`}
            </span>
            <button onClick={() => setEditing(true)} className="ml-auto text-xs font-bold text-primary hover:underline">
              Edit
            </button>
          </div>
        )}
      </div>

      <div className="px-5 pt-3 grid grid-cols-3 gap-2">
        <ScoreBar label="Pace" value={option.family_pace_fit_score} color="hsl(18 95% 55%)" />
        <ScoreBar label="Safety" value={option.safety_confidence_score} color="hsl(145 55% 38%)" />
        <ScoreBar label="Crowd" value={option.crowd_fit_score} color="hsl(195 90% 55%)" />
      </div>

      {option.tradeoffs.length > 0 && (
        <ul className="px-5 pt-3 space-y-1">
          {option.tradeoffs.slice(0, 2).map((t) => (
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
      <div className="h-1.5 rounded-full bg-muted border border-foreground/10 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value}%`, background: color }} />
      </div>
    </div>
  );
}

export default Do;
