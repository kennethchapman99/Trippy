import { describe, expect, it } from "vitest";
import { deriveLiveBanner } from "@/components/ShortlistRow";
import { displayBedLayout, lodgingPhotoUrls } from "@/pages/Stays";

describe("deriveLiveBanner", () => {
  it("does not show a provider warning before a shortlist has loaded", () => {
    expect(deriveLiveBanner([], [], "lodging")).toBeNull();
  });

  it("suppresses the banner when any row has live data", () => {
    expect(
      deriveLiveBanner([], [{ live_data_status: "partial" }], "cars"),
    ).toBeNull();
  });

  it("distinguishes missing credentials from providers that returned no rows", () => {
    expect(
      deriveLiveBanner(["SERPAPI_KEY is not configured"], [], "cars")?.title,
    ).toContain("provider connected");

    expect(
      deriveLiveBanner(["SerpAPI Google Flights returned no offers for this route/date."], [], "flights")
        ?.title,
    ).toContain("No live flight rows returned");
  });
});

describe("displayBedLayout", () => {
  it("does not expose internal preference guidance as sourced bed evidence", () => {
    expect(
      displayBedLayout("king bed strongly preferred; queen compromise needs a clear upside"),
    ).toBe("Bed layout pending OpenClaw/FireCrawl verification");
  });

  it("keeps actual sourced bed layouts visible", () => {
    expect(displayBedLayout("3 beds, king")).toBe("3 beds, king");
  });
});

describe("lodgingPhotoUrls", () => {
  it("uses only property photo URLs supplied by the lodging source", () => {
    expect(
      lodgingPhotoUrls({
        photo_urls: [
          "https://hotel.example/exterior.jpg",
          "https://hotel.example/exterior.jpg",
          "",
          "/local-attraction.jpg",
        ],
      }),
    ).toEqual(["https://hotel.example/exterior.jpg"]);
  });

  it("does not invent a destination fallback when a lodging row has no photos", () => {
    expect(lodgingPhotoUrls({ photo_urls: [] })).toEqual([]);
    expect(lodgingPhotoUrls({})).toEqual([]);
  });
});
