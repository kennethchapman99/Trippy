import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav, type Stage } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import { trippyClient } from "@/api/trippyClient";
import {
  AlertTriangle, ArrowLeft, Plane, Sun, Sparkles, Fish, UtensilsCrossed,
  Coffee, RefreshCcw, MapPin, Clock,
} from "lucide-react";

const stages: Stage[] = [
  { id: 1, label: "Intake", status: "done" },
  { id: 2, label: "Shape", status: "done" },
  { id: 3, label: "Flights", status: "done" },
  { id: 4, label: "Stays", status: "done" },
  { id: 5, label: "Cars", status: "done" },
  { id: 6, label: "Do", status: "done" },
  { id: 7, label: "Timeline", status: "current" },
  { id: 8, label: "Packet", status: "todo" },
];

type Block = {
  start: string;
  end: string;
  title: string;
  detail?: string;
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  tone: "travel" | "relax" | "hero" | "snorkel" | "food";
  tags: { label: string; tone?: "travel" | "place" }[];
  flag?: string;
};

type Day = {
  n: number;
  weekday: string;
  date: string;
  vibe: string;
  load: "Full day" | "Easy" | "Half" | "Open";
  blocks: Block[];
};

const toneStyle = {
  travel: { bg: "bg-secondary/15", ring: "ring-secondary/40", dot: "hsl(var(--secondary))" },
  relax: { bg: "bg-sunshine/25", ring: "ring-sunshine/40", dot: "hsl(var(--sunshine))" },
  hero: { bg: "bg-accent/20", ring: "ring-accent/40", dot: "hsl(var(--accent))" },
  snorkel: { bg: "bg-secondary/15", ring: "ring-secondary/40", dot: "hsl(195 90% 55%)" },
  food: { bg: "bg-coral/20", ring: "ring-coral/40", dot: "hsl(var(--coral))" },
} as const;

const tagStyle = {
  travel: "bg-secondary/15 text-secondary-foreground border-secondary/30",
  place: "bg-muted border-foreground/15 text-foreground",
  default: "bg-muted border-foreground/15 text-foreground",
};

const days: Day[] = [
  {
    n: 1, weekday: "Sat", date: "Day 1", vibe: "Arrive · settle", load: "Full day",
    blocks: [
      { start: "10:00", end: "12:55", title: "Arrival flight / transfer", detail: "Backend timeline wiring next: hydrate from workspace Master Timeline", icon: Plane, tone: "travel", tags: [{ label: "travel", tone: "travel" }] },
      { start: "18:30", end: "21:00", title: "First dinner near lodging", detail: "Placeholder until workspace rows are mapped", icon: UtensilsCrossed, tone: "food", tags: [{ label: "food" }] },
    ],
  },
  {
    n: 2, weekday: "Sun", date: "Day 2", vibe: "Low-friction exploration", load: "Easy",
    blocks: [
      { start: "09:00", end: "11:00", title: "Easy local morning", detail: "Use this page as the Canvas route target for selected trips", icon: Sun, tone: "relax", tags: [{ label: "relax" }] },
      { start: "13:00", end: "14:30", title: "Lunch / reset", detail: "Real rows will come from /api/trip workspace data", icon: Coffee, tone: "food", tags: [{ label: "low-key" }] },
    ],
  },
  {
    n: 3, weekday: "Mon", date: "Day 3", vibe: "Hero activity", load: "Half",
    blocks: [
      { start: "08:00", end: "12:00", title: "Hero activity window", detail: "Selected activities will land here in the next slice", icon: Sparkles, tone: "hero", tags: [{ label: "hero" }], flag: "Keep this as a high-signal, low-clutter timeline surface" },
      { start: "13:30", end: "15:00", title: "Food stop", detail: "Backend shortlists can provide the final choice", icon: UtensilsCrossed, tone: "food", tags: [{ label: "food" }] },
    ],
  },
  {
    n: 4, weekday: "Tue", date: "Day 4", vibe: "Open buffer", load: "Open",
    blocks: [
      { start: "10:00", end: "13:00", title: "Flexible buffer", detail: "Protect against weather, fatigue, and travel friction", icon: Fish, tone: "snorkel", tags: [{ label: "buffer" }] },
    ],
  },
];

const Timeline = () => {
  const location = useLocation();
  const tripId = new URLSearchParams(location.search).get("trip_id") || "";
  const tripQuery = useQuery({
    queryKey: ["trippy", "trip", tripId],
    queryFn: () => trippyClient.getTrip(tripId),
    enabled: Boolean(tripId),
  });
  const intake = tripQuery.data?.intake;
  const title = intake?.trip_name || tripId || "Trip timeline";
  const destination = intake?.destination_seeds?.join(" · ") || "Destination TBD";
  const travelers = intake?.party?.total_travelers || intake?.travelers || "?";

  return (
    <AppShell>
      <div className="bg-gradient-hero border-b-2 border-foreground/10 px-6 md:px-10 pt-8 pb-10">
        <Link to={tripId ? `/trip/shape?trip_id=${encodeURIComponent(tripId)}` : "/"} className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground/70 hover:text-foreground transition-colors mb-4">
          <ArrowLeft className="h-4 w-4" /> Back to trip shape
        </Link>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="px-3 py-1 rounded-full bg-card border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">Planning · Stage 7 of 8</span>
          <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">{intake?.duration_label || `${intake?.duration_days ?? "?"} days`}</span>
          <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">{travelers} traveler(s)</span>
          <div className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker">
            <AlertTriangle className="h-4 w-4 text-sunshine" />
            <div className="text-xs leading-tight"><div className="font-bold">Routed by trip_id</div><div className="opacity-70">Backend-aware</div></div>
          </div>
        </div>
        <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">{title}</h1>
        <p className="text-foreground/70 italic mt-2 font-medium">{tripQuery.isLoading ? "Loading from Trippy…" : destination}</p>
      </div>

      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">Stage 7 · Master timeline</div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">Timeline shell for this trip.</h2>
            <p className="text-muted-foreground mt-1 max-w-2xl">The selected trip is now routed into this page. Next slice maps workspace Master Timeline rows into these blocks.</p>
          </div>
          <Button onClick={() => tripQuery.refetch()} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors text-foreground">
            <RefreshCcw className="h-4 w-4" /> Refresh trip
          </Button>
        </div>

        {tripQuery.error && <div className="mb-5 rounded-2xl border-2 border-coral/50 bg-coral/10 p-4 font-semibold">Backend error: {tripQuery.error.message}</div>}
        <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card overflow-hidden">
          {days.map((d, i) => <DayRow key={d.n} day={d} isLast={i === days.length - 1} />)}
        </div>
      </div>
    </AppShell>
  );
};

const loadStyle = {
  "Full day": "bg-foreground text-background",
  Easy: "bg-palm/25 text-palm",
  Half: "bg-sunshine/40 text-foreground",
  Open: "bg-muted text-muted-foreground",
} as const;

const DayRow = ({ day, isLast }: { day: Day; isLast: boolean }) => (
  <div className={`grid grid-cols-[120px_1fr] md:grid-cols-[160px_1fr] ${isLast ? "" : "border-b-2 border-foreground/10"} hover:bg-muted/20 transition-colors`}>
    <div className="px-4 md:px-6 py-5 border-r-2 border-dashed border-foreground/10 bg-gradient-to-b from-muted/30 to-transparent">
      <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Day {day.n}</div>
      <div className="font-[Fredoka] text-3xl md:text-4xl font-bold leading-none mt-1">{day.weekday}</div>
      <div className="text-xs text-muted-foreground font-bold mt-1">{day.date}</div>
      <span className={`inline-block mt-3 px-2 py-0.5 rounded-full text-[10px] font-bold border-2 border-foreground/15 ${loadStyle[day.load]}`}>{day.load}</span>
      <div className="hidden md:block text-[11px] text-muted-foreground italic mt-2 leading-snug">{day.vibe}</div>
    </div>
    <div className="py-3 px-2 md:px-4 space-y-1.5">{day.blocks.map((b, idx) => <BlockRow key={idx} block={b} />)}</div>
  </div>
);

const BlockRow = ({ block }: { block: Block }) => {
  const Icon = block.icon;
  const t = toneStyle[block.tone];
  return (
    <div className="group">
      <div className="grid grid-cols-[78px_28px_1fr_auto] md:grid-cols-[96px_32px_1fr_auto] items-center gap-2 md:gap-3 px-2 md:px-3 py-2 rounded-xl ring-1 ring-transparent hover:ring-foreground/10 hover:bg-muted/40 transition-colors">
        <div className="font-mono text-[11px] md:text-xs font-bold tabular-nums leading-tight text-right text-foreground/70"><div>{block.start}</div><div className="text-muted-foreground">– {block.end}</div></div>
        <div className={`h-7 w-7 rounded-lg ${t.bg} flex items-center justify-center border-2 border-foreground/10`}><Icon className="h-3.5 w-3.5" style={{ color: t.dot }} /></div>
        <div className="min-w-0"><div className="text-sm font-bold leading-tight truncate">{block.title}</div>{block.detail && <div className="text-xs text-muted-foreground leading-tight truncate mt-0.5">{block.detail}</div>}</div>
        <div className="hidden md:flex items-center gap-1 shrink-0">{block.tags.map((tag) => <span key={tag.label} className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${tag.tone ? tagStyle[tag.tone] : tagStyle.default}`}>{tag.label}</span>)}</div>
      </div>
      {block.flag && <div className="ml-[88px] md:ml-[140px] mr-2 md:mr-3 mb-1 mt-0.5 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-coral/10 border border-coral/30 text-[11px] font-medium text-foreground/80"><AlertTriangle className="h-3 w-3 text-primary shrink-0" />{block.flag}<Clock className="h-3 w-3 ml-auto text-muted-foreground" /></div>}
    </div>
  );
};

export default Timeline;
