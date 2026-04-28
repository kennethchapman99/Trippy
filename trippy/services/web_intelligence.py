"""Firecrawl-backed web intelligence normalization for travel domains."""

from __future__ import annotations

from trippy.models.web_research import (
    ActivityWebOption,
    CarRentalWebOption,
    FlightWebContext,
    LodgingWebOption,
    WebResearchResult,
)
from trippy.services.firecrawl import FirecrawlService


class TravelWebIntelligenceService:
    def __init__(self, *, firecrawl: FirecrawlService | None = None) -> None:
        self._firecrawl = firecrawl or FirecrawlService()

    def extract_travel_page_context(self, url: str, query: str = "") -> WebResearchResult:
        if query:
            rows = self._firecrawl.research(query, limit=1)
            if rows:
                return rows[0]
        return self._firecrawl.scrape_url(url)

    def research_lodging_web(self, query: str) -> list[LodgingWebOption]:
        rows = self._firecrawl.research(query)
        return [
            LodgingWebOption(
                name=(row.source_title or row.source_domain),
                address_or_area=row.structured_data.get("description", ""),
                url=row.source_url,
                amenities=_sniff_list(
                    row.raw_markdown_excerpt, ["pool", "wifi", "parking", "breakfast"]
                ),
                family_fit_notes=_sniff_sentence(
                    row.raw_markdown_excerpt, ["family", "kids", "suite", "queen"]
                ),
                cancellation_policy=_sniff_sentence(
                    row.raw_markdown_excerpt, ["cancellation", "refundable"]
                ),
                check_in_time=_sniff_sentence(row.raw_markdown_excerpt, ["check-in", "check in"]),
                check_out_time=_sniff_sentence(
                    row.raw_markdown_excerpt, ["check-out", "check out"]
                ),
                parking_notes=_sniff_sentence(row.raw_markdown_excerpt, ["parking"]),
                pet_policy=_sniff_sentence(row.raw_markdown_excerpt, ["pet"]),
                accessibility_notes=_sniff_sentence(
                    row.raw_markdown_excerpt, ["accessible", "wheelchair"]
                ),
                proximity_notes=_sniff_sentence(
                    row.raw_markdown_excerpt, ["minutes", "walk", "airport"]
                ),
                source_urls=[row.source_url],
                confidence=row.confidence,
                warnings=row.warnings,
            )
            for row in rows
        ]

    def research_activities_web(self, query: str) -> list[ActivityWebOption]:
        rows = self._firecrawl.research(query)
        return [
            ActivityWebOption(
                name=row.source_title or "Activity option",
                location=row.source_domain,
                url=row.source_url,
                duration=_sniff_sentence(row.raw_markdown_excerpt, ["hour", "duration"]),
                schedule_or_hours=_sniff_sentence(
                    row.raw_markdown_excerpt, ["open", "hours", "daily"]
                ),
                price_text=_sniff_sentence(row.raw_markdown_excerpt, ["$", "CAD", "USD", "price"]),
                age_restrictions=_sniff_sentence(
                    row.raw_markdown_excerpt, ["age", "years", "minimum"]
                ),
                cancellation_policy=_sniff_sentence(
                    row.raw_markdown_excerpt, ["cancellation", "refund"]
                ),
                weather_dependency=_sniff_sentence(
                    row.raw_markdown_excerpt, ["weather", "rain", "wind"]
                ),
                family_fit_notes=_sniff_sentence(row.raw_markdown_excerpt, ["family", "kids"]),
                accessibility_notes=_sniff_sentence(
                    row.raw_markdown_excerpt, ["accessible", "mobility"]
                ),
                source_urls=[row.source_url],
                confidence=row.confidence,
                warnings=row.warnings,
            )
            for row in rows
        ]

    def enrich_flight_with_web_context(self, query: str) -> FlightWebContext:
        rows = self._firecrawl.research(query, limit=2)
        text = "\n".join(row.raw_markdown_excerpt for row in rows)
        return FlightWebContext(
            route=query,
            baggage_policy=_sniff_sentence(text, ["baggage", "bag", "carry-on", "checked"]),
            carry_on_policy=_sniff_sentence(text, ["carry-on", "carry on"]),
            checked_bag_policy=_sniff_sentence(text, ["checked bag", "checked baggage"]),
            fare_rules=_sniff_sentence(text, ["fare", "basic", "economy", "rules"]),
            change_cancel_policy=_sniff_sentence(text, ["change", "cancel", "refund"]),
            seat_selection_notes=_sniff_sentence(text, ["seat selection", "seats"]),
            family_travel_notes=_sniff_sentence(text, ["family", "child", "infant"]),
            airport_transfer_notes=_sniff_sentence(text, ["airport transfer", "shuttle", "train"]),
            source_urls=[row.source_url for row in rows if row.source_url],
            confidence=max((row.confidence for row in rows), default=0.0),
            warnings=sorted({warning for row in rows for warning in row.warnings}),
        )

    def enrich_car_rental_with_web_context(self, query: str) -> list[CarRentalWebOption]:
        rows = self._firecrawl.research(query)
        return [
            CarRentalWebOption(
                vendor=row.source_title or row.source_domain,
                price_text=_sniff_sentence(row.raw_markdown_excerpt, ["CAD", "$", "per day"]),
                mileage_policy=_sniff_sentence(
                    row.raw_markdown_excerpt, ["mileage", "kilometer", "km"]
                ),
                insurance_notes=_sniff_sentence(
                    row.raw_markdown_excerpt, ["insurance", "coverage"]
                ),
                deposit_notes=_sniff_sentence(row.raw_markdown_excerpt, ["deposit", "hold"]),
                child_seat_notes=_sniff_sentence(
                    row.raw_markdown_excerpt, ["child seat", "booster"]
                ),
                cancellation_policy=_sniff_sentence(row.raw_markdown_excerpt, ["cancel", "refund"]),
                source_urls=[row.source_url],
                confidence=row.confidence,
                warnings=row.warnings,
            )
            for row in rows
        ]


def _sniff_sentence(text: str, tokens: list[str]) -> str:
    lowered = text.lower()
    for token in tokens:
        index = lowered.find(token.lower())
        if index >= 0:
            start = max(0, index - 40)
            end = min(len(text), index + 140)
            return " ".join(text[start:end].split())
    return ""


def _sniff_list(text: str, tokens: list[str]) -> list[str]:
    lowered = text.lower()
    return [token for token in tokens if token in lowered]
