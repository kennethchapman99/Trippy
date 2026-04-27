import { useState } from "react";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import {
  Sparkles, Send, Calendar, Users, DollarSign, Plane, MapPin,
  ArrowLeft, Wand2, Mountain, UtensilsCrossed, Waves, Building2,
  TreePine, Snowflake, Check,
} from "lucide-react";

const vibes = [
  { icon: Waves, label: "Beach + chill", color: "hsl(195 90% 65%)" },
  { icon: Mountain, label: "Adventure", color: "hsl(145 55% 38%)" },
  { icon: UtensilsCrossed, label: "Food + culture", color: "hsl(8 90% 65%)" },
  { icon: Building2, label: "City escape", color: "hsl(215 75% 28%)" },
  { icon: TreePine, label: "Nature + wildlife", color: "hsl(178 70% 45%)" },
  { icon: Snowflake, label: "Cold + cozy", color: "hsl(205 88% 48%)" },
];

const ideas = [
  {
    place: "Costa Rica",
    region: "Manuel Antonio + Arenal",
    fit: 94,
    tags: ["Beach", "Wildlife", "Kid-friendly"],
    why: "Matches your 'less driving with kids' rule. Direct flight from JFK. Sloths.",
    emoji: "🦥",
    color: "linear-gradient(135deg, hsl(178 70% 45%), hsl(145 55% 38%))",
  },
  {
    place: "Portugal",
    region: "Lisbon + Algarve coast",
    fit: 88,
    tags: ["Food", "Beach", "Easy logistics"],
    why: "You loved Lisbon last May. Algarve adds the beach week kids want.",
    emoji: "🐚",
    color: "linear-gradient(135deg, hsl(45 100% 60%), hsl(8 90% 65%))",
  },
  {
    place: "Japan",
    region: "Tokyo + Hakone + Kyoto",
    fit: 81,
    tags: ["Culture", "Food", "Bucket list"],
    why: "Long flight is the friction. Spring cherry-blossom window aligns with break.",
    emoji: "🌸",
    color: "linear-gradient(135deg, hsl(8 90% 65%), hsl(18 95% 55%))",
  },
];

const NewTrip = () => {
  const [mode, setMode] = useState<"ideate" | "form">("ideate");
  const [prompt, setPrompt] = useState("");
  const [pickedVibes, setPickedVibes] = useState<string[]>(["Beach + chill", "Food + culture"]);
  const [showIdeas, setShowIdeas] = useState(false);

  const toggleVibe = (v: string) =>
    setPickedVibes((p) => (p.includes(v) ? p.filter((x) => x !== v) : [...p, v]));

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
              onClick={() => { setMode(m.id as "ideate" | "form"); setShowIdeas(false); }}
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
          /* IDEATE MODE */
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
                <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/15 text-sm font-bold hover:border-primary/40 transition-colors">
                  <Calendar className="h-3.5 w-3.5" /> Mar 14–23
                </button>
                <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/15 text-sm font-bold hover:border-primary/40 transition-colors">
                  <Users className="h-3.5 w-3.5" /> Family of 4
                </button>
                <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/15 text-sm font-bold hover:border-primary/40 transition-colors">
                  <DollarSign className="h-3.5 w-3.5" /> ~$7k
                </button>
                <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card border-2 border-foreground/15 text-sm font-bold hover:border-primary/40 transition-colors">
                  <Plane className="h-3.5 w-3.5" /> From JFK
                </button>
                <Button
                  onClick={() => setShowIdeas(true)}
                  className="ml-auto h-11 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-card hover:translate-y-[-2px] transition-bounce px-5"
                >
                  <Send className="h-4 w-4" /> Get ideas
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
            </div>

            {/* Ideas grid */}
            {showIdeas && (
              <div className="animate-fade-up">
                <div className="flex items-center justify-between mb-4 mt-4">
                  <h3 className="font-[Fredoka] text-2xl font-bold">
                    Hermes picked <span className="text-gradient-sunset">3 fits</span>
                  </h3>
                  <button className="text-sm font-bold text-muted-foreground hover:text-primary">Show 3 more →</button>
                </div>
                <div className="grid md:grid-cols-3 gap-5">
                  {ideas.map((idea, i) => (
                    <div
                      key={idea.place}
                      className="group relative rounded-3xl overflow-hidden border-2 border-foreground/10 bg-card shadow-card hover:-translate-y-1 hover:shadow-glow transition-bounce animate-fade-up"
                      style={{ animationDelay: `${i * 0.08}s` }}
                    >
                      <div className="relative h-32 flex items-center justify-center" style={{ background: idea.color }}>
                        <span className="text-6xl drop-shadow-lg">{idea.emoji}</span>
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
                          {idea.tags.map((tag) => (
                            <span key={tag} className="px-2 py-0.5 rounded-full bg-muted border border-foreground/10 text-xs font-bold">
                              {tag}
                            </span>
                          ))}
                        </div>
                        <Button className="w-full mt-4 h-10 rounded-xl bg-foreground text-background font-bold hover:bg-foreground/90">
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
          /* FORM MODE */
          <div className="rounded-[2rem] border-2 border-foreground/15 bg-card shadow-card p-7 md:p-9 space-y-6">
            <FormRow label="Trip name" hint="You can change this later">
              <input
                placeholder="Spring break 2026"
                className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary"
              />
            </FormRow>

            <div className="grid md:grid-cols-2 gap-5">
              <FormRow label="Dates"><DummyInput icon={Calendar} placeholder="Mar 14 – Mar 23" /></FormRow>
              <FormRow label="Who's going"><DummyInput icon={Users} placeholder="2 adults, 2 kids (8, 11)" /></FormRow>
              <FormRow label="Budget (all-in USD)"><DummyInput icon={DollarSign} placeholder="7000" /></FormRow>
              <FormRow label="Departing from"><DummyInput icon={Plane} placeholder="JFK / LGA / EWR" /></FormRow>
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
                placeholder="No red-eyes. No long-haul. No 6am wake-ups."
                className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background px-4 font-medium focus:outline-none focus:border-primary"
              />
            </FormRow>

            <div className="flex justify-end gap-3 pt-2 border-t-2 border-foreground/10">
              <Button variant="outline" className="h-12 rounded-xl font-bold border-2 border-foreground/20 px-5">
                Save as draft
              </Button>
              <Button
                onClick={() => { setMode("ideate"); setShowIdeas(true); }}
                className="h-12 rounded-xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-6"
              >
                <Sparkles className="h-4 w-4" /> Generate ideas
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

const DummyInput = ({ icon: Icon, placeholder }: { icon: React.ComponentType<{ className?: string }>; placeholder: string }) => (
  <div className="relative">
    <Icon className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
    <input
      placeholder={placeholder}
      className="h-12 w-full rounded-xl border-2 border-foreground/10 bg-background pl-10 pr-4 font-medium focus:outline-none focus:border-primary"
    />
  </div>
);

export default NewTrip;
