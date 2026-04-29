import { useEffect, useMemo, useState } from "react";

const NEGATIVE_CACHE = "__none__";
const CACHE_VERSION = "v3";
const STOP_WORDS = new Set([
  "trip",
  "vacation",
  "holiday",
  "week",
  "weekend",
  "easy",
  "reef",
  "food",
  "beach",
  "base",
  "adventure",
  "lodging",
  "hotel",
  "resort",
  "stay",
  "stays",
  "and",
  "or",
  "the",
  "a",
  "an",
  "with",
  "to",
  "from",
  "in",
]);

const REJECT_PATTERNS = /flag|coat[_-]of[_-]arms|bandeira|escudo|brasão|logo|seal|emblem|map\b|locator/i;

function uniqueClean(parts: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of parts) {
    const value = raw?.trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

function splitPlaces(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(/[·,|/]+/)
    .map((p) => p.trim())
    .filter(Boolean);
}

function importantNameWords(name: string | undefined, places: string[]): string[] {
  if (!name) return [];
  const placeWords = new Set(places.flatMap((s) => s.toLowerCase().split(/\s+/)));
  const out: string[] = [];
  for (const word of name.split(/\s+/)) {
    const cleaned = word.replace(/[^a-zA-Z]/g, "");
    if (!cleaned || cleaned.length < 3) continue;
    const lower = cleaned.toLowerCase();
    if (STOP_WORDS.has(lower) || placeWords.has(lower)) continue;
    if (!out.includes(cleaned)) out.push(cleaned);
  }
  return out;
}

export function buildImageQueries({
  title,
  destination,
  destinations,
  regions,
  location,
}: {
  title?: string;
  destination?: string;
  destinations?: string[];
  regions?: string[];
  location?: string;
}): string[] {
  const places = uniqueClean([
    ...splitPlaces(destination),
    ...(destinations ?? []),
    ...(regions ?? []),
    ...splitPlaces(location),
  ]);
  const nameWords = importantNameWords(title, places);

  const queries: string[] = [];
  const add = (...parts: Array<string | undefined>) => {
    const query = parts.filter(Boolean).join(" ").trim().replace(/\s+/g, " ");
    if (query && !queries.includes(query)) queries.push(query);
  };

  add(places[0], nameWords[0], places[1]);
  add(places[0], nameWords[0]);
  add(places[0], places[1]);
  add(places[0]);
  add(places[1], nameWords[0]);
  if (nameWords.length) add(nameWords.slice(0, 2).join(" "));

  return queries.map((q) => `${q} travel`).slice(0, 6);
}

async function fetchOpenverseImage(query: string): Promise<string | null> {
  const url = `https://api.openverse.org/v1/images/?q=${encodeURIComponent(query)}&page_size=20&mature=false`;
  const res = await fetch(url);
  if (!res.ok) return null;
  const data = await res.json();
  const results: Array<{ url?: string; thumbnail?: string; title?: string }> = data?.results ?? [];
  for (const result of results) {
    const candidate = result.thumbnail || result.url;
    if (!candidate) continue;
    const haystack = `${candidate} ${result.title ?? ""}`;
    if (REJECT_PATTERNS.test(haystack)) continue;
    return candidate;
  }
  return null;
}

export function useDestinationImage(input: Parameters<typeof buildImageQueries>[0]): string | null {
  const queries = useMemo(() => buildImageQueries(input), [
    input.title,
    input.destination,
    input.location,
    input.destinations?.join("|"),
    input.regions?.join("|"),
  ]);
  const cacheKey = queries.length ? `trippy:cover:${CACHE_VERSION}:${queries.join("|")}` : null;

  const [url, setUrl] = useState<string | null>(() => {
    if (!cacheKey || typeof localStorage === "undefined") return null;
    const cached = localStorage.getItem(cacheKey);
    if (cached === null || cached === NEGATIVE_CACHE) return null;
    return cached;
  });

  useEffect(() => {
    if (!cacheKey || queries.length === 0) return;
    const cached = localStorage.getItem(cacheKey);
    if (cached !== null) {
      setUrl(cached === NEGATIVE_CACHE ? null : cached);
      return;
    }

    let cancelled = false;
    (async () => {
      for (const query of queries) {
        try {
          const image = await fetchOpenverseImage(query);
          if (cancelled) return;
          if (image) {
            localStorage.setItem(cacheKey, image);
            setUrl(image);
            return;
          }
        } catch {
          // Try the next, broader query.
        }
      }
      if (!cancelled) localStorage.setItem(cacheKey, NEGATIVE_CACHE);
    })();

    return () => {
      cancelled = true;
    };
  }, [cacheKey, queries]);

  return url;
}
