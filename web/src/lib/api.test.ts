import { describe, expect, it } from "vitest";
import { mergeShortlistIntoTrip, type ShortlistState, type TripState } from "@/lib/api";

function shortlist(category: ShortlistState["category"], warning: string): ShortlistState {
  return {
    trip_id: "trip-1",
    category,
    recommended_option_id: null,
    recommendation_summary: "",
    flight_options: [],
    lodging_options: [],
    car_options: [],
    activity_options: [],
    partial_failures: [],
    warnings: [warning],
    next_actions: [],
  };
}

describe("mergeShortlistIntoTrip", () => {
  it("replaces a stale shortlist with the fresh API result", () => {
    const trip = {
      trip_id: "trip-1",
      intake: null,
      draft: null,
      workspace: null,
      trip_packet: null,
      shortlists: [shortlist("flights", "old handoff rows")],
      run_log: [],
      next_step: "",
    } satisfies TripState;

    const merged = mergeShortlistIntoTrip(trip, shortlist("flights", "Duffel returned live rows"));

    expect(merged?.shortlists).toHaveLength(1);
    expect(merged?.shortlists[0].warnings).toEqual(["Duffel returned live rows"]);
  });

  it("adds a new category without dropping existing shortlists", () => {
    const trip = {
      trip_id: "trip-1",
      intake: null,
      draft: null,
      workspace: null,
      trip_packet: null,
      shortlists: [shortlist("flights", "live flights")],
      run_log: [],
      next_step: "",
    } satisfies TripState;

    const merged = mergeShortlistIntoTrip(trip, shortlist("cars", "live cars"));

    expect(merged?.shortlists.map((item) => item.category)).toEqual(["flights", "cars"]);
  });
});
