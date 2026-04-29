import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { StageNav } from "@/components/StageNav";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle, ArrowLeft, ChevronDown, Loader2, RefreshCcw, AlertCircle,
  ExternalLink, CheckCircle2, Clock, Sparkles, FileSpreadsheet,
  Plane, MapPinned, Utensils, Sun, Home, Car, Ticket,
  Info, Navigation, Phone, Hash, ShoppingCart,
} from "lucide-react";
import { api, type ActivityOption, type FlightOption, type LodgingOption, type WorkspaceTab } from "@/lib/api";
import { buildStages, shortlistOptions } from "@/lib/stages";
import { TripMap } from "@/components/TripMap";
import { useGeocodes } from "@/lib/geocode";
import {
  buildActivityPins,
  buildFlightPins,
  buildLodgingPins,
  makeGeocodeLookup,
} from "@/lib/pinBuilders";

type TimelineLink = {
  label: string;
  href: string;
  kind?: "external" | "maps" | "phone" | "reference" | "booking";
};

type TimelineEvent = {
  id: string;
  day: number;
  dateLabel: string;
  start: string;
  end: string;
  type: "flight" | "transfer" | "stay" | "food" | "beach" | "activity" | "prep" | "travel";
  title: string;
  subtitle: string;
  detail: string;
  tags: string[];
  links: TimelineLink[];
  alert?: string;
};

type TimelineDay = {
  day: number;
  dateLabel: string;
  weekday: string;
  mood: string;
  note: string;
  events: TimelineEvent[];
};

const FALLBACK_TIMELINE: TimelineDay[] = [
  {
    day: 1,
    dateLabel: "Mar 14",
    weekday: "Sat",
    mood: "Full day",
    note: "Arrive · beach dinner",
    events: [
      {
        id: "sample-flight-out",
        day: 1,
        dateLabel: "Mar 14",
        start: "10:00",
        end: "12:55",
        type: "flight",
        title: "AC 1726 · YYZ → SMB",
        subtitle: "Air Canada · seats 14A-14E booked",
        detail: "Confirmation AC · KX9P4M",
        tags: ["travel", "YYZ → SMB"],
        links: [
          { label: "Manage booking", href: "https://www.aircanada.com/ca/en/aco/home/book/manage-bookings.html", kind: "booking" },
          { label: "Boarding passes", href: "https://www.aircanada.com/ca/en/aco/home/fly/check-in.html", kind: "reference" },
        ],
      },
      {
        id: "sample-transfer",
        day: 1,
        dateLabel: "Mar 14",
        start: "13:30",
        end: "15:00",
        type: "transfer",
        title: "Transfer + check-in",
        subtitle: "Pre-arranged van · car seat confirmed",
        detail: "Tropicar · TR-44821 · +1 345 555 0142",
        tags: ["logistics"],
        links: [
          { label: "Pickup point", href: "https://www.google.com/maps/search/?api=1&query=Owen+Roberts+International+Airport", kind: "maps" },
          { label: "Call driver", href: "tel:+13455550142", kind: "phone" },
        ],
      },
      {
        id: "sample-dinner-1",
        day: 1,
        dateLabel: "Mar 14",
        start: "18:30",
        end: "21:00",
        type: "food",
        title: "Dinner on Seven Mile Beach",
        subtitle: "Calico Jack's · kid-friendly · 15-min walk",
        detail: "First-night easy dinner near the condo.",
        tags: ["food", "SMB"],
        links: [
          { label: "Menu + reviews", href: "https://www.google.com/search?q=Calico+Jack%27s+Grand+Cayman+menu+reviews", kind: "reference" },
          { label: "Walk · 15 min", href: "https://www.google.com/maps/search/?api=1&query=Calico+Jack%27s+Grand+Cayman", kind: "maps" },
        ],
      },
    ],
  },
  {
    day: 2,
    dateLabel: "Mar 15",
    weekday: "Sun",
    mood: "Easy",
    note: "Settle in",
    events: [
      {
        id: "sample-beach",
        day: 2,
        dateLabel: "Mar 15",
        start: "09:00",
        end: "11:00",
        type: "beach",
        title: "Beach + settle in",
        subtitle: "Short snorkel at Governor's Beach",
        detail: "Keep it flexible after travel day.",
        tags: ["relax", "SMB"],
        links: [
          { label: "Beach guide", href: "https://www.google.com/search?q=Governor%27s+Beach+Grand+Cayman+guide", kind: "reference" },
          { label: "Governor's Beach", href: "https://www.google.com/maps/search/?api=1&query=Governor%27s+Beach+Grand+Cayman", kind: "maps" },
        ],
      },
      {
        id: "sample-lunch-condo",
        day: 2,
        dateLabel: "Mar 15",
        start: "13:00",
        end: "14:30",
        type: "food",
        title: "Late lunch at the condo",
        subtitle: "Grocery run handled the night before",
        detail: "Simple lunch and reset window.",
        tags: ["low-key"],
        links: [{ label: "Grocery list", href: "https://www.google.com/search?q=Grand+Cayman+grocery+stores+Seven+Mile+Beach", kind: "reference" }],
      },
    ],
  },
  {
    day: 3,
    dateLabel: "Mar 16",
    weekday: "Mon",
    mood: "Full day",
    note: "Hero day",
    events: [
      {
        id: "sample-stingray",
        day: 3,
        dateLabel: "Mar 16",
        start: "08:00",
        end: "12:00",
        type: "activity",
        title: "Stingray City + Starfish Point",
        subtitle: "Private charter · 8am push-off",
        detail: "Confirmation SC-7821 · Captain Marco · Marina dock B",
        tags: ["hero", "North Sound"],
        links: [
          { label: "Charter voucher", href: "https://www.google.com/search?q=Stingray+City+private+charter+Grand+Cayman", kind: "reference" },
          { label: "Marina dock B", href: "https://www.google.com/maps/search/?api=1&query=Grand+Cayman+Marina+dock+B", kind: "maps" },
        ],
        alert: "Sunscreen + rash guards in the day bag",
      },
      {
        id: "sample-kaibo",
        day: 3,
        dateLabel: "Mar 16",
        start: "13:30",
        end: "15:00",
        type: "food",
        title: "Lunch @ Kaibo",
        subtitle: "Outdoor seating, dock view",
        detail: "Drive · 8 min from Starfish Point.",
        tags: ["food"],
        links: [
          { label: "Menu + reviews", href: "https://www.google.com/search?q=Kaibo+Grand+Cayman+menu+reviews", kind: "reference" },
          { label: "Drive · 8 min", href: "https://www.google.com/maps/search/?api=1&query=Kaibo+Grand+Cayman", kind: "maps" },
        ],
      },
    ],
  },
  {
    day: 4,
    dateLabel: "Mar 17",
    weekday: "Tue",
    mood: "Full day",
    note: "Reef day",
    events: [
      {
        id: "sample-rum-point",
        day: 4,
        dateLabel: "Mar 17",
        start: "10:00",
        end: "13:00",
        type: "beach",
        title: "Reef day at Rum Point",
        subtitle: "Rentals on-site · shallow entry for kids",
        detail: "Leave a wide return buffer.",
        tags: ["snorkel", "East End"],
        links: [
          { label: "Reef map", href: "https://www.google.com/search?q=Rum+Point+Grand+Cayman+snorkeling+map", kind: "reference" },
          { label: "Drive · 35 min", href: "https://www.google.com/maps/search/?api=1&query=Rum+Point+Grand+Cayman", kind: "maps" },
        ],
      },
    ],
  },
];

const EVENT_STYLES: Record<TimelineEvent["type"], { Icon: typeof Plane; chip: string; ring: string }> = {
  flight: { Icon: Plane, chip: "bg-secondary/10 text-secondary border-secondary/25", ring: "bg-secondary/10 text-secondary border-secondary/25" },
  transfer: { Icon: MapPinned, chip: "bg-secondary/10 text-secondary border-secondary/25", ring: "bg-secondary/10 text-secondary border-secondary/25" },
  stay: { Icon: Home, chip: "bg-palm/10 text-palm border-palm/25", ring: "bg-palm/10 text-palm border-palm/25" },
  food: { Icon: Utensils, chip: "bg-coral/10 text-coral border-coral/25", ring: "bg-coral/10 text-coral border-coral/25" },
  beach: { Icon: Sun, chip: "bg-sunshine/20 text-foreground border-sunshine/40", ring: "bg-sunshine/20 text-foreground border-sunshine/40" },
  activity: { Icon: Sparkles, chip: "bg-accent/10 text-accent border-accent/30", ring: "bg-accent/10 text-accent border-accent/30" },
  prep: { Icon: ShoppingCart, chip: "bg-muted text-foreground border-foreground/10", ring: "bg-muted text-foreground border-foreground/10" },
  travel: { Icon: Car, chip: "bg-secondary/10 text-secondary border-secondary/25", ring: "bg-secondary/10 text-secondary border-secondary/25" },
};

const LINK_ICONS: Record<NonNullable<TimelineLink["kind"]>, typeof ExternalLink> = {
  external: ExternalLink,
  maps: Navigation,
  phone: Phone,
  reference: Info,
  booking: Ticket,
};

function formatDateLabel(dateValue: string | null | undefined, fallback = ""): string {
  if (!dateValue) return fallback;
  const date = new Date(`${dateValue}T00:00:00`);
  if (Number.isNaN(date.getTime())) return dateValue;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function weekdayLabel(dateValue: string | null | undefined, fallback = ""): string {
  if (!dateValue) return fallback;
  const date = new Date(`${dateValue}T00:00:00`);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString(undefined, { weekday: "short" });
}

function googleSearchLink(query: string): string {
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

function googleMapsLink(query: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function eventTypeFromText(value: string): TimelineEvent["type"] {
  const s = value.toLowerCase();
  if (s.includes("flight")) return "flight";
  if (s.includes("car") || s.includes("transfer") || s.includes("pickup")) return "transfer";
  if (s.includes("lodging") || s.includes("check in") || s.includes("check out")) return "stay";
  if (s.includes("food") || s.includes("lunch") || s.includes("dinner") || s.includes("restaurant")) return "food";
  if (s.includes("beach") || s.includes("reef") || s.includes("snorkel")) return "beach";
  return "activity";
}

function selectedFlights(options: FlightOption[]): FlightOption[] {
  const chosen = options.filter((o) => ["approved", "booked", "confirmed"].includes(o.row_status));
  return chosen.length > 0 ? chosen : options.slice(0, 2);
}

function selectedLodging(options: LodgingOption[]): LodgingOption[] {
  const chosen = options.filter((o) => ["approved", "booked", "confirmed"].includes(o.row_status));
  return chosen.length > 0 ? chosen : options.slice(0, 1);
}

function selectedActivities(options: ActivityOption[]): ActivityOption[] {
  const chosen = options.filter((o) => ["approved", "booked", "confirmed"].includes(o.row_status) || o.scheduled_day);
  return chosen.length > 0 ? chosen : options.slice(0, 6);
}

function timelineFromWorkspace(masterTab: WorkspaceTab | undefined): TimelineEvent[] {
  if (!masterTab?.rows.length) return [];
  const indexFor = (...names: string[]) =>
    masterTab.headers.findIndex((header) => names.some((name) => header.toLowerCase().includes(name)));

  const dayIndex = indexFor("day");
  const dateIndex = indexFor("date");
  const startIndex = indexFor("start");
  const endIndex = indexFor("end");
  const typeIndex = indexFor("type");
  const titleIndex = indexFor("title");
  const locationIndex = indexFor("location");
  const providerIndex = indexFor("provider");
  const statusIndex = indexFor("status");
  const notesIndex = indexFor("notes");
  const linkIndex = indexFor("link");
  const flagsIndex = indexFor("friction");

  return masterTab.rows.map((raw, rowIndex) => {
    const row = raw as unknown[];
    const day = Number(row[dayIndex] ?? rowIndex + 1) || rowIndex + 1;
    const dateRaw = String(row[dateIndex] ?? "");
    const title = String(row[titleIndex] ?? "Timeline item");
    const location = String(row[locationIndex] ?? "");
    const provider = String(row[providerIndex] ?? "");
    const typeRaw = String(row[typeIndex] ?? title);
    const notes = String(row[notesIndex] ?? "");
    const href = String(row[linkIndex] ?? "");
    const links: TimelineLink[] = [
      href ? { label: "Open source", href, kind: "external" } : null,
      location ? { label: location, href: googleMapsLink(location), kind: "maps" } : null,
    ].filter((link): link is TimelineLink => Boolean(link));

    return {
      id: `workspace-${rowIndex}-${title}`,
      day,
      dateLabel: formatDateLabel(dateRaw, dateRaw || `Day ${day}`),
      start: String(row[startIndex] ?? ""),
      end: String(row[endIndex] ?? ""),
      type: eventTypeFromText(`${typeRaw} ${title}`),
      title,
      subtitle: [provider, location].filter(Boolean).join(" · "),
      detail: notes || String(row[statusIndex] ?? ""),
      tags: [String(row[typeIndex] ?? ""), String(row[statusIndex] ?? "")].filter(Boolean).slice(0, 3),
      links,
      alert: String(row[flagsIndex] ?? "") || undefined,
    };
  });
}

function timelineFromShortlists(args: {
  flights: FlightOption[];
  lodging: LodgingOption[];
  activities: ActivityOption[];
  startDate?: string | null;
}): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  selectedFlights(args.flights).forEach((flight, index) => {
    const day = index === 0 ? 1 : Math.max(1, index + 1);
    const dateValue = flight.departure_date || args.startDate || "";
    events.push({
      id: `flight-${flight.option_id}`,
      day,
      dateLabel: formatDateLabel(dateValue, `Day ${day}`),
      start: flight.departure_time,
      end: flight.arrival_time,
      type: "flight",
      title: `${flight.flight_numbers.join(" / ") || flight.airline} · ${flight.departure_airport} → ${flight.arrival_airport}`,
      subtitle: [flight.airline, flight.total_travel_duration, flight.timing_fit].filter(Boolean).join(" · "),
      detail: flight.recommendation_rationale || flight.baggage_cabin_notes,
      tags: ["travel", `${flight.departure_airport} → ${flight.arrival_airport}`],
      links: [
        flight.deep_link ? { label: "Booking source", href: flight.deep_link, kind: "booking" } : null,
        flight.validation?.evidence_url ? { label: "Live evidence", href: flight.validation.evidence_url, kind: "reference" } : null,
      ].filter((link): link is TimelineLink => Boolean(link)),
      alert: flight.friction_flags[0],
    });
  });

  selectedLodging(args.lodging).forEach((stay, index) => {
    const day = index === 0 ? 1 : index + 2;
    const dateValue = args.startDate || "";
    events.push({
      id: `stay-${stay.option_id}`,
      day,
      dateLabel: formatDateLabel(dateValue, `Day ${day}`),
      start: index === 0 ? "15:00" : "",
      end: "",
      type: "stay",
      title: `Check in: ${stay.name}`,
      subtitle: [stay.location_area, stay.island_or_region, stay.bed_layout].filter(Boolean).join(" · "),
      detail: stay.comfort_fit || stay.occupancy_fit,
      tags: ["stay", stay.location_area].filter(Boolean),
      links: [
        stay.deep_link ? { label: "Listing", href: stay.deep_link, kind: "booking" } : null,
        stay.location_area ? { label: "Area map", href: googleMapsLink(`${stay.name} ${stay.location_area}`), kind: "maps" } : null,
      ].filter((link): link is TimelineLink => Boolean(link)),
      alert: stay.friction_flags[0],
    });
  });

  selectedActivities(args.activities).forEach((activity, index) => {
    const day = activity.scheduled_day || activity.suggested_day || Math.min(index + 2, 7);
    const dateValue = activity.scheduled_date || activity.suggested_date || "";
    events.push({
      id: `activity-${activity.option_id}`,
      day,
      dateLabel: formatDateLabel(dateValue, `Day ${day}`),
      start: activity.scheduled_start_time || activity.suggested_start_time,
      end: activity.scheduled_end_time || activity.suggested_end_time,
      type: eventTypeFromText(`${activity.activity_name} ${activity.island_location}`),
      title: activity.activity_name,
      subtitle: [activity.island_location, activity.duration, activity.age_family_fit].filter(Boolean).join(" · "),
      detail: activity.review_safety_signal || activity.group_size_signal,
      tags: [activity.recommendation_grade, activity.island_location].filter(Boolean),
      links: [
        activity.deep_link ? { label: "Details", href: activity.deep_link, kind: "external" } : null,
        activity.validation?.evidence_url ? { label: "Reviews", href: activity.validation.evidence_url, kind: "reference" } : null,
        activity.island_location ? { label: "Map", href: googleMapsLink(activity.island_location), kind: "maps" } : null,
      ].filter((link): link is TimelineLink => Boolean(link)),
      alert: activity.friction_flags[0],
    });
  });

  return events;
}

function groupTimeline(events: TimelineEvent[], startDate?: string | null, duration?: number | null): TimelineDay[] {
  const byDay = new Map<number, TimelineEvent[]>();
  events.forEach((event) => {
    const existing = byDay.get(event.day) ?? [];
    existing.push(event);
    byDay.set(event.day, existing);
  });

  const maxDay = Math.max(duration ?? 0, ...events.map((event) => event.day), 0);
  if (maxDay === 0) return [];

  return Array.from({ length: maxDay }, (_, index) => {
    const day = index + 1;
    const date = startDate ? new Date(`${startDate}T00:00:00`) : null;
    if (date && !Number.isNaN(date.getTime())) date.setDate(date.getDate() + index);
    const iso = date && !Number.isNaN(date.getTime()) ? date.toISOString().slice(0, 10) : "";
    const dayEvents = (byDay.get(day) ?? []).sort((a, b) => (a.start || "99:99").localeCompare(b.start || "99:99"));
    const hasFlight = dayEvents.some((event) => event.type === "flight" || event.type === "transfer");
    const hasHero = dayEvents.some((event) => event.tags.some((tag) => tag.toLowerCase().includes("hero")));

    return {
      day,
      dateLabel: formatDateLabel(iso, dayEvents[0]?.dateLabel || `Day ${day}`),
      weekday: weekdayLabel(iso, dayEvents[0]?.dateLabel?.split(" ")[0] || ""),
      mood: hasFlight || dayEvents.length > 2 ? "Full day" : hasHero ? "Hero day" : "Easy",
      note: dayEvents.length > 0 ? dayEvents.map((event) => event.title).slice(0, 2).join(" · ") : "Open buffer",
      events: dayEvents.length > 0 ? dayEvents : [{
        id: `buffer-${day}`,
        day,
        dateLabel: formatDateLabel(iso, `Day ${day}`),
        start: "",
        end: "",
        type: "prep",
        title: "Open buffer",
        subtitle: "Keep this day flexible until bookings are locked.",
        detail: "Use the space for weather swaps, groceries, laundry, naps, or a low-key local meal.",
        tags: ["buffer"],
        links: [{ label: "Nearby ideas", href: googleSearchLink("family friendly things to do near trip destination"), kind: "reference" }],
      }],
    };
  });
}

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
  const warningCount = workspace?.warnings.length ?? 0;
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
  const lodgingOpts = useMemo(
    () => lodgingShortlist?.lodging_options ?? [],
    [lodgingShortlist]
  );
  const activityOpts = useMemo(
    () => activityShortlist?.activity_options ?? [],
    [activityShortlist]
  );
  const flightOpts = useMemo(
    () => flightShortlist?.flight_options ?? [],
    [flightShortlist]
  );

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
  const timelineDays = useMemo(() => {
    const workspaceEvents = timelineFromWorkspace(masterTab);
    const shortlistEvents = timelineFromShortlists({
      flights: flightOpts,
      lodging: lodgingOpts,
      activities: activityOpts,
      startDate: intake?.travel_window.start_date,
    });
    const events = workspaceEvents.length > 0 ? workspaceEvents : shortlistEvents;
    if (events.length > 0) {
      return groupTimeline(events, intake?.travel_window.start_date, intake?.duration_days);
    }
    return FALLBACK_TIMELINE;
  }, [activityOpts, flightOpts, intake?.duration_days, intake?.travel_window.start_date, lodgingOpts, masterTab]);
  const timelineSource = masterTab?.rows.length
    ? "Workspace timeline"
    : flightOpts.length + lodgingOpts.length + activityOpts.length > 0
      ? "Live trip timeline"
      : "Sample complete timeline";

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
          {warningCount > 0 && (
            <a
              href="#friction-review"
              className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background transition-bounce"
              aria-label={`Review ${warningCount} friction flag${warningCount !== 1 ? "s" : ""}`}
            >
              <AlertTriangle className="h-4 w-4 text-sunshine" />
              <div className="text-xs leading-tight">
                <div className="font-bold">{warningCount} friction flag{warningCount !== 1 ? "s" : ""}</div>
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
      <div className="px-6 md:px-10 py-5 border-b-2 border-foreground/10 bg-card/60 backdrop-blur sticky top-0 z-30">
        <StageNav stages={stages} />
      </div>

      {/* Body */}
      <div className="px-6 md:px-10 py-8">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
              Stage 7 · {timelineSource}
            </div>
            <h2 className="font-[Fredoka] text-3xl md:text-4xl font-bold mt-1">
              Complete timeline, one page.
            </h2>
            <p className="text-muted-foreground mt-1 max-w-2xl">
              Flights, stays, activities, logistics, buffer windows, and handy links are grouped by day so the trip can be scanned fast.
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
                {(tripQuery.error as Error)?.message ?? "Check that the Trippy backend is running."}
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

        {!tripQuery.isLoading && timelineDays.length > 0 && (
          <CompleteTimeline days={timelineDays} />
        )}

        {/* Workspace not yet built */}
        {!tripQuery.isLoading && !workspace && tripId && (
          <div className="mt-6 rounded-3xl border-2 border-dashed border-foreground/20 bg-muted/20 p-6 md:p-8 flex flex-col md:flex-row md:items-center text-left gap-4">
            <div className="h-16 w-16 rounded-2xl bg-gradient-sunset border-2 border-foreground shadow-sticker flex items-center justify-center">
              <Sparkles className="h-8 w-8 text-primary-foreground" />
            </div>
            <div className="flex-1">
              <h3 className="font-[Fredoka] text-2xl font-bold">Workspace not built yet</h3>
              <p className="text-muted-foreground text-sm mt-2 max-w-sm">
                {nextStep || "Build the workspace to generate the audit tabs, Google Sheet handoff, and planning packet."}
              </p>
            </div>
            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
              <label className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={createSheet}
                  onChange={(e) => setCreateSheet(e.target.checked)}
                  className="h-4 w-4 rounded border-2 border-foreground/30 accent-primary"
                />
                <FileSpreadsheet className="h-4 w-4" />
                Google Sheet
              </label>
              <Button
                onClick={() => workspaceMutation.mutate()}
                disabled={workspaceMutation.isPending}
                className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
              >
                {workspaceMutation.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> {createSheet ? "Building + sheet…" : "Building…"}</>
                ) : (
                  <>Build workspace</>
                )}
              </Button>
            </div>
            {workspaceMutation.isError && (
              <p className="text-sm text-destructive font-medium">
                {(workspaceMutation.error as Error)?.message}
              </p>
            )}
          </div>
        )}

        {/* Workspace next actions */}
        {workspace && workspace.next_actions.length > 0 && (
          <div className="mt-6 mb-6 rounded-3xl border-2 border-foreground/10 bg-card shadow-card p-5">
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

        {/* Workspace warnings */}
        {workspace && workspace.warnings.length > 0 && (
          <div id="friction-review" className="mb-6 scroll-mt-32 rounded-3xl border-2 border-coral/30 bg-coral/5 p-5">
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

const CompleteTimeline = ({ days }: { days: TimelineDay[] }) => (
  <div className="overflow-hidden rounded-[2rem] border-2 border-foreground/10 bg-card shadow-card mb-6">
    {days.map((day, dayIndex) => (
      <section
        key={`${day.day}-${day.dateLabel}`}
        className={`grid gap-0 md:grid-cols-[240px_1fr] ${dayIndex > 0 ? "border-t-2 border-foreground/10" : ""}`}
      >
        <aside className="bg-background/55 px-6 py-6 md:px-8 md:py-8 md:border-r-2 md:border-dashed md:border-foreground/15">
          <div className="text-xs font-bold uppercase tracking-[0.22em] text-muted-foreground">
            Day {day.day}
          </div>
          <div className="mt-3 font-[Fredoka] text-5xl font-bold leading-none">
            {day.weekday || `Day ${day.day}`}
          </div>
          <div className="mt-3 text-lg font-bold text-muted-foreground">{day.dateLabel}</div>
          <div className="mt-5 inline-flex rounded-full border-2 border-foreground bg-foreground px-4 py-2 text-sm font-bold text-background">
            {day.mood}
          </div>
          <p className="mt-4 text-sm italic text-muted-foreground">{day.note}</p>
        </aside>

        <div className="px-5 py-5 md:px-8 md:py-7">
          <div className="space-y-7">
            {day.events.map((event) => (
              <TimelineEventCard key={event.id} event={event} />
            ))}
          </div>
        </div>
      </section>
    ))}
  </div>
);

const TimelineEventCard = ({ event }: { event: TimelineEvent }) => {
  const style = EVENT_STYLES[event.type];
  const Icon = style.Icon;

  return (
    <article className="grid gap-4 md:grid-cols-[96px_48px_1fr_auto] md:items-start">
      <div className="font-mono text-lg font-bold leading-tight text-muted-foreground md:text-right">
        {event.start ? (
          <>
            <div>{event.start}</div>
            {event.end && <div>- {event.end}</div>}
          </>
        ) : (
          <div className="text-sm font-sans uppercase tracking-wider">Flexible</div>
        )}
      </div>

      <div className={`flex h-12 w-12 items-center justify-center rounded-full border-2 ${style.ring}`}>
        <Icon className="h-5 w-5" />
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h3 className="font-[Fredoka] text-2xl font-bold leading-tight tracking-normal">
            {event.title}
          </h3>
          <div className="flex flex-wrap gap-2">
            {event.tags.filter(Boolean).slice(0, 3).map((tag) => (
              <span
                key={`${event.id}-${tag}`}
                className="rounded-full border border-foreground/15 bg-muted/70 px-3 py-1 text-xs font-bold"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>

        {event.subtitle && (
          <p className="mt-1 text-lg font-semibold text-muted-foreground">{event.subtitle}</p>
        )}
        {event.detail && (
          <p className="mt-3 flex items-start gap-2 text-sm font-semibold text-muted-foreground">
            <Hash className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{event.detail}</span>
          </p>
        )}

        {event.links.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
            {event.links.map((link) => {
              const LinkIcon = LINK_ICONS[link.kind ?? "external"];
              return (
                <a
                  key={`${event.id}-${link.label}-${link.href}`}
                  href={link.href}
                  target={link.href.startsWith("http") ? "_blank" : undefined}
                  rel={link.href.startsWith("http") ? "noopener noreferrer" : undefined}
                  className="inline-flex items-center gap-1.5 text-sm font-bold text-muted-foreground hover:text-foreground"
                >
                  <LinkIcon className="h-4 w-4" />
                  {link.label}
                </a>
              );
            })}
          </div>
        )}

        {event.alert && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-2xl border-2 border-coral/35 bg-coral/10 px-4 py-3 text-sm font-semibold text-muted-foreground">
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-primary" />
              {event.alert}
            </span>
            <Clock className="h-4 w-4 shrink-0" />
          </div>
        )}
      </div>

      <div className={`hidden rounded-full border px-3 py-1 text-xs font-bold md:block ${style.chip}`}>
        {event.type}
      </div>
    </article>
  );
};

export default Timeline;
