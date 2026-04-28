// Typed API client — all calls are proxied via Vite to http://localhost:8788

export interface DashboardTripTile {
  trip_id: string;
  name: string;
  status: string; // "dream" | "planned" | "booked" | "lived"
  destination: string;
  date_label: string;
  family_fit_score: number;
  comfort_score: number;
  budget_band: string;
  planning_completeness: number;
  hero_label: string;
  traveler_summary: string;
  next_actions: string[];
  key_risks: string[];
}

export interface TravelDashboard {
  past_trips: DashboardTripTile[];
  planned_trips: DashboardTripTile[];
  ideas: unknown[];
}

export interface RunLogEvent {
  event_id: string;
  event_type: string;
  created_at: string;
  trip_id: string | null;
  summary: string;
  title: string;
  severity: string; // "ok" | "error" | "warn" | "proposal"
}

export interface AppState {
  dashboard: TravelDashboard;
  intakes: unknown[];
  recent_workflows: unknown[];
  run_log: RunLogEvent[];
  suggested_trip_id: string | null;
}

export interface TripConcept {
  concept_id: string;
  title: string;
  destinations: string[];
  recommended_duration_days: number;
  best_season: string;
  estimated_cost_band_cad: string;
  estimated_travel_burden: string;
  family_fit_score: number;
  comfort_convenience_score: number;
  rationale: string[];
  why_it_may_not_fit: string[];
  major_risks: string[];
}

export interface TripComparison {
  concepts: TripConcept[];
  recommended_concept_id: string | null;
}

export interface SuggestIdeasResponse {
  workflow_id: string;
  comparison: TripComparison;
  next_step: string;
}

export interface TripIntake {
  trip_id: string;
  trip_name: string;
  destination_seeds: string[];
  travel_window: {
    start_date: string | null;
    end_date: string | null;
    label: string | null;
    season: string | null;
  };
  travelers: number;
  party: {
    adults: number;
    children: number;
    party_type: string;
  };
  duration_days: number | null;
}

export interface CreateIntakeResponse {
  workflow_id: string;
  intake: TripIntake;
  next_step: string;
}

export interface TripPlanOption {
  option_id: string;
  title: string;
  summary: string;
  regions: string[];
  nights_by_region: Record<string, number>;
  rationale: string[];
  major_risks: string[];
  travel_burden: string;
  family_comfort_score: number;
  recommendation_strength: number;
  lodging_strategy: string;
}

export interface TripPlanDraft {
  trip_id: string;
  options: TripPlanOption[];
  recommended_option_id: string | null;
  selected_option_id: string | null;
}

export interface WorkspaceTab {
  name: string;
  headers: string[];
  rows: unknown[][];
}

export interface TripWorkspaceState {
  trip_id: string;
  status: string;
  tabs: WorkspaceTab[];
  next_actions: string[];
  warnings: string[];
  google_sheet_url: string | null;
}

// ── Shortlist types ────────────────────────────────────────────────

export type ShortlistCategory = "flights" | "lodging" | "cars" | "activities";
export type RecommendationGrade = "strong" | "good" | "conditional" | "weak";
export type RowStatus =
  | "seeded" | "researched" | "verified_live" | "stale"
  | "rejected" | "approved" | "booked" | "confirmed";

export interface FlightOption {
  option_id: string;
  rank: number;
  airline: string;
  flight_numbers: string[];
  departure_date: string;
  arrival_date: string;
  departure_airport: string;
  arrival_airport: string;
  departure_time: string;
  arrival_time: string;
  stops: number;
  layover_airports: string[];
  layover_duration: string | null;
  total_travel_duration: string;
  timing_fit: string;
  recommendation_label: string;
  recommendation_rationale: string;
  fare_estimate_cad: string;
  price_band: string;
  baggage_cabin_notes: string;
  booking_source: string;
  deep_link: string;
  friction_score: number;
  family_comfort_score: number;
  recommendation_grade: RecommendationGrade;
  tradeoffs: string[];
  friction_flags: string[];
  row_status: RowStatus;
}

export interface LodgingOption {
  option_id: string;
  rank: number;
  source: string;
  name: string;
  location_area: string;
  island_or_region: string;
  lodging_type: string;
  bed_layout: string;
  occupancy_fit: string;
  comfort_fit: string;
  parking_practicality: string;
  driving_practicality: string;
  walkability: string;
  cancellation_notes: string;
  price_band: string;
  current_price_signal: string;
  deep_link: string;
  friction_score: number;
  family_comfort_score: number;
  recommendation_grade: RecommendationGrade;
  tradeoffs: string[];
  friction_flags: string[];
  row_status: RowStatus;
}

export interface CarOption {
  option_id: string;
  rank: number;
  booking_source: string;
  pickup_location: string;
  dropoff_location: string;
  vehicle_class: string;
  price_band: string;
  current_price_signal: string;
  seating_capacity: number | null;
  passenger_fit: string;
  luggage_fit: string;
  cancellation_notes: string;
  fees_caution: string;
  deep_link: string;
  family_comfort_score: number;
  luggage_practicality_score: number;
  pickup_dropoff_simplicity_score: number;
  driving_parking_suitability_score: number;
  total_friction_score: number;
  recommendation_grade: RecommendationGrade;
  tradeoffs: string[];
  friction_flags: string[];
  row_status: RowStatus;
}

export interface ActivityOption {
  option_id: string;
  rank: number;
  activity_name: string;
  source: string;
  island_location: string;
  group_size_signal: string;
  review_safety_signal: string;
  age_family_fit: string;
  price_band: string;
  duration: string;
  suggested_day: number | null;
  suggested_date: string;
  suggested_start_time: string;
  suggested_end_time: string;
  scheduled_day: number | null;
  scheduled_date: string;
  scheduled_start_time: string;
  scheduled_end_time: string;
  deep_link: string;
  family_pace_fit_score: number;
  safety_confidence_score: number;
  crowd_fit_score: number;
  total_friction_score: number;
  recommendation_grade: RecommendationGrade;
  tradeoffs: string[];
  friction_flags: string[];
  row_status: RowStatus;
}

export interface ShortlistState {
  trip_id: string;
  category: ShortlistCategory;
  recommended_option_id: string | null;
  recommendation_summary: string;
  flight_options: FlightOption[];
  lodging_options: LodgingOption[];
  car_options: CarOption[];
  activity_options: ActivityOption[];
  partial_failures: string[];
  warnings: string[];
  next_actions: string[];
}

export interface ShortlistResponse {
  workflow_id: string;
  shortlist: ShortlistState;
  next_step: string;
}

export interface TripState {
  trip_id: string;
  intake: TripIntake | null;
  draft: TripPlanDraft | null;
  workspace: TripWorkspaceState | null;
  trip_packet: unknown | null;
  shortlists: ShortlistState[];
  run_log: RunLogEvent[];
  next_step: string;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `GET ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `POST ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getState: () => get<AppState>("/api/state"),
  getTrip: (tripId: string) =>
    get<TripState>(`/api/trip?trip_id=${encodeURIComponent(tripId)}`),
  suggestIdeas: (payload: Record<string, unknown>) =>
    post<SuggestIdeasResponse>("/api/suggest-ideas", payload),
  createIntake: (payload: Record<string, unknown>) =>
    post<CreateIntakeResponse>("/api/intake", payload),
  draftPlan: (tripId: string) =>
    post<{ workflow_id: string; draft: TripPlanDraft }>("/api/draft", {
      trip_id: tripId,
    }),
  selectPlan: (tripId: string, optionId: string) =>
    post<{ workflow_id: string; draft: TripPlanDraft }>("/api/select", {
      trip_id: tripId,
      option_id: optionId,
    }),
  addFeedback: (payload: Record<string, unknown>) =>
    post<unknown>("/api/feedback", payload),
  buildWorkspace: (tripId: string, opts?: { create_google_sheet?: boolean }) =>
    post<{ workflow_id: string; workspace: TripWorkspaceState }>("/api/workspace", {
      trip_id: tripId,
      create_google_sheet: opts?.create_google_sheet ?? false,
    }),
  buildShortlist: (
    tripId: string,
    category: ShortlistCategory,
    opts?: { validate_live?: boolean; deep_research?: boolean }
  ) =>
    post<ShortlistResponse>("/api/shortlist", {
      trip_id: tripId,
      category,
      validate_live: opts?.validate_live ?? false,
      deep_research: opts?.deep_research ?? false,
    }),
  selectFlight: (tripId: string, optionId: string) =>
    post<ShortlistResponse>("/api/select-flight", {
      trip_id: tripId,
      option_id: optionId,
    }),
  selectLodging: (tripId: string, optionId: string) =>
    post<ShortlistResponse>("/api/select-lodging", {
      trip_id: tripId,
      option_id: optionId,
    }),
  selectCar: (tripId: string, optionId: string) =>
    post<ShortlistResponse>("/api/select-car", {
      trip_id: tripId,
      option_id: optionId,
    }),
  selectActivity: (tripId: string, optionId: string) =>
    post<ShortlistResponse>("/api/select-activity", {
      trip_id: tripId,
      option_id: optionId,
    }),
  addFlightCandidate: (payload: {
    trip_id: string;
    link: string;
    name?: string;
    notes?: string;
  }) => post<ShortlistResponse>("/api/flight-candidate", payload),
  addLodgingCandidate: (payload: {
    trip_id: string;
    link: string;
    name?: string;
    notes?: string;
  }) => post<ShortlistResponse>("/api/lodging-candidate", payload),
  scheduleActivity: (payload: {
    trip_id: string;
    option_id: string;
    day?: number;
    date?: string;
    start_time?: string;
    end_time?: string;
  }) => post<ShortlistResponse>("/api/schedule-activity", payload),
  planningAdvice: (payload: { trip_id: string; question: string }) =>
    post<{ advice: unknown; next_step: string }>("/api/planning-advice", payload),
};
