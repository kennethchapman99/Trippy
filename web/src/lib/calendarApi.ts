export interface TripCalendarSummary {
  status: string;
  calendar_version: number;
  date_dependency_hash: string;
  envelope_locked: boolean;
  trip_start_date: string;
  trip_end_date: string;
  trip_nights: number | null;
  stay_nights_total: number;
  booking_safe: boolean;
  blocking_issues: string[];
  warnings: string[];
}

export interface TripEnvelopePayload {
  locked: boolean;
  outbound_flight_option_id: string;
  return_flight_option_id: string;
  trip_start_datetime: string;
  trip_start_date: string;
  trip_end_datetime: string;
  trip_end_date: string;
  home_return_datetime: string;
  origin_airport: string;
  destination_airport: string;
  return_airport: string;
  home_arrival_airport: string;
  trip_days: number | null;
  trip_nights: number | null;
  timezone_notes: string[];
  source: string;
}

export interface StaySegmentPayload {
  segment_id: string;
  sequence: number;
  region: string;
  location_label: string;
  start_date: string;
  end_date: string;
  nights: number;
  lodging_option_id: string;
  status: string;
  check_in_status: string;
  check_out_status: string;
  constraints: string[];
  warnings: string[];
}

export interface TransferSegmentPayload {
  transfer_id: string;
  sequence: number;
  from_region: string;
  to_region: string;
  from_airport: string;
  to_airport: string;
  date: string;
  mode: string;
  selected_option_id: string;
  candidate_option_ids: string[];
  price_status: string;
  friction_score: number | null;
  booking_safe: boolean;
  warnings: string[];
}

export interface TripCalendarPayload {
  trip_id: string;
  schema_version: string;
  status: string;
  calendar_version: number;
  date_dependency_hash: string;
  trip_envelope: TripEnvelopePayload;
  stay_segments: StaySegmentPayload[];
  transfer_segments: TransferSegmentPayload[];
  integrity: {
    invariant_results: Record<string, boolean>;
    booking_safe: boolean;
    blocking_issues: string[];
    warnings: string[];
    stale_option_ids: string[];
  };
}

export interface TripCalendarResponse {
  trip_id: string;
  calendar: TripCalendarPayload;
  summary: TripCalendarSummary;
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

export const calendarApi = {
  getCalendar: (tripId: string) =>
    get<TripCalendarResponse>(`/api/calendar?trip_id=${encodeURIComponent(tripId)}`),
  rebuildCalendar: (tripId: string) =>
    post<TripCalendarResponse>("/api/calendar/rebuild", { trip_id: tripId }),
};
