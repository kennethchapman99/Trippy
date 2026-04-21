"""Deterministic travel source registry and routing rules."""

from __future__ import annotations

from trippy.models.sources import (
    SourceAccessMode,
    SourceConfidence,
    SourcePlan,
    TravelSource,
    TravelSourceCategory,
)


class TravelSourceRegistry:
    """Registry for choosing travel sources without ad hoc browsing."""

    def __init__(self, sources: list[TravelSource] | None = None) -> None:
        self._sources = sources or _default_sources()

    def list_sources(
        self,
        category: TravelSourceCategory | None = None,
    ) -> list[TravelSource]:
        if category is None:
            return list(self._sources)
        return [source for source in self._sources if category in source.categories]

    def get(self, platform_name: str) -> TravelSource | None:
        normalized = platform_name.casefold()
        for source in self._sources:
            if source.platform_name.casefold() == normalized:
                return source
        return None

    def plan_for(self, category: TravelSourceCategory) -> SourcePlan:
        routing = _ROUTING[category]
        return SourcePlan(
            category=category,
            primary=self._sources_by_name(routing["primary"], category=category),
            secondary=self._sources_by_name(routing["secondary"], category=category),
            validation=self._sources_by_name(routing["validation"], category=category),
            notes=_ROUTING_NOTES[category],
        )

    def _sources_by_name(
        self,
        names: list[str],
        *,
        category: TravelSourceCategory,
    ) -> list[TravelSource]:
        sources = []
        for name in names:
            source = self.get(name)
            if source is not None and category in source.categories:
                sources.append(source)
        return sources


_ROUTING: dict[TravelSourceCategory, dict[str, list[str]]] = {
    TravelSourceCategory.FLIGHTS: {
        "primary": ["Google Flights"],
        "secondary": ["Kayak.ca", "Expedia", "Flighthub"],
        "validation": ["Kayak.ca", "Expedia"],
    },
    TravelSourceCategory.CITY_LODGING: {
        "primary": ["Booking.com"],
        "secondary": ["Expedia"],
        "validation": ["Tripadvisor", "Trivago", "Expedia"],
    },
    TravelSourceCategory.PRIVATE_LODGING: {
        "primary": ["Airbnb", "VRBO"],
        "secondary": ["Booking.com"],
        "validation": ["Tripadvisor", "Booking.com"],
    },
    TravelSourceCategory.TOURS: {
        "primary": ["GetYourGuide"],
        "secondary": ["Airbnb Experiences"],
        "validation": ["Tripadvisor"],
    },
    TravelSourceCategory.CAR_RENTALS: {
        "primary": ["Booking.com"],
        "secondary": ["Expedia", "Kayak.ca"],
        "validation": ["Tripadvisor"],
    },
    TravelSourceCategory.DEALS: {
        "primary": ["Travelzoo"],
        "secondary": ["Expedia"],
        "validation": ["Tripadvisor"],
    },
    TravelSourceCategory.VALIDATION: {
        "primary": ["Tripadvisor"],
        "secondary": ["Trivago", "Expedia"],
        "validation": [],
    },
}


_ROUTING_NOTES: dict[TravelSourceCategory, list[str]] = {
    TravelSourceCategory.FLIGHTS: [
        "Use Google Flights first for schedule shape, directness, and total travel time.",
        "Cross-check price and routing with Kayak.ca, Expedia, and Flighthub before recommending.",
        "Do not treat an OTA fare as final until baggage, seats, cancellation, and airline booking path are clear.",
    ],
    TravelSourceCategory.CITY_LODGING: [
        "Prioritize central, walkable boutique hotels with explicit family bed fit.",
        "Validate neighborhood, reviews, and location tradeoffs before recommending.",
    ],
    TravelSourceCategory.PRIVATE_LODGING: [
        "Use private rentals mainly outside dense city cores or when space/privacy clearly beats hotel convenience.",
        "Validate access, parking, safety, reviews, cancellation, and bed layout hard.",
    ],
    TravelSourceCategory.TOURS: [
        "Prefer small, safe, well-reviewed operators over mass-market large-group experiences.",
        "Cross-check operator quality and crowd signals before recommending.",
    ],
    TravelSourceCategory.CAR_RENTALS: [
        "Prefer Booking.com first, with Expedia and Kayak.ca as comparison layers.",
        "Penalize weak pickup/dropoff clarity, hidden fees, poor cancellation terms, weak vehicle fit, and destination parking pain.",
    ],
    TravelSourceCategory.DEALS: [
        "Use Travelzoo for inspiration and deal awareness, not as the sole source of final booking confidence.",
    ],
    TravelSourceCategory.VALIDATION: [
        "Use validation sources to catch review, location, crowd, and quality issues before ready-to-click handoff.",
    ],
}


def _default_sources() -> list[TravelSource]:
    return [
        TravelSource(
            platform_name="Google Flights",
            categories=[TravelSourceCategory.FLIGHTS],
            strengths=[
                "Fast flight schedule discovery",
                "Good directness and total-duration comparison",
                "Good calendar and fare-shape exploration",
            ],
            weaknesses=[
                "Not a booking system",
                "Does not fully resolve baggage, seat, loyalty, or OTA terms",
            ],
            confidence_level=SourceConfidence.HIGH,
            access_modes=[
                SourceAccessMode.BROWSER_AUTOMATION,
                SourceAccessMode.MANUAL_HANDOFF,
            ],
            prefer_when=["discovering flight shape", "comparing direct vs connection tradeoffs"],
            avoid_when=["final payment handoff without airline/OTA validation"],
        ),
        TravelSource(
            platform_name="Kayak.ca",
            categories=[TravelSourceCategory.FLIGHTS, TravelSourceCategory.CAR_RENTALS],
            strengths=["Broad comparison surface", "Useful fare and rental cross-checking"],
            weaknesses=["Can route to lower-trust booking paths", "Terms can vary by provider"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["secondary flight comparison", "car rental price validation"],
            avoid_when=["provider terms are unclear", "hidden-fee risk is high"],
        ),
        TravelSource(
            platform_name="Expedia",
            categories=[
                TravelSourceCategory.FLIGHTS,
                TravelSourceCategory.CITY_LODGING,
                TravelSourceCategory.CAR_RENTALS,
                TravelSourceCategory.DEALS,
                TravelSourceCategory.VALIDATION,
            ],
            strengths=["Broad inventory", "Useful package, lodging, and car comparison"],
            weaknesses=["OTA terms and cancellation rules need careful review"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["cross-checking price and availability", "bundled comparison"],
            avoid_when=["terms are worse than booking direct", "support chain is unclear"],
        ),
        TravelSource(
            platform_name="Flighthub",
            categories=[TravelSourceCategory.FLIGHTS],
            strengths=["Additional Canadian-market flight fare comparison"],
            weaknesses=["Lower trust for final handoff unless terms are very clear"],
            confidence_level=SourceConfidence.LOW,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["spot-checking fare competitiveness"],
            avoid_when=["family comfort, flexibility, or support quality matters more than fare"],
        ),
        TravelSource(
            platform_name="Booking.com",
            categories=[
                TravelSourceCategory.CITY_LODGING,
                TravelSourceCategory.PRIVATE_LODGING,
                TravelSourceCategory.CAR_RENTALS,
            ],
            strengths=[
                "Strong lodging inventory",
                "Good city hotel discovery",
                "Useful car-rental comparison surface",
            ],
            weaknesses=[
                "Room/bed layouts still need explicit validation",
                "Map areas can be too broad",
            ],
            confidence_level=SourceConfidence.HIGH,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["central city hotels", "car rental first-pass discovery"],
            avoid_when=["bed setup is ambiguous", "location creates unnecessary transit burden"],
        ),
        TravelSource(
            platform_name="Tripadvisor",
            categories=[
                TravelSourceCategory.CITY_LODGING,
                TravelSourceCategory.PRIVATE_LODGING,
                TravelSourceCategory.TOURS,
                TravelSourceCategory.CAR_RENTALS,
                TravelSourceCategory.DEALS,
                TravelSourceCategory.VALIDATION,
            ],
            strengths=[
                "Review validation",
                "Neighborhood, attraction, and operator quality signals",
            ],
            weaknesses=["Ranking can be noisy", "Availability and final pricing are not enough"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["validating reviews, safety, crowds, and location quality"],
            avoid_when=["using it as the only booking source"],
        ),
        TravelSource(
            platform_name="Trivago",
            categories=[TravelSourceCategory.CITY_LODGING, TravelSourceCategory.VALIDATION],
            strengths=["Hotel price and distribution cross-checking"],
            weaknesses=["Thin on family-specific fit and bed detail"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["hotel price validation"],
            avoid_when=["deciding family fit without primary lodging detail"],
        ),
        TravelSource(
            platform_name="Airbnb",
            categories=[TravelSourceCategory.PRIVATE_LODGING],
            strengths=["Private family space", "Kitchen/laundry/privacy options"],
            weaknesses=["Access, safety, cancellation, exact location, and bed setup vary widely"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["non-city private stays", "space and privacy materially improve comfort"],
            avoid_when=["dense city core where boutique hotel convenience is better"],
        ),
        TravelSource(
            platform_name="VRBO",
            categories=[TravelSourceCategory.PRIVATE_LODGING],
            strengths=["Family-sized vacation rentals", "Good for non-city private stays"],
            weaknesses=["Inventory quality and location practicality require careful validation"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["family-sized private stays outside major city cores"],
            avoid_when=["parking, road access, or safety details are weak"],
        ),
        TravelSource(
            platform_name="GetYourGuide",
            categories=[TravelSourceCategory.TOURS],
            strengths=[
                "Structured tour discovery",
                "Clear cancellation and operator info in many cases",
            ],
            weaknesses=["Can skew mass-market; group size and crowd exposure need review"],
            confidence_level=SourceConfidence.HIGH,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["small-group tours and activities with review/safety signals"],
            avoid_when=["large-group or low-specificity operator listings"],
        ),
        TravelSource(
            platform_name="Airbnb Experiences",
            categories=[TravelSourceCategory.TOURS],
            strengths=["Smaller, local-feeling activities when available"],
            weaknesses=["Inventory coverage is inconsistent by destination"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["small intimate food or neighborhood experiences"],
            avoid_when=["safety/review depth is weak"],
        ),
        TravelSource(
            platform_name="Hertz",
            categories=[TravelSourceCategory.CAR_RENTALS],
            strengths=["Direct rental provider", "Useful for direct terms and loyalty checks"],
            weaknesses=["Not the default first discovery surface for Trippy"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["validating direct rental terms after aggregator discovery"],
            avoid_when=["aggregator has clearer family-fit comparison"],
        ),
        TravelSource(
            platform_name="Travelzoo",
            categories=[TravelSourceCategory.DEALS],
            strengths=["Inspiration and deal discovery"],
            weaknesses=["Deal fit can be generic and restrictive"],
            confidence_level=SourceConfidence.MEDIUM,
            access_modes=[SourceAccessMode.BROWSER_AUTOMATION, SourceAccessMode.MANUAL_HANDOFF],
            prefer_when=["inspiration and opportunistic deal scanning"],
            avoid_when=["deal constraints undermine comfort or family fit"],
        ),
    ]
