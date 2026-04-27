import { useState } from "react";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { StageNav, type Stage } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle, ArrowLeft, Check, Edit3, RefreshCcw, Sparkles,
  ThumbsUp, AlertCircle, X,
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

type ShapeOption = {
  title: string;
  badge: string;
  badgeTone: "good" | "ok" | "risky";
  segments: { label: string; nights: number; color: string }[];
  pill: { label: string; tone: "easy" | "balanced" | "ambitious" };
  risk: { label: string; tone: "ok" | "warn" | "bad" };
  strength: number;
  comfort: number;
  pros: string[];
  warnings?: string[];
  pick?: boolean;
};

const options: ShapeOption[] = [
  {
    title: "Single Base — Seven Mile Beach",
    badge: "Trippy's pick",
    badgeTone: "good",
    segments: [
      { label: "Seven Mile Beach", nights: 7, color: "hsl(178 70% 60%)" },
    ],
    pill: { label: "easy", tone: "easy" },
    risk: { label: "low risk · many family suites", tone: "ok" },
    strength: 78,
    comfort: 82,
    pros: [
      "Lowest friction for a party of 5 (2 adults, 3 kids)",
      "Best first draft while exact transport is still unvalidated",
      "Unpack once; day-trip to Stingray City and Rum Point",
    ],
    warnings: ["May underuse Rum Point if the best dinners are spread out"],
    pick: true,
  },
  {
    title: "Two-Region Balanced — SMB + Rum Point",
    badge: "balanced",
    badgeTone: "ok",
    segments: [
      { label: "Seven Mile Beach", nights: 4, color: "hsl(178 70% 60%)" },
      { label: "Rum Point", nights: 3, color: "hsl(45 100% 70%)" },
    ],
    pill: { label: "balanced", tone: "balanced" },
    risk: { label: "moderate · one mid-trip transition with buffer", tone: "warn" },
    strength: 64,
    comfort: 68,
    pros: [
      "Broader sense of place, better East End snorkeling",
      "Usually best pattern on 8–10 day trips",
    ],
    warnings: ["7 days is tight — the move can eat a full trip day"],
  },
  {
    title: "Triad — SMB + West Bay + Rum Point",
    badge: "ambitious",
    badgeTone: "risky",
    segments: [
      { label: "Seven Mile Beach", nights: 2, color: "hsl(178 70% 60%)" },
      { label: "West Bay", nights: 2, color: "hsl(8 90% 70%)" },
      { label: "Rum Point", nights: 3, color: "hsl(45 100% 70%)" },
    ],
    pill: { label: "ambitious", tone: "ambitious" },
    risk: { label: "high · three check-ins, three lodging searches", tone: "bad" },
    strength: 41,
    comfort: 49,
    pros: ["Maximum destination coverage"],
    warnings: [
      "Three check-ins with 5 people and kids is a friction trap",
      "Loses roughly a day and a half to logistics",
    ],
  },
];

const TripShape = () => {
  const [selected, setSelected] = useState(0);

  return (
    <AppShell>
      {/* Hero */}
      <div className="bg-gradient-hero border-b-2 border-foreground/10 px-6 md:px-10 pt-8 pb-10 relative">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground/70 hover:text-foreground transition-colors mb-4"
        >
          <ArrowLeft className="h-4 w-4" /> Back to trips
        </Link>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="px-3 py-1 rounded-full bg-card border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
            Planning · Stage 2 of 8
          </span>
          <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">
            7 days
          </span>
          <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">
            Whole family · 5 travelers (2 adults, 3 children)
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
              Stage 2 · Trip shape
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Pick the rhythm of the week.
            </h2>
            <p className="text-muted-foreground mt-1 max-w-2xl">
              Trippy built three shapes from the intake. The recommended one minimizes moves for a family of five during a 7-day window.
            </p>
          </div>
          <button className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors">
            <RefreshCcw className="h-4 w-4" /> Refresh from intake
          </button>
        </div>

        <div className="grid lg:grid-cols-3 gap-5">
          {options.map((o, i) => {
            const isSelected = selected === i;
            return (
              <article
                key={o.title}
                className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce flex flex-col ${
                  isSelected
                    ? "border-foreground shadow-sticker -translate-y-1"
                    : "border-foreground/10 shadow-card hover:-translate-y-0.5"
                }`}
              >
                {/* Segment ribbon */}
                <div className="relative px-5 pt-5">
                  <div className="flex flex-wrap items-center gap-1.5 mb-3">
                    {o.segments.map((s) => (
                      <span
                        key={s.label}
                        className="px-2.5 py-1 rounded-full text-xs font-bold border-2 border-foreground/20"
                        style={{ background: s.color }}
                      >
                        {s.label}
                      </span>
                    ))}
                    {o.pick && (
                      <span className="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-foreground text-background text-[10px] font-bold uppercase tracking-wider">
                        <Sparkles className="h-3 w-3" /> Trippy's pick
                      </span>
                    )}
                  </div>

                  {/* Visual nights bar */}
                  <div className="relative h-2.5 rounded-full bg-muted border-2 border-foreground/10 overflow-hidden flex">
                    {o.segments.map((s, idx) => {
                      const total = o.segments.reduce((a, b) => a + b.nights, 0);
                      return (
                        <div
                          key={idx}
                          style={{ width: `${(s.nights / total) * 100}%`, background: s.color }}
                          className={idx > 0 ? "border-l-2 border-foreground/30" : ""}
                        />
                      );
                    })}
                  </div>
                  <div className="flex justify-between text-[10px] font-bold text-muted-foreground mt-1.5 px-0.5">
                    {o.segments.map((s, idx) => (
                      <span key={idx}>{s.nights}n</span>
                    ))}
                  </div>
                </div>

                <div className="p-5 pt-4 flex-1 flex flex-col">
                  <h3 className="font-[Fredoka] text-xl font-bold leading-tight">
                    {o.title}
                  </h3>

                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-bold border-2 border-foreground/20 ${
                        o.pill.tone === "easy"
                          ? "bg-palm/30"
                          : o.pill.tone === "balanced"
                            ? "bg-sunshine/40"
                            : "bg-coral/40"
                      }`}
                    >
                      {o.pill.label}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 text-xs font-semibold ${
                        o.risk.tone === "ok"
                          ? "text-palm"
                          : o.risk.tone === "warn"
                            ? "text-primary"
                            : "text-destructive"
                      }`}
                    >
                      {o.risk.tone === "ok" ? (
                        <ThumbsUp className="h-3 w-3" />
                      ) : (
                        <AlertCircle className="h-3 w-3" />
                      )}
                      {o.risk.label}
                    </span>
                  </div>

                  {/* Meters */}
                  <div className="grid grid-cols-2 gap-3 mt-4">
                    <Meter label="Strength" value={o.strength} color="hsl(145 55% 38%)" />
                    <Meter label="Comfort" value={o.comfort} color="hsl(18 95% 55%)" />
                  </div>

                  {/* Pros */}
                  <ul className="mt-4 space-y-1.5">
                    {o.pros.map((p) => (
                      <li key={p} className="flex items-start gap-2 text-sm">
                        <Check className="h-4 w-4 text-palm shrink-0 mt-0.5" />
                        <span className="text-foreground/85 leading-snug">{p}</span>
                      </li>
                    ))}
                  </ul>

                  {/* Warnings */}
                  {o.warnings && (
                    <div className="mt-3 rounded-xl border-2 border-coral/40 bg-coral/10 p-3 space-y-1">
                      {o.warnings.map((w) => (
                        <div key={w} className="flex items-start gap-2 text-xs">
                          <AlertTriangle className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                          <span className="font-medium text-foreground/85 leading-snug">{w}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-5 pt-4 border-t-2 border-foreground/10">
                    <Button
                      onClick={() => setSelected(i)}
                      className={`flex-1 h-10 rounded-xl font-bold border-2 ${
                        isSelected
                          ? "bg-palm text-primary-foreground border-foreground shadow-card hover:bg-palm/90"
                          : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
                      }`}
                    >
                      {isSelected ? (
                        <>
                          <Check className="h-4 w-4" /> Selected
                        </>
                      ) : (
                        "Select"
                      )}
                    </Button>
                    <button className="inline-flex items-center gap-1.5 px-3 h-10 rounded-xl text-sm font-bold text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
                      <Edit3 className="h-4 w-4" /> Edit
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>

        {/* Teach Trippy */}
        <div className="mt-8 rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-6">
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Teach Trippy
            </div>
            <div className="flex gap-1.5">
              <FeedbackPill label="helpful" tone="good" />
              <FeedbackPill label="needs work" tone="warn" />
              <FeedbackPill label="wrong" tone="bad" />
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

const Meter = ({ label, value, color }: { label: string; value: number; color: string }) => (
  <div>
    <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
      <span>{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
    <div className="h-2 rounded-full bg-muted border-2 border-foreground/10 overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${value}%`, background: color }} />
    </div>
  </div>
);

const FeedbackPill = ({ label, tone }: { label: string; tone: "good" | "warn" | "bad" }) => {
  const cls =
    tone === "good"
      ? "bg-palm/20 border-palm/40 text-palm"
      : tone === "warn"
        ? "bg-sunshine/30 border-foreground/20"
        : "bg-coral/20 border-coral/40 text-coral";
  return (
    <button className={`px-3 py-1 rounded-full border-2 text-xs font-bold hover:scale-105 transition-transform ${cls}`}>
      {label === "wrong" && <X className="inline h-3 w-3 mr-1" />}
      {label}
    </button>
  );
};

export default TripShape;
