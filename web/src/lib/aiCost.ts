export interface AiCostCallRecord {
  id: string;
  trip_id: string | null;
  service: string;
  model: string;
  mode: string;
  prompt_version: string;
  status: string;
  cache_hit: boolean;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  started_at: string;
  ended_at: string | null;
  error: string;
  metadata: Record<string, unknown>;
}

export interface AiCostSummary {
  trip_id: string;
  total_calls: number;
  cache_hits: number;
  total_duration_ms: number;
  estimated_cost_usd: number;
  by_service: Record<string, number>;
  by_model: Record<string, number>;
  recent_calls: AiCostCallRecord[];
}

export async function getAiCostSummary(tripId: string): Promise<AiCostSummary> {
  const res = await fetch(`/api/ai-cost?trip_id=${encodeURIComponent(tripId)}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `GET ai cost failed: ${res.status}`);
  }
  return res.json() as Promise<AiCostSummary>;
}

export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "$0.0000";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0s";
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}
