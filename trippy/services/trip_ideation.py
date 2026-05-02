"""Destination-agnostic trip concept generation.

Idea-stage output is intentionally a set of scanner briefs, not named destination
recommendations. Trippy should not smuggle a hardcoded catalog of places into the
planning flow before resolver/provider evidence has populated trip JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from trippy import config
from trippy.memory.store import MemoryStore
from trippy.models.ideas import TripComparison, TripConcept, TripIdeaRequest
from trippy.models.preferences import FamilyTravelPreferences
from trippy.services.llm_client import TrippyLLMClient

_PROMPT_VERSION = "trip-ideation-v2"

@dataclass(frozen=True)
class _ConceptArchetype:
    concept_id: str
    title: str
    destination_slots: list[str]
    recommended_duration_days: int
    travel_burden_hours: float
    direct_flight_friendliness: int
    family_fit: int
    comfort: int
    food: int
    crowd_risk: int
    tags: set[str]
    rationale_seed: list[str]
    risks: list[str]


_ARCHETYPES = [
    _ConceptArchetype(
        concept_id="json-first-low-friction-single-base",
        title="Unpack Once, Easy Pace",
        destination_slots=[
            "Best stay area from your trip details",
            "Nearby food, beach, or activity cluster",
        ],
        recommended_duration_days=6,
        travel_burden_hours=5.0,
        direct_flight_friendliness=9,
        family_fit=88,
        comfort=90,
        food=78,
        crowd_risk=34,
        tags={
            "low-friction",
            "single-base",
            "comfort",
            "food",
            "short-flight",
            "family",
            "beach",
            "water",
            "snorkeling",
            "reef",
        },
        rationale_seed=[
            "Keeps lodging, baggage, meals, and daily pacing simple while resolver evidence is still incomplete.",
            "Best first pass when the family wants comfort and low transition cost.",
        ],
        risks=[
            "May underuse a broad destination if scanner evidence later proves the best activities are far apart.",
        ],
    ),
    _ConceptArchetype(
        concept_id="json-first-food-culture-base",
        title="Walkable Food + Culture Base",
        destination_slots=[
            "Walkable food and culture base",
            "Nearby market, old-town, or neighborhood area",
        ],
        recommended_duration_days=6,
        travel_burden_hours=6.0,
        direct_flight_friendliness=8,
        family_fit=82,
        comfort=84,
        food=94,
        crowd_risk=55,
        tags={"food", "culture", "walkable", "city", "single-base"},
        rationale_seed=[
            "Prioritizes food access and walkable daily structure without naming a city or neighborhood.",
            "Works only after lodging areas and activity clusters are resolved into JSON.",
        ],
        risks=[
            "Crowds, parking, and room fit need evidence before this becomes a recommendation.",
        ],
    ),
    _ConceptArchetype(
        concept_id="json-first-nature-water-base",
        title="Nature + Water Reset",
        destination_slots=[
            "Nature or water base",
            "Weather-backup activity area",
        ],
        recommended_duration_days=6,
        travel_burden_hours=6.0,
        direct_flight_friendliness=7,
        family_fit=84,
        comfort=80,
        food=76,
        crowd_risk=42,
        tags={"nature", "beach", "water", "snorkeling", "reef", "chill", "family"},
        rationale_seed=[
            "Matches water/nature goals while keeping the actual place unresolved until evidence exists.",
            "Requires weather, safety, operator, and transfer evidence before ranking exact activities.",
        ],
        risks=[
            "Weather and sea conditions can invalidate activity plans; keep backup options unresolved until sourced.",
        ],
    ),
    _ConceptArchetype(
        concept_id="json-first-two-region-balanced",
        title="Two Bases, More Variety",
        destination_slots=[
            "Main stay area",
            "Second base only if it earns the move",
        ],
        recommended_duration_days=9,
        travel_burden_hours=7.0,
        direct_flight_friendliness=7,
        family_fit=80,
        comfort=78,
        food=84,
        crowd_risk=48,
        tags={"food", "culture", "nature", "two-base", "balanced"},
        rationale_seed=[
            "Allows more variety while still forcing each extra base to earn its transfer friction.",
            "Good only when resolver evidence shows distinct activity/lodging clusters.",
        ],
        risks=[
            "Can become unnecessary packing and check-in friction if the second base is not evidence-backed.",
        ],
    ),
    _ConceptArchetype(
        concept_id="json-first-activity-led-sampler",
        title="Best-Of Activity Sampler",
        destination_slots=[
            "Main lodging base",
            "One or two activity clusters",
        ],
        recommended_duration_days=10,
        travel_burden_hours=8.0,
        direct_flight_friendliness=6,
        family_fit=76,
        comfort=72,
        food=78,
        crowd_risk=58,
        tags={
            "adventure",
            "nature",
            "activity",
            "sampler",
            "active",
            "beach",
            "water",
            "snorkeling",
            "reef",
        },
        rationale_seed=[
            "Useful when the user's goals are activity-led and the exact destination is not yet resolved.",
            "Keeps activities as evidence requirements rather than canned recommendations.",
        ],
        risks=[
            "Higher risk of overpacking the trip; provider schedules and drive times must constrain the plan.",
        ],
    ),
    _ConceptArchetype(
        concept_id="json-first-value-flexible-search",
        title="Value Finder",
        destination_slots=[
            "Flexible destination candidate",
            "Practical lodging/search area",
        ],
        recommended_duration_days=6,
        travel_burden_hours=7.0,
        direct_flight_friendliness=6,
        family_fit=78,
        comfort=74,
        food=76,
        crowd_risk=46,
        tags={
            "value",
            "flexible",
            "budget",
            "low-crowd",
            "beach",
            "water",
            "snorkeling",
            "reef",
        },
        rationale_seed=[
            "Keeps the brief broad so scanner/provider evidence can find value without hidden steering.",
            "Requires explicit confirmation before any destination candidate becomes a selected trip.",
        ],
        risks=[
            "A broad search can feel vague unless the UI quickly asks the user to confirm resolved airports and places.",
        ],
    ),
]


class TripIdeationService:
    """Generate ranked family-fit scanner briefs from loose constraints."""

    def __init__(
        self,
        preferences: FamilyTravelPreferences | None = None,
        memory: MemoryStore | None = None,
        anthropic_client: Any | None = None,
        enabled: bool | None = None,
        model: str | None = None,
    ) -> None:
        self._prefs = preferences or FamilyTravelPreferences()
        self._memory = memory
        self._enabled = config.TRIPPY_IDEATION_LLM_ENABLED if enabled is None else enabled
        self._model = model or config.TRIPPY_TRIP_IDEATION_MODEL
        self._llm = TrippyLLMClient(anthropic_client=anthropic_client)

    def compare(self, request: TripIdeaRequest, *, limit: int = 5) -> TripComparison:
        if self._enabled:
            comparison = self._compare_with_llm(request, limit=limit)
            if comparison is not None and comparison.concepts:
                return comparison
            if self._llm.mode == "required":
                raise RuntimeError("Trip ideation LLM is required but unavailable")
            fallback = self._compare_with_fallback(request, limit=limit)
            fallback.scoring_notes.insert(0, "LLM ideation was unavailable; deterministic emergency fallback was used explicitly.")
            fallback.advisor["status"] = "fallback_used"
            fallback.advisor["llm_status"] = comparison.advisor if comparison is not None else {}
            return fallback
        return self._compare_with_fallback(request, limit=limit)

    def _compare_with_llm(self, request: TripIdeaRequest, *, limit: int) -> TripComparison | None:
        prompt = _ideation_prompt(request, self._prefs, self._memory, limit)
        result = self._llm.complete_json(
            service="trip_ideation",
            model=self._model,
            prompt=prompt,
            system=(
                "You are Trippy's senior AI trip ideation agent. Return strict JSON only. "
                "Do not invent prices, availability, booking links, flight numbers, drive times, or confirmations."
            ),
            max_tokens=2800,
            prompt_version=_PROMPT_VERSION,
        )
        if result.status != "success" or result.json is None:
            return TripComparison(
                request=request,
                concepts=[],
                recommended_concept_id=None,
                scoring_notes=[
                    f"Ideation LLM unavailable: {result.error or result.status}.",
                    "No destination concepts were fabricated by the LLM path.",
                ],
                advisor={
                    "status": "llm_unavailable",
                    "model": self._model,
                    "prompt_version": _PROMPT_VERSION,
                    "error": result.error,
                    "fallback_available": self._llm.mode == "advisory",
                },
            )
        try:
            payload = result.json
            concepts = [
                _concept_from_llm(item)
                for item in payload.get("concepts", [])[:limit]
                if isinstance(item, dict)
            ]
            if not concepts:
                raise ValueError("Ideation LLM returned no concepts")
            recommended = str(payload.get("recommended_concept_id") or concepts[0].concept_id)
            return TripComparison(
                request=request,
                concepts=concepts,
                recommended_concept_id=recommended,
                scoring_notes=_string_list(payload.get("warnings"))
                + [
                    f"status={payload.get('status') or 'llm_success'}",
                    "LLM ideation generated real destination concepts from user constraints; source facts still require provider or user evidence before booking.",
                ],
                advisor={
                    "status": payload.get("status") or "llm_success",
                    "model": payload.get("model") or self._model,
                    "prompt_version": _PROMPT_VERSION,
                    "request_summary": payload.get("request_summary") or "",
                    "assumptions": _string_list(payload.get("assumptions")),
                    "questions_for_user": _string_list(payload.get("questions_for_user")),
                    "next_actions": _string_list(payload.get("next_actions")),
                    "warnings": _string_list(payload.get("warnings")),
                    "raw_response": result.text,
                },
            )
        except Exception as exc:
            return TripComparison(
                request=request,
                concepts=[],
                scoring_notes=[f"Ideation LLM response failed validation: {exc}."],
                advisor={
                    "status": "llm_unavailable",
                    "model": self._model,
                    "prompt_version": _PROMPT_VERSION,
                    "error": str(exc),
                    "fallback_available": self._llm.mode == "advisory",
                },
            )

    def _compare_with_fallback(self, request: TripIdeaRequest, *, limit: int) -> TripComparison:
        experience_intents = _required_experience_intents(request)
        archetypes = _experience_filtered_archetypes(_ARCHETYPES, experience_intents)
        concepts = [self._score_archetype(archetype, request) for archetype in archetypes]
        filtered = _duration_filtered_concepts(concepts, request, limit)
        if filtered:
            concepts = filtered
        ranked = sorted(concepts, key=lambda concept: concept.total_score, reverse=True)[:limit]
        recommendation = ranked[0].concept_id if ranked else None
        scoring_notes = [
            "Ideas are destination-agnostic scanner briefs, not named destination recommendations.",
            "No city, country, airport, neighborhood, hotel, airline, or activity is inferred from keywords.",
            "Before planning, resolver/provider evidence must write explicit geography into TripIntake JSON.",
        ]
        if request.duration_days:
            scoring_notes.insert(
                0,
                f"Requested duration is {request.duration_days} day(s); suggestions are duration-fit first.",
            )
        if _contains_regional_wording(request):
            scoring_notes.insert(
                0,
                "Regional wording was treated as user intent only; no known destination catalog was consulted.",
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
        comparison.advisor = {
            "kind": "trip_ideas",
            "status": "fallback_used",
            "model": self._model,
            "prompt_version": _PROMPT_VERSION,
            "prompt": _ideation_prompt(request, self._prefs, self._memory, limit),
            "summary": "Emergency deterministic ideation fallback used because LLM ideation was disabled or unavailable.",
        }
        return comparison

    def _score_archetype(
        self, archetype: _ConceptArchetype, request: TripIdeaRequest
    ) -> TripConcept:
        score = archetype.family_fit + archetype.comfort + archetype.food
        rationale = list(archetype.rationale_seed)
        why_not = list(archetype.risks)
        goals = {_normalize_goal(goal) for goal in request.goals}
        avoid = {_normalize_goal(item) for item in request.avoid}
        matched_goals = goals & archetype.tags
        score += len(matched_goals) * 8
        if matched_goals:
            rationale.append(f"Matches requested goals: {', '.join(sorted(matched_goals))}.")

        experience_intents = _required_experience_intents(request)
        matched_experiences = {
            intent
            for intent in experience_intents
            if _archetype_matches_experience(archetype, intent)
        }
        if matched_experiences:
            score += len(matched_experiences) * 18
            rationale.append(
                f"Matches required experience: {', '.join(sorted(matched_experiences))}."
            )

        if request.duration_days:
            diff = abs(request.duration_days - archetype.recommended_duration_days)
            if diff == 0:
                score += 18
                rationale.append("Duration matches the requested trip length.")
            elif diff <= 1:
                score += 10
                rationale.append("Duration is close to the requested trip length.")
            elif diff <= 2:
                score += 4
                rationale.append("Duration is workable but needs pacing discipline.")
            elif request.duration_days < archetype.recommended_duration_days:
                score -= 20 + (archetype.recommended_duration_days - request.duration_days) * 8
                why_not.append(
                    f"Ideal version is {archetype.recommended_duration_days} days, which does not respect the requested {request.duration_days}-day constraint without cutting scope."
                )
            else:
                score -= diff * 2

        if request.max_flight_hours and archetype.travel_burden_hours > request.max_flight_hours:
            penalty = int((archetype.travel_burden_hours - request.max_flight_hours) * 4)
            score -= penalty
            why_not.append(
                f"Estimated travel burden around {archetype.travel_burden_hours:.1f}h exceeds requested max."
            )

        if request.direct_flight_preferred or self._prefs.flight.prefer_direct:
            score += archetype.direct_flight_friendliness
            if archetype.direct_flight_friendliness < 7:
                why_not.append("Direct-flight friendliness is only moderate; verify exact routing.")

        if "crowds" in avoid or "huge crowds" in avoid or self._prefs.crowd.avoid_huge_crowds_when_possible:
            crowd_penalty = max(0, archetype.crowd_risk - 55)
            score -= crowd_penalty
            if crowd_penalty:
                why_not.append("Crowd exposure needs evidence-backed season and timing choices.")

        if "food" in archetype.tags and self._prefs.food.food_is_major_objective:
            score += 10

        if "city" in archetype.tags and self._prefs.lodging_context.city_prefer_urban_core:
            rationale.append("Requires user-confirmed walkable lodging areas before connector searches.")

        required_research = [
            "Resolve candidate destination names, countries, map locations, and gateway airports into TripIntake JSON.",
            "Live flight options, total travel time, layovers, baggage, seats, and loyalty application.",
            "Exact lodging short list with bed layout, location, safety, parking/access, and cancellation terms.",
            "Provider-backed activities/tours with strong review, safety, schedule, and weather evidence.",
            "Entry requirements, passport validity rules, health precautions, and local cash guidance from official/current sources.",
        ]

        recommended_duration = (
            min(archetype.recommended_duration_days, request.duration_days)
            if request.duration_days
            else archetype.recommended_duration_days
        )
        return TripConcept(
            concept_id=archetype.concept_id,
            title=archetype.title,
            destinations=archetype.destination_slots,
            recommended_duration_days=recommended_duration,
            best_season="requires resolver/provider evidence",
            estimated_cost_band_cad="not estimated until destination, dates, party, and providers are resolved",
            estimated_travel_burden=_travel_burden(archetype.travel_burden_hours),
            estimated_flight_hours=archetype.travel_burden_hours,
            direct_flight_friendliness=archetype.direct_flight_friendliness,
            family_fit_score=archetype.family_fit,
            comfort_convenience_score=archetype.comfort,
            food_score=archetype.food,
            crowd_risk=archetype.crowd_risk,
            total_score=max(0, min(100, score // 3)),
            country_prior_signals=[],
            rationale=rationale,
            why_it_may_not_fit=why_not,
            major_risks=archetype.risks,
            required_research=required_research,
        )


def _travel_burden(flight_hours: float) -> str:
    if flight_hours <= 6:
        return "moderate"
    if flight_hours <= 9:
        return "meaningful"
    return "high"


def _ideation_prompt(
    request: TripIdeaRequest,
    prefs: FamilyTravelPreferences,
    memory: MemoryStore | None,
    limit: int,
) -> str:
    memory_context = memory.to_context_string() if memory is not None else ""
    output_schema = {
        "status": "llm_success",
        "model": "model name",
        "request_summary": "plain English summary",
        "recommended_concept_id": "string",
        "concepts": [
            {
                "concept_id": "string",
                "title": "string",
                "destination_candidates": [
                    {
                        "name": "string",
                        "country": "string",
                        "region": "string",
                        "gateway_airports": ["IATA"],
                        "why_it_fits": ["string"],
                        "concerns": ["string"],
                        "evidence_needed": ["string"],
                        "confidence": 0.0,
                    }
                ],
                "recommended_duration_days": 0,
                "best_season": "string",
                "estimated_travel_burden": "string",
                "family_fit_score": 0,
                "comfort_convenience_score": 0,
                "food_score": 0,
                "crowd_risk": 0,
                "total_score": 0,
                "rationale": ["string"],
                "why_it_may_not_fit": ["string"],
                "major_risks": ["string"],
                "required_research": ["string"],
            }
        ],
        "questions_for_user": ["string"],
        "next_actions": ["string"],
        "warnings": ["string"],
    }
    parts = [
        f"# Trippy Trip Ideation ({_PROMPT_VERSION})",
        "Generate real trip concepts for Ken/Sue/family from the request, preferences, memory, constraints, goals, avoidances, travel window, party, and flight burden.",
        "Use judgment. Do not return templates like single-base search placeholders.",
        "Separate known user input from assumptions. Gateway airports may be candidates only and must be marked as evidence needed before booking.",
        "Never invent prices, availability, booking links, flight numbers, drive times, bed layouts, or confirmation details.",
        f"Return up to {limit} concepts.",
        "",
        "## Request",
        json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True),
        "",
        prefs.to_context_string(),
    ]
    if memory_context:
        parts.extend(["", memory_context])
    parts.extend(["", "## Output JSON Schema", json.dumps(output_schema, indent=2)])
    return "\n".join(parts)


def _concept_from_llm(item: dict[str, Any]) -> TripConcept:
    candidates = [c for c in item.get("destination_candidates", []) if isinstance(c, dict)]
    destinations = []
    for candidate in candidates:
        label_parts = [
            str(candidate.get("name") or "").strip(),
            str(candidate.get("region") or "").strip(),
            str(candidate.get("country") or "").strip(),
        ]
        label = ", ".join(part for part in label_parts if part)
        if label:
            destinations.append(label)
    return TripConcept(
        concept_id=str(item.get("concept_id") or _slug(str(item.get("title") or "llm-concept"))),
        title=str(item.get("title") or "LLM Trip Concept"),
        destinations=destinations or ["Destination candidates require user confirmation"],
        recommended_duration_days=max(1, _int(item.get("recommended_duration_days"), 7)),
        best_season=str(item.get("best_season") or "requires current source verification"),
        estimated_cost_band_cad="not estimated until dated provider evidence exists",
        estimated_travel_burden=str(item.get("estimated_travel_burden") or "requires flight evidence"),
        estimated_flight_hours=0.0,
        direct_flight_friendliness=0,
        family_fit_score=_score(item.get("family_fit_score")),
        comfort_convenience_score=_score(item.get("comfort_convenience_score")),
        food_score=_score(item.get("food_score")),
        crowd_risk=_score(item.get("crowd_risk")),
        total_score=_score(item.get("total_score")),
        country_prior_signals=[],
        rationale=_string_list(item.get("rationale")),
        why_it_may_not_fit=_string_list(item.get("why_it_may_not_fit")),
        major_risks=_string_list(item.get("major_risks")),
        required_research=_string_list(item.get("required_research"))
        or [
            "Validate gateway airport, flight timing, lodging locations, dated activity availability, and local logistics from source evidence."
        ],
    )


def _required_experience_intents(request: TripIdeaRequest) -> set[str]:
    text = _request_text(request)
    intents: set[str] = set()
    if any(term in text for term in ("snorkel", "snorkeling", "snorkelling", "snorkling", "reef")):
        intents.add("snorkeling")
    if any(term in text for term in ("beach", "water", "swim", "ocean")):
        intents.add("beach_water")
    return intents


def _experience_filtered_archetypes(
    archetypes: list[_ConceptArchetype],
    experience_intents: set[str],
) -> list[_ConceptArchetype]:
    if not experience_intents:
        return archetypes
    matched = [
        archetype
        for archetype in archetypes
        if all(_archetype_matches_experience(archetype, intent) for intent in experience_intents)
    ]
    return matched or archetypes


def _archetype_matches_experience(archetype: _ConceptArchetype, intent: str) -> bool:
    if intent == "snorkeling":
        return bool(archetype.tags & {"snorkeling", "reef"})
    if intent == "beach_water":
        return bool(archetype.tags & {"beach", "water", "reef", "snorkeling"})
    return intent in archetype.tags


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


def _normalize_goal(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").split()).replace(" ", "-")


def _contains_regional_wording(request: TripIdeaRequest) -> bool:
    text = _request_text(request)
    return any(term in text for term in ("region", "coast", "island", "caribbean", "europe", "asia"))


def _duration_filtered_concepts(
    concepts: list[TripConcept],
    request: TripIdeaRequest,
    limit: int,
) -> list[TripConcept]:
    if not request.duration_days:
        return []
    tolerance = 0 if request.duration_days <= 6 else 1 if request.duration_days <= 8 else 2
    max_days = request.duration_days + tolerance
    duration_fit = [
        concept for concept in concepts if concept.recommended_duration_days <= max_days
    ]
    return duration_fit


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _score(value: Any) -> int:
    return max(0, min(100, _int(value, 0)))


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "llm-concept"
