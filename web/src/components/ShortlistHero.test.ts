import { describe, expect, it } from "vitest";
import { deriveTripDateRangeLabel } from "@/components/ShortlistHero";
import type { ShortlistState, TripIntake } from "@/lib/api";

const intake: TripIntake = {
  trip_id: "trip-1",
  trip_name: "Test Trip",
  destination_seeds: ["Azores"],
  travel_window: {
    start_date: "2027-06-01",
    end_date: "2027-06-08",
    label: null,
    season: null,
  },
  travelers: 2,
  party: {
    adults: 2,
    children: 0,
    party_type: "couple",
  },
  duration_days: 7,
};

function flightShortlist(rowStatus: "researched" | "approved", explicitReturn = false): ShortlistState {
  return {
    trip_id: "trip-1",
    category: "flights",
    recommended_option_id: "flight-1",
    recommendation_summary: "",
    flight_options: [
      {
        option_id: "flight-1",
        rank: 1,
        airline: "Air Canada",
        flight_numbers: ["AC100"],
        departure_date: "2027-06-10",
        arrival_date: "2027-06-11",
        departure_airport: "YYZ",
        arrival_airport: "PDL",
        departure_time: "10:00",
        arrival_time: "08:00",
        stops: 1,
        layover_airports: [],
        layover_duration: null,
        total_travel_duration: "10h",
        timing_fit: "",
        recommendation_label: "",
        recommendation_rationale: "",
        fare_estimate_cad: "$1,000",
        price_band: "$1,000",
        baggage_cabin_notes: "",
        booking_source: "Google Flights",
        deep_link: "https://www.google.com/travel/flights/search?departure=2027-06-10&return=2027-06-17",
        friction_score: 10,
        family_comfort_score: 90,
        recommendation_grade: "strong",
        tradeoffs: [],
        friction_flags: [],
        row_status: rowStatus,
      },
      {
        option_id: "flight-return",
        rank: 2,
        airline: "Air Canada",
        flight_numbers: ["AC101"],
        departure_date: "2027-06-18",
        arrival_date: "2027-06-18",
        departure_airport: "PDL",
        arrival_airport: "YYZ",
        departure_time: "11:00",
        arrival_time: "15:00",
        stops: 1,
        layover_airports: [],
        layover_duration: null,
        total_travel_duration: "10h",
        timing_fit: "",
        recommendation_label: "",
        recommendation_rationale: "",
        fare_estimate_cad: "$1,000",
        price_band: "$1,000",
        baggage_cabin_notes: "",
        booking_source: "Google Flights",
        deep_link: "",
        friction_score: 10,
        family_comfort_score: 90,
        recommendation_grade: "strong",
        tradeoffs: [],
        friction_flags: [],
        row_status: explicitReturn ? "approved" : "researched",
      },
    ],
    lodging_options: [],
    car_options: [],
    activity_options: [],
    partial_failures: [],
    warnings: [],
    next_actions: [],
    artifacts: explicitReturn
      ? {
          flight_selection: {
            selected_outbound_option_id: "flight-1",
            selected_return_option_id: "flight-return",
            constraint_status: "complete",
          },
        }
      : undefined,
  };
}

describe("deriveTripDateRangeLabel", () => {
  it("uses selected flight departure and return dates ahead of intake dates", () => {
    expect(deriveTripDateRangeLabel(intake, [flightShortlist("approved")])).toBe(
      "Jun 10 - Jun 17, 2027",
    );
  });

  it("does not use an unselected recommended flight", () => {
    expect(deriveTripDateRangeLabel(intake, [flightShortlist("researched")])).toBe(
      "Jun 1 - Jun 8, 2027",
    );
  });

  it("uses an explicit selected return flight when present", () => {
    expect(deriveTripDateRangeLabel(intake, [flightShortlist("approved", true)])).toBe(
      "Jun 10 - Jun 18, 2027",
    );
  });
});
