import { describe, expect, it } from "vitest";
import { buildStages } from "@/lib/stages";
import type { TripState } from "@/lib/api";

function tripState(overrides: Partial<TripState> = {}): TripState {
  return {
    trip_id: "trip-1",
    intake: null,
    draft: null,
    workspace: null,
    trip_packet: null,
    shortlists: [],
    run_log: [],
    next_step: "",
    ...overrides,
  };
}

describe("buildStages", () => {
  it("allows navigation back to earlier visited stages even when they are not complete", () => {
    const stages = buildStages(tripState(), "flights");

    expect(stages.find((stage) => stage.label === "Shape")).toMatchObject({
      status: "todo",
      href: "/trip/trip-1/shape",
      canNavigate: true,
    });
  });

  it("keeps future incomplete stages locked", () => {
    const stages = buildStages(tripState(), "flights");

    expect(stages.find((stage) => stage.label === "Stays")).toMatchObject({
      status: "todo",
      href: "/trip/trip-1/stays",
      canNavigate: false,
    });
  });
});
