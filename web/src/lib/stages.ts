import type { Stage } from "@/components/StageNav";
import type { TripState, ShortlistCategory } from "@/lib/api";

export type StageKey = "intake" | "shape" | "flights" | "stays" | "cars" | "do" | "timeline" | "packet";

const STAGE_DEFS: { key: StageKey; id: number; label: string }[] = [
  { key: "intake", id: 1, label: "Intake" },
  { key: "shape", id: 2, label: "Shape" },
  { key: "flights", id: 3, label: "Flights" },
  { key: "stays", id: 4, label: "Stays" },
  { key: "cars", id: 5, label: "Cars" },
  { key: "do", id: 6, label: "Do" },
  { key: "timeline", id: 7, label: "Timeline" },
  { key: "packet", id: 8, label: "Packet" },
];

const CATEGORY_BY_STAGE: Partial<Record<StageKey, ShortlistCategory>> = {
  flights: "flights",
  stays: "lodging",
  cars: "cars",
  do: "activities",
};

function shortlistDone(state: TripState | undefined, category: ShortlistCategory): boolean {
  if (!state) return false;
  const sl = state.shortlists?.find((s) => s.category === category);
  if (!sl) return false;
  const opts =
    category === "flights"
      ? sl.flight_options
      : category === "lodging"
        ? sl.lodging_options
        : category === "cars"
          ? sl.car_options
          : sl.activity_options;
  return opts.some((o) => o.row_status === "approved" || o.row_status === "booked" || o.row_status === "confirmed");
}

function shortlistExists(state: TripState | undefined, category: ShortlistCategory): boolean {
  if (!state) return false;
  return !!state.shortlists?.find((s) => s.category === category);
}

function stagePath(tripId: string | undefined, key: StageKey): string | undefined {
  if (!tripId) return undefined;
  switch (key) {
    case "intake":
      return undefined;
    case "packet":
      return `/trip/${tripId}/timeline`;
    case "do":
      return `/trip/${tripId}/do`;
    default:
      return `/trip/${tripId}/${key}`;
  }
}

function isDone(state: TripState | undefined, key: StageKey): boolean {
  if (!state) return false;
  switch (key) {
    case "intake":
      return !!state.intake;
    case "shape":
      return !!state.draft?.selected_option_id;
    case "flights":
    case "stays":
    case "cars":
    case "do":
      return shortlistDone(state, CATEGORY_BY_STAGE[key]!);
    case "timeline":
      return !!state.workspace;
    case "packet":
      return !!state.trip_packet;
  }
}

export function buildStages(state: TripState | undefined, current: StageKey): Stage[] {
  let foundCurrent = false;
  const tripId = state?.trip_id;
  return STAGE_DEFS.map((def): Stage => {
    const href = stagePath(tripId, def.key);
    const canNavigate = !!href && (!foundCurrent || def.key === current || isDone(state, def.key));

    if (def.key === current) {
      foundCurrent = true;
      return { id: def.id, label: def.label, status: "current", href, canNavigate };
    }
    if (!foundCurrent && isDone(state, def.key)) {
      return { id: def.id, label: def.label, status: "done", href, canNavigate };
    }
    return { id: def.id, label: def.label, status: "todo", href, canNavigate };
  });
}

export function nextStagePath(tripId: string, current: StageKey): string {
  const idx = STAGE_DEFS.findIndex((s) => s.key === current);
  const next = STAGE_DEFS[idx + 1];
  if (!next) return `/trip/${tripId}/timeline`;
  if (next.key === "intake") return "/new";
  if (next.key === "packet") return `/trip/${tripId}/timeline`;
  return `/trip/${tripId}/${next.key === "do" ? "do" : next.key}`;
}

export function shortlistOptions(
  state: TripState | undefined,
  category: ShortlistCategory,
) {
  if (!state) return null;
  const sl = state.shortlists?.find((s) => s.category === category);
  return sl ?? null;
}

export { shortlistExists };
