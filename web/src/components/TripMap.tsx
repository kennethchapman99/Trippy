import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import {
  Plane,
  BedDouble,
  Car,
  Utensils,
  Camera,
  Mountain,
  Waves,
  Ship,
  X,
  Star,
  ExternalLink,
  type LucideIcon,
} from "lucide-react";

export type MapPinType =
  | "flight"
  | "lodging"
  | "car"
  | "food"
  | "sight"
  | "hike"
  | "beach"
  | "boat";

export interface MapPin {
  id: string;
  type: MapPinType;
  title: string;
  subtitle?: string;
  lng: number;
  lat: number;
  /** ISO datetime — drives chronological order + scrubber */
  at?: string;
  rating?: number;
  reviews?: number;
  photo?: string;
  price?: string;
  notes?: string;
}

export interface TripMapProps {
  pins: MapPin[];
  /** Initial center; if omitted, fits to pins */
  center?: [number, number];
  zoom?: number;
  height?: string;
  /** Compact = decision-support inline use. Full = primary map page. */
  variant?: "full" | "compact";
  /** Hide the chronological scrubber (e.g. for split-stay decision view) */
  showScrubber?: boolean;
  /** Optional alternative location groups to compare (e.g. island A vs island B) */
  groups?: { id: string; label: string; color: string; pinIds: string[] }[];
  className?: string;
}

const TYPE_META: Record<MapPinType, { label: string; icon: LucideIcon; color: string }> = {
  flight:  { label: "Flights",  icon: Plane,     color: "205 88% 48%" },
  lodging: { label: "Lodging",  icon: BedDouble, color: "18 95% 55%"  },
  car:     { label: "Cars",     icon: Car,       color: "215 60% 14%" },
  food:    { label: "Food",     icon: Utensils,  color: "8 90% 65%"   },
  sight:   { label: "Sights",   icon: Camera,    color: "178 70% 45%" },
  hike:    { label: "Hikes",    icon: Mountain,  color: "145 55% 38%" },
  beach:   { label: "Beaches",  icon: Waves,     color: "195 90% 65%" },
  boat:    { label: "Boats",    icon: Ship,      color: "215 75% 28%" },
};

const TOKEN_KEY = "trippy.mapbox.token";
const DEFAULT_MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN ?? "";

export const TripMap = ({
  pins,
  center,
  zoom = 9,
  height = "100%",
  variant = "full",
  showScrubber = true,
  groups,
  className = "",
}: TripMapProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<mapboxgl.Marker[]>([]);

  const [token, setToken] = useState<string>(
    () => localStorage.getItem(TOKEN_KEY) || DEFAULT_MAPBOX_TOKEN
  );
  const [tokenInput, setTokenInput] = useState("");
  const [activeTypes, setActiveTypes] = useState<Set<MapPinType>>(
    () => new Set(Object.keys(TYPE_META) as MapPinType[])
  );
  const [filterOpen, setFilterOpen] = useState(false);
  const [selected, setSelected] = useState<MapPin | null>(null);
  const [scrubIdx, setScrubIdx] = useState(0);
  const [playing, setPlaying] = useState(false);

  // Sort chronologically for scrubber
  const chronological = useMemo(
    () => [...pins].filter((p) => p.at).sort((a, b) => (a.at! < b.at! ? -1 : 1)),
    [pins]
  );

  const visiblePins = useMemo(
    () => pins.filter((p) => activeTypes.has(p.type)),
    [pins, activeTypes]
  );

  // Init map
  useEffect(() => {
    if (!token || !containerRef.current || mapRef.current) return;
    mapboxgl.accessToken = token;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/outdoors-v12",
      center: center ?? [pins[0]?.lng ?? 0, pins[0]?.lat ?? 20],
      zoom,
      pitch: variant === "full" ? 35 : 0,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      if (pins.length > 1) {
        const b = new mapboxgl.LngLatBounds();
        pins.forEach((p) => b.extend([p.lng, p.lat]));
        map.fitBounds(b, { padding: 80, duration: 0, maxZoom: 11 });
      }
    });

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Render markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    visiblePins.forEach((pin) => {
      const meta = TYPE_META[pin.type];
      const groupColor = groups?.find((g) => g.pinIds.includes(pin.id))?.color;
      const color = groupColor ?? `hsl(${meta.color})`;

      const el = document.createElement("button");
      el.className =
        "group relative flex items-center justify-center w-10 h-10 rounded-full border-[3px] border-[hsl(215_60%_14%)] shadow-[0_4px_0_hsl(215_60%_14%/0.9)] transition-transform hover:scale-110 active:scale-95";
      el.style.background = color;
      el.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">${iconPath(pin.type)}</svg>`;
      el.onclick = (e) => {
        e.stopPropagation();
        setSelected(pin);
        map.flyTo({ center: [pin.lng, pin.lat], zoom: 13, duration: 900 });
      };

      const marker = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([pin.lng, pin.lat])
        .addTo(map);
      markersRef.current.push(marker);
    });

    // Draw chronological route line
    const sourceId = "trippy-route";
    const layerId = "trippy-route-line";
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
    const visibleChrono = chronological.filter((p) => activeTypes.has(p.type));
    if (showScrubber && visibleChrono.length > 1) {
      map.addSource(sourceId, {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: visibleChrono.map((p) => [p.lng, p.lat]),
          },
        },
      });
      map.addLayer({
        id: layerId,
        type: "line",
        source: sourceId,
        paint: {
          "line-color": "hsl(18, 95%, 55%)",
          "line-width": 3,
          "line-dasharray": [2, 2],
          "line-opacity": 0.6,
        },
      });
    }
  }, [visiblePins, chronological, activeTypes, groups, showScrubber]);

  // Auto-play scrubber
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setScrubIdx((i) => {
        const next = i + 1;
        if (next >= chronological.length) {
          setPlaying(false);
          return i;
        }
        return next;
      });
    }, 1800);
    return () => clearInterval(id);
  }, [playing, chronological.length]);

  // Fly to scrubbed pin
  useEffect(() => {
    const map = mapRef.current;
    const pin = chronological[scrubIdx];
    if (!map || !pin) return;
    map.flyTo({ center: [pin.lng, pin.lat], zoom: 12, duration: 1200, essential: true });
    setSelected(pin);
  }, [scrubIdx, chronological]);

  const toggleType = (t: MapPinType) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  // ------- Token gate -------
  if (!token) {
    return (
      <div
        className={`relative rounded-3xl border-2 border-foreground/10 bg-gradient-sky overflow-hidden flex items-center justify-center ${className}`}
        style={{ height }}
      >
        <div className="max-w-md p-8 bg-card/95 backdrop-blur rounded-3xl border-2 border-foreground/10 shadow-card text-center space-y-3">
          <div className="text-2xl font-[Fredoka] font-bold">🗺️ Connect Mapbox</div>
          <p className="text-sm text-muted-foreground">
            Paste your Mapbox public token to light up the map. Free tier covers ~50k loads/month.
            Grab one at{" "}
            <a
              href="https://account.mapbox.com/access-tokens/"
              target="_blank"
              rel="noreferrer"
              className="text-secondary font-bold underline"
            >
              mapbox.com
            </a>
            .
          </p>
          <input
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="pk.eyJ1Ijoi..."
            className="w-full px-4 py-3 rounded-2xl border-2 border-foreground/15 bg-background font-mono text-sm"
          />
          <button
            onClick={() => {
              if (tokenInput.startsWith("pk.")) {
                localStorage.setItem(TOKEN_KEY, tokenInput.trim());
                setToken(tokenInput.trim());
              }
            }}
            className="w-full px-5 py-3 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker"
          >
            Light up the map
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative rounded-3xl overflow-hidden border-2 border-foreground/10 shadow-card ${className}`} style={{ height }}>
      <div ref={containerRef} className="absolute inset-0" />

      {/* Filter slide-out */}
      <div className="absolute top-4 left-4 z-10 flex items-start gap-2">
        <button
          onClick={() => setFilterOpen((v) => !v)}
          className="px-4 py-2.5 rounded-2xl bg-card border-2 border-foreground shadow-sticker font-bold text-sm flex items-center gap-2"
        >
          <span className="h-2 w-2 rounded-full bg-gradient-sunset" />
          Layers · {activeTypes.size}
        </button>
        <div
          className={`bg-card/95 backdrop-blur rounded-2xl border-2 border-foreground/15 shadow-card overflow-hidden transition-all duration-300 ${
            filterOpen ? "max-w-xs opacity-100 p-3" : "max-w-0 opacity-0 p-0"
          }`}
        >
          <div className="flex flex-col gap-1.5 min-w-[180px]">
            {(Object.keys(TYPE_META) as MapPinType[]).map((t) => {
              const m = TYPE_META[t];
              const Icon = m.icon;
              const on = activeTypes.has(t);
              const count = pins.filter((p) => p.type === t).length;
              return (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={`flex items-center justify-between gap-3 px-3 py-2 rounded-xl border-2 text-sm font-bold transition-bounce ${
                    on ? "border-foreground/80 bg-background" : "border-transparent text-muted-foreground bg-muted/40"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className="h-6 w-6 rounded-full flex items-center justify-center border-2 border-foreground/80"
                      style={{ background: `hsl(${m.color})` }}
                    >
                      <Icon className="h-3.5 w-3.5 text-white" />
                    </span>
                    {m.label}
                  </span>
                  <span className="text-xs opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Group legend (split-stay decision mode) */}
      {groups && groups.length > 0 && (
        <div className="absolute top-4 right-16 z-10 bg-card/95 backdrop-blur rounded-2xl border-2 border-foreground/15 shadow-card p-2 flex gap-2">
          {groups.map((g) => (
            <span key={g.id} className="flex items-center gap-1.5 px-2 py-1 text-xs font-bold">
              <span className="h-3 w-3 rounded-full border-2 border-foreground/80" style={{ background: g.color }} />
              {g.label}
            </span>
          ))}
        </div>
      )}

      {/* Detail card */}
      {selected && (
        <div className="absolute bottom-4 left-4 right-4 md:right-auto md:max-w-sm z-20 bg-card rounded-2xl border-2 border-foreground/15 shadow-card overflow-hidden animate-fade-up">
          {selected.photo && (
            <div className="h-32 w-full overflow-hidden bg-muted">
              <img src={selected.photo} alt={selected.title} className="w-full h-full object-cover" />
            </div>
          )}
          <button
            onClick={() => setSelected(null)}
            className="absolute top-2 right-2 h-8 w-8 rounded-full bg-card border-2 border-foreground/20 flex items-center justify-center"
          >
            <X className="h-4 w-4" />
          </button>
          <div className="p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span
                className="h-7 w-7 rounded-full flex items-center justify-center border-2 border-foreground/80"
                style={{ background: `hsl(${TYPE_META[selected.type].color})` }}
              >
                {(() => {
                  const Icon = TYPE_META[selected.type].icon;
                  return <Icon className="h-3.5 w-3.5 text-white" />;
                })()}
              </span>
              <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                {TYPE_META[selected.type].label}
              </span>
              {selected.price && (
                <span className="ml-auto text-sm font-bold">{selected.price}</span>
              )}
            </div>
            <h3 className="font-[Fredoka] text-lg font-bold leading-tight">{selected.title}</h3>
            {selected.subtitle && <p className="text-sm text-muted-foreground">{selected.subtitle}</p>}
            {(selected.rating || selected.reviews) && (
              <div className="flex items-center gap-1 text-sm">
                <Star className="h-4 w-4 fill-[hsl(var(--sunshine))] text-[hsl(var(--sunshine))]" />
                <span className="font-bold">{selected.rating?.toFixed(1)}</span>
                <span className="text-muted-foreground">({selected.reviews} reviews)</span>
              </div>
            )}
            {selected.notes && <p className="text-sm">{selected.notes}</p>}
            {selected.at && (
              <div className="text-xs text-muted-foreground font-mono">
                {new Date(selected.at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
              </div>
            )}
            <button className="w-full mt-2 px-3 py-2 rounded-xl bg-muted hover:bg-muted/70 text-sm font-bold flex items-center justify-center gap-2">
              View details <ExternalLink className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Chronological scrubber */}
      {showScrubber && chronological.length > 1 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 bg-card/95 backdrop-blur rounded-2xl border-2 border-foreground/15 shadow-card px-4 py-3 w-[min(560px,calc(100%-2rem))]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setPlaying((p) => !p)}
              className="h-10 w-10 rounded-full bg-gradient-sunset border-2 border-foreground shadow-sticker text-primary-foreground font-bold shrink-0"
            >
              {playing ? "❚❚" : "▶"}
            </button>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between text-xs font-bold mb-1">
                <span className="truncate">{chronological[scrubIdx]?.title}</span>
                <span className="text-muted-foreground font-mono shrink-0 ml-2">
                  {scrubIdx + 1} / {chronological.length}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={chronological.length - 1}
                value={scrubIdx}
                onChange={(e) => {
                  setPlaying(false);
                  setScrubIdx(Number(e.target.value));
                }}
                className="w-full accent-[hsl(var(--primary))]"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// inline svg paths for marker icons (avoids rendering React into a DOM element)
function iconPath(t: MapPinType) {
  switch (t) {
    case "flight":  return '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>';
    case "lodging": return '<path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"/>';
    case "car":     return '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/>';
    case "food":    return '<path d="M3 11h18M3 11a9 9 0 0 1 18 0M12 11v9M2 19h20"/>';
    case "sight":   return '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>';
    case "hike":    return '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>';
    case "beach":   return '<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>';
    case "boat":    return '<path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1s1.2 1 2.5 1c2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1M19.4 18 22 12H2l2.6 6M3 9V4l9 4M14 7V3h-4"/>';
  }
}

export default TripMap;
