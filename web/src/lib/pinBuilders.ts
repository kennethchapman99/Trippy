import type { MapPin, MapPinType } from "@/components/TripMap";
import type {
  ActivityOption,
  FlightOption,
  LodgingOption,
} from "@/lib/api";
import { lookupFallback, type LngLat } from "@/lib/geocode";

function activityType(name: string, location: string): MapPinType {
  const s = `${name} ${location}`.toLowerCase();
  if (/\b(hike|trail|trek|summit|crater)\b/.test(s)) return "hike";
  if (/\b(beach|cove|shore|sand)\b/.test(s)) return "beach";
  if (/\b(snorkel|sail|boat|cruise|kayak|surf|whale)\b/.test(s)) return "boat";
  if (/\b(restaurant|dinner|lunch|food|luau|cafe|brunch)\b/.test(s)) return "food";
  return "sight";
}

export type GeocodeFn = (query: string) => LngLat | null | undefined;

export function makeGeocodeLookup(
  pairs: { query: string; coords: LngLat | null | undefined }[]
): GeocodeFn {
  const m = new Map<string, LngLat>();
  for (const { query, coords } of pairs) {
    if (coords) m.set(query.trim().toLowerCase().replace(/\s+/g, " "), coords);
  }
  return (q: string) => {
    if (!q) return undefined;
    return m.get(q.trim().toLowerCase().replace(/\s+/g, " "));
  };
}

export function buildLodgingPins(
  options: LodgingOption[],
  geocode: GeocodeFn
): MapPin[] {
  return options
    .map((o): MapPin | null => {
      const q = [o.location_area, o.island_or_region].filter(Boolean).join(", ");
      const coords = geocode(q) ?? lookupFallback(q);
      if (!coords) return null;
      return {
        id: `lodging-${o.option_id}`,
        type: "lodging",
        title: o.name,
        subtitle: [o.location_area, o.island_or_region].filter(Boolean).join(" · "),
        lng: coords[0],
        lat: coords[1],
        price: o.current_price_signal || o.price_band || undefined,
        notes: o.comfort_fit || undefined,
      };
    })
    .filter((p): p is MapPin => p !== null);
}

export function buildActivityPins(
  options: ActivityOption[],
  geocode: GeocodeFn
): MapPin[] {
  return options
    .map((o): MapPin | null => {
      const coords =
        geocode(o.island_location) ?? lookupFallback(o.island_location || "");
      if (!coords) return null;
      const at =
        o.scheduled_date && o.scheduled_start_time
          ? `${o.scheduled_date}T${o.scheduled_start_time}`
          : o.suggested_date && o.suggested_start_time
            ? `${o.suggested_date}T${o.suggested_start_time}`
            : undefined;
      return {
        id: `activity-${o.option_id}`,
        type: activityType(o.activity_name, o.island_location),
        title: o.activity_name,
        subtitle: o.island_location,
        lng: coords[0],
        lat: coords[1],
        at,
        price: o.price_band || undefined,
        notes: o.age_family_fit || undefined,
      };
    })
    .filter((p): p is MapPin => p !== null);
}

export function buildFlightPins(
  options: FlightOption[],
  geocode: GeocodeFn
): MapPin[] {
  const pins: MapPin[] = [];
  for (const o of options) {
    if (o.row_status !== "approved") continue;
    const dep = geocode(o.departure_airport) ?? lookupFallback(o.departure_airport);
    const arr = geocode(o.arrival_airport) ?? lookupFallback(o.arrival_airport);
    if (dep) {
      pins.push({
        id: `flight-${o.option_id}-dep`,
        type: "flight",
        title: `${o.departure_airport} → ${o.arrival_airport}`,
        subtitle: `${o.airline} ${o.flight_numbers.join(" / ")}`,
        lng: dep[0],
        lat: dep[1],
        at: o.departure_date && o.departure_time ? `${o.departure_date}T${o.departure_time}` : undefined,
        price: o.fare_estimate_cad || undefined,
      });
    }
    if (arr) {
      pins.push({
        id: `flight-${o.option_id}-arr`,
        type: "flight",
        title: `Arrive ${o.arrival_airport}`,
        subtitle: `${o.airline} ${o.flight_numbers.join(" / ")}`,
        lng: arr[0],
        lat: arr[1],
        at: o.arrival_date && o.arrival_time ? `${o.arrival_date}T${o.arrival_time}` : undefined,
      });
    }
  }
  return pins;
}

export function buildSeedPins(
  seeds: string[],
  geocode: GeocodeFn
): MapPin[] {
  return seeds
    .map((s, i): MapPin | null => {
      const coords = geocode(s) ?? lookupFallback(s);
      if (!coords) return null;
      return {
        id: `seed-${i}-${s}`,
        type: "sight",
        title: s,
        lng: coords[0],
        lat: coords[1],
      };
    })
    .filter((p): p is MapPin => p !== null);
}
