import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { StageNav, type Stage } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
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
  date: string; // e.g. "Mar 14"
  vibe: string; // e.g. "Arrive · settle"
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
    n: 1, weekday: "Sat", date: "Mar 14", vibe: "Arrive · beach dinner", load: "Full day",
    blocks: [
      {
        start: "10:00", end: "12:55", title: "AC 1726 · YYZ → SMB",
        detail: "Air Canada · seats 14A–14E booked", icon: Plane, tone: "travel",
        tags: [{ label: "travel", tone: "travel" }, { label: "YYZ → SMB", tone: "place" }],
      },
      {
        start: "13:30", end: "15:00", title: "Transfer + check-in",
        detail: "Pre-arranged van · car seat confirmed", icon: MapPin, tone: "travel",
        tags: [{ label: "logistics" }],
      },
      {
        start: "18:30", end: "21:00", title: "Dinner on Seven Mile Beach",
        detail: "Calico Jack's · kid-friendly · 15-min walk", icon: UtensilsCrossed, tone: "food",
        tags: [{ label: "food" }, { label: "SMB", tone: "place" }],
      },
    ],
  },
  {
    n: 2, weekday: "Sun", date: "Mar 15", vibe: "Settle in", load: "Easy",
    blocks: [
      {
        start: "09:00", end: "11:00", title: "Beach + settle in",
        detail: "Short snorkel at Governor's Beach", icon: Sun, tone: "relax",
        tags: [{ label: "relax" }, { label: "SMB", tone: "place" }],
      },
      {
        start: "13:00", end: "14:30", title: "Late lunch at the condo",
        detail: "Grocery run handled the night before", icon: Coffee, tone: "food",
        tags: [{ label: "low-key" }],
      },
    ],
  },
  {
    n: 3, weekday: "Mon", date: "Mar 16", vibe: "Hero day", load: "Full day",
    blocks: [
      {
        start: "08:00", end: "12:00", title: "Stingray City + Starfish Point",
        detail: "Private charter · 8am push-off", icon: Sparkles, tone: "hero",
        tags: [{ label: "hero" }, { label: "North Sound", tone: "place" }],
        flag: "Sunscreen + rash guards in the day bag",
      },
      {
        start: "13:30", end: "15:00", title: "Lunch @ Kaibo",
        detail: "Outdoor seating, dock view", icon: UtensilsCrossed, tone: "food",
        tags: [{ label: "food" }],
      },
    ],
  },
  {
    n: 4, weekday: "Tue", date: "Mar 17", vibe: "Reef day", load: "Half",
    blocks: [
      {
        start: "10:00", end: "13:00", title: "Reef day at Rum Point",
        detail: "Rentals on-site · shallow entry for kids", icon: Fish, tone: "snorkel",
        tags: [{ label: "snorkel" }, { label: "East End", tone: "place" }],
      },
      {
        start: "13:00", end: "14:30", title: "Lunch @ Rum Point Club",
        detail: "Walk-in usually fine before noon", icon: UtensilsCrossed, tone: "food",
        tags: [{ label: "food" }],
      },
    ],
  },
  {
    n: 5, weekday: "Wed", date: "Mar 18", vibe: "Food day", load: "Half",
    blocks: [
      {
        start: "11:00", end: "14:00", title: "Cayman Cookout tastings",
        detail: "Adults rotate · kids' adventure afternoon booked", icon: UtensilsCrossed, tone: "food",
        tags: [{ label: "food" }, { label: "West Bay", tone: "place" }],
      },
      {
        start: "15:00", end: "17:00", title: "Kids' adventure session",
        detail: "Resort program · 5–11 age group", icon: Sparkles, tone: "hero",
        tags: [{ label: "kids" }],
      },
    ],
  },
  {
    n: 6, weekday: "Thu", date: "Mar 19", vibe: "Free + spa", load: "Open",
    blocks: [
      {
        start: "09:00", end: "12:00", title: "Free morning · spa window",
        detail: "Backup for weather day · keep flexible", icon: Sun, tone: "relax",
        tags: [{ label: "relax" }, { label: "SMB", tone: "place" }],
      },
    ],
  },
  {
    n: 7, weekday: "Fri", date: "Mar 20", vibe: "Depart", load: "Half",
    blocks: [
      {
        start: "11:00", end: "12:30", title: "Lunch before cab",
        detail: "Pack the night before · 2 checked bags", icon: UtensilsCrossed, tone: "food",
        tags: [{ label: "logistics" }],
      },
      {
        start: "14:30", end: "18:00", title: "AC 1727 · SMB → YYZ",
        detail: "Cab booked 12:45 · stroller gate-checked", icon: Plane, tone: "travel",
        tags: [{ label: "travel", tone: "travel" }, { label: "SMB → YYZ", tone: "place" }],
      },
    ],
  },
];

const Timeline = () => {
  return (
    <AppShell>
      {/* Hero */}
      <div className="bg-gradient-hero border-b-2 border-foreground/10 px-6 md:px-10 pt-8 pb-10">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground/70 hover:text-foreground transition-colors mb-4"
        >
          <ArrowLeft className="h-4 w-4" /> Back to trips
        </Link>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="px-3 py-1 rounded-full bg-card border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
            Planning · Stage 7 of 8
          </span>
          <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">
            7 days
          </span>
          <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">
            Whole family · 5 travelers
          </span>
          <div className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker">
            <AlertTriangle className="h-4 w-4 text-sunshine" />
            <div className="text-xs leading-tight">
              <div className="font-bold">3 friction flags</div>
              <div className="opacity-70">Trippy is watching</div>
            </div>
          </div>
        </div>
        <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">
          Cayman Reef + <span className="text-gradient-sunset">Food Easy</span> Week
        </h1>
        <p className="text-foreground/70 italic mt-2 font-medium">
          Seven Mile Beach · West Bay · Stingray City · Rum Point
        </p>
      </div>

      {/* Stage nav */}
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      {/* Body */}
      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 7 · Master timeline
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Seven days, one page.
            </h2>
            <p className="text-muted-foreground mt-1 max-w-2xl">
              Trippy composes the timeline from flights, stays, and activities — and re-checks for friction whenever a piece changes.
            </p>
          </div>
          <button className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors">
            <RefreshCcw className="h-4 w-4" /> Re-audit
          </button>
        </div>

        {/* Compact dense timeline */}
        <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card overflow-hidden">
          {days.map((d, i) => (
            <DayRow key={d.n} day={d} isLast={i === days.length - 1} />
          ))}
        </div>

        {/* Teach Trippy */}
        <div className="mt-8 rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-6">
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Teach Trippy
            </div>
            <div className="flex gap-1.5">
              <span className="px-3 py-1 rounded-full bg-palm/20 border-2 border-palm/40 text-palm text-xs font-bold">helpful</span>
              <span className="px-3 py-1 rounded-full bg-sunshine/30 border-2 border-foreground/20 text-xs font-bold">needs work</span>
              <span className="px-3 py-1 rounded-full bg-coral/20 border-2 border-coral/40 text-coral text-xs font-bold">wrong</span>
            </div>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <input
              placeholder="What should Trippy remember about this stage?"
              className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
            />
            <input
              placeholder="What should change before the next step?"
              className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
            />
          </div>
          <div className="flex items-center justify-between flex-wrap gap-3 mt-4">
            <label className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <input type="checkbox" className="h-4 w-4 rounded border-2 border-foreground/30 accent-primary" />
              Propose this as future learning
            </label>
            <Button className="h-10 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-card px-5">
              Send feedback
            </Button>
          </div>
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

const DayRow = ({ day, isLast }: { day: Day; isLast: boolean }) => {
  return (
    <div
      className={`grid grid-cols-[120px_1fr] md:grid-cols-[160px_1fr] ${
        isLast ? "" : "border-b-2 border-foreground/10"
      } hover:bg-muted/20 transition-colors`}
    >
      {/* LEFT: date column */}
      <div className="px-4 md:px-6 py-5 border-r-2 border-dashed border-foreground/10 bg-gradient-to-b from-muted/30 to-transparent">
        <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
          Day {day.n}
        </div>
        <div className="font-[Fredoka] text-3xl md:text-4xl font-bold leading-none mt-1">
          {day.weekday}
        </div>
        <div className="text-xs text-muted-foreground font-bold mt-1">{day.date}</div>
        <span
          className={`inline-block mt-3 px-2 py-0.5 rounded-full text-[10px] font-bold border-2 border-foreground/15 ${loadStyle[day.load]}`}
        >
          {day.load}
        </span>
        <div className="hidden md:block text-[11px] text-muted-foreground italic mt-2 leading-snug">
          {day.vibe}
        </div>
      </div>

      {/* RIGHT: nested time blocks */}
      <div className="py-3 px-2 md:px-4 space-y-1.5">
        {day.blocks.map((b, idx) => (
          <BlockRow key={idx} block={b} />
        ))}
      </div>
    </div>
  );
};

const BlockRow = ({ block }: { block: Block }) => {
  const Icon = block.icon;
  const t = toneStyle[block.tone];
  return (
    <div className="group">
      <div
        className={`grid grid-cols-[78px_28px_1fr_auto] md:grid-cols-[96px_32px_1fr_auto] items-center gap-2 md:gap-3 px-2 md:px-3 py-2 rounded-xl ring-1 ring-transparent hover:ring-foreground/10 hover:bg-muted/40 transition-colors`}
      >
        {/* time range */}
        <div className="font-mono text-[11px] md:text-xs font-bold tabular-nums leading-tight text-right text-foreground/70">
          <div>{block.start}</div>
          <div className="text-muted-foreground">– {block.end}</div>
        </div>

        {/* icon chip */}
        <div
          className={`h-7 w-7 rounded-lg ${t.bg} flex items-center justify-center border-2 border-foreground/10`}
        >
          <Icon className="h-3.5 w-3.5" style={{ color: t.dot }} />
        </div>

        {/* title + detail */}
        <div className="min-w-0">
          <div className="text-sm font-bold leading-tight truncate">{block.title}</div>
          {block.detail && (
            <div className="text-xs text-muted-foreground leading-tight truncate mt-0.5">
              {block.detail}
            </div>
          )}
        </div>

        {/* tags */}
        <div className="hidden md:flex items-center gap-1 shrink-0">
          {block.tags.map((tag) => (
            <span
              key={tag.label}
              className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${
                tag.tone ? tagStyle[tag.tone] : tagStyle.default
              }`}
            >
              {tag.label}
            </span>
          ))}
        </div>
      </div>
      {block.flag && (
        <div className="ml-[88px] md:ml-[140px] mr-2 md:mr-3 mb-1 mt-0.5 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-coral/10 border border-coral/30 text-[11px] font-medium text-foreground/80">
          <AlertTriangle className="h-3 w-3 text-primary shrink-0" />
          {block.flag}
          <Clock className="h-3 w-3 ml-auto text-muted-foreground" />
        </div>
      )}
    </div>
  );
};

export default Timeline;
