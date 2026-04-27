import type {
  AppState,
  CanvasIdeaCard,
  CanvasTripCard,
  RunLogEvent,
  TripIdeaConcept,
  TripIntake,
  TripStatus,
} from "@/types/trippy";

const covers = [
  "linear-gradient(135deg, hsl(178 70% 45%), hsl(145 55% 38%))",
  "linear-gradient(135deg, hsl(8 90% 65%), hsl(18 95% 55%))",
  "linear-gradient(135deg, hsl(205 88% 48%), hsl(215 75% 28%))",
  "linear-gradient(135deg, hsl(45 100% 60%), hsl(8 90% 65%))",
];

const emojis = ["🌴", "🗺️", "✈️", "🐚", "🧭", "🏝️"];

export function appStateToTripCards(appState?: AppState | null): CanvasTripCard[] {
  const intakes = appState?.intakes ?? [];
  return intakes.map((intake, index) => intakeToTripCard(intake, index));
}

export function intakeToTripCard(intake: TripIntake, index = 0): CanvasTripCard {
  const destination = (intake.destination_seeds ?? []).join(", ") || "Destination TBD";
  const travelers = intake.party?.total_travelers ?? intake.travelers ?? 0;
  const progress = tripProgress(intake);
  return {
    id: intake.trip_id,
    title: intake.trip_name || intake.trip_id,
    destination,
    dates: dateLabel(intake),
    who: travelers ? partyLabel(intake, travelers) : "Travelers TBD",
    status: statusForProgress(progress),
    progress,
    legs: Math.max(1, intake.destination_seeds?.length ?? 1),
    cover: covers[index % covers.length],
    emoji: emojis[index % emojis.length],
  };
}

export function ideaToCard(concept: TripIdeaConcept, index = 0): CanvasIdeaCard {
  const place = concept.destination || concept.name || concept.title || "Trip idea";
  const fit = Math.round(Number(concept.fit_score ?? concept.score ?? 80));
  return {
    id: concept.concept_id || `${place}-${index}`,
    place,
    region: concept.region || `${concept.recommended_duration_days ?? "?"} day fit`,
    fit,
    tags: concept.tags?.length ? concept.tags : (concept.strengths ?? []).slice(0, 3),
    why: concept.rationale || concept.why || concept.strengths?.[0] || "Strong fit based on your Trippy preferences.",
    friction: concept.cautions ?? [],
    payload: concept,
  };
}

export function runLogToActivity(events?: RunLogEvent[]) {
  return (events ?? []).slice(-5).reverse().map((event) => ({
    actor: event.title?.startsWith("ui-") ? "Trippy" : "Hermes",
    summary: event.summary || event.title || event.event_type || "Workflow event",
    when: event.created_at ? new Date(event.created_at).toLocaleDateString() : "recently",
  }));
}

export function ideaToIntakePayload(card: CanvasIdeaCard, request: Record<string, unknown> = {}) {
  const concept = card.payload;
  const duration = concept.recommended_duration_days ?? request.duration_days ?? 7;
  const destination = concept.destination || card.place;
  return {
    trip_name: concept.title || concept.name || `${destination} ${new Date().getFullYear()}`,
    destinations: destination,
    duration,
    travel_window: String(request.time_of_year || "Flexible"),
    party_type: String(request.party_type || "whole_family"),
    travelers: Number(request.travelers || 5),
    adults: Number(request.adults || 2),
    children: Number(request.children || 3),
    departure_airports: "YYZ",
    budget_cad: request.budget_cad,
    max_travel_time_hours: request.max_flight_hours,
    goals: Array.isArray(request.goals) ? request.goals.join(", ") : request.goals || card.tags.join(", "),
    avoidances: Array.isArray(request.avoidances)
      ? request.avoidances.join(", ")
      : request.avoidances || card.friction.join(", "),
    notes: card.why,
  };
}

function dateLabel(intake: TripIntake): string {
  const window = intake.travel_window;
  if (window?.start_date && window?.end_date) return `${window.start_date} – ${window.end_date}`;
  if (window?.label) return window.label;
  if (window?.season) return window.season;
  return intake.duration_label || `${intake.duration_days ?? "?"} days`;
}

function partyLabel(intake: TripIntake, travelers: number): string {
  const type = intake.party?.party_type ?? "trip";
  if (type === "couple" || type === "adults_only") return "KenNSue";
  if (type === "whole_family") return `Family of ${travelers}`;
  return `${travelers} traveler(s)`;
}

function tripProgress(intake: TripIntake): number {
  let score = 20;
  if (intake.destination_seeds?.length) score += 15;
  if (intake.travel_window?.label || intake.travel_window?.start_date) score += 15;
  if (intake.goals?.length) score += 15;
  if (intake.budget_cad) score += 10;
  if (intake.party?.total_travelers || intake.travelers) score += 10;
  return Math.min(70, score);
}

function statusForProgress(progress: number): TripStatus {
  if (progress >= 95) return "complete";
  if (progress >= 80) return "booked";
  if (progress >= 35) return "planning";
  return "ideating";
}
