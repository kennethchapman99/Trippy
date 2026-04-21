"""Country-level priors from historical family ratings and notes."""

from __future__ import annotations

import re
from pathlib import Path

from trippy.models.country_priors import CountryFitSignal, CountryPrior, CountryPriorBand
from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType


class CountryPriorService:
    """Country preference priors used as directional planning intelligence."""

    def __init__(self, priors: list[CountryPrior] | None = None) -> None:
        self._priors = priors or _default_country_priors()

    def list_priors(self) -> list[CountryPrior]:
        return list(self._priors)

    def get(self, country: str) -> CountryPrior | None:
        wanted = _normalize(country)
        for prior in self._priors:
            names = [prior.country, *prior.aliases]
            if any(_normalize(name) == wanted for name in names):
                return prior
        return None

    def fit_for_country(self, country: str) -> CountryFitSignal | None:
        prior = self.get(country)
        return _fit_signal(prior) if prior else None

    def fit_for_text(self, text: str) -> list[CountryFitSignal]:
        normalized_text = f" {_normalize(text)} "
        matches: list[CountryFitSignal] = []
        for prior in self._priors:
            names = [prior.country, *prior.aliases]
            if any(f" {_normalize(name)} " in normalized_text for name in names):
                matches.append(_fit_signal(prior))
        return matches

    def propose_memory_updates(
        self,
        *,
        learning_dir: Path | None = None,
        memory_path: Path | None = None,
        source_workflow_id: str | None = None,
        countries: list[str] | None = None,
    ) -> list[LearningProposal]:
        selected = self._priors
        if countries:
            wanted = {_normalize(country) for country in countries}
            selected = [
                prior
                for prior in selected
                if _normalize(prior.country) in wanted
                or any(_normalize(alias) in wanted for alias in prior.aliases)
            ]
        proposals = [
            LearningProposal(
                proposal_type=ProposalType.MEMORY,
                summary=f"Review country prior for {prior.country}: {prior.band.value}",
                source_workflow_id=source_workflow_id,
                after={
                    "key": f"country_prior:{_slug(prior.country)}",
                    "value": prior.model_dump(mode="json"),
                    "category": "preference",
                    "confidence": prior.confidence,
                    "source": "historical-country-ratings",
                    "notes": "Directional country-level prior. Override with trip-specific goals, season, sub-region, or newer evidence.",
                },
            )
            for prior in selected
        ]
        return LearningEventStore(learning_dir, memory_path=memory_path).add_proposals(proposals)


def _fit_signal(prior: CountryPrior) -> CountryFitSignal:
    return CountryFitSignal(
        country=prior.country,
        rating=prior.rating,
        band=prior.band,
        confidence=prior.confidence,
        score_adjustment=_score_adjustment(prior),
        rationale=_rationale(prior),
        positive_signals=prior.positive_signals,
        caution_signals=prior.caution_signals,
        planning_rules=prior.planning_rules,
    )


def _score_adjustment(prior: CountryPrior) -> int:
    if prior.band == CountryPriorBand.STRONG_POSITIVE:
        return 8 if (prior.rating or 0) >= 9 else 5
    if prior.band == CountryPriorBand.MIXED:
        return 2 if (prior.rating or 0) >= 8 else 0
    if prior.band == CountryPriorBand.CAUTION:
        return -6
    return 0


def _rationale(prior: CountryPrior) -> str:
    rating = f"{prior.rating}/10" if prior.rating is not None else "unrated"
    positives = ", ".join(prior.positive_signals[:3]) or "no strong positive signal"
    cautions = ", ".join(prior.caution_signals[:3])
    suffix = f"; watch {cautions}" if cautions else ""
    return f"Historical country prior for {prior.country}: {rating}, {prior.band.value}; positives: {positives}{suffix}."


def _prior(
    country: str,
    rating: int | None,
    positives: list[str],
    cautions: list[str],
    positive_signals: list[str],
    caution_signals: list[str],
    *,
    aliases: list[str] | None = None,
    rules: list[str] | None = None,
) -> CountryPrior:
    return CountryPrior(
        country=country,
        rating=rating,
        band=_band(rating, caution_signals),
        confidence=0.85 if rating is not None else 0.45,
        positive_notes=positives,
        caution_notes=cautions,
        positive_signals=positive_signals,
        caution_signals=caution_signals,
        aliases=aliases or [],
        planning_rules=[
            "Use this as a directional prior, not a rigid rule.",
            "Check exact sub-region, season, logistics, and trip style before recommending.",
            *(rules or []),
        ],
    )


def _band(rating: int | None, caution_signals: list[str]) -> CountryPriorBand:
    if rating is None:
        return CountryPriorBand.NEUTRAL
    if rating >= 9:
        return CountryPriorBand.STRONG_POSITIVE
    if rating <= 6:
        return CountryPriorBand.CAUTION
    if rating == 7 or len(caution_signals) >= 3:
        return CountryPriorBand.MIXED
    return CountryPriorBand.MIXED


def _default_country_priors() -> list[CountryPrior]:
    return [
        _prior(
            "Canada",
            10,
            [
                "Lots of places",
                "Tofino felt like Canada Hawaii",
                "East Coast and Quebec were favorite trips",
            ],
            ["Taxes", "Huge drives", "Poor rail"],
            ["natural beauty", "multi-location depth", "family familiarity"],
            ["huge drives", "poor rail", "cost/tax drag"],
        ),
        _prior(
            "USA",
            6,
            ["Lots of places", "California coast seems awesome", "Many great spots"],
            ["Fearful", "Awful politically right now"],
            ["destination variety", "California coast potential"],
            ["safety/comfort concern", "political discomfort"],
            aliases=["United States", "United States of America"],
        ),
        _prior(
            "Mexico",
            8,
            ["Food", "Cheap", "Nice people", "Easy weather and beaches"],
            [
                "Not always drivable",
                "Seagrass can hurt waterfront by region",
                "Not always safe feeling",
            ],
            ["food", "value", "easy weather", "beach potential"],
            ["safety varies by region", "driving practicality", "beach-condition risk"],
        ),
        _prior(
            "Costa Rica",
            8,
            ["Wildlife", "Surfing", "Feels safe", "Easy beaches and weather"],
            ["Getting expensive", "Food not amazing"],
            ["wildlife", "surfing", "safety", "easy beaches"],
            ["expense creep", "food disappointment"],
            aliases=["Costca Rica"],
        ),
        _prior(
            "St Lucia",
            7,
            ["Great food", "Fun Airbnb vibe", "Cheaper"],
            ["Hard roads to drive", "Mostly safe feel"],
            ["food", "private rental upside", "value"],
            ["hard driving", "road stress"],
            aliases=["Saint Lucia"],
        ),
        _prior(
            "St Maarten",
            6,
            [],
            ["Stayed during cruise", "Touristy and full"],
            [],
            ["touristy/crowded"],
            aliases=["Sint Maarten", "Saint Martin"],
        ),
        _prior(
            "St Kitts",
            6,
            [],
            ["Stayed during cruise", "Touristy and full"],
            [],
            ["touristy/crowded"],
            aliases=["Saint Kitts"],
        ),
        _prior(
            "St Thomas",
            6,
            [],
            ["Stayed during cruise", "Touristy and full"],
            [],
            ["touristy/crowded"],
            aliases=["Saint Thomas"],
        ),
        _prior(
            "Antigua",
            7,
            ["All inclusive", "Stayed on resort"],
            [],
            ["resort ease", "beach potential"],
            [],
        ),
        _prior(
            "Trinidad and Tobago",
            7,
            ["Loved it", "Amazing and cheap food"],
            ["Not safe"],
            ["food", "value", "unique local experience"],
            ["safety concern"],
            aliases=["Trinadad and Tobago", "Trinidad"],
        ),
        _prior(
            "Curacao",
            8,
            ["Super drivable", "Colorful and fun", "Good beaches"],
            ["Food hit and miss", "Theft", "Car break-in", "Long flight", "Euro was expensive"],
            ["drivable", "colorful atmosphere", "beaches"],
            ["theft/safety", "cost", "flight burden", "food inconsistency"],
            aliases=["Curaçao"],
        ),
        _prior(
            "Peru",
            10,
            ["Amazing experiences", "Safe", "Cheap", "Multiple cool locations"],
            ["Got sick", "Risk of shutdown of services in some places"],
            ["adventure", "value", "multi-location depth", "safety"],
            ["health/sickness", "service disruption risk"],
        ),
        _prior(
            "France",
            9,
            [
                "European feel",
                "Safe",
                "Great food",
                "Family friendly",
                "South of France and Paris are amazing",
            ],
            ["Expensive"],
            ["food", "safety", "family-friendly", "urban plus south-country depth"],
            ["expense"],
        ),
        _prior(
            "Italy",
            7,
            ["History and culture was great"],
            ["Expensive", "Too hot in summer", "Food was just ok", "Rome busy"],
            ["culture/history"],
            ["expense", "summer heat", "food-expectation risk", "crowds"],
        ),
        _prior(
            "Monaco",
            7,
            ["Luxury", "Quick visit"],
            ["Not to stay in"],
            ["luxury novelty"],
            ["not a stay base"],
        ),
        _prior(
            "UK",
            6,
            ["Scotland is interesting", "Nice to have seen"],
            ["Food is gross", "Expensive"],
            ["Scotland interest"],
            ["food disappointment", "expense"],
            aliases=["United Kingdom", "England", "Scotland"],
        ),
        _prior(
            "Finland",
            8,
            [
                "Fresh feeling",
                "Northern Ontario but Europe",
                "Fun tangent to Europe",
                "New foods to try",
            ],
            ["Expensive"],
            ["fresh atmosphere", "new foods", "Europe tangent"],
            ["expense"],
        ),
        _prior(
            "The Netherlands",
            8,
            ["So fun", "Interesting", "Fun people"],
            [],
            ["culture", "fun atmosphere", "people"],
            [],
            aliases=["Netherlands", "Holland"],
        ),
        _prior(
            "Egypt",
            7,
            ["Amazing diving", "Food was incredible", "Adventure upside"],
            ["Pushing for tips", "Crowded", "Bags snatched", "Got sick", "Harassment/disrespect"],
            ["diving", "food", "adventure"],
            ["crowds", "health/sickness", "harassment", "comfort/safety"],
        ),
        _prior(
            "Greece",
            10,
            [
                "Santorini was extremely romantic",
                "Food amazing",
                "Easy and safe drive",
                "Postcard views",
                "Unforgettable",
            ],
            [],
            ["romantic atmosphere", "food", "scenery", "safety", "easy movement"],
            [],
        ),
        _prior(
            "China",
            7,
            ["Loved the food", "Big culture change"],
            ["Dirty sometimes", "Language barrier"],
            ["food", "unique culture"],
            ["cleanliness inconsistency", "language barrier"],
        ),
        _prior(
            "New Zealand",
            10,
            ["Perfect natural environment", "So much to do", "Great people", "Family lives there"],
            ["Far flight", "Food wasn't amazing"],
            ["nature", "activities", "people", "family connection"],
            ["long flight burden", "food disappointment"],
        ),
        _prior(
            "Belize",
            9,
            ["Beach and snorkel feel", "Awesome food", "Biking on the beach", "Great snorkeling"],
            ["Not easy to get to", "Second flight to the atoll"],
            ["beach/water", "snorkeling", "food"],
            ["extra-hop travel burden"],
        ),
        _prior(
            "Morocco",
            8,
            ["Unique and amazing cultural experience", "Fun adventure"],
            ["Didn't love the food"],
            ["unique culture", "adventure"],
            ["food disappointment"],
            aliases=["Morroco"],
        ),
        _prior(
            "Spain",
            8,
            ["Canary Islands and Madrid", "Great food"],
            ["Island was traffic-y"],
            ["food", "city plus island variety"],
            ["traffic"],
        ),
        _prior(
            "Switzerland",
            7,
            ["Mountains", "So much more to see"],
            ["Crazy expensive"],
            ["mountains", "natural beauty"],
            ["extreme expense"],
        ),
        _prior(
            "Cuba",
            6,
            ["Beautiful beaches"],
            ["Terrible food"],
            ["beaches"],
            ["food disappointment"],
        ),
        _prior(
            "The Bahamas",
            7,
            ["Generally ok"],
            [],
            ["beach potential"],
            [],
            aliases=["Bahamas"],
        ),
        _prior(
            "Vatican",
            None,
            ["Small"],
            ["Not meaningful as a country-level trip base"],
            [],
            ["too small as destination base"],
            aliases=["Vatican City"],
        ),
        _prior(
            "Thailand",
            9,
            ["Amazing culture", "Amazing food", "More to see in Chiang Mai/Chiang Rai"],
            ["Koh Samui crowded roads", "Not good for cars", "Bad snorkeling", "Busy beaches"],
            ["food", "culture", "north Thailand upside"],
            ["crowded beach zones", "hard driving", "snorkeling disappointment"],
        ),
        _prior(
            "Japan",
            9,
            ["So clean", "Great culture", "Want to see more"],
            ["Kinda expensive"],
            ["cleanliness", "culture", "repeat interest"],
            ["expense"],
        ),
    ]


def _normalize(value: str) -> str:
    text = value.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
