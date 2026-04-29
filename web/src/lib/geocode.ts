import { useQueries, useQuery } from "@tanstack/react-query";

const TOKEN_KEY = "trippy.mapbox.token";
const DEFAULT_MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN ?? "";

export function getMapboxToken(): string {
  if (typeof window === "undefined") return DEFAULT_MAPBOX_TOKEN;
  return localStorage.getItem(TOKEN_KEY) || DEFAULT_MAPBOX_TOKEN;
}

export type LngLat = [number, number];

// Curated fallback coords so we don't hammer Mapbox for common queries.
// Keys are normalized (lowercased, trimmed, single-spaced).
const FALLBACK: Record<string, LngLat> = {
  "azores": [-25.6756, 37.7412],
  "sao miguel": [-25.5089, 37.7804],
  "são miguel": [-25.5089, 37.7804],
  "ponta delgada": [-25.6756, 37.7412],
  "furnas": [-25.3108, 37.7725],
  "ribeira grande": [-25.5207, 37.8210],
  "lagoa": [-25.5724, 37.7448],
  "vila franca do campo": [-25.4316, 37.7167],
  "sete cidades": [-25.7942, 37.8625],
  "mosteiros": [-25.8192, 37.8907],
  "capelas": [-25.6934, 37.8337],
  "caloura": [-25.5068, 37.7078],
  "nordeste": [-25.1463, 37.8338],
  "angra do heroismo": [-27.2208, 38.6552],
  "angra do heroísmo": [-27.2208, 38.6552],
  "terceira": [-27.2147, 38.7223],
  "faial": [-28.7044, 38.5750],
  "horta": [-28.6290, 38.5347],
  "pico": [-28.3989, 38.4689],
  "hawaii": [-155.5828, 19.8968],
  "maui": [-156.3319, 20.7984],
  "oahu": [-157.8583, 21.4389],
  "honolulu": [-157.8583, 21.3069],
  "kauai": [-159.5261, 22.0964],
  "big island": [-155.5828, 19.5429],
  "hawaii (big island)": [-155.5828, 19.5429],
  "wailea": [-156.4421, 20.6868],
  "kihei": [-156.4456, 20.7644],
  "lahaina": [-156.6825, 20.8783],
  "kaanapali": [-156.6936, 20.9244],
  "hana": [-155.9904, 20.7589],
  "volcano village": [-155.2356, 19.4302],
  "kona": [-155.9962, 19.6390],
  "kailua-kona": [-155.9962, 19.6390],
  "waikiki": [-157.8267, 21.2766],
  "ogg": [-156.4305, 20.8987],
  "koa": [-156.0456, 19.7388],
  "hnl": [-157.9224, 21.3187],
  "lih": [-159.3389, 21.9760],
  "sfo": [-122.3790, 37.6213],
  "lax": [-118.4085, 33.9416],
  "yvr": [-123.1840, 49.1967],
  "yyz": [-79.6306, 43.6777],
  "yyc": [-114.0203, 51.1215],
};

function normalize(q: string): string {
  return q.trim().toLowerCase().replace(/\s+/g, " ");
}

function fallbackFor(query: string): LngLat | undefined {
  const n = normalize(query);
  if (FALLBACK[n]) return FALLBACK[n];
  // Try first segment before " · " or "," (e.g. "Wailea · Maui" → "wailea")
  const head = n.split(/[·,]/)[0].trim();
  if (head && FALLBACK[head]) return FALLBACK[head];
  // Try any token match
  for (const key of Object.keys(FALLBACK)) {
    if (n.includes(key)) return FALLBACK[key];
  }
  return undefined;
}

async function mapboxGeocode(query: string): Promise<LngLat | null> {
  const token = getMapboxToken();
  const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(
    query
  )}.json?limit=1&access_token=${token}`;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    const feat = data?.features?.[0];
    if (!feat?.center || feat.center.length < 2) return null;
    return [feat.center[0], feat.center[1]];
  } catch {
    return null;
  }
}

export function useGeocode(query: string | null | undefined) {
  return useQuery({
    queryKey: ["geocode", normalize(query ?? "")],
    queryFn: async (): Promise<LngLat | null> => {
      if (!query) return null;
      const fb = fallbackFor(query);
      if (fb) return fb;
      return mapboxGeocode(query);
    },
    enabled: !!query,
    staleTime: 24 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });
}

export function useGeocodes(queries: (string | null | undefined)[]) {
  return useQueries({
    queries: queries.map((q) => ({
      queryKey: ["geocode", normalize(q ?? "")],
      queryFn: async (): Promise<LngLat | null> => {
        if (!q) return null;
        const fb = fallbackFor(q);
        if (fb) return fb;
        return mapboxGeocode(q);
      },
      enabled: !!q,
      staleTime: 24 * 60 * 60 * 1000,
      gcTime: 24 * 60 * 60 * 1000,
    })),
  });
}

export function lookupFallback(query: string): LngLat | undefined {
  return fallbackFor(query);
}
