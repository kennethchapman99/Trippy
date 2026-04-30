"""Deterministic first-pass trip concept generation and comparison."""

from __future__ import annotations

from dataclasses import dataclass

from trippy.memory.store import MemoryStore
from trippy.models.ideas import TripComparison, TripConcept, TripIdeaRequest
from trippy.models.preferences import FamilyTravelPreferences
from trippy.services.country_priors import CountryPriorService
from trippy.services.planning_advisor import PlanningAdvisorService


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
        concept_id="island-nature-short-comfort",
        title="Island Nature Easy Week",
        countries=[],
        destinations=["Primary island base", "Thermal or nature area", "Scenic viewpoint area"],
        recommended_duration_days=6,
        best_season="late summer or early fall",
        estimated_cost_band_cad="CAD 12k-20k for a couple before final flights and lodging",
        estimated_flight_hours=5.8,
        direct_flight_friendliness=7,
        base_family_fit=86,
        base_comfort=84,
        food_score=78,
        crowd_risk=36,
        tags={
            "nature",
            "food",
            "island",
            "short-flight",
            "low-crowd",
            "chill",
        },
        risks=[
            "Weather can disrupt outdoor plans; keep flexible hot springs, food, and scenic backup days."
        ],
    ),
    _ConceptTemplate(
        concept_id="quebec-city-montreal-food-short",
        title="Quebec City + Montreal Food Long Weekend",
        countries=["Canada"],
        destinations=["Montreal", "Quebec City"],
        recommended_duration_days=5,
        best_season="summer or fall",
        estimated_cost_band_cad="CAD 5k-10k for a couple depending on hotels and dining",
        estimated_flight_hours=1.5,
        direct_flight_friendliness=10,
        base_family_fit=84,
        base_comfort=88,
        food_score=90,
        crowd_risk=45,
        tags={"food", "culture", "city", "walkable", "short-flight", "low-friction"},
        risks=[
            "Old Quebec can feel crowded in peak windows; pick shoulder dates and central lodging."
        ],
    ),
    _ConceptTemplate(
        concept_id="mexico-city-food-short",
        title="Mexico City Food + Neighborhoods",
        countries=["Mexico"],
        destinations=["Roma Norte", "Condesa", "Centro or Polanco"],
        recommended_duration_days=6,
        best_season="winter or early spring",
        estimated_cost_band_cad="CAD 8k-15k for a couple depending on dining and hotel level",
        estimated_flight_hours=5.0,
        direct_flight_friendliness=8,
        base_family_fit=80,
        base_comfort=82,
        food_score=97,
        crowd_risk=55,
        tags={"food", "culture", "city", "walkable", "short-flight"},
        risks=[
            "Neighborhood choice and private transfers matter; avoid turning this into a stressful driving trip."
        ],
    ),
    _ConceptTemplate(
        concept_id="belize-reef-jungle-short",
        title="Belize Reef + Easy Adventure",
        countries=["Belize"],
        destinations=["Ambergris Caye or Caye Caulker", "San Ignacio optional"],
        recommended_duration_days=6,
        best_season="winter or spring dry season",
        estimated_cost_band_cad="CAD 9k-18k for a couple before final tours and lodging",
        estimated_flight_hours=4.8,
        direct_flight_friendliness=6,
        base_family_fit=82,
        base_comfort=78,
        food_score=76,
        crowd_risk=42,
        tags={
            "belize",
            "caribbean",
            "beach",
            "nature",
            "adventure",
            "short-flight",
            "water",
            "reef",
            "snorkel",
            "snorkeling",
            "chill",
        },
        risks=["Extra hops to islands can eat time; keep the route simple for only six days."],
    ),
    _ConceptTemplate(
        concept_id="cayman-reef-food-easy-week",
        title="Cayman Reef + Food Easy Week",
        countries=["Cayman Islands"],
        destinations=["Seven Mile Beach", "West Bay", "Stingray City or Rum Point"],
        recommended_duration_days=7,
        best_season="winter or spring, including March break if prices are acceptable",
        estimated_cost_band_cad="CAD 18k-32k for family of 5 before exact flights, lodging, and activities",
        estimated_flight_hours=4.2,
        direct_flight_friendliness=8,
        base_family_fit=84,
        base_comfort=86,
        food_score=82,
        crowd_risk=50,
        tags={
            "cayman",
            "cayman islands",
            "caribbean",
            "beach",
            "water",
            "reef",
            "snorkel",
            "snorkeling",
            "food",
            "family",
            "low-friction",
            "short-flight",
            "chill",
        },
        risks=[
            "March break pricing can be high; value needs live validation.",
            "Use smaller operators and beach timing to avoid crowded excursion windows.",
        ],
    ),
    _ConceptTemplate(
        concept_id="curacao-color-beach-drivable-short",
        title="Curacao Color + Beach Base",
        countries=["Curacao"],
        destinations=["Willemstad", "Westpunt beaches", "Klein Curacao optional"],
        recommended_duration_days=6,
        best_season="winter, spring, or early fall outside peak holiday pricing",
        estimated_cost_band_cad="CAD 9k-17k for a couple before final flights, lodging, and car",
        estimated_flight_hours=5.8,
        direct_flight_friendliness=7,
        base_family_fit=78,
        base_comfort=78,
        food_score=76,
        crowd_risk=40,
        tags={
            "curacao",
            "curaçao",
            "caribbean",
            "beach",
            "island",
            "water",
            "reef",
            "snorkel",
            "snorkeling",
            "drivable",
            "colorful",
            "chill",
            "rental",
        },
        risks=[
            "Historical notes are mixed: colorful and drivable, but theft/safety, cost, and food consistency need careful validation.",
            "Do not leave valuables in a car at beaches; lodging location and parking security matter.",
        ],
    ),
    _ConceptTemplate(
        concept_id="st-lucia-private-rental-food-short",
        title="St Lucia Private Rental + Food Week",
        countries=["St Lucia"],
        destinations=["Soufriere", "Rodney Bay optional", "Marigot Bay optional"],
        recommended_duration_days=6,
        best_season="winter or spring shoulder windows",
        estimated_cost_band_cad="CAD 10k-18k for a couple before exact villa/hotel and car choices",
        estimated_flight_hours=5.4,
        direct_flight_friendliness=6,
        base_family_fit=76,
        base_comfort=74,
        food_score=84,
        crowd_risk=42,
        tags={
            "st lucia",
            "saint lucia",
            "caribbean",
            "beach",
            "island",
            "food",
            "rental",
            "scenery",
            "chill",
        },
        risks=[
            "Historical prior likes food and Airbnb/private-stay upside, but hard roads are a major caution.",
            "This only works if transfers or driving routes avoid road-stress and night-driving friction.",
        ],
    ),
    _ConceptTemplate(
        concept_id="mexico-caribbean-food-beach-short",
        title="Mexico Caribbean Food + Beach Base",
        countries=["Mexico"],
        destinations=["Isla Mujeres or Puerto Morelos", "Valladolid optional"],
        recommended_duration_days=6,
        best_season="winter or early spring before heavy heat and seaweed risk",
        estimated_cost_band_cad="CAD 8k-16k for a couple depending on beach lodging and dining",
        estimated_flight_hours=4.2,
        direct_flight_friendliness=9,
        base_family_fit=78,
        base_comfort=76,
        food_score=88,
        crowd_risk=60,
        tags={
            "mexico",
            "caribbean",
            "beach",
            "food",
            "short-flight",
            "water",
            "reef",
            "snorkel",
            "snorkeling",
            "chill",
            "value",
        },
        risks=[
            "Mexico is historically strong for food, value, and weather, but safety, crowding, and beach/seaweed conditions vary sharply by area.",
            "Avoid overbuilt resort zones unless convenience clearly beats the crowd exposure.",
        ],
    ),
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
        region_intents = _explicit_region_intents(request)
        experience_intents = _required_experience_intents(request)
        templates = _region_filtered_templates(_TEMPLATES, region_intents)
        templates = _experience_filtered_templates(templates, experience_intents)
        concepts = [self._score_template(template, request) for template in templates]
        filtered = _duration_filtered_concepts(concepts, request, limit)
        if filtered:
            concepts = filtered
        ranked = sorted(concepts, key=lambda concept: concept.total_score, reverse=True)[:limit]
        recommendation = ranked[0].concept_id if ranked else None
        scoring_notes = [
            "Scores are deterministic first-pass estimates, not live prices or availability.",
            "Visa, entry, vaccination, exact fare, and listing availability require live research before booking.",
            "Family smoothness, central lodging, food access, bed fit, and crowd/transport friction are weighted above raw price.",
        ]
        if request.duration_days:
            scoring_notes.insert(
                0,
                f"Requested duration is {request.duration_days} day(s); suggestions are duration-fit first, not generic best trips.",
            )
        if region_intents:
            scoring_notes.insert(
                0,
                f"Explicit destination intent detected: {', '.join(sorted(region_intents))}. Off-region concepts are excluded before scoring.",
            )
        if experience_intents:
            scoring_notes.insert(
                0,
                f"Required experience detected: {', '.join(sorted(experience_intents))}. Concepts without that experience are excluded before scoring.",
            )
        comparison = TripComparison(
            request=request,
            concepts=ranked,
            recommended_concept_id=recommendation,
            scoring_notes=scoring_notes,
        )
        comparison.advisor = (
            PlanningAdvisorService(
                preferences=self._prefs,
                memory=self._memory,
                enabled=False,
            )
            .advise_trip_ideas(request, comparison)
            .model_dump(mode="json")
        )
        return comparison

    def _score_template(self, template: _ConceptTemplate, request: TripIdeaRequest) -> TripConcept:
        score = template.base_family_fit + template.base_comfort + template.food_score
        party_label = "family" if request.travelers >= 3 else "couple"
        rationale = [
            f"Fits comfort-first {party_label} travel better than lowest-price optimization.",
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
        experience_intents = _required_experience_intents(request)
        matched_experiences = {
            intent
            for intent in experience_intents
            if _template_matches_experience(template, intent)
        }
        if matched_experiences:
            score += len(matched_experiences) * 18
            rationale.append(
                f"Matches required experience: {', '.join(sorted(matched_experiences))}."
            )

        if request.duration_days:
            diff = abs(request.duration_days - template.recommended_duration_days)
            if diff == 0:
                score += 18
                rationale.append("Duration matches the requested trip length.")
            elif diff <= 1:
                score += 10
                rationale.append("Duration is close to the requested trip length.")
            elif diff <= 2:
                score += 4
                rationale.append("Duration is workable but needs pacing discipline.")
            elif request.duration_days < template.recommended_duration_days:
                score -= 20 + (template.recommended_duration_days - request.duration_days) * 8
                why_not.append(
                    f"Ideal version is {template.recommended_duration_days} days, which does not respect the requested {request.duration_days}-day constraint without cutting scope."
                )
            else:
                score -= diff * 2

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


def _explicit_region_intents(request: TripIdeaRequest) -> set[str]:
    text = _request_text(request)
    intents: set[str] = set()
    if any(
        term in text
        for term in (
            "caribbean",
            "carribean",
            "carribbean",
            "west indies",
            "antilles",
        )
    ):
        intents.add("caribbean")
    if "azores" in text:
        intents.add("azores")
    if "portugal" in text:
        intents.add("portugal")
    return intents


def _region_filtered_templates(
    templates: list[_ConceptTemplate],
    region_intents: set[str],
) -> list[_ConceptTemplate]:
    if not region_intents:
        return templates
    matched = [
        template
        for template in templates
        if all(_template_matches_region(template, intent) for intent in region_intents)
    ]
    return matched or templates


def _template_matches_region(template: _ConceptTemplate, intent: str) -> bool:
    haystack = _template_text(template)
    if intent == "caribbean":
        return "caribbean" in template.tags or any(
            term in haystack
            for term in (
                "belize",
                "curacao",
                "curaçao",
                "st lucia",
                "saint lucia",
                "st maarten",
                "saint martin",
                "st kitts",
                "st thomas",
                "cuba",
                "dominican",
                "barbados",
                "jamaica",
                "aruba",
                "bonaire",
                "puerto rico",
                "isla mujeres",
                "cancun",
                "riviera maya",
            )
        )
    return intent in template.tags or intent in haystack


def _required_experience_intents(request: TripIdeaRequest) -> set[str]:
    text = _request_text(request)
    intents: set[str] = set()
    if any(term in text for term in ("snorkel", "snorkeling", "snorkelling", "snorkling", "reef")):
        intents.add("snorkeling")
    if any(term in text for term in ("beach", "water", "swim", "ocean")):
        intents.add("beach_water")
    return intents


def _experience_filtered_templates(
    templates: list[_ConceptTemplate],
    experience_intents: set[str],
) -> list[_ConceptTemplate]:
    if not experience_intents:
        return templates
    matched = [
        template
        for template in templates
        if all(_template_matches_experience(template, intent) for intent in experience_intents)
    ]
    return matched or templates


def _template_matches_experience(template: _ConceptTemplate, intent: str) -> bool:
    if intent == "snorkeling":
        return bool(template.tags & {"snorkel", "snorkeling", "reef"})
    if intent == "beach_water":
        return bool(template.tags & {"beach", "water", "reef", "snorkel", "snorkeling"})
    return intent in template.tags


def _request_text(request: TripIdeaRequest) -> str:
    parts = [
        request.time_of_year or "",
        request.desired_vibe or "",
        request.activity_level or "",
        request.party_type or "",
        *request.goals,
        *request.avoid,
    ]
    return " ".join(parts).lower()


def _template_text(template: _ConceptTemplate) -> str:
    return " ".join(
        [
            template.title,
            *template.countries,
            *template.destinations,
            *template.tags,
        ]
    ).lower()


def _duration_filtered_concepts(
    concepts: list[TripConcept],
    request: TripIdeaRequest,
    limit: int,
) -> list[TripConcept]:
    """Prefer concepts that fit the requested trip length before generic ranking.

    If the user asks for six days, a nine- or ten-day concept should not show up
    just because it scores well on food or country priors. Longer concepts are
    only allowed back in when there are not enough duration-fit ideas.
    """
    if not request.duration_days:
        return []
    tolerance = 0 if request.duration_days <= 6 else 1 if request.duration_days <= 8 else 2
    max_days = request.duration_days + tolerance
    duration_fit = [
        concept for concept in concepts if concept.recommended_duration_days <= max_days
    ]
    return duration_fit if len(duration_fit) >= limit else []
