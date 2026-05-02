import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle, ArrowLeft, Check, ChevronDown, Loader2, MapPin, RefreshCcw, Sparkles,
  ThumbsUp, AlertCircle,
} from "lucide-react";
import { api, type TripPlanOption } from "@/lib/api";
import { buildStages } from "@/lib/stages";

const SEGMENT_COLORS = [
  "hsl(178 70% 60%)",
  "hsl(45 100% 70%)",
  "hsl(8 90% 70%)",
  "hsl(205 88% 60%)",
  "hsl(270 70% 70%)",
];

function burdenToPill(burden: string): { label: string; tone: "easy" | "balanced" | "ambitious" } {
  const b = burden.toLowerCase();
  if (b.includes("low") || b.includes("easy")) return { label: "easy", tone: "easy" };
  if (b.includes("high") || b.includes("ambitious") || b.includes("challenging"))
    return { label: "ambitious", tone: "ambitious" };
  return { label: "balanced", tone: "balanced" };
}

function burdenToRisk(burden: string, risks: string[]): { label: string; tone: "ok" | "warn" | "bad" } {
  const b = burden.toLowerCase();
  if (b.includes("high") || b.includes("ambitious")) {
    return { label: risks[0] ?? "high friction", tone: "bad" };
  }
  if (b.includes("moderate") || b.includes("balanced")) {
    return { label: risks[0] ?? "moderate friction", tone: "warn" };
  }
  return { label: "low risk", tone: "ok" };
}

function cleanPlanningText(value: string): string {
  return value
    .replace(/\b(?:primary|first|second) confirmed base\b/gi, "chosen stay area")
    .replace(/\bprimary base\b/gi, "main stay area")
    .replace(/\bscanner evidence\b/gi, "location research")
    .replace(/\buser-approved JSON\b/gi, "your trip details")
    .replace(/\btrip JSON\b/gi, "your trip details")
    .replace(/\bresolver evidence\b/gi, "location research")
    .replace(/\bprovider\/scanner evidence\b/gi, "source research")
    .replace(/\s+·\s+/g, " · ")
    .trim();
}

function userFacingShapeTitle(option: TripPlanOption): string {
  const regions = option.regions.filter(Boolean);
  const title = option.title.toLowerCase();
  if (option.option_id.includes("single") || title.includes("single-base")) {
    return regions[0] ? `Unpack Once in ${regions[0]}` : "Unpack Once";
  }
  if (option.option_id.includes("two") || title.includes("two-region")) {
    return regions.length >= 2 ? `${regions[0]} + ${regions[1]} Without the Rush` : "Two Good Bases";
  }
  if (option.option_id.includes("multi") || title.includes("multi-spot")) {
    return regions.length ? `${regions[0]} and the Best Side Trips` : "The Big Sampler";
  }
  if (title.includes("one-island") || title.includes("easy version")) {
    return regions[0] ? `Unpack Once in ${regions[0]}` : "Unpack Once";
  }
  if (title.includes("more ambitious") || title.includes("sampler")) {
    return regions.length ? `${regions[0]} and the Best Side Trips` : "The Big Sampler";
  }
  return cleanPlanningText(option.title);
}

function mapEmbedUrl(regions: string[]): string {
  const query = regions.filter(Boolean).join(" to ") || "trip map";
  return `https://www.google.com/maps?q=${encodeURIComponent(query)}&output=embed`;
}

const TripShape = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);
  const [feedbackText, setFeedbackText] = useState("");

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const draftMutation = useMutation({
    mutationFn: () => api.draftPlan(tripId!),
    onSuccess: () => tripQuery.refetch(),
  });

  const selectMutation = useMutation({
    mutationFn: (optionId: string) => api.selectPlan(tripId!, optionId),
    onSuccess: () => navigate(`/trip/${tripId}/flights`),
  });

  const feedbackMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.addFeedback(payload),
    onSuccess: () => setFeedbackText(""),
  });

  // Auto-draft if no draft exists
  useEffect(() => {
    if (
      tripQuery.isSuccess &&
      !tripQuery.data?.draft &&
      tripId &&
      !draftMutation.isPending &&
      !draftMutation.isSuccess
    ) {
      draftMutation.mutate();
    }
  }, [tripQuery.isSuccess, tripQuery.data?.draft, tripId]);

  // Pre-select the recommended option
  useEffect(() => {
    const draft = tripQuery.data?.draft;
    if (draft && !selected) {
      setSelected(draft.selected_option_id ?? draft.recommended_option_id ?? null);
    }
  }, [tripQuery.data?.draft]);

  const intake = tripQuery.data?.intake;
  const draft = tripQuery.data?.draft;
  const options: TripPlanOption[] = draft?.options ?? [];
  const stages = buildStages(tripQuery.data, "shape");
  const isGenerating = draftMutation.isPending || (tripQuery.isLoading && !draft);

  const tripName = intake?.trip_name ?? "Your trip";
  const destination = intake?.destination_seeds?.join(" · ") ?? "";
  const flags = options.flatMap((o) => o.major_risks).length;

  return (
    <AppShell>
      {/* Hero */}
      <div className="bg-gradient-hero border-b-2 border-foreground/10 px-4 md:px-6 lg:px-8 pt-6 pb-7 relative">
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
          {intake?.duration_days && (
            <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">
              {intake.duration_days} days
            </span>
          )}
          {intake?.party && (
            <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">
              {intake.party.adults + intake.party.children} travelers
            </span>
          )}
          {flags > 0 && (
            <a
              href="#friction-review"
              className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background transition-bounce"
              aria-label={`Review ${flags} friction flag${flags !== 1 ? "s" : ""}`}
            >
              <AlertTriangle className="h-4 w-4 text-sunshine" />
              <div className="text-xs leading-tight">
                <div className="font-bold">{flags} friction flag{flags !== 1 ? "s" : ""}</div>
                <div className="opacity-70">Review friction</div>
              </div>
              <ChevronDown className="h-3.5 w-3.5 opacity-70" />
            </a>
          )}
        </div>
        <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">
          {tripName}
        </h1>
        {destination && (
          <p className="text-foreground/70 italic mt-2 font-medium">{destination}</p>
        )}
      </div>

      {/* Stage nav */}
      <div className="px-4 md:px-6 lg:px-8 py-4 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      {/* Body */}
      <div className="px-4 md:px-6 lg:px-8 py-6">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 2 · Trip shape
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Pick the rhythm of the trip.
            </h2>
            <p className="text-muted-foreground mt-1 max-w-2xl">
              Trippy built these shapes from your intake. Pick the one that feels right. You can adjust later.
            </p>
          </div>
          <button
            onClick={() => draftMutation.mutate()}
            disabled={draftMutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors"
          >
            {draftMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCcw className="h-4 w-4" />
            )}
            {draftMutation.isPending ? "Regenerating…" : "Regenerate"}
          </button>
        </div>

        {/* Loading / generating state */}
        {(isGenerating || !tripId) && (
          <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <div className="font-bold text-lg">
              {!tripId ? "No trip ID in URL" : "Trippy is building your options…"}
            </div>
            <div className="text-sm">This usually takes 15–30 seconds.</div>
          </div>
        )}

        {/* Error states */}
        {(tripQuery.isError || draftMutation.isError) && (
          <div className="rounded-3xl border-2 border-destructive/30 bg-destructive/5 p-6 flex items-start gap-4 mb-6">
            <AlertCircle className="h-6 w-6 text-destructive shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-destructive">Couldn't load trip</div>
              <div className="text-sm text-muted-foreground mt-1">
                {((tripQuery.error || draftMutation.error) as Error)?.message ?? "Check that the Trippy backend is running."}
              </div>
            </div>
          </div>
        )}

        {/* Options grid */}
        {!isGenerating && options.length > 0 && (
          <>
            <div id="friction-review" className="grid scroll-mt-32 xl:grid-cols-2 gap-5">
              {options.map((o) => {
                const isSelected = selected === o.option_id;
                const isRecommended = draft?.recommended_option_id === o.option_id;
                const pill = burdenToPill(o.travel_burden);
                const risk = burdenToRisk(o.travel_burden, o.major_risks);
                const segments = Object.entries(o.nights_by_region).map(([label, nights], idx) => ({
                  label,
                  nights,
                  color: SEGMENT_COLORS[idx % SEGMENT_COLORS.length],
                }));
                const totalNights = segments.reduce((a, b) => a + b.nights, 0);

                return (
                  <TripShapeCard
                    key={o.option_id}
                    option={o}
                    isSelected={isSelected}
                    isRecommended={isRecommended}
                    pill={pill}
                    risk={risk}
                    segments={segments}
                    totalNights={totalNights}
                    onChoose={() => setSelected(o.option_id)}
                  />
                );
              })}
            </div>

            {/* Confirm selection CTA */}
            {selected && (
              <div className="mt-6 flex justify-end">
                <Button
                  onClick={() => selectMutation.mutate(selected)}
                  disabled={selectMutation.isPending}
                  className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
                >
                  {selectMutation.isPending ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Locking in…</>
                  ) : (
                    <>Lock in this shape → Flights</>
                  )}
                </Button>
              </div>
            )}
          </>
        )}

        {/* Teach Trippy */}
        {!isGenerating && (
          <div className="mt-8 rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-6">
            <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
              <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
                Teach Trippy
              </div>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              <input
                value={feedbackText}
                onChange={(e) => setFeedbackText(e.target.value)}
                placeholder="What should Trippy remember about this stage?"
                className="h-11 rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium text-sm focus:outline-none focus:border-primary"
              />
            </div>
            <div className="flex items-center justify-end mt-4">
              <Button
                onClick={() =>
                  feedbackMutation.mutate({
                    rating: "helpful",
                    notes: feedbackText,
                    future_learning: true,
                  })
                }
                disabled={!feedbackText || feedbackMutation.isPending}
                className="h-10 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-card px-5"
              >
                {feedbackMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : feedbackMutation.isSuccess ? (
                  "Saved ✓"
                ) : (
                  "Send feedback"
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
};

function TripShapeCard({
  option,
  isSelected,
  isRecommended,
  pill,
  risk,
  segments,
  totalNights,
  onChoose,
}: {
  option: TripPlanOption;
  isSelected: boolean;
  isRecommended: boolean;
  pill: { label: string; tone: "easy" | "balanced" | "ambitious" };
  risk: { label: string; tone: "ok" | "warn" | "bad" };
  segments: Array<{ label: string; nights: number; color: string }>;
  totalNights: number;
  onChoose: () => void;
}) {
  return (
    <article
      className={`rounded-3xl border-2 bg-card overflow-hidden transition-bounce flex flex-col ${
        isSelected
          ? "border-foreground shadow-sticker -translate-y-1"
          : "border-foreground/10 shadow-card hover:-translate-y-0.5"
      }`}
    >
      <div className="relative h-72 md:h-80 overflow-hidden bg-muted">
        <iframe
          title={`${userFacingShapeTitle(option)} map`}
          src={mapEmbedUrl(option.regions)}
          loading="eager"
          className="absolute inset-0 h-full w-full border-0"
        />
        <div className="pointer-events-none absolute left-3 bottom-3 inline-flex items-center gap-1.5 rounded-full bg-background/95 px-2.5 py-1 text-[11px] font-bold text-foreground border-2 border-foreground/15">
          <MapPin className="h-3.5 w-3.5 text-primary" />
          {option.regions.filter(Boolean).join(" + ") || "Map"}
        </div>
        {isRecommended && (
          <span className="absolute top-3 right-3 inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-background/95 text-foreground text-[10px] font-bold uppercase tracking-wider border-2 border-foreground/20">
            <Sparkles className="h-3 w-3 text-primary" /> Trippy pick
          </span>
        )}
      </div>

      {/* Segment ribbon */}
      <div className="relative px-5 pt-5">
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          {segments.map((s) => (
            <span
              key={s.label}
              className="px-2.5 py-1 rounded-full text-xs font-bold border-2 border-foreground/20"
              style={{ background: s.color }}
            >
              {s.label}
            </span>
          ))}
        </div>

        {segments.length > 0 && (
          <>
            <div className="relative h-2.5 rounded-full bg-muted border-2 border-foreground/10 overflow-hidden flex">
              {segments.map((s, idx) => (
                <div
                  key={idx}
                  style={{
                    width: `${totalNights ? (s.nights / totalNights) * 100 : 0}%`,
                    background: s.color,
                  }}
                  className={idx > 0 ? "border-l-2 border-foreground/30" : ""}
                />
              ))}
            </div>
            <div className="flex justify-between text-[10px] font-bold text-muted-foreground mt-1.5 px-0.5">
              {segments.map((s, idx) => (
                <span key={idx}>{s.nights}n</span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="p-5 pt-4 flex-1 flex flex-col">
        <h3 className="font-[Fredoka] text-xl font-bold leading-tight">{userFacingShapeTitle(option)}</h3>

        <div className="flex flex-wrap items-center gap-2 mt-2">
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-bold border-2 border-foreground/20 ${
              pill.tone === "easy"
                ? "bg-palm/30"
                : pill.tone === "balanced"
                  ? "bg-sunshine/40"
                  : "bg-coral/40"
            }`}
          >
            {pill.label}
          </span>
          <span
            className={`inline-flex items-center gap-1 text-xs font-semibold ${
              risk.tone === "ok"
                ? "text-palm"
                : risk.tone === "warn"
                  ? "text-primary"
                  : "text-destructive"
            }`}
          >
            {risk.tone === "ok" ? (
              <ThumbsUp className="h-3 w-3" />
            ) : (
              <AlertTriangle className="h-3 w-3" />
            )}
            {risk.label}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 mt-4">
          <Meter label="Strength" value={option.recommendation_strength} color="hsl(145 55% 38%)" />
          <Meter label="Comfort" value={option.family_comfort_score} color="hsl(18 95% 55%)" />
        </div>

        <ul className="mt-4 space-y-1.5">
          {option.rationale.slice(0, 3).map((p) => cleanPlanningText(p)).map((p) => (
            <li key={p} className="flex items-start gap-2 text-sm">
              <Check className="h-4 w-4 text-palm shrink-0 mt-0.5" />
              <span className="text-foreground/85 leading-snug">{p}</span>
            </li>
          ))}
        </ul>

        {option.major_risks.length > 0 && (
          <div className="mt-3 rounded-xl border-2 border-coral/40 bg-coral/10 p-3 space-y-1">
            {option.major_risks.slice(0, 2).map((w) => cleanPlanningText(w)).map((w) => (
              <div key={w} className="flex items-start gap-2 text-xs">
                <AlertTriangle className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                <span className="font-medium text-foreground/85 leading-snug">{w}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 mt-5 pt-4 border-t-2 border-foreground/10">
          <Button
            onClick={onChoose}
            className={`flex-1 h-10 rounded-xl font-bold border-2 ${
              isSelected
                ? "bg-palm text-primary-foreground border-foreground shadow-card hover:bg-palm/90"
                : "bg-card text-foreground border-foreground/20 hover:border-foreground/50"
            }`}
          >
            {isSelected ? (
              <><Check className="h-4 w-4" /> Selected</>
            ) : (
              "Select"
            )}
          </Button>
        </div>
      </div>
    </article>
  );
}

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

export default TripShape;
