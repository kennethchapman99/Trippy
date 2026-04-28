import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle, ArrowLeft, Loader2, RefreshCcw, AlertCircle,
  ExternalLink, CheckCircle2, Clock, Sparkles, FileSpreadsheet,
} from "lucide-react";
import { api, type WorkspaceTab } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import { TripMap } from "@/components/TripMap";
import { useGeocodes } from "@/lib/geocode";
import {
  buildActivityPins,
  buildFlightPins,
  buildLodgingPins,
  makeGeocodeLookup,
} from "@/lib/pinBuilders";

const Timeline = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const queryClient = useQueryClient();
  const [createSheet, setCreateSheet] = useState(false);

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 60_000,
  });

  const workspaceMutation = useMutation({
    mutationFn: () => api.buildWorkspace(tripId!, { create_google_sheet: createSheet }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trip", tripId] }),
  });

  const intake = tripQuery.data?.intake;
  const workspace = tripQuery.data?.workspace;
  const draft = tripQuery.data?.draft;
  const runLog = tripQuery.data?.run_log ?? [];
  const nextStep = tripQuery.data?.next_step ?? "";
  const stages = buildStages(tripQuery.data, "timeline");

  const tripName = intake?.trip_name ?? "Your trip";
  const destination = intake?.destination_seeds?.join(" · ") ?? "";

  const selectedOption = draft?.options?.find(
    (o) => o.option_id === (draft?.selected_option_id ?? draft?.recommended_option_id)
  );

  const lodgingShortlist = shortlistOptions(tripQuery.data, "lodging");
  const activityShortlist = shortlistOptions(tripQuery.data, "activities");
  const flightShortlist = shortlistOptions(tripQuery.data, "flights");
  const lodgingOpts = lodgingShortlist?.lodging_options ?? [];
  const activityOpts = activityShortlist?.activity_options ?? [];
  const flightOpts = flightShortlist?.flight_options ?? [];

  const allQueries = [
    ...lodgingOpts.map((o) =>
      [o.location_area, o.island_or_region].filter(Boolean).join(", ")
    ),
    ...activityOpts.map((o) => o.island_location || ""),
    ...flightOpts.flatMap((o) => [o.departure_airport, o.arrival_airport]),
  ];
  const allGeocodes = useGeocodes(allQueries);
  const lookup = makeGeocodeLookup(
    allQueries.map((q, i) => ({ query: q, coords: allGeocodes[i]?.data ?? null }))
  );
  const tripMapPins = [
    ...buildLodgingPins(lodgingOpts, lookup),
    ...buildActivityPins(activityOpts, lookup),
    ...buildFlightPins(flightOpts, lookup),
  ].sort((a, b) => {
    if (!a.at && !b.at) return 0;
    if (!a.at) return 1;
    if (!b.at) return -1;
    return a.at < b.at ? -1 : 1;
  });

  const timelineTabs: WorkspaceTab[] = workspace?.tabs ?? [];
  const masterTab = timelineTabs.find(
    (t) => t.name.toLowerCase().includes("timeline") || t.name.toLowerCase().includes("master")
  );

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
        </div>
        <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">
          {tripName}
        </h1>
        {destination && (
          <p className="text-foreground/70 italic mt-2 font-medium">{destination}</p>
        )}
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
              Hermes composes the timeline from flights, stays, and activities — and re-checks for friction whenever a piece changes.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {workspace && (
              <label className="inline-flex items-center gap-1.5 text-xs font-bold text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={createSheet}
                  onChange={(e) => setCreateSheet(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-2 border-foreground/30 accent-primary"
                />
                + Google Sheet
              </label>
            )}
            <button
              onClick={() => workspaceMutation.mutate()}
              disabled={workspaceMutation.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors"
            >
              {workspaceMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCcw className="h-4 w-4" />
              )}
              {workspace ? "Re-audit" : "Build workspace"}
            </button>
          </div>
        </div>

        {/* Loading */}
        {tripQuery.isLoading && (
          <div className="flex items-center justify-center py-24 text-muted-foreground gap-3">
            <Loader2 className="h-6 w-6 animate-spin" />
            <span className="font-bold">Loading trip state…</span>
          </div>
        )}

        {/* Error */}
        {tripQuery.isError && (
          <div className="rounded-3xl border-2 border-destructive/30 bg-destructive/5 p-6 flex items-start gap-4 mb-6">
            <AlertCircle className="h-6 w-6 text-destructive shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-destructive">Couldn't load trip</div>
              <div className="text-sm text-muted-foreground mt-1">
                {(tripQuery.error as Error)?.message ?? "Check that the Hermes backend is running."}
              </div>
            </div>
          </div>
        )}

        {/* No tripId */}
        {!tripId && (
          <div className="text-center py-24 text-muted-foreground">
            <p className="font-bold mb-2">No trip selected.</p>
            <Link to="/" className="text-primary font-bold hover:underline">← Back to trips</Link>
          </div>
        )}

        {/* Plan summary from selected option */}
        {selectedOption && !tripQuery.isLoading && (
          <div className="mb-6 rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-1">
                  Selected shape
                </div>
                <h3 className="font-[Fredoka] text-2xl font-bold">{selectedOption.title}</h3>
                <p className="text-sm text-muted-foreground mt-1 max-w-xl">{selectedOption.summary}</p>
              </div>
              <div className="flex gap-3 shrink-0">
                <ScorePill label="Strength" value={selectedOption.recommendation_strength} />
                <ScorePill label="Comfort" value={selectedOption.family_comfort_score} />
              </div>
            </div>

            {selectedOption.rationale.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {selectedOption.rationale.slice(0, 3).map((r) => (
                  <span key={r} className="px-3 py-1 rounded-full bg-palm/15 border border-palm/30 text-xs font-bold">
                    {r}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Workspace not yet built */}
        {!tripQuery.isLoading && !workspace && tripId && (
          <div className="rounded-3xl border-2 border-dashed border-foreground/20 bg-muted/20 p-12 flex flex-col items-center text-center gap-4">
            <div className="h-16 w-16 rounded-2xl bg-gradient-sunset border-2 border-foreground shadow-sticker flex items-center justify-center">
              <Sparkles className="h-8 w-8 text-primary-foreground" />
            </div>
            <div>
              <h3 className="font-[Fredoka] text-2xl font-bold">Timeline not yet built</h3>
              <p className="text-muted-foreground text-sm mt-2 max-w-sm">
                {nextStep || "Build the workspace to generate the master timeline, risk audit, and planning packet."}
              </p>
            </div>
            <label className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={createSheet}
                onChange={(e) => setCreateSheet(e.target.checked)}
                className="h-4 w-4 rounded border-2 border-foreground/30 accent-primary"
              />
              <FileSpreadsheet className="h-4 w-4" />
              Also create a Google Sheet workspace
            </label>
            <Button
              onClick={() => workspaceMutation.mutate()}
              disabled={workspaceMutation.isPending}
              className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
            >
              {workspaceMutation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> {createSheet ? "Building + creating sheet…" : "Building…"}</>
              ) : (
                <>Build workspace</>
              )}
            </Button>
            {workspaceMutation.isError && (
              <p className="text-sm text-destructive font-medium">
                {(workspaceMutation.error as Error)?.message}
              </p>
            )}
          </div>
        )}

        {/* Workspace — Google Sheet link */}
        {workspace?.google_sheet_url && (
          <a
            href={workspace.google_sheet_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 mb-6 rounded-2xl border-2 border-foreground/15 bg-card px-5 py-3 font-bold text-sm hover:border-foreground/40 transition-colors"
          >
            <ExternalLink className="h-4 w-4 text-primary" />
            Open in Google Sheets
          </a>
        )}

        {/* Workspace next actions */}
        {workspace && workspace.next_actions.length > 0 && (
          <div className="mb-6 rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-5">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Next actions
            </div>
            <ul className="space-y-2">
              {workspace.next_actions.map((action) => (
                <li key={action} className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-palm shrink-0 mt-0.5" />
                  <span>{action}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Workspace warnings */}
        {workspace && workspace.warnings.length > 0 && (
          <div className="mb-6 rounded-3xl border-2 border-coral/30 bg-coral/5 p-5">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Friction flags
            </div>
            <ul className="space-y-2">
              {workspace.warnings.map((w) => (
                <li key={w} className="flex items-start gap-2 text-sm">
                  <AlertTriangle className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Master timeline tab */}
        {masterTab && masterTab.rows.length > 0 && (
          <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card overflow-hidden mb-6">
            <div className="px-6 py-4 border-b-2 border-foreground/10 font-[Fredoka] text-xl font-bold">
              {masterTab.name}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b-2 border-foreground/10 bg-muted/30">
                    {masterTab.headers.map((h) => (
                      <th key={h} className="text-left px-4 py-2.5 text-xs font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-foreground/10">
                  {masterTab.rows.map((row, ri) => (
                    <tr key={ri} className="hover:bg-muted/20 transition-colors">
                      {(row as unknown[]).map((cell, ci) => (
                        <td key={ci} className="px-4 py-3 text-sm font-medium">
                          {String(cell ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Trip map */}
        {tripMapPins.length > 0 && (
          <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card overflow-hidden mb-6">
            <div className="px-6 py-4 border-b-2 border-foreground/10 flex items-center justify-between">
              <div className="font-[Fredoka] text-xl font-bold flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-[hsl(var(--primary))]" /> Trip map
              </div>
              <div className="text-xs text-muted-foreground font-semibold">
                {tripMapPins.length} pin{tripMapPins.length === 1 ? "" : "s"} · press ▶ to fly the trip
              </div>
            </div>
            <div className="p-4">
              <TripMap pins={tripMapPins} height="540px" />
            </div>
          </div>
        )}

        {/* All workspace tabs (except master, already shown) */}
        {workspace && timelineTabs.filter((t) => t !== masterTab && t.rows.length > 0).map((tab) => (
          <div key={tab.name} className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card overflow-hidden mb-6">
            <div className="px-6 py-4 border-b-2 border-foreground/10 font-[Fredoka] text-xl font-bold">
              {tab.name}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b-2 border-foreground/10 bg-muted/30">
                    {tab.headers.map((h) => (
                      <th key={h} className="text-left px-4 py-2.5 text-xs font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-foreground/10">
                  {tab.rows.map((row, ri) => (
                    <tr key={ri} className="hover:bg-muted/20 transition-colors">
                      {(row as unknown[]).map((cell, ci) => (
                        <td key={ci} className="px-4 py-3 text-sm font-medium">
                          {String(cell ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}

        {/* Recent activity for this trip */}
        {!tripQuery.isLoading && runLog.length > 0 && (
          <div className="rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-6">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-4 flex items-center gap-2">
              <Clock className="h-4 w-4" /> Trip activity
            </div>
            <ul className="divide-y divide-foreground/10">
              {runLog.slice(-8).reverse().map((e) => (
                <li key={e.event_id} className="py-3 flex items-center justify-between text-sm gap-4">
                  <div>
                    <span className="font-bold">{e.title}</span>
                    {e.summary && <span className="text-muted-foreground"> · {e.summary}</span>}
                  </div>
                  <span className="text-muted-foreground font-semibold shrink-0 text-xs">
                    {e.created_at ? new Date(e.created_at).toLocaleString() : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </AppShell>
  );
};

const ScorePill = ({ label, value }: { label: string; value: number }) => (
  <div className="text-center">
    <div className="text-2xl font-[Fredoka] font-bold">{value}</div>
    <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</div>
  </div>
);

export default Timeline;
