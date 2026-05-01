import { useEffect, useState } from "react";
import {
  formatDuration,
  formatUsd,
  getAiCostSummary,
  type AiCostSummary,
} from "@/lib/aiCost";

const SAVEY_ICON_SRC =
  "data:image/webp;base64,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";

type LoadState = "idle" | "loading" | "loaded" | "error";

export function AiCostTile({ tripId }: { tripId: string | null }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<LoadState>("idle");
  const [summary, setSummary] = useState<AiCostSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || !tripId || status === "loading" || status === "loaded") return;
    setStatus("loading");
    getAiCostSummary(tripId)
      .then((data) => {
        setSummary(data);
        setStatus("loaded");
      })
      .catch((err: Error) => {
        setError(err.message);
        setStatus("error");
      });
  }, [open, tripId, status]);

  return (
    <div className="hidden md:block mt-auto">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full flex items-center gap-3 p-3 rounded-2xl bg-gradient-sky border-2 border-foreground/10 text-left hover:border-foreground/40 hover:-translate-y-0.5 transition-bounce"
      >
        <img
          src={SAVEY_ICON_SRC}
          alt="Savey"
          className="h-12 w-12 rounded-2xl object-cover border-2 border-foreground/70 bg-background"
        />
        <div className="text-sm min-w-0">
          <div className="font-bold leading-tight">Savey</div>
          <div className="text-muted-foreground text-xs">AI cost</div>
        </div>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/35 p-6">
          <div className="w-full max-w-xl rounded-3xl bg-card border-2 border-foreground shadow-sticker overflow-hidden">
            <div className="flex items-center gap-3 p-5 border-b-2 border-foreground/10 bg-gradient-sky">
              <img
                src={SAVEY_ICON_SRC}
                alt="Savey"
                className="h-14 w-14 rounded-2xl object-cover border-2 border-foreground/70 bg-background"
              />
              <div>
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
                  Savey · AI accountant
                </div>
                <h2 className="font-[Fredoka] text-2xl font-bold">Trip AI cost</h2>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="ml-auto h-9 w-9 rounded-full border-2 border-foreground/20 bg-background font-bold hover:border-foreground/50"
                aria-label="Close AI cost details"
              >
                ×
              </button>
            </div>

            <div className="p-5 space-y-4">
              {!tripId && (
                <div className="rounded-2xl border-2 border-foreground/10 bg-background p-4 text-sm font-medium text-muted-foreground">
                  Open a trip to see per-trip AI call and cost details.
                </div>
              )}

              {tripId && status === "loading" && (
                <div className="text-sm font-bold text-muted-foreground">Loading AI cost details…</div>
              )}

              {tripId && status === "error" && (
                <div className="rounded-2xl border-2 border-coral/40 bg-coral/10 p-4 text-sm">
                  <div className="font-bold">AI cost endpoint is not available yet.</div>
                  <div className="text-muted-foreground mt-1">{error}</div>
                </div>
              )}

              {summary && (
                <>
                  <div className="grid grid-cols-4 gap-3">
                    <Metric label="Cost" value={formatUsd(summary.estimated_cost_usd)} />
                    <Metric label="Calls" value={String(summary.total_calls)} />
                    <Metric label="Cache hits" value={String(summary.cache_hits)} />
                    <Metric label="Time" value={formatDuration(summary.total_duration_ms)} />
                  </div>

                  <div className="rounded-2xl border-2 border-foreground/10 bg-background p-4">
                    <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground mb-3">
                      Recent calls
                    </div>
                    {summary.recent_calls.length === 0 ? (
                      <div className="text-sm text-muted-foreground">No AI calls recorded for this trip yet.</div>
                    ) : (
                      <div className="space-y-2 max-h-64 overflow-auto pr-1">
                        {summary.recent_calls.slice().reverse().map((call) => (
                          <div
                            key={call.id}
                            className="grid grid-cols-[1fr_auto] gap-2 rounded-xl border-2 border-foreground/10 bg-card p-3 text-xs"
                          >
                            <div>
                              <div className="font-bold">{call.service}</div>
                              <div className="text-muted-foreground">{call.model}</div>
                            </div>
                            <div className="text-right">
                              <div className="font-bold">{formatUsd(call.estimated_cost_usd)}</div>
                              <div className="text-muted-foreground">
                                {call.cache_hit ? "cache" : call.status}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border-2 border-foreground/10 bg-background p-3">
      <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-[Fredoka] text-xl font-bold leading-tight mt-1">{value}</div>
    </div>
  );
}
