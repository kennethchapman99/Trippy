import type { FlightOption, ShortlistState } from "@/lib/api";

export type FlightFlowPhase = "departure_required" | "return_required" | "locked";

export interface FlightFlowState {
  trip_id: string;
  phase: FlightFlowPhase;
  selected_departure: FlightOption | null;
  selected_return: FlightOption | null;
  trip_envelope: Record<string, unknown> | null;
  departure_options: FlightOption[];
  return_options: FlightOption[];
  return_search: Record<string, unknown> | null;
  can_continue: boolean;
  next_action: string;
}

export interface FlightFlowResponse {
  flight_flow: FlightFlowState;
  shortlist: ShortlistState | null;
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

export const flightFlowApi = {
  getState: (tripId: string) =>
    get<FlightFlowResponse>(`/api/flights/state?trip_id=${encodeURIComponent(tripId)}`),
  searchDepartures: (tripId: string) =>
    post<FlightFlowResponse>("/api/flights/search-departures", {
      trip_id: tripId,
      validate_live: true,
      deep_research: true,
    }),
  selectDeparture: (tripId: string, optionId: string) =>
    post<FlightFlowResponse>("/api/flights/select-departure", {
      trip_id: tripId,
      option_id: optionId,
    }),
  searchReturns: (tripId: string) =>
    post<FlightFlowResponse>("/api/flights/search-returns", {
      trip_id: tripId,
      validate_live: true,
      deep_research: false,
    }),
  selectReturn: (tripId: string, optionId: string) =>
    post<FlightFlowResponse>("/api/flights/select-return", {
      trip_id: tripId,
      option_id: optionId,
    }),
  resetDeparture: (tripId: string) =>
    post<FlightFlowResponse>("/api/flights/reset-departure", {
      trip_id: tripId,
    }),
};
