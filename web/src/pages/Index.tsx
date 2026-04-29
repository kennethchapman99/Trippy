import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/AppShell";
import {
  Plus, MapPin, Calendar, Users, Plane, Hotel, Car, Sparkles,
  ArrowRight, Search, Lightbulb, Clock, Loader2, AlertCircle,
} from "lucide-react";
import { api, type DashboardTripTile, type RunLogEvent } from "@/lib/api";
import { useDestinationImage } from "@/lib/destinationImages";

type UIStatus = "ideating" | "planning" | "booked" | "complete";

function toUIStatus(status: string): UIStatus {
  if (status === "lived") return "complete";
  if (status === "booked") return "booked";
  if (status === "planned") return "planning";
  return "ideating";
}

const COVER_GRADIENTS = [
  "linear-gradient(135deg, hsl(178 70% 45%), hsl(145 55% 38%))",
  "linear-gradient(135deg, hsl(8 90% 65%), hsl(18 95% 55%))",
  "linear-gradient(135deg, hsl(205 88% 48%), hsl(215 75% 28%))",
  "linear-gradient(135deg, hsl(45 100% 60%), hsl(8 90% 65%))",
  "linear-gradient(135deg, hsl(270 70% 60%), hsl(215 75% 28%))",
];

const statusStyles: Record<UIStatus, { label: string; cls: string }> = {
  ideating: { label: "Ideating", cls: "bg-sunshine/30 text-foreground" },
  planning: { label: "Planning", cls: "bg-coral/30 text-foreground" },
  booked: { label: "Booked", cls: "bg-palm/25 text-foreground" },
  complete: { label: "Complete", cls: "bg-muted text-muted-foreground" },
};

function relativeTime(isoString: string): string {
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return "recently";
  const diffMs = Date.now() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 2) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString();
}

function actorFor(event: RunLogEvent): string {
  if (event.event_type === "user_feedback") return "You";
  return "Trippy";
}

function TripTile({ trip: t, index: i, cover }: { trip: DashboardTripTile; index: number; cover: string }) {
  const uiStatus = toUIStatus(t.status);
  const s = statusStyles[uiStatus];
  const imageUrl = useDestinationImage({ destination: t.destination, title: t.name });
  const [imgFailed, setImgFailed] = useState(false);

  return (
    <Link
      to={`/trip/${t.trip_id}/shape`}
      className="group relative rounded-3xl overflow-hidden border-2 border-foreground/10 bg-card shadow-card hover:-translate-y-1 hover:shadow-glow transition-bounce animate-fade-up"
      style={{ animationDelay: `${i * 0.05}s` }}
    >
      {/* Cover */}
      <div className="relative h-32 overflow-hidden" style={{ background: cover }}>
        {imageUrl && !imgFailed && (
          <img
            src={imageUrl}
            alt={t.destination || t.name}
            loading="lazy"
            onError={() => setImgFailed(true)}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-transparent pointer-events-none" />
        <span className={`absolute top-3 right-3 px-3 py-1 rounded-full text-xs font-bold border-2 border-foreground/20 ${s.cls} backdrop-blur`}>
          {s.label}
        </span>
      </div>

      <div className="p-5">
        <h3 className="font-[Fredoka] text-xl font-bold leading-tight">{t.name}</h3>
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-muted-foreground font-semibold">
          {t.date_label && (
            <span className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5" /> {t.date_label}
            </span>
          )}
          {t.traveler_summary && (
            <span className="flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5" /> {t.traveler_summary}
            </span>
          )}
          {t.destination && (
            <span className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5" /> {t.destination}
            </span>
          )}
        </div>

        {/* Progress */}
        <div className="mt-4">
          <div className="flex justify-between text-xs font-bold mb-1.5">
            <span className="text-muted-foreground uppercase tracking-wider">Plan progress</span>
            <span className="text-foreground">{t.planning_completeness}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full bg-gradient-sunset rounded-full transition-all"
              style={{ width: `${t.planning_completeness}%` }}
            />
          </div>
        </div>

        {/* Booking pills */}
        <div className="flex gap-2 mt-4">
          {[
            { Icon: Plane, on: t.planning_completeness > 25 },
            { Icon: Hotel, on: t.planning_completeness > 50 },
            { Icon: Car, on: t.planning_completeness > 70 },
            { Icon: Sparkles, on: t.planning_completeness > 85 },
          ].map((p, idx) => (
            <div
              key={idx}
              className={`h-8 w-8 rounded-xl flex items-center justify-center border-2 ${
                p.on
                  ? "bg-palm/20 border-palm/40 text-foreground"
                  : "bg-muted border-foreground/10 text-muted-foreground/50"
              }`}
            >
              <p.Icon className="h-4 w-4" />
            </div>
          ))}
        </div>
      </div>
    </Link>
  );
}

const Index = () => {
  const { data, isLoading, error } = useQuery({
    queryKey: ["app-state"],
    queryFn: api.getState,
    staleTime: 30_000,
  });

  const allTrips: DashboardTripTile[] = data
    ? [...(data.dashboard.planned_trips ?? []), ...(data.dashboard.past_trips ?? [])]
    : [];

  const spotlight = data?.suggested_trip_id
    ? allTrips.find((t) => t.trip_id === data.suggested_trip_id) ?? allTrips[0]
    : allTrips[0];

  const activityLog: RunLogEvent[] = data?.run_log?.slice(-5).reverse() ?? [];

  const activeCount = (data?.dashboard.planned_trips ?? []).length;

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-6 py-10 md:py-12">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-10">
          <div>
            <p className="font-bold text-sm uppercase tracking-widest text-primary mb-2 flex items-center gap-1.5">
              <Plane className="h-4 w-4" /> Welcome back
            </p>
            <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-tight">
              Where to <span className="text-gradient-sunset">next</span>?
            </h1>
            <p className="text-muted-foreground mt-2 text-base">
              {isLoading ? (
                "Loading your trips…"
              ) : error ? (
                "Couldn't reach Trippy backend."
              ) : activeCount > 0 ? (
                <>
                  You have{" "}
                  <span className="font-bold text-foreground">{activeCount} trip{activeCount !== 1 ? "s" : ""}</span>{" "}
                  in motion.
                </>
              ) : (
                "No trips yet — start one below."
              )}
            </p>
          </div>
          <div className="flex gap-3">
            <div className="relative">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                placeholder="Search trips…"
                className="h-12 w-full md:w-64 rounded-2xl border-2 border-foreground/10 bg-card pl-10 pr-4 font-medium focus:outline-none focus:border-primary transition-colors"
              />
            </div>
            <Button
              asChild
              className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-5"
            >
              <Link to="/new">
                <Plus className="h-5 w-5" /> New trip
              </Link>
            </Button>
          </div>
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center justify-center py-24 text-muted-foreground gap-3">
            <Loader2 className="h-6 w-6 animate-spin" />
            <span className="font-bold">Connecting to Trippy…</span>
          </div>
        )}

        {/* Error state */}
        {error && !isLoading && (
          <div className="rounded-3xl border-2 border-destructive/30 bg-destructive/5 p-8 mb-8 flex items-start gap-4">
            <AlertCircle className="h-6 w-6 text-destructive shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-destructive">Backend not reachable</div>
              <div className="text-sm text-muted-foreground mt-1">
                Make sure the Trippy server is running:{" "}
                <code className="font-mono bg-muted px-1 rounded">uv run python -m trippy.ui.server --port 8788</code>
              </div>
            </div>
          </div>
        )}

        {/* Spotlight card */}
        {spotlight && !isLoading && !error && (
          <div className="relative mb-10 rounded-[2rem] overflow-hidden border-2 border-foreground shadow-sticker bg-gradient-hero p-7 md:p-9">
            <div className="grid md:grid-cols-[1fr_auto] gap-6 items-center">
              <div>
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-coral/40 border-2 border-foreground/20 text-xs font-bold uppercase tracking-wider">
                  <Lightbulb className="h-3.5 w-3.5" /> Needs you
                </span>
                <h2 className="font-[Fredoka] text-2xl md:text-3xl font-bold mt-3 leading-tight">
                  {spotlight.name}: {spotlight.hero_label || spotlight.next_actions[0] || "Continue planning."}
                </h2>
                <p className="text-foreground/70 mt-2 max-w-xl">
                  {spotlight.key_risks[0] ?? spotlight.destination}
                </p>
              </div>
              <Button
                asChild
                className="h-12 rounded-2xl bg-foreground text-background font-bold px-6 shadow-card hover:translate-y-[-2px] transition-bounce"
              >
                <Link to={`/trip/${spotlight.trip_id}/shape`}>
                  Continue <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </div>
          </div>
        )}

        {/* Trips grid */}
        {!isLoading && !error && (
          <>
            <div className="flex items-center justify-between mb-5">
              <h2 className="font-[Fredoka] text-2xl font-bold">Your trips</h2>
              <div className="flex gap-2 text-sm font-bold">
                {["All", "Active", "Booked", "Past"].map((t, i) => (
                  <button
                    key={t}
                    className={`px-3 py-1.5 rounded-full border-2 transition-bounce ${
                      i === 0
                        ? "bg-foreground text-background border-foreground"
                        : "border-foreground/15 text-muted-foreground hover:border-foreground/40"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-5">
              {allTrips.map((t, i) => {
                const cover = COVER_GRADIENTS[i % COVER_GRADIENTS.length];
                return <TripTile key={t.trip_id} trip={t} index={i} cover={cover} />;
              })}

              {/* New trip card */}
              <Link
                to="/new"
                className="group rounded-3xl border-2 border-dashed border-foreground/25 hover:border-primary bg-muted/30 hover:bg-card flex flex-col items-center justify-center text-center p-10 min-h-[280px] transition-bounce"
              >
                <div className="h-16 w-16 rounded-2xl bg-gradient-sunset border-2 border-foreground shadow-sticker flex items-center justify-center group-hover:rotate-6 transition-bounce">
                  <Plus className="h-8 w-8 text-primary-foreground" />
                </div>
                <div className="font-[Fredoka] text-xl font-bold mt-4">Start a new trip</div>
                <div className="text-sm text-muted-foreground mt-1 max-w-xs">
                  Drop your goals or fill the form. Trippy takes it from there.
                </div>
              </Link>
            </div>
          </>
        )}

        {/* Recent activity */}
        {!isLoading && !error && (
          <div className="mt-10 rounded-3xl border-2 border-foreground/10 bg-card p-6 shadow-card">
            <h3 className="font-[Fredoka] text-xl font-bold mb-4 flex items-center gap-2">
              <Clock className="h-5 w-5 text-primary" /> Recent activity
            </h3>
            {activityLog.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2">No activity yet. Start planning a trip!</p>
            ) : (
              <ul className="divide-y divide-foreground/10">
                {activityLog.map((a) => (
                  <li key={a.event_id} className="py-3 flex items-center justify-between text-sm">
                    <span>
                      <span className="font-bold">{actorFor(a)}</span> · {a.summary || a.title}
                    </span>
                    <span className="text-muted-foreground font-semibold shrink-0 ml-4">
                      {relativeTime(a.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
};

export default Index;
