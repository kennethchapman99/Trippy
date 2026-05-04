import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ExternalLink, Loader2, RefreshCcw } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { EmptyShortlist } from "@/components/EmptyShortlist";
import { ShortlistHero } from "@/components/ShortlistHero";
import { StageNav } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import { api, mergeShortlistIntoTrip, type FlightOption, type TripState } from "@/lib/api";
import { flightFlowApi, type FlightFlowResponse } from "@/lib/flightFlowApi";
import { buildStages } from "@/lib/stages";

export default function FlightsFlow() {
  const { tripId } = useParams<{ tripId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [autoReturnSearchFor, setAutoReturnSearchFor] = useState("");

  const tripQuery = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.getTrip(tripId!),
    enabled: !!tripId,
    staleTime: 30_000,
  });
  const flowQuery = useQuery({
    queryKey: ["flight-flow", tripId],
    queryFn: () => flightFlowApi.getState(tripId!),
    enabled: !!tripId,
    staleTime: 10_000,
  });

  function mergeFlow(response: FlightFlowResponse) {
    queryClient.setQueryData<FlightFlowResponse>(["flight-flow", tripId], response);
    if (response.shortlist) {
      queryClient.setQueryData<TripState>(["trip", tripId], (current) =>
        mergeShortlistIntoTrip(current, response.shortlist!),
      );
    }
    queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    queryClient.invalidateQueries({ queryKey: ["flight-flow", tripId] });
  }

  const searchDepartures = useMutation({ mutationFn: () => flightFlowApi.searchDepartures(tripId!), onSuccess: mergeFlow });
  const selectDeparture = useMutation({ mutationFn: (id: string) => flightFlowApi.selectDeparture(tripId!, id), onSuccess: (r) => { setAutoReturnSearchFor(""); mergeFlow(r); } });
  const searchReturns = useMutation({ mutationFn: () => flightFlowApi.searchReturns(tripId!), onSuccess: mergeFlow });
  const selectReturn = useMutation({ mutationFn: (id: string) => flightFlowApi.selectReturn(tripId!, id), onSuccess: mergeFlow });
  const resetDeparture = useMutation({ mutationFn: () => flightFlowApi.resetDeparture(tripId!), onSuccess: (r) => { setAutoReturnSearchFor(""); mergeFlow(r); } });

  const trip = tripQuery.data;
  const flow = flowQuery.data?.flight_flow;
  const stages = buildStages(trip, "flights");
  const activePhase = flow?.phase === "return_required" ? "return" : "departure";
  const rows = (activePhase === "return" ? flow?.return_options ?? [] : flow?.departure_options ?? []).filter(isVisibleFlight);
  const busy = searchDepartures.isPending || selectDeparture.isPending || searchReturns.isPending || selectReturn.isPending || resetDeparture.isPending;
  const error = tripQuery.error || flowQuery.error || searchDepartures.error || searchReturns.error || selectDeparture.error || selectReturn.error || resetDeparture.error;

  useEffect(() => {
    if (!flow || flow.phase !== "return_required") return;
    const id = flow.selected_departure?.option_id;
    if (!id || flow.return_options.length > 0 || autoReturnSearchFor === id) return;
    setAutoReturnSearchFor(id);
    searchReturns.mutate();
  }, [flow?.phase, flow?.selected_departure?.option_id, flow?.return_options.length, autoReturnSearchFor]);

  const title = flow?.phase === "locked" ? "Flights locked." : activePhase === "return" ? "Pick your return flight." : "Pick your departure flight.";
  const researchLabel = activePhase === "return" ? "Research returns" : "Research departures";

  return (
    <AppShell>
      <ShortlistHero intake={trip?.intake} shortlists={trip?.shortlists} stageLabel="Flights" stageNumber={3} flagCount={rows.reduce((sum, row) => sum + row.friction_flags.length, 0)} />
      <div className="px-4 md:px-6 lg:px-8 py-4 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30"><StageNav stages={stages} /></div>
      <div className="px-4 md:px-6 lg:px-8 py-6">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-4">
          <div><div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">Stage 3 · Flights</div><h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">{title}</h2></div>
          <button onClick={() => activePhase === "return" ? searchReturns.mutate() : searchDepartures.mutate()} disabled={busy} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border-2 border-foreground/15 text-sm font-bold hover:border-foreground/40 transition-colors">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            {researchLabel}
          </button>
        </div>

        <FlightGateStatus flow={flow} />

        {error && <div className="rounded-2xl border-2 border-destructive/30 bg-destructive/5 p-4 mb-4 text-sm font-bold text-destructive">{(error as Error)?.message || String(error)}</div>}
        {(tripQuery.isLoading || flowQuery.isLoading) && <div className="flex items-center justify-center py-24 text-muted-foreground gap-3"><Loader2 className="h-6 w-6 animate-spin" /><span className="font-bold">Loading...</span></div>}

        {flow?.selected_departure && <SelectedFlight label="Departure selected" option={flow.selected_departure} />}
        {flow?.phase === "return_required" && <div className="mb-4 flex gap-2 flex-wrap"><Button variant="outline" className="rounded-xl border-2 font-bold" disabled={busy} onClick={() => resetDeparture.mutate()}>Change departure</Button><Button variant="outline" className="rounded-xl border-2 font-bold" disabled={busy} onClick={() => searchReturns.mutate()}><RefreshCcw className="h-4 w-4" /> Re-research returns</Button></div>}
        {flow?.selected_return && <SelectedFlight label="Return selected" option={flow.selected_return} />}
        {flow?.phase === "return_required" && <div className="rounded-2xl border-2 border-foreground/10 bg-card p-4 mb-4 text-sm font-bold text-muted-foreground">Return search: {flow.selected_departure?.arrival_airport} to {flow.selected_departure?.departure_airport}</div>}

        {rows.length === 0 && !flowQuery.isLoading && <EmptyShortlist title={activePhase === "return" ? "No return rows yet" : "No departure options yet"} description={activePhase === "return" ? "Re-run return research. The backend should return live rows or fallback return-search rows." : "Search departure options first."} ctaLabel={researchLabel} onBuild={() => activePhase === "return" ? searchReturns.mutate() : searchDepartures.mutate()} isLoading={busy} isError={Boolean(error)} errorMessage={(error as Error)?.message} />}

        <div className="flex flex-col gap-4">
          {rows.map((row) => <FlightCard key={`${activePhase}-${row.option_id}`} option={row} selected={activePhase === "return" ? row.option_id === flow?.selected_return?.option_id : row.option_id === flow?.selected_departure?.option_id} activePhase={activePhase} busy={busy} onSelect={() => activePhase === "return" ? selectReturn.mutate(row.option_id) : selectDeparture.mutate(row.option_id)} />)}
        </div>

        {flow?.can_continue && <div className="mt-6 flex justify-end"><Button onClick={() => navigate(`/trip/${tripId}/stays`)} className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker px-8">Continue to Stays <ArrowRight className="h-4 w-4" /></Button></div>}
      </div>
    </AppShell>
  );
}

function FlightGateStatus({ flow }: { flow: FlightFlowResponse["flight_flow"] | undefined }) {
  const departureDone = Boolean(flow?.selected_departure);
  const returnDone = Boolean(flow?.selected_return);
  const locked = flow?.phase === "locked" && departureDone && returnDone;
  const items = [
    { label: "1. Departure flight", done: departureDone, detail: departureDone ? routeLabel(flow?.selected_departure) : "required to set trip start" },
    { label: "2. Return flight", done: returnDone, detail: returnDone ? routeLabel(flow?.selected_return) : "required to set trip end" },
    { label: "3. Trip dates", done: locked, detail: locked ? "locked from selected flights" : "not final yet" },
  ];
  return (
    <div className="rounded-2xl border-2 border-foreground/10 bg-card p-4 mb-4">
      <div className="font-bold text-foreground mb-3">Trip date lock requires both envelope flights</div>
      <div className="grid gap-2 md:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className={`rounded-xl border-2 px-3 py-2 ${item.done ? "border-palm/30 bg-palm/5" : "border-foreground/10 bg-background/60"}`}>
            <div className="text-sm font-bold flex items-center gap-2">{item.done && <Check className="h-4 w-4 text-palm" />}{item.label}</div>
            <div className="text-xs text-muted-foreground mt-1">{item.detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function routeLabel(option: FlightOption | null | undefined): string {
  if (!option) return "";
  return `${option.departure_airport} to ${option.arrival_airport}`;
}

function SelectedFlight({ label, option }: { label: string; option: FlightOption }) {
  return <div className="rounded-2xl border-2 border-foreground/10 bg-card p-4 mb-4 text-sm"><div className="font-bold text-foreground">{label}</div><div className="text-muted-foreground mt-1">{option.departure_airport} to {option.arrival_airport} · arrives {option.arrival_date} {option.arrival_time} · {option.airline}</div></div>;
}

function FlightCard({ option, selected, activePhase, busy, onSelect }: { option: FlightOption; selected: boolean; activePhase: "departure" | "return"; busy: boolean; onSelect: () => void }) {
  return <article className={`rounded-3xl border-2 bg-card overflow-hidden ${selected ? "border-foreground shadow-sticker" : "border-foreground/10 shadow-card"}`}><div className="px-5 py-3 border-b-2 border-foreground/10 flex items-center gap-3"><span className="font-bold truncate">{option.airline}</span><span className="text-xs text-muted-foreground font-mono">{option.flight_numbers.join(" → ")}</span></div><div className="grid grid-cols-1 md:grid-cols-3 gap-5 px-5 py-5"><TimeBlock time={option.departure_time} subline={`${option.departure_date} · ${option.departure_airport}`} /><TimeBlock time={option.arrival_time} subline={`${option.arrival_date} · ${option.arrival_airport}`} /><div className="md:text-right font-[Fredoka] text-3xl font-bold text-palm">{priceText(option)}</div></div>{option.friction_flags.length > 0 && <div className="mx-5 mb-4 rounded-xl border border-coral/40 bg-coral/5 px-3 py-2 text-xs">{option.friction_flags.slice(0, 3).join(" · ")}</div>}<div className="px-5 py-3 border-t-2 border-foreground/10 flex items-center gap-3"><Button onClick={onSelect} disabled={busy} className="h-10 rounded-xl font-bold border-2 px-5">{selected ? <><Check className="h-4 w-4" /> Selected</> : activePhase === "return" ? "Select return" : "Select departure"}</Button>{option.deep_link && <a href={option.deep_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-bold text-foreground/80 hover:text-foreground"><ExternalLink className="h-3.5 w-3.5" /> Open search</a>}</div></article>;
}

function TimeBlock({ time, subline }: { time: string; subline: string }) { return <div><div className="font-[Fredoka] text-3xl md:text-4xl font-bold">{time || "-"}</div><div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mt-1.5">{subline}</div></div>; }
function isVisibleFlight(option: FlightOption): boolean { return !/duffel airways/i.test(option.airline || "") && !(option.flight_numbers || []).some((n) => /^ZZ/i.test(n)); }
function priceText(option: FlightOption): string { return option.fare_estimate_cad || option.price_band || "Quote required"; }
