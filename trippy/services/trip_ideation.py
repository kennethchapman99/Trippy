"""Deterministic first-pass trip concept generation and comparison."""

from __future__ import annotations

from dataclasses import dataclass

from trippy.memory.store import MemoryStore
from trippy.models.ideas import TripComparison, TripConcept, TripIdeaRequest
from trippy.models.preferences import FamilyTravelPreferences
from trippy.services.country_priors import CountryPriorService


@dataclass(frozen=True)
class _ConceptTemplate:
    concept_id: str
    title: str
    countries: list[str]
    destinations: list[str]
    recommended_duration_days: int
    best_season: str
    estimated_cost_band_cad: str
    estimated_flight_hours: float
    direct_flight_friendliness: int
    base_family_fit: int
    base_comfort: int
    food_score: int
    crowd_risk: int
    tags: set[str]
    risks: list[str]


_TEMPLATES = [
    _ConceptTemplate(
        concept_id="portugal-food-cities-coast",
        title="Portugal Food Cities + Coast",
        countries=["Portugal"],
        destinations=["Lisbon", "Porto", "Douro Valley or Cascais"],
        recommended_duration_days=10,
        best_season="spring or fall",
        estimated_cost_band_cad="CAD 18k-28k for family of 5 before splurge meals",
        estimated_flight_hours=7.0,
        direct_flight_friendliness=7,
        base_family_fit=86,
        base_comfort=84,
        food_score=88,
        crowd_risk=45,
        tags={"food", "culture", "city", "coast", "walkable", "low-crowd"},
        risks=["Lisbon hills and parking can be annoying; avoid rental car while in-city."],
    ),
    _ConceptTemplate(
        concept_id="japan-food-rail-cities",
        title="Japan Food + Rail Cities",
        countries=["Japan"],
        destinations=["Tokyo", "Kyoto", "Osaka or Hiroshima"],
        recommended_duration_days=14,
        best_season="late fall or shoulder-season spring",
        estimated_cost_band_cad="CAD 28k-45k for family of 5 depending on flights and room setup",
        estimated_flight_hours=13.0,
        direct_flight_friendliness=8,
        base_family_fit=84,
        base_comfort=78,
        food_score=97,
        crowd_risk=75,
        tags={"food", "culture", "city", "transit", "adventure", "rail"},
        risks=["Crowds are real; lodging must validate 3+ beds and central transit access."],
    ),
    _ConceptTemplate(
        concept_id="mexico-city-oaxaca-food",
        title="Mexico City + Oaxaca Food Trip",
        countries=["Mexico"],
        destinations=["Mexico City", "Oaxaca"],
        recommended_duration_days=9,
        best_season="winter or early spring",
        estimated_cost_band_cad="CAD 16k-26k for family of 5",
        estimated_flight_hours=5.5,
        direct_flight_friendliness=8,
        base_family_fit=80,
        base_comfort=78,
        food_score=96,
        crowd_risk=55,
        tags={"food", "culture", "city", "walkable", "short-flight"},
        risks=["Choose neighborhoods carefully; private transfers may beat rental car stress."],
    ),
    _ConceptTemplate(
        concept_id="costa-rica-private-rental-adventure",
        title="Costa Rica Private Rental + Adventure",
        countries=["Costa Rica"],
        destinations=["Arenal", "Manuel Antonio or Guanacaste"],
        recommended_duration_days=10,
        best_season="winter dry season",
        estimated_cost_band_cad="CAD 20k-34k for family of 5",
        estimated_flight_hours=5.5,
        direct_flight_friendliness=6,
        base_family_fit=86,
        base_comfort=76,
        food_score=72,
        crowd_risk=50,
        tags={"adventure", "nature", "beach", "rental", "chill"},
        risks=[
            "Driving and parking are practical in some areas, stressful in others; vet roads hard."
        ],
    ),
    _ConceptTemplate(
        concept_id="italy-food-culture-rail",
        title="Italy Food + Culture By Rail",
        countries=["Italy"],
        destinations=["Rome", "Florence", "Bologna or Venice"],
        recommended_duration_days=12,
        best_season="spring or fall",
        estimated_cost_band_cad="CAD 24k-38k for family of 5",
        estimated_flight_hours=8.5,
        direct_flight_friendliness=7,
        base_family_fit=82,
        base_comfort=80,
        food_score=94,
        crowd_risk=80,
        tags={"food", "culture", "city", "rail", "walkable"},
        risks=["Peak crowds can crush comfort; use shoulder season and central boutique hotels."],
    ),
]


class TripIdeationService:
    """Generate ranked family-fit trip concepts from loose constraints."""

    def __init__(
        self,
        preferences: FamilyTravelPreferences | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        self._prefs = preferences or FamilyTravelPreferences()
        self._memory = memory
        self._country_priors = CountryPriorService()

    def compare(self, request: TripIdeaRequest, *, limit: int = 5) -> TripComparison:
        concepts = [self._score_template(template, request) for template in _TEMPLATES]
        ranked = sorted(concepts, key=lambda concept: concept.total_score, reverse=True)[:limit]
        recommendation = ranked[0].concept_id if ranked else None
        return TripComparison(
            request=request,
            concepts=ranked,
            recommended_concept_id=recommendation,
            scoring_notes=[
                "Scores are deterministic first-pass estimates, not live prices or availability.",
                "Visa, entry, vaccination, exact fare, and listing availability require live research before booking.",
                "Family smoothness, central lodging, food access, bed fit, and crowd/transport friction are weighted above raw price.",
            ],
        )

    def _score_template(self, template: _ConceptTemplate, request: TripIdeaRequest) -> TripConcept:
        score = template.base_family_fit + template.base_comfort + template.food_score
        rationale = [
            "Fits comfort-first family travel better than lowest-price optimization.",
            "Food access is scored as a major trip objective.",
        ]
        why_not = list(template.risks)
        country_fits = [
            fit
            for country in template.countries
            if (fit := self._country_priors.fit_for_country(country))
        ]
        for fit in country_fits:
            score += fit.score_adjustment
            rationale.append(f"Fit based on past country-level history: {fit.rationale}")
            if fit.caution_signals:
                why_not.append(
                    f"{fit.country} country prior has caution signals: {', '.join(fit.caution_signals[:4])}."
                )

        goals = {goal.lower() for goal in request.goals}
        avoid = {item.lower() for item in request.avoid}
        matched_goals = goals & template.tags
        score += len(matched_goals) * 8
        if matched_goals:
            rationale.append(f"Matches requested goals: {', '.join(sorted(matched_goals))}.")

        if request.duration_days:
            diff = abs(request.duration_days - template.recommended_duration_days)
            if diff <= 2:
                score += 12
                rationale.append("Duration is close to the recommended pacing.")
            elif request.duration_days < template.recommended_duration_days:
                score -= 14
                why_not.append("Requested duration may compress the itinerary too much.")

        if request.max_flight_hours and template.estimated_flight_hours > request.max_flight_hours:
            penalty = int((template.estimated_flight_hours - request.max_flight_hours) * 4)
            score -= penalty
            why_not.append(
                f"Estimated flight time around {template.estimated_flight_hours:.1f}h exceeds requested max."
            )

        if request.direct_flight_preferred or self._prefs.flight.prefer_direct:
            score += template.direct_flight_friendliness
            if template.direct_flight_friendliness < 7:
                why_not.append("Direct-flight friendliness is only moderate; verify exact routing.")

        if "crowds" in avoid or self._prefs.crowd.avoid_huge_crowds_when_possible:
            crowd_penalty = max(0, template.crowd_risk - 55)
            score -= crowd_penalty
            if crowd_penalty:
                why_not.append("Crowd exposure needs careful season and activity selection.")

        if "food" in template.tags and self._prefs.food.food_is_major_objective:
            score += 10

        if "city" in template.tags and self._prefs.lodging_context.city_prefer_urban_core:
            rationale.append("Requires central, walkable lodging to preserve comfort and time.")

        if "rental" in template.tags and self._prefs.lodging_context.non_city_prefer_private_rental:
            rationale.append(
                "Private rental can work well outside major city cores if location and access are vetted."
            )

        required_research = [
            "Live flight options, total travel time, layovers, baggage, seats, and loyalty application.",
            "Exact lodging short list with bed layout, king-bed availability, location, safety, parking/access, and cancellation terms.",
            "Visa/entry requirements, passport validity rules, vaccination or health precautions, and local cash guidance.",
            "Small-group tour/activity operators with strong review and safety signals.",
            "Validate country prior against exact sub-region, season, logistics, and trip style.",
        ]

        return TripConcept(
            concept_id=template.concept_id,
            title=template.title,
            destinations=template.destinations,
            recommended_duration_days=template.recommended_duration_days,
            best_season=template.best_season,
            estimated_cost_band_cad=template.estimated_cost_band_cad,
            estimated_travel_burden=_travel_burden(template.estimated_flight_hours),
            estimated_flight_hours=template.estimated_flight_hours,
            direct_flight_friendliness=template.direct_flight_friendliness,
            family_fit_score=template.base_family_fit,
            comfort_convenience_score=template.base_comfort,
            food_score=template.food_score,
            crowd_risk=template.crowd_risk,
            total_score=max(0, min(100, score // 3)),
            country_prior_signals=[fit.rationale for fit in country_fits],
            rationale=rationale,
            why_it_may_not_fit=why_not,
            major_risks=template.risks,
            required_research=required_research,
        )


def _travel_burden(flight_hours: float) -> str:
    if flight_hours <= 6:
        return "moderate"
    if flight_hours <= 9:
        return "meaningful"
    return "high"
