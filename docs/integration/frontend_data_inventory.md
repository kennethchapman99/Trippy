# Frontend data inventory

/Users/kchapman/Hermes/Trippy/web/src/components/ui/command.tsx:47:        "flex h-11 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
/Users/kchapman/Hermes/Trippy/web/src/components/ui/sidebar.tsx:52:  const [openMobile, setOpenMobile] = React.useState(false);
/Users/kchapman/Hermes/Trippy/web/src/components/ui/sidebar.tsx:56:  const [_open, _setOpen] = React.useState(defaultOpen);
/Users/kchapman/Hermes/Trippy/web/src/components/ui/select.tsx:20:      "flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
/Users/kchapman/Hermes/Trippy/web/src/components/ui/textarea.tsx:11:        "flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
/Users/kchapman/Hermes/Trippy/web/src/components/ui/input.tsx:11:          "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
/Users/kchapman/Hermes/Trippy/web/src/components/ui/carousel.tsx:50:    const [canScrollPrev, setCanScrollPrev] = React.useState(false);
/Users/kchapman/Hermes/Trippy/web/src/components/ui/carousel.tsx:51:    const [canScrollNext, setCanScrollNext] = React.useState(false);
/Users/kchapman/Hermes/Trippy/web/src/hooks/use-mobile.tsx:6:  const [isMobile, setIsMobile] = React.useState<boolean | undefined>(undefined);
/Users/kchapman/Hermes/Trippy/web/src/hooks/use-toast.ts:167:  const [state, setState] = React.useState<State>(memoryState);
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:1:import { useState } from "react";
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:51:  const [mode, setMode] = useState<"ideate" | "form">("ideate");
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:52:  const [prompt, setPrompt] = useState("");
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:53:  const [pickedVibes, setPickedVibes] = useState<string[]>(["Beach + chill", "Food + culture"]);
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:54:  const [showIdeas, setShowIdeas] = useState(false);
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:112:                placeholder="e.g. March break, 9 days, family of 4, kids are 8 and 11. We loved Lisbon last spring. Want beach + some culture, not too much driving. Budget around $7k all-in. No long-haul flights."
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:114:                className="w-full p-6 bg-transparent resize-none focus:outline-none text-base leading-relaxed placeholder:text-muted-foreground/70"
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:214:                placeholder="Spring break 2026"
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:220:              <FormRow label="Dates"><DummyInput icon={Calendar} placeholder="Mar 14 – Mar 23" /></FormRow>
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:221:              <FormRow label="Who's going"><DummyInput icon={Users} placeholder="2 adults, 2 kids (8, 11)" /></FormRow>
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:222:              <FormRow label="Budget (all-in USD)"><DummyInput icon={DollarSign} placeholder="7000" /></FormRow>
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:223:              <FormRow label="Departing from"><DummyInput icon={Plane} placeholder="JFK / LGA / EWR" /></FormRow>
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:247:                placeholder="No red-eyes. No long-haul. No 6am wake-ups."
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:280:const DummyInput = ({ icon: Icon, placeholder }: { icon: React.ComponentType<{ className?: string }>; placeholder: string }) => (
/Users/kchapman/Hermes/Trippy/web/src/pages/NewTrip.tsx:284:      placeholder={placeholder}
/Users/kchapman/Hermes/Trippy/web/src/pages/Index.tsx:96:                placeholder="Search trips…"
/Users/kchapman/Hermes/Trippy/web/src/pages/TripShape.tsx:1:import { useState } from "react";
/Users/kchapman/Hermes/Trippy/web/src/pages/TripShape.tsx:96:  const [selected, setSelected] = useState(0);
/Users/kchapman/Hermes/Trippy/web/src/pages/TripShape.tsx:313:              placeholder="What should Trippy remember about this stage?"
/Users/kchapman/Hermes/Trippy/web/src/pages/TripShape.tsx:317:              placeholder="What should change before the next step?"
/Users/kchapman/Hermes/Trippy/web/src/pages/Timeline.tsx:246:              placeholder="What should Trippy remember about this stage?"
/Users/kchapman/Hermes/Trippy/web/src/pages/Timeline.tsx:250:              placeholder="What should change before the next step?"
