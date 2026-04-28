import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/AppShell";
import { trippyClient } from "@/api/trippyClient";
import { appStateToTripCards, runLogToActivity } from "@/lib/trippyViewModels";
import type { TripStatus } from "@/types/trippy";
import {
  Plus, MapPin, Calendar, Users, Plane, Hotel, Car, Sparkles,
  ArrowRight, Search, Lightbulb, Clock, RefreshCw,
} from "lucide-react";

const statusStyles: Record<TripStatus, { label: string; cls: string }> = {
  ideating: { label: "Ideating", cls: "bg-sunshine/30 text-foreground" },
  planning: { label: "Planning", cls: "bg-coral/30 text-foreground" },
  booked: { label: "Booked", cls: "bg-palm/25 text-foreground" },
  complete: { label: "Complete", cls: "bg-muted text-muted-foreground" },
};

const Index = () => {
  const [query, setQuery] = useState("");
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["trippy", "app-state"],
    queryFn: trippyClient.getAppState,
  });

  const trips = useMemo(() => appStateToTripCards(data), [data]);
  const filteredTrips = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return trips;
    return trips.filter((trip) =>
      [trip.title, trip.destination, trip.who, trip.status].some((value) =>
        value.toLowerCase().includes(term),
      ),
    );
  }, [query, trips]);
  const activity = useMemo(() => runLogToActivity(data?.run_log), [data]);
  const spotlightTrip = filteredTrips[0];
  const activeCount = trips.filter((trip) => trip.status !== "complete").length;

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-6 py-10 md:py-12">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-10">
          <div>
            <p className="font-bold text-sm uppercase tracking-widest text-primary mb-2">
              Live Trippy backend ✈️
            </p>
            <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-tight">
              Where to <span className="text-gradient-sunset">next</span>?
            </h1>
            <p className="text-muted-foreground mt-2 text-base">
              {isLoading ? (
                "Loading trips from Trippy…"
              ) : error ? (
                "Backend not reachable. Start: uv run trippy ui --port 8788 --no-open"
              ) : (
                <>You have <span className="font-bold text-foreground">{activeCount}</span> active trip(s) in Trippy.</>
              )}
            </p>
          </div>
          <div className="flex gap-3">
            <div className="relative">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search trips…"
                className="h-12 w-full md:w-64 rounded-2xl border-2 border-foreground/10 bg-card pl-10 pr-4 font-medium focus:outline-none focus:border-primary transition-colors"
              />
            </div>
            <Button
              onClick={() => refetch()}
              variant="outline"
              className="h-12 rounded-2xl font-bold border-2 border-foreground/20 px-4"
            >
              <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            </Button>
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

        <div className="relative mb-10 rounded-[2rem] overflow-hidden border-2 border-foreground shadow-sticker bg-gradient-hero p-7 md:p-9">
          <div className="grid md:grid-cols-[1fr_auto] gap-6 items-center">
            <div>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-coral/40 border-2 border-foreground/20 text-xs font-bold uppercase tracking-wider">
                <Lightbulb className="h-3.5 w-3.5" /> Next best action
              </span>
              <h2 className="font-[Fredoka] text-2xl md:text-3xl font-bold mt-3 leading-tight">
                {spotlightTrip ? `${spotlightTrip.title}: continue planning` : "Start by creating or generating a trip"}
              </h2>
              <p className="text-foreground/70 mt-2 max-w-xl">
                {spotlightTrip?.nextStep || "Canvas is now reading the Trippy backend. Generate ideas or select an existing trip to keep moving."}
              </p>
            </div>
            <Button
              asChild
              className="h-12 rounded-2xl bg-foreground text-background font-bold px-6 shadow-card hover:translate-y-[-2px] transition-bounce"
            >
              <Link to={spotlightTrip ? `/trip/shape?trip_id=${encodeURIComponent(spotlightTrip.id)}` : "/new"}>
                {spotlightTrip ? "Open trip" : "Generate ideas"} <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>

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
          {filteredTrips.map((t, i) => {
            const s = statusStyles[t.status];
            return (
              <Link
                key={t.id}
                to={`/trip/shape?trip_id=${encodeURIComponent(t.id)}`}
                className="group relative rounded-3xl overflow-hidden border-2 border-foreground/10 bg-card shadow-card hover:-translate-y-1 hover:shadow-glow transition-bounce animate-fade-up"
                style={{ animationDelay: `${i * 0.05}s` }}
              >
                <div className="relative h-32" style={{ background: t.cover }}>
                  <span className="absolute top-3 left-3 text-4xl drop-shadow-md">{t.emoji}</span>
                  <span className={`absolute top-3 right-3 px-3 py-1 rounded-full text-xs font-bold border-2 border-foreground/20 ${s.cls} backdrop-blur`}>
                    {s.label}
                  </span>
                </div>

                <div className="p-5">
                  <h3 className="font-[Fredoka] text-xl font-bold leading-tight">{t.title}</h3>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-muted-foreground font-semibold">
                    <span className="flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" /> {t.dates}</span>
                    <span className="flex items-center gap-1.5"><Users className="h-3.5 w-3.5" /> {t.who}</span>
                    <span className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> {t.legs} leg(s)</span>
                  </div>

                  <div className="mt-4">
                    <div className="flex justify-between text-xs font-bold mb-1.5">
                      <span className="text-muted-foreground uppercase tracking-wider">Plan progress</span>
                      <span className="text-foreground">{t.progress}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-gradient-sunset rounded-full transition-all" style={{ width: `${t.progress}%` }} />
                    </div>
                  </div>

                  <div className="flex gap-2 mt-4">
                    {[
                      { i: Plane, on: t.progress > 30 },
                      { i: Hotel, on: t.progress > 50 },
                      { i: Car, on: t.progress > 70 },
                      { i: Sparkles, on: t.progress > 85 },
                    ].map((p, idx) => (
                      <div
                        key={idx}
                        className={`h-8 w-8 rounded-xl flex items-center justify-center border-2 ${
                          p.on
                            ? "bg-palm/20 border-palm/40 text-foreground"
                            : "bg-muted border-foreground/10 text-muted-foreground/50"
                        }`}
                      >
                        <p.i className="h-4 w-4" />
                      </div>
                    ))}
                  </div>
                </div>
              </Link>
            );
          })}

          <Link
            to="/new"
            className="group rounded-3xl border-2 border-dashed border-foreground/25 hover:border-primary bg-muted/30 hover:bg-card flex flex-col items-center justify-center text-center p-10 min-h-[280px] transition-bounce"
          >
            <div className="h-16 w-16 rounded-2xl bg-gradient-sunset border-2 border-foreground shadow-sticker flex items-center justify-center group-hover:rotate-6 transition-bounce">
              <Plus className="h-8 w-8 text-primary-foreground" />
            </div>
            <div className="font-[Fredoka] text-xl font-bold mt-4">Start a new trip</div>
            <div className="text-sm text-muted-foreground mt-1 max-w-xs">
              Drop your goals or fill the form — Trippy takes it from there.
            </div>
          </Link>
        </div>

        <div className="mt-10 rounded-3xl border-2 border-foreground/10 bg-card p-6 shadow-card">
          <h3 className="font-[Fredoka] text-xl font-bold mb-4 flex items-center gap-2">
            <Clock className="h-5 w-5 text-primary" /> Recent backend activity
          </h3>
          <ul className="divide-y divide-foreground/10">
            {(activity.length ? activity : [{ actor: "Trippy", summary: "No backend activity yet", when: "now" }]).map((a) => (
              <li key={`${a.actor}-${a.summary}-${a.when}`} className="py-3 flex items-center justify-between text-sm">
                <span><span className="font-bold">{a.actor}</span> · {a.summary}</span>
                <span className="text-muted-foreground font-semibold">{a.when}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </AppShell>
  );
};

export default Index;
