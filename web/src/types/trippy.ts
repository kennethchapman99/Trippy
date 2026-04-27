export type TripStatus = "ideating" | "planning" | "booked" | "complete";

export type TripIntake = {
  trip_id: string;
  trip_name?: string;
  destination_seeds?: string[];
  duration_days?: number | string | null;
  duration_label?: string | null;
  travelers?: number | null;
  budget_cad?: number | null;
  goals?: string[];
  avoidances?: string[];
  departure_airports?: string[];
  travel_window?: {
    label?: string | null;
    season?: string | null;
    start_date?: string | null;
    end_date?: string | null;
  } | null;
  party?: {
    party_type?: string;
    adults?: number;
    children?: number;
    child_ages?: number[];
    total_travelers?: number;
  } | null;
};

export type AppState = {
  intakes?: TripIntake[];
  recent_workflows?: WorkflowSummary[];
  run_log?: RunLogEvent[];
  suggested_trip_id?: string | null;
};

export type TripState = {
  trip_id: string;
  intake?: TripIntake | null;
  draft?: Record<string, unknown> | null;
  workspace?: Record<string, unknown> | null;
  shortlists?: Record<string, unknown>[];
  recent_workflows?: WorkflowSummary[];
  run_log?: RunLogEvent[];
  next_step?: string | null;
};

export type WorkflowSummary = {
  id?: string;
  title?: string;
  summary?: string;
  status?: string;
  trip_id?: string | null;
  created_at?: string;
};

export type RunLogEvent = {
  event_type?: string;
  title?: string;
  summary?: string;
  severity?: string;
  trip_id?: string | null;
  created_at?: string;
};

export type IdeaRequest = {
  time_of_year?: string;
  duration_days?: number;
  budget_cad?: number;
  travelers?: number;
  party_type?: string;
  adults?: number;
  children?: number;
  max_flight_hours?: number;
  direct_flight_preferred?: boolean;
  goals?: string | string[];
  avoidances?: string | string[];
  desired_vibe?: string;
  activity_level?: string;
};

export type TripIdeaConcept = {
  concept_id?: string;
  destination?: string;
  name?: string;
  title?: string;
  region?: string;
  fit_score?: number;
  score?: number;
  recommended_duration_days?: number;
  tags?: string[];
  strengths?: string[];
  cautions?: string[];
  rationale?: string;
  why?: string;
};

export type IdeaResponse = {
  workflow_id?: string;
  comparison?: {
    concepts?: TripIdeaConcept[];
    request?: Record<string, unknown>;
  };
  next_step?: string;
};

export type CanvasTripCard = {
  id: string;
  title: string;
  destination: string;
  dates: string;
  who: string;
  status: TripStatus;
  progress: number;
  legs: number;
  cover: string;
  emoji: string;
  nextStep?: string;
};

export type CanvasIdeaCard = {
  id: string;
  place: string;
  region: string;
  fit: number;
  tags: string[];
  why: string;
  friction: string[];
  payload: TripIdeaConcept;
};
