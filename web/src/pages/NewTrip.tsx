import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { trippyClient } from "@/api/trippyClient";
import { ideaToCard, ideaToIntakePayload } from "@/lib/trippyViewModels";
import type { CanvasIdeaCard, IdeaRequest } from "@/types/trippy";
import {
  Sparkles, Send, Calendar, Users, DollarSign, Plane, MapPin,
  ArrowLeft, Wand2, Mountain, UtensilsCrossed, Waves, Building2,
  TreePine, Snowflake, Check, Loader2, AlertTriangle,
} from "lucide-react";

const vibes = [
  { icon: Waves, label: "Beach + chill", color: "hsl(195 90% 65%)" },
  { icon: Mountain, label: "Adventure", color: "hsl(145 55% 38%)" },
  { icon: UtensilsCrossed, label: "Food + culture", color: "hsl(8 90% 65%)" },
  { icon: Building2, label: "City escape", color: "hsl(215 75% 28%)" },
  { icon: TreePine, label: "Nature + wildlife", color: "hsl(178 70% 45%)" },
  { icon: Snowflake, label: "Cold + cozy", color: "hsl(205 88% 48%)" },
];

const defaultPrompt =
  "March break, 9 days, family of 5 from YYZ. We want beach, food, low friction, memorable activities, and not too much driving. Budget around CAD 9000 all-in. Avoid stressful transfers and huge crowds.";

const NewTrip = () => {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"ideate" | "form">("ideate");
  const [prompt, setPrompt] = useState("");
  const [pickedVibes, setPickedVibes] = useState<string[]>(["Beach + chill", "Food + culture"]);
  const [lastIdeaRequest, setLastIdeaRequest] = useState<Record<string, unknown>>({});
  const [creatingIdeaId, setCreatingIdeaId] = useState<string | null>(null);

  const ideasMutation = useMutation({
    mutationFn: (payload: IdeaRequest) => trippyClient.suggestIdeas(payload),
    onSuccess: (response) => {
      setLastIdeaRequest((response.comparison?.request ?? {}) as Record<string, unknown>);
    },
  });

  const createIntakeMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => trippyClient.createIntake(payload),
    onSuccess: async (response) => {
      const tripId = response.intake?.trip_id;
      if (!tripId) return;
      try {
        await trippyClient.draftPlan(tripId);
      } catch {
        // Trip creation succeeded; let Trip Shape surface any draft issue.
      }
      navigate(`/trip/shape?trip_id=${encodeURIComponent(tripId)}`);
    },
    onSettled: () => setCreatingIdeaId(null),
  });

  const ideaCards = useMemo(
    () => (ideasMutation.data?.comparison?.concepts ?? []).map((concept, index) => ideaToCard(concept, index)),
    [ideasMutation.data],
  );

  const toggleVibe = (v: string) =>
    setPickedVibes((p) => (p.includes(v) ? p.filter((x) => x !== v) : [...p, v]));

  const getIdeas = () => {
    const request = promptToIdeaRequest(prompt || defaultPrompt, pickedVibes);
    ideasMutation.mutate(request);
  };

  const pickIdea = (idea: CanvasIdeaCard) => {
    setCreatingIdeaId(idea.id);
    createIntakeMutation.mutate(ideaToIntakePayload(idea, lastIdeaRequest));
  };

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto px-6 py-8 md:py-10">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-bold text-muted-foreground hover:text-foreground transition-colors mb-6">
          <ArrowLeft className="h-4 w-4" /> Back to trips
        </Link>

        <div className="mb-8">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sunshine/30 border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
            <Sparkles className="h-3.5 w-3.5" /> New trip
          </span>
          <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-tight mt-3">
            Let's <span className="text-gradient-sunset">dream up</span> your next trip.
          </h1>
          <p className="text-muted-foreground mt-2 max-w-2xl">
            This page now calls the live Trippy backend. Ideas, scores, and created trips come from `/api/suggest-ideas` and `/api/intake`.
          </p>
        </div>

        <div className="inline-flex p-1.5 rounded-2xl bg-muted border-2 border-foreground/10 mb-6">
          {[
            { id: "ideate", label: "Brain dump", icon: Wand2 },
            { id: "form", label: "Fill the form", icon: Calendar },
          ].map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id as "ideate" | "form")}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-sm transition-bounce ${
                mode === m.id
                  ? "bg-card text-foreground shadow-card border-2 border-foreground/15"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <m.icon className="h-4 w-4" /> {m.label}
            </button>
          ))}
        </div>

        {mode === "ideate" ? (
          <div className="space-y-6">
            <div className="relative rounded-[2rem] border-2 border-foreground bg-card shadow-sticker overflow-hidden">
              <div className="bg-gradient-hero px-6 py-3 border-b-2 border-foreground/15 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <span className="font-bold text-sm">Tell Trippy everything</span>
              </div>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={defaultPrompt}
                rows={5}
                className="w-full p-6 bg-transparent resize-none focus:outline-none text-base leading-relaxed placeholder:text-muted-foreground/70"
              />
              <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-t-2 border-foreground/10 bg-muted/30">
                <InfoChip icon={Calendar} label="Flexible dates" />
                <InfoChip icon={Users} label="Family-aware" />
                <InfoChip icon={DollarSign} label="CAD budget" />
                <InfoChip icon={Plane} label="YYZ default" />
                <Button
                  onClick={getIdeas}
                  disabled={ideasMutation.isPending}
                  className="ml-auto h-11 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-card hover:translate-y-[-2px] transition-bounce px-5"
                >
                  {ideasMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  {ideasMutation.isPending ? "Getting ideas" : "Get ideas"}
                </Button>
              </div>
            </div>

            <div>
              <h3 className="font-[Fredoka] text-lg font-bold mb-3">Or just pick a vibe</h3>
              <div className="flex flex-wrap gap-3">
                {vibes.map((v) => {
                  const on = pickedVibes.includes(v.label);
                  return (
                    <button
                      key={v.label}
                      onClick={() => toggleVibe(v.label)}
                      className={`group flex items-center gap-2 px-4 py-2.5 rounded-2xl font-bold text-sm transition-bounce border-2 ${
                        on
                          ? "border-foreground shadow-sticker text-primary-foreground"
                          : "border-foreground/15 bg-card text-foreground hover:border-foreground/40"
                      }`}
                      style={on ? { background: v.color } : {}}
                    >
                      <v.icon className="h-4 w-4" />
                      {v.label}
                      {on && <Check className="h-4 w-4" />}
                    </button>
                  );
                })}
              </div>
            </div>

            {ideasMutation.error && (
              <div className="rounded-2xl border-2 border-coral/50 bg-coral/10 p-4 text-sm font-semibold flex gap-2">
                <AlertTriangle className="h-5 w-5 text-primary shrink-0" />
                <span>{ideasMutation.error.message}</span>
              </div>
            )}

            {ideaCards.length > 0 && (
              <div className="animate-fade-up">
                <div className="flex items-center justify-between mb-4 mt-4">
                  <h3 className="font-[Fredoka] text-2xl font-bold">
                    Trippy picked <span className="text-gradient-sunset">{ideaCards.length} fits</span>
                  </h3>
                  <button onClick={getIdeas} className="text-sm font-bold text-muted-foreground hover:text-primary">Refresh ideas →</button>
                </div>
                <div className="grid md:grid-cols-3 gap-5">
                  {ideaCards.map((idea, i) => (
                    <div
                      key={idea.id}
                      className="group relative rounded-3xl overflow-hidden border-2 border-foreground/10 bg-card shadow-card hover:-translate-y-1 hover:shadow-glow transition-bounce animate-fade-up"
                      style={{ animationDelay: `${i * 0.08}s` }}
                    >
                      <div className="relative h-32 flex items-center justify-center" style={{ background: ideaGradient(i) }}>
                        <span className="text-6xl drop-shadow-lg">{ideaEmoji(i)}</span>
                        <div className="absolute top-3 right-3 bg-background rounded-full px-2.5 py-1 border-2 border-foreground/20 text-xs font-bold flex items-center gap-1">
                          <Sparkles className="h-3 w-3 text-primary" /> {idea.fit}% fit
                        </div>
                      </div>
                      <div className="p-5">
                        <h4 className="font-[Fredoka] text-xl font-bold">{idea.place}</h4>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground font-semibold mt-0.5">
                          <MapPin className="h-3 w-3" /> {idea.region}
                        </div>
                        <p className="text-sm text-foreground/75 mt-3 leading-relaxed">{idea.why}</p>
                        <div className="flex flex-wrap gap-1.5 mt-4">
                          {idea.tags.slice(0, 4).map((tag) => (
                            <span key={tag} className="px-2 py-0.5 rounded-full bg-muted border border-foreground/10 text-xs font-bold">
                              {tag}
                            </span>
                          ))}
                        </div>
                        {idea.friction.length > 0 && (
                          <div className="mt-3 text-xs text-muted-foreground font-semibold">
                            Watch: {idea.friction.slice(0, 2).join(" · ")}
                          </div>
                        )}
                        <Button
                          onClick={() => pickIdea(idea)}
                          disabled={createIntakeMutation.isPending}
                          className="w-full mt-4 h-10 rounded-xl bg-foreground text-background font-bold hover:bg-foreground/90"
                        >
                          {creatingIdeaId === idea.id ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                          Pick this idea
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <DirectTripForm
            pickedVibes={pickedVibes}
            toggleVibe={toggleVibe}
            onSubmit={(payload) => createIntakeMutation.mutate(payload)}
            isSaving={createIntakeMutation.isPending}
          />
        )}
      </div>
    </AppShell>
  );
};

function promptToIdeaRequest(prompt: string, pickedVibes: string[]): IdeaRequest {
  const text = `${prompt} ${pickedVibes.join(", ")}`.toLowerCase();
  const days = numberMatch(text, /(\d+)\s*(day|days|night|nights)/) ?? 7;
  const budget = numberMatch(text, /(cad|\$|budget|around|~)\s*([0-9][0-9,]*)/) ?? numberMatch(text, /([0-9][0-9,]*)\s*(cad|all-in|budget)/);
  const travelers = numberMatch(text, /family of\s*(\d+)/) ?? numberMatch(text, /(\d+)\s*traveler/) ?? 5;
  const maxFlight = numberMatch(text, /(\d+)\s*(hour|hr|hrs).*flight/);
  return {
    time_of_year: text.includes("march") ? "March break" : "Flexible",
    duration_days: days,
    budget_cad: budget,
    travelers,
    party_type: travelers <= 2 ? "couple" : "whole_family",
    adults: travelers <= 2 ? 2 : 2,
    children: Math.max(0, travelers - 2),
    max_flight_hours: maxFlight,
    direct_flight_preferred: !text.includes("long-haul"),
    goals: [prompt, ...pickedVibes].filter(Boolean).join(", "),
    avoidances: text.includes("crowd") ? "huge crowds, stressful transfers" : "stressful transfers",
    desired_vibe: pickedVibes.join(", "),
    activity_level: text.includes("adventure") ? "active" : "balanced",
  };
}

function numberMatch(text: string, pattern: RegExp): number | undefined {
  const match = text.match(pattern);
  const raw = match?.[1] && /\d/.test(match[1]) ? match[1] : match?.[2];
  const value = raw ? Number(String(raw).replace(/,/g, "")) : Number.NaN;
  return Number.isFinite(value) ? value : undefined;
}

function ideaGradient(index: number) {
  return [
    "linear-gradient(135deg, hsl(178 70% 45%), hsl(145 55% 38%))",
    "linear-gradient(135deg, hsl(45 100% 60%), hsl(8 90% 65%))",
    "linear-gradient(135deg, hsl(8 90% 65%), hsl(18 95% 55%))",
  ][index % 3];
}

function ideaEmoji(index: number) {
  return ["🌴", "🐚", "🗺️", "✈️"][index % 4];
}

const InfoChip = ({ icon: Icon, label }: { icon: React.ComponentType<{ className?: string }>; label: string }) => (
  <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/15 text-sm font-bold">
    <Icon className="h-3.5 w-3.5" /> {label}
  </span>
);

const DirectTripForm = ({
  pickedVibes,
  toggleVibe,
  onSubmit,
  isSaving,
}: {
  pickedVibes: string[];
  toggleVibe: (v: string) => void;
  onSubmit: (payload: Record<string, unknown>) => void;
  isSaving: boolean;
}) => {
  const [form, setForm] = useState({
    trip_name: "Spring break 2026",
    destinations: "",
    travel_window: "Mar 14 – Mar 23",
    duration: "9 days",
    travelers: "5",
    adults: "2",
    children: "3",
    budget_cad: "9000",
    departure_airports: "YYZ",
    avoidances: "No red-eyes. No long-haul. No 6am wake-ups.",
  });
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <div className="rounded-[2rem] border-2 border-foreground/15 bg-card shadow-card p-7 md:p-9 space-y-6">
      <FormRow label="Trip name" hint="Saved directly into Trippy">
        <input value={form.trip_name} onChange={(e) => update("trip_name", e.target.value)} className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary" />
      </FormRow>
      <div className="grid md:grid-cols-2 gap-5">
        <FormRow label="Destination"><input value={form.destinations} onChange={(e) => update("destinations", e.target.value)} placeholder="Azores, Cayman, Japan..." className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary" /></FormRow>
        <FormRow label="Dates"><DummyInput icon={Calendar} value={form.travel_window} onChange={(v) => update("travel_window", v)} /></FormRow>
        <FormRow label="Who's going"><DummyInput icon={Users} value={`${form.travelers} travelers`} onChange={() => undefined} /></FormRow>
        <FormRow label="Budget CAD"><DummyInput icon={DollarSign} value={form.budget_cad} onChange={(v) => update("budget_cad", v)} /></FormRow>
        <FormRow label="Departing from"><DummyInput icon={Plane} value={form.departure_airports} onChange={(v) => update("departure_airports", v)} /></FormRow>
        <FormRow label="Duration"><input value={form.duration} onChange={(e) => update("duration", e.target.value)} className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary" /></FormRow>
      </div>
      <FormRow label="Vibes" hint="Saved as goals">
        <div className="flex flex-wrap gap-2">
          {vibes.map((v) => {
            const on = pickedVibes.includes(v.label);
            return (
              <button key={v.label} onClick={() => toggleVibe(v.label)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 text-sm font-bold transition-bounce ${on ? "bg-foreground text-background border-foreground" : "border-foreground/15 hover:border-foreground/40"}`}>
                <v.icon className="h-3.5 w-3.5" /> {v.label}
              </button>
            );
          })}
        </div>
      </FormRow>
      <FormRow label="Hard nos" hint="Trippy will avoid these">
        <input value={form.avoidances} onChange={(e) => update("avoidances", e.target.value)} className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary" />
      </FormRow>
      <div className="flex justify-end gap-3 pt-2 border-t-2 border-foreground/10">
        <Button
          onClick={() => onSubmit({
            ...form,
            party_type: Number(form.travelers) <= 2 ? "couple" : "whole_family",
            travelers: Number(form.travelers),
            adults: Number(form.adults),
            children: Number(form.children),
            goals: pickedVibes.join(", "),
          })}
          disabled={isSaving || !form.trip_name || !form.destinations}
          className="h-12 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-6"
        >
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Save and open trip shape
        </Button>
      </div>
    </div>
  );
};

const FormRow = ({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) => (
  <div>
    <div className="flex items-baseline justify-between mb-2">
      <label className="font-[Fredoka] font-bold text-base">{label}</label>
      {hint && <span className="text-xs text-muted-foreground font-semibold">{hint}</span>}
    </div>
    {children}
  </div>
);

const DummyInput = ({ icon: Icon, value, onChange }: { icon: React.ComponentType<{ className?: string }>; value: string; onChange: (value: string) => void }) => (
  <div className="relative">
    <Icon className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
    <input value={value} onChange={(event) => onChange(event.target.value)} className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background pl-10 pr-4 font-medium focus:outline-none focus:border-primary" />
  </div>
);

export default NewTrip;
