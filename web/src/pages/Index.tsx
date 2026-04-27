import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/AppShell";
import {
  Plus, MapPin, Calendar, Users, Plane, Hotel, Car, Sparkles,
  ArrowRight, Search, Lightbulb, Clock,
} from "lucide-react";

type TripStatus = "ideating" | "planning" | "booked" | "complete";

const trips: {
  id: string;
  title: string;
  dates: string;
  who: string;
  status: TripStatus;
  progress: number;
  legs: number;
  cover: string;
  emoji: string;
}[] = [
  {
    id: "1",
    title: "Costa Rica spring break",
    dates: "Mar 14 – 23, 2026",
    who: "Family of 4",
    status: "planning",
    progress: 62,
    legs: 3,
    cover: "linear-gradient(135deg, hsl(178 70% 45%), hsl(145 55% 38%))",
    emoji: "🌴",
  },
  {
    id: "2",
    title: "Tokyo + Kyoto loop",
    dates: "Oct 4 – 18, 2026",
    who: "Just us two",
    status: "ideating",
    progress: 18,
    legs: 2,
    cover: "linear-gradient(135deg, hsl(8 90% 65%), hsl(18 95% 55%))",
    emoji: "🗼",
  },
  {
    id: "3",
    title: "Iceland ring road",
    dates: "Jul 2 – 12, 2026",
    who: "Family of 4",
    status: "booked",
    progress: 92,
    legs: 6,
    cover: "linear-gradient(135deg, hsl(205 88% 48%), hsl(215 75% 28%))",
    emoji: "🧊",
  },
  {
    id: "4",
    title: "Lisbon + Algarve",
    dates: "May 22 – Jun 1, 2025",
    who: "Family of 4",
    status: "complete",
    progress: 100,
    legs: 4,
    cover: "linear-gradient(135deg, hsl(45 100% 60%), hsl(8 90% 65%))",
    emoji: "🐚",
  },
];

const statusStyles: Record<TripStatus, { label: string; cls: string }> = {
  ideating: { label: "Ideating", cls: "bg-sunshine/30 text-foreground" },
  planning: { label: "Planning", cls: "bg-coral/30 text-foreground" },
  booked: { label: "Booked", cls: "bg-palm/25 text-foreground" },
  complete: { label: "Complete", cls: "bg-muted text-muted-foreground" },
};

const Index = () => {
  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-6 py-10 md:py-12">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-10">
          <div>
            <p className="font-bold text-sm uppercase tracking-widest text-primary mb-2">
              Welcome back ✈️
            </p>
            <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-tight">
              Where to <span className="text-gradient-sunset">next</span>?
            </h1>
            <p className="text-muted-foreground mt-2 text-base">
              You have <span className="font-bold text-foreground">3 trips</span> in motion. One needs your eyes.
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

        {/* Spotlight card — needs attention */}
        <div className="relative mb-10 rounded-[2rem] overflow-hidden border-2 border-foreground shadow-sticker bg-gradient-hero p-7 md:p-9">
          <div className="grid md:grid-cols-[1fr_auto] gap-6 items-center">
            <div>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-coral/40 border-2 border-foreground/20 text-xs font-bold uppercase tracking-wider">
                <Lightbulb className="h-3.5 w-3.5" /> Needs you
              </span>
              <h2 className="font-[Fredoka] text-2xl md:text-3xl font-bold mt-3 leading-tight">
                Costa Rica: pick between Manuel Antonio and Tamarindo for leg 2.
              </h2>
              <p className="text-foreground/70 mt-2 max-w-xl">
                Hermes ranked both. Manuel Antonio fits your "less driving with kids" rule better, but Tamarindo has the surf lessons Maya asked for.
              </p>
            </div>
            <Button
              asChild
              className="h-12 rounded-2xl bg-foreground text-background font-bold px-6 shadow-card hover:translate-y-[-2px] transition-bounce"
            >
              <Link to="/new">
                Decide now <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>

        {/* Trips grid */}
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
          {trips.map((t, i) => {
            const s = statusStyles[t.status];
            return (
              <Link
                key={t.id}
                to="/new"
                className="group relative rounded-3xl overflow-hidden border-2 border-foreground/10 bg-card shadow-card hover:-translate-y-1 hover:shadow-glow transition-bounce animate-fade-up"
                style={{ animationDelay: `${i * 0.05}s` }}
              >
                {/* Cover */}
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
                    <span className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> {t.legs} legs</span>
                  </div>

                  {/* Progress */}
                  <div className="mt-4">
                    <div className="flex justify-between text-xs font-bold mb-1.5">
                      <span className="text-muted-foreground uppercase tracking-wider">Plan progress</span>
                      <span className="text-foreground">{t.progress}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full bg-gradient-sunset rounded-full transition-all"
                        style={{ width: `${t.progress}%` }}
                      />
                    </div>
                  </div>

                  {/* Booking pills */}
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
              Drop your goals or fill the form — Hermes takes it from there.
            </div>
          </Link>
        </div>

        {/* Recent activity */}
        <div className="mt-10 rounded-3xl border-2 border-foreground/10 bg-card p-6 shadow-card">
          <h3 className="font-[Fredoka] text-xl font-bold mb-4 flex items-center gap-2">
            <Clock className="h-5 w-5 text-primary" /> Recent activity
          </h3>
          <ul className="divide-y divide-foreground/10">
            {[
              { who: "Hermes", what: "Validated 4 hotels in Manuel Antonio", when: "2h ago" },
              { who: "You", what: "Locked KEF→RVK flight on Icelandair", when: "yesterday" },
              { who: "Hermes", what: "Flagged tight 50min layover in DFW", when: "2d ago" },
            ].map((a) => (
              <li key={a.what} className="py-3 flex items-center justify-between text-sm">
                <span><span className="font-bold">{a.who}</span> · {a.what}</span>
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
