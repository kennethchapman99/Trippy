import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import {
  Sparkles, Send, Calendar, Users, DollarSign, Plane, MapPin,
  ArrowLeft, Wand2, Mountain, UtensilsCrossed, Waves, Building2,
  TreePine, Snowflake, Check, Loader2, AlertCircle,
} from "lucide-react";
import { api, type TripConcept } from "@/lib/api";

const vibes = [
  { icon: Waves, label: "Beach + chill", color: "hsl(195 90% 65%)" },
  { icon: Mountain, label: "Adventure", color: "hsl(145 55% 38%)" },
  { icon: UtensilsCrossed, label: "Food + culture", color: "hsl(8 90% 65%)" },
  { icon: Building2, label: "City escape", color: "hsl(215 75% 28%)" },
  { icon: TreePine, label: "Nature + wildlife", color: "hsl(178 70% 45%)" },
  { icon: Snowflake, label: "Cold + cozy", color: "hsl(205 88% 48%)" },
];

const COVER_GRADIENTS = [
  "linear-gradient(135deg, hsl(178 70% 45%), hsl(145 55% 38%))",
  "linear-gradient(135deg, hsl(45 100% 60%), hsl(8 90% 65%))",
  "linear-gradient(135deg, hsl(8 90% 65%), hsl(18 95% 55%))",
  "linear-gradient(135deg, hsl(205 88% 48%), hsl(215 75% 28%))",
];

const EMOJIS = ["🌴", "🐚", "🌸", "🧊", "🗺️", "✈️"];

function conceptToIdeaPayload(concept: TripConcept): Record<string, unknown> {
  return {
    trip_name: concept.title,
    destinations: concept.destinations,
    mode: "destination_exploration",
    goals: concept.rationale.slice(0, 3),
    avoidances: concept.why_it_may_not_fit.slice(0, 2),
    travelers: 5,
    adults: 2,
    children: 3,
    party_type: "whole_family",
    duration_days: concept.recommended_duration_days,
  };
}

const NewTrip = () => {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"ideate" | "form">("ideate");
  const [prompt, setPrompt] = useState("");
  const [pickedVibes, setPickedVibes] = useState<string[]>(["Beach + chill", "Food + culture"]);
  const [concepts, setConcepts] = useState<TripConcept[]>([]);

  // Form fields
  const [tripName, setTripName] = useState("");
  const [dates, setDates] = useState("");
  const [who, setWho] = useState("");
  const [budget, setBudget] = useState("");
  const [origin, setOrigin] = useState("");
  const [hardNos, setHardNos] = useState("");

  const toggleVibe = (v: string) =>
    setPickedVibes((p) => (p.includes(v) ? p.filter((x) => x !== v) : [...p, v]));

  const ideaMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.suggestIdeas(payload),
    onSuccess: (data) => setConcepts(data.comparison.concepts),
  });

  const intakeMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.createIntake(payload),
    onSuccess: (data) => navigate(`/trip/${data.intake.trip_id}/shape`),
  });

  const handleGetIdeas = () => {
    ideaMutation.mutate({
      desired_vibe: pickedVibes.join(", ") || undefined,
      goals: prompt || undefined,
      travelers: 5,
      adults: 2,
      children: 3,
      party_type: "whole_family",
    });
  };

  const handlePickConcept = (concept: TripConcept) => {
    intakeMutation.mutate(conceptToIdeaPayload(concept));
  };

  const handleFormSubmit = () => {
    const budgetNum = parseFloat(budget.replace(/[^0-9.]/g, "")) || undefined;
    const payload: Record<string, unknown> = {
      trip_name: tripName || "New trip",
      mode: "destination_exploration",
      goals: pickedVibes,
      avoidances: hardNos ? [hardNos] : [],
      travelers: 5,
      adults: 2,
      children: 3,
      party_type: "whole_family",
      budget_cad: budgetNum,
      departure_airports: origin ? [origin] : ["YYZ"],
    };
    // Generate ideas first, then switch to ideate mode
    setMode("ideate");
    ideaMutation.mutate(payload);
    if (!intakeMutation.isPending) {
      intakeMutation.mutate(payload);
    }
  };

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto px-6 py-8 md:py-10">
        {/* Back */}
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-bold text-muted-foreground hover:text-foreground transition-colors mb-6">
          <ArrowLeft className="h-4 w-4" /> Back to trips
        </Link>

        {/* Header */}
        <div className="mb-8">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sunshine/30 border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
            <Sparkles className="h-3.5 w-3.5" /> New trip
          </span>
          <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-tight mt-3">
            Let's <span className="text-gradient-sunset">dream up</span> your next trip.
          </h1>
          <p className="text-muted-foreground mt-2 max-w-2xl">
            Tell Hermes what you're craving — or fill the form if you already know. Either way, we'll come back with ranked, family-fit ideas.
          </p>
        </div>

        {/* Mode toggle */}
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
            {/* Prompt box */}
            <div className="relative rounded-[2rem] border-2 border-foreground bg-card shadow-sticker overflow-hidden">
              <div className="bg-gradient-hero px-6 py-3 border-b-2 border-foreground/15 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <span className="font-bold text-sm">Tell Hermes everything</span>
              </div>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="e.g. March break, 9 days, family of 4, kids are 8 and 11. We loved Lisbon last spring. Want beach + some culture, not too much driving. Budget around $7k all-in. No long-haul flights."
                rows={5}
                className="w-full p-6 bg-transparent resize-none focus:outline-none text-base leading-relaxed placeholder:text-muted-foreground/70"
              />
              <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-t-2 border-foreground/10 bg-muted/30">
                <Button
                  onClick={handleGetIdeas}
                  disabled={ideaMutation.isPending}
                  className="ml-auto h-11 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-card hover:translate-y-[-2px] transition-bounce px-5"
                >
                  {ideaMutation.isPending ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Thinking…</>
                  ) : (
                    <><Send className="h-4 w-4" /> Get ideas</>
                  )}
                </Button>
              </div>
            </div>

            {/* Vibe chips */}
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
              {pickedVibes.length > 0 && concepts.length === 0 && (
                <button
                  onClick={handleGetIdeas}
                  disabled={ideaMutation.isPending}
                  className="mt-4 text-sm font-bold text-primary hover:underline"
                >
                  {ideaMutation.isPending ? "Getting ideas…" : "Get ideas for these vibes →"}
                </button>
              )}
            </div>

            {/* Error */}
            {ideaMutation.isError && (
              <div className="flex items-start gap-3 rounded-2xl border-2 border-destructive/30 bg-destructive/5 p-4">
                <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-bold text-destructive">Couldn't get ideas</div>
                  <div className="text-muted-foreground mt-1">
                    {(ideaMutation.error as Error)?.message ?? "Check that the Hermes backend is running."}
                  </div>
                </div>
              </div>
            )}

            {/* Ideas grid */}
            {concepts.length > 0 && (
              <div className="animate-fade-up">
                <div className="flex items-center justify-between mb-4 mt-4">
                  <h3 className="font-[Fredoka] text-2xl font-bold">
                    Hermes picked <span className="text-gradient-sunset">{concepts.length} fits</span>
                  </h3>
                  <button
                    onClick={handleGetIdeas}
                    disabled={ideaMutation.isPending}
                    className="text-sm font-bold text-muted-foreground hover:text-primary"
                  >
                    {ideaMutation.isPending ? "Refreshing…" : "Refresh →"}
                  </button>
                </div>
                <div className="grid md:grid-cols-3 gap-5">
                  {concepts.map((concept, i) => (
                    <div
                      key={concept.concept_id}
                      className="group relative rounded-3xl overflow-hidden border-2 border-foreground/10 bg-card shadow-card hover:-translate-y-1 hover:shadow-glow transition-bounce animate-fade-up"
                      style={{ animationDelay: `${i * 0.08}s` }}
                    >
                      <div className="relative h-32 flex items-center justify-center" style={{ background: COVER_GRADIENTS[i % COVER_GRADIENTS.length] }}>
                        <span className="text-6xl drop-shadow-lg">{EMOJIS[i % EMOJIS.length]}</span>
                        <div className="absolute top-3 right-3 bg-background rounded-full px-2.5 py-1 border-2 border-foreground/20 text-xs font-bold flex items-center gap-1">
                          <Sparkles className="h-3 w-3 text-primary" /> {concept.family_fit_score}% fit
                        </div>
                      </div>
                      <div className="p-5">
                        <h4 className="font-[Fredoka] text-xl font-bold">{concept.title}</h4>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground font-semibold mt-0.5">
                          <MapPin className="h-3 w-3" /> {concept.destinations.join(" · ")}
                        </div>
                        <p className="text-sm text-foreground/75 mt-3 leading-relaxed">
                          {concept.rationale[0] ?? concept.estimated_travel_burden}
                        </p>
                        <div className="flex flex-wrap gap-1.5 mt-4">
                          {[concept.estimated_cost_band_cad, concept.best_season, `${concept.recommended_duration_days}d`].filter(Boolean).map((tag) => (
                            <span key={tag} className="px-2 py-0.5 rounded-full bg-muted border border-foreground/10 text-xs font-bold">
                              {tag}
                            </span>
                          ))}
                        </div>
                        <Button
                          onClick={() => handlePickConcept(concept)}
                          disabled={intakeMutation.isPending}
                          className="w-full mt-4 h-10 rounded-xl bg-foreground text-background font-bold hover:bg-foreground/90"
                        >
                          {intakeMutation.isPending ? (
                            <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
                          ) : (
                            "Pick this idea"
                          )}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          /* FORM MODE */
          <div className="rounded-[2rem] border-2 border-foreground/15 bg-card shadow-card p-7 md:p-9 space-y-6">
            <FormRow label="Trip name" hint="You can change this later">
              <input
                value={tripName}
                onChange={(e) => setTripName(e.target.value)}
                placeholder="Spring break 2026"
                className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary"
              />
            </FormRow>

            <div className="grid md:grid-cols-2 gap-5">
              <FormRow label="Dates">
                <div className="relative">
                  <Calendar className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    value={dates}
                    onChange={(e) => setDates(e.target.value)}
                    placeholder="Mar 14 – Mar 23"
                    className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background pl-10 pr-4 font-medium focus:outline-none focus:border-primary"
                  />
                </div>
              </FormRow>
              <FormRow label="Who's going">
                <div className="relative">
                  <Users className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    value={who}
                    onChange={(e) => setWho(e.target.value)}
                    placeholder="2 adults, 2 kids (8, 11)"
                    className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background pl-10 pr-4 font-medium focus:outline-none focus:border-primary"
                  />
                </div>
              </FormRow>
              <FormRow label="Budget (all-in CAD)">
                <div className="relative">
                  <DollarSign className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                    placeholder="7000"
                    className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background pl-10 pr-4 font-medium focus:outline-none focus:border-primary"
                  />
                </div>
              </FormRow>
              <FormRow label="Departing from">
                <div className="relative">
                  <Plane className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    value={origin}
                    onChange={(e) => setOrigin(e.target.value)}
                    placeholder="YYZ / YUL / YVR"
                    className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background pl-10 pr-4 font-medium focus:outline-none focus:border-primary"
                  />
                </div>
              </FormRow>
            </div>

            <FormRow label="Vibes" hint="Pick as many as fit">
              <div className="flex flex-wrap gap-2">
                {vibes.map((v) => {
                  const on = pickedVibes.includes(v.label);
                  return (
                    <button
                      key={v.label}
                      onClick={() => toggleVibe(v.label)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 text-sm font-bold transition-bounce ${
                        on ? "bg-foreground text-background border-foreground" : "border-foreground/15 hover:border-foreground/40"
                      }`}
                    >
                      <v.icon className="h-3.5 w-3.5" /> {v.label}
                    </button>
                  );
                })}
              </div>
            </FormRow>

            <FormRow label="Hard nos" hint="Hermes will avoid these">
              <input
                value={hardNos}
                onChange={(e) => setHardNos(e.target.value)}
                placeholder="No red-eyes. No long-haul. No 6am wake-ups."
                className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary"
              />
            </FormRow>

            {intakeMutation.isError && (
              <div className="flex items-start gap-3 rounded-2xl border-2 border-destructive/30 bg-destructive/5 p-4">
                <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                <div className="text-sm text-destructive font-medium">
                  {(intakeMutation.error as Error)?.message ?? "Failed to save trip."}
                </div>
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2 border-t-2 border-foreground/10">
              <Button variant="outline" className="h-12 rounded-xl font-bold border-2 border-foreground/20 px-5">
                Save as draft
              </Button>
              <Button
                onClick={handleFormSubmit}
                disabled={intakeMutation.isPending || ideaMutation.isPending}
                className="h-12 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-6"
              >
                {intakeMutation.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
                ) : (
                  <><Sparkles className="h-4 w-4" /> Start planning</>
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
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

export default NewTrip;
