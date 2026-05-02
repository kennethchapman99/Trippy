import type React from "react";
import { AlertTriangle, Star } from "lucide-react";

export type RowLabelTone = "primary" | "warm" | "neutral";

export interface RowLabel {
  text: string;
  tone: RowLabelTone;
}

export interface LivePill {
  text: string;
  tone: "live" | "signal" | "band";
}

export function deriveRowLabel(
  recommendationLabel: string,
  isRecommended: boolean,
  fallbackGrade: string,
): RowLabel {
  const labels = (recommendationLabel || "").split(" · ").map((s) => s.trim()).filter(Boolean);
  if (isRecommended || labels.includes("Recommended") || labels.includes("Selected")) {
    return { text: "Trippy's pick", tone: "primary" };
  }
  if (labels.includes("Runner-up")) return { text: "Runner-up", tone: "warm" };
  if (labels.includes("Budget-best")) return { text: "Budget-best", tone: "warm" };
  if (labels.includes("Shortest")) return { text: "Shortest", tone: "warm" };
  if (labels.includes("Lowest-friction")) return { text: "Lowest-friction", tone: "warm" };
  return { text: fallbackGrade.replace(/^./, (c) => c.toUpperCase()), tone: "neutral" };
}

export function deriveLivePill(option: {
  live_data_status?: string;
  validation?: { source_name?: string };
}): LivePill {
  const status = option.live_data_status;
  const source = option.validation?.source_name;
  if (status === "live_verified") {
    return { text: source ? `Live verified · ${source}` : "Live verified", tone: "live" };
  }
  if (status === "live_signal" || status === "partial") {
    return { text: source ? `Live signal · ${source}` : "Live signal", tone: "signal" };
  }
  return { text: "live-verify band", tone: "band" };
}

export function deriveLiveBanner(
  warnings: string[],
  options: Array<{ live_data_status?: string }>,
  category: "flights" | "lodging" | "cars" | "activities",
): { title: string; detail: string } | null {
  if (options.length === 0 && warnings.length === 0) return null;
  const hasLive = options.some(
    (o) => o.live_data_status === "live_verified" || o.live_data_status === "live_signal" || o.live_data_status === "partial",
  );
  if (hasLive) return null;
  const provider = warnings.find((w) => /serpapi|duffel|openclaw|playwright|firecrawl/i.test(w));
  const missingProvider = warnings.some((w) => /not configured|missing|unavailable/i.test(w));
  const labels: Record<typeof category, string> = {
    flights: "flight",
    lodging: "lodging",
    cars: "car",
    activities: "activity",
  };
  const title = missingProvider
    ? `Live ${labels[category]} search is not connected yet.`
    : provider
      ? `No live ${labels[category]} rows returned yet.`
      : `No live ${labels[category]} rows in this shortlist yet.`;
  return {
    title,
    detail:
      missingProvider
        ? `Use Re-research after live ${labels[category]} search is connected, or add a candidate manually.`
        : provider || `Try Re-research, or add a ${labels[category]} candidate manually.`,
  };
}

export function RowHeaderStrip({
  label,
  pill,
  left,
}: {
  label: RowLabel;
  pill: LivePill;
  left: React.ReactNode;
}) {
  return (
    <header
      className={`flex items-center justify-between gap-3 px-5 py-2.5 border-b-2 border-foreground/10 ${
        label.tone === "primary"
          ? "bg-primary/10"
          : label.tone === "warm"
            ? "bg-sunshine/20"
            : "bg-muted/40"
      }`}
    >
      <div className="flex items-center gap-2 min-w-0">
        {label.tone === "primary" && <Star className="h-4 w-4 text-primary fill-primary" />}
        <span
          className={`text-xs font-bold uppercase tracking-wider ${
            label.tone === "primary" ? "text-primary" : "text-foreground/80"
          }`}
        >
          {label.text}
        </span>
        <span className="text-foreground/30">·</span>
        {left}
      </div>
      <span
        className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full whitespace-nowrap ${
          pill.tone === "live"
            ? "bg-palm/20 text-palm border border-palm/40"
            : pill.tone === "signal"
              ? "bg-sunshine/30 text-foreground/80 border border-foreground/15"
              : "bg-muted text-muted-foreground border border-foreground/10"
        }`}
      >
        {pill.text}
      </span>
    </header>
  );
}

export function LiveProvidersBanner({
  banner,
}: {
  banner: { title: string; detail: string } | null;
}) {
  if (!banner) return null;
  return (
    <div className="mb-4 rounded-2xl border-2 border-sunshine/60 bg-sunshine/15 px-4 py-3 flex items-start gap-3">
      <AlertTriangle className="h-5 w-5 text-foreground/70 shrink-0 mt-0.5" />
      <div className="text-sm">
        <div className="font-bold">{banner.title}</div>
        <div className="text-foreground/75">{banner.detail}</div>
      </div>
    </div>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/10 text-xs font-bold text-foreground/80">
      {children}
    </span>
  );
}
