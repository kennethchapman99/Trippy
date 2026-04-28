import { useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav, type Stage } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import { trippyClient } from "@/api/trippyClient";
import {
  AlertTriangle, ArrowLeft, Check, Loader2, RefreshCcw, Sparkles, ArrowRight,
} from "lucide-react";

const stages: Stage[] = [
  { id: 1, label: "Intake", status: "done" },
  { id: 2, label: "Shape", status: "current" },
  { id: 3, label: "Flights", status: "todo" },
  { id: 4, label: "Stays", status: "todo" },
  { id: 5, label: "Cars", status: "todo" },
  { id: 6, label: "Do", status: "todo" },
  { id: 7, label: "Timeline", status: "todo" },
  { id: 8, label: "Packet", status: "todo" },
];

type PlanOption = Record<string, unknown> & {
  option_id?: string;
  title?: string;
  name?: string;
  summary?: string;
  route_summary?: string;
  recommended?: boolean;
  strengths?: string[];
  risks?: string[];
  friction_flags?: string[];
  estimated_comfort_score?: number;
  comfort_score?: number;
  fit_score?: number;
  segments?: Array<Record<string, unknown>>;
};

const TripShape = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const tripId = new URLSearchParams(location.search).get("trip_id") || "";

  const tripQuery = useQuery({
    queryKey: ["trippy", "trip", tripId],
    queryFn: () => trippyClient.getTrip(tripId),
    enabled: Boolean(tripId),
  });

  const draftMutation = useMutation({
    mutationFn: () => trippyClient.draftPlan(tripId),
    onSuccess: () => tripQuery.refetch(),
  });

  const options = useMemo(() => {
    const draft = tripQuery.data?.draft as { options?: PlanOption[]; recommended_option_id?: string; selected_option_id?: string } | null | undefined;
    return draft?.options ?? [];
  }, [tripQuery.data]);

  const selectedId = useMemo(() => {
    const draft = tripQuery.data?.draft as { recommended_option_id?: string; selected_option_id?: string } | null | undefined;
    return draft?.selected_option_id || draft?.recommended_option_id || options[0]?.option_id || "";
  }, [options, tripQuery.data]);

  const intake = tripQuery.data?.intake;
  const title = intake?.trip_name || tripId || "Trip shape";
  const destination = intake?.destination_seeds?.join(", ") || "Destination TBD";
  const travelers = intake?.party?.total_travelers || intake?.travelers || "?";

  return (
    <AppShell>
      <div className="bg-gradient-hero border-b-2 border-foreground/10 px-6 md:px-10 pt-8 pb-10 relative">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground/70 hover:text-foreground transition-colors mb-4">
          <ArrowLeft className="h-4 w-4" /> Back to trips
        </Link>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="px-3 py-1 rounded-full bg-card border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
            Planning · Stage 2 of 8
          </span>
          <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">
            {intake?.duration_label || `${intake?.duration_days ?? "?"} days`}
          </span>
          <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">
            {travelers} traveler(s)
          </span>
          <div className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker">
            <AlertTriangle className="h-4 w-4 text-sunshine" />
            <div className="text-xs leading-tight">
              <div className="font-bold">Live backend</div>
              <div className="opacity-70">Trippy state</div>
            </div>
          </div>
        </div>
        <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">
          {title}
        </h1>
        <p className="text-foreground/70 italic mt-2 font-medium">{destination}</p>
      </div>

      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">Stage 2 · Trip shape</div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">Pick the rhythm of the trip.</h2>
            <p className="text-muted-foreground mt-1 max-w-2xl">
              These options come from Trippy's backend draft plan. If none exist yet, generate them here.
            </p>
          </div>
          <Button
            onClick={() => draftMutation.mutate()}
            disabled={!tripId || draftMutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors text-foreground"
          >
            {draftMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            Refresh from backend
          </Button>
        </div>

        {!tripId && <EmptyState message="No trip_id was provided. Open a trip from the dashboard or create one from New Trip." />}
        {tripQuery.isLoading && <EmptyState message="Loading trip shape from Trippy…" />}
        {tripQuery.error && <EmptyState message={`Backend error: ${tripQuery.error.message}`} />}
        {!tripQuery.isLoading && tripId && options.length === 0 && (
          <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-8">
            <h3 className="font-[Fredoka] text-2xl font-bold">No plan draft yet</h3>
            <p className="text-muted-foreground mt-2">Generate backend trip-shape options, then choose one before moving to timeline.</p>
            <Button onClick={() => draftMutation.mutate()} disabled={draftMutation.isPending} className="mt-5 h-11 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-card px-5">
              {draftMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Generate trip shape
            </Button>
          </div>
        )}

        <div className="grid lg:grid-cols-3 gap-5">
          {options.map((option, index) => {
            const optionId = String(option.option_id || `option-${index}`);
            const selected = optionId === selectedId;
            const strengths = option.strengths ?? [];
            const risks = option.risks ?? option.friction_flags ?? [];
            const score = Number(option.estimated_comfort_score ?? option.comfort_score ?? option.fit_score ?? 70);
            return (
              <article key={optionId} className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce flex flex-col ${selected ? "border-foreground shadow-sticker -translate-y-1" : "border-foreground/10 shadow-card hover:-translate-y-0.5"}`}>
                <div className="relative px-5 pt-5">
                  <div className="flex flex-wrap items-center gap-1.5 mb-3">
                    <span className="px-2.5 py-1 rounded-full text-xs font-bold border-2 border-foreground/20 bg-sunshine/40">Option {index + 1}</span>
                    {selected && <span className="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-foreground text-background text-[10px] font-bold uppercase tracking-wider"><Sparkles className="h-3 w-3" /> Current pick</span>}
                  </div>
                  <div className="relative h-2.5 rounded-full bg-muted border-2 border-foreground/10 overflow-hidden">
                    <div className="h-full bg-gradient-sunset" style={{ width: `${Math.max(10, Math.min(100, score))}%` }} />
                  </div>
                </div>
                <div className="p-5 pt-4 flex-1 flex flex-col">
                  <h3 className="font-[Fredoka] text-xl font-bold leading-tight">{String(option.title || option.name || optionId)}</h3>
                  <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{String(option.summary || option.route_summary || "Backend-generated trip-shape option")}</p>
                  <ul className="mt-4 space-y-1.5">
                    {strengths.slice(0, 4).map((item) => <li key={item} className="flex items-start gap-2 text-sm"><Check className="h-4 w-4 text-palm shrink-0 mt-0.5" /><span>{item}</span></li>)}
                  </ul>
                  {risks.length > 0 && <div className="mt-3 rounded-xl border-2 border-coral/40 bg-coral/10 p-3 text-xs font-semibold"><AlertTriangle className="h-3.5 w-3.5 text-primary inline mr-1" />{risks.slice(0, 2).join(" · ")}</div>}
                  <div className="flex items-center gap-2 mt-5 pt-4 border-t-2 border-foreground/10">
                    <Button onClick={() => navigate(`/trip/timeline?trip_id=${encodeURIComponent(tripId)}`)} className="flex-1 h-10 rounded-xl font-bold border-2 bg-foreground text-background border-foreground/20 hover:border-foreground/50">
                      Continue <ArrowRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
};

const EmptyState = ({ message }: { message: string }) => (
  <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-8 text-muted-foreground font-semibold">{message}</div>
);

export default TripShape;
