import type { AppState, IdeaRequest, IdeaResponse, TripState } from "@/types/trippy";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : `Request failed: ${response.status}`;
    throw new Error(message);
  }
  return data as T;
}

export const trippyClient = {
  getAppState(): Promise<AppState> {
    return requestJson<AppState>("/api/state");
  },

  getTrip(tripId: string): Promise<TripState> {
    return requestJson<TripState>(`/api/trip?trip_id=${encodeURIComponent(tripId)}`);
  },

  suggestIdeas(payload: IdeaRequest): Promise<IdeaResponse> {
    return requestJson<IdeaResponse>("/api/suggest-ideas", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  createIntake(payload: Record<string, unknown>): Promise<{ intake: { trip_id: string }; workflow_id?: string; next_step?: string }> {
    return requestJson("/api/intake", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  draftPlan(tripId: string): Promise<Record<string, unknown>> {
    return requestJson("/api/draft", {
      method: "POST",
      body: JSON.stringify({ trip_id: tripId }),
    });
  },
};
