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

export interface TripState {
  trip_id: string;
  intake: TripIntake | null;
  draft: TripPlanDraft | null;
  workspace: TripWorkspaceState | null;
  trip_packet: unknown | null;
  shortlists: unknown[];
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
  buildWorkspace: (tripId: string) =>
    post<{ workflow_id: string; workspace: TripWorkspaceState }>("/api/workspace", {
      trip_id: tripId,
    }),
};
