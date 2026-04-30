"""Preference-rich LLM planning advisor for trip strategy decisions."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from trippy import config
from trippy.memory.store import MemoryStore
from trippy.models.ideas import TripComparison, TripIdeaRequest
from trippy.models.planning_advice import PlanningAdviceKind, PlanningAdviceResult
from trippy.models.preferences import FamilyTravelPreferences
from trippy.models.shortlists import ResearchShortlistState
from trippy.models.trip_planning import TripIntake, TripPlanDraft, TripPlanOption
from trippy.services.country_priors import CountryPriorService

_PROMPT_VERSION = "planning-advisor-v1"
_MAX_TOKENS = 1800


class PlanningAdvisorService:
    """Build strong planning prompts and optionally ask an LLM for strategy.

    The service is deliberately advisory: it does not mutate trip state, memory, skills,
    or shortlist rows. Callers decide how to persist or display its recommendation.
    """

    def __init__(
        self,
        *,
        preferences: FamilyTravelPreferences | None = None,
        memory: MemoryStore | None = None,
        anthropic_client: Any | None = None,
        enabled: bool | None = None,
        model: str | None = None,
    ) -> None:
        self._prefs = preferences or FamilyTravelPreferences()
        self._memory = memory or MemoryStore(config.MEMORY_PATH)
        self._client = anthropic_client
        self._enabled = config.PLANNING_LLM_ENABLED if enabled is None else enabled
        self._model = model or config.PLANNING_LLM_MODEL
        self._country_priors = CountryPriorService()

    def advise_trip_ideas(
        self,
        request: TripIdeaRequest,
        comparison: TripComparison,
    ) -> PlanningAdviceResult:
        prompt = self._prompt(
            PlanningAdviceKind.TRIP_IDEAS,
            user_goal=(
                "Evaluate these generated trip concepts. Obey the requested duration, season, "
                "party, goals, avoidances, flight burden, and family preferences before ranking."
            ),
            request_payload=request.model_dump(mode="json"),
            comparison_payload=_compact_dump(comparison.model_dump(mode="json"), ["advisor"]),
        )
        return self._call_or_fallback(
            PlanningAdviceKind.TRIP_IDEAS,
            prompt,
            fallback="Use the highest scoring duration-fit concept, then ask the user to confirm or reject it before detailed intake.",
        )

    def advise_trip_shape(
        self,
        intake: TripIntake,
        draft: TripPlanDraft,
    ) -> PlanningAdviceResult:
        prompt = self._prompt(
            PlanningAdviceKind.TRIP_SHAPE,
            user_goal=(
                "Choose the best trip shape and explain how the family should experience the destination. "
                "For islands, decide whether to prioritize one base, two bases, or a broader sampler."
            ),
            intake=intake,
            draft_payload=_compact_dump(draft.model_dump(mode="json"), ["advisor"]),
        )
        return self._call_or_fallback(
            PlanningAdviceKind.TRIP_SHAPE,
            prompt,
            fallback="Use the recommended plan option until exact flights, lodging, and local logistics prove a better structure.",
        )

    def advise_lodging_structure(
        self,
        intake: TripIntake,
        option: TripPlanOption,
        state: ResearchShortlistState | None = None,
    ) -> PlanningAdviceResult:
        prompt = self._prompt(
            PlanningAdviceKind.LODGING_STRUCTURE,
            user_goal=(
                "Decide whether this trip should use one stay or split stays. Recommend night allocation, "
                "where each base should be, why the split is or is not worth it, and what evidence is still needed."
            ),
            intake=intake,
            plan_option_payload=option.model_dump(mode="json"),
            shortlist_payload=_shortlist_summary(state) if state is not None else {},
        )
        return self._call_or_fallback(
            PlanningAdviceKind.LODGING_STRUCTURE,
            prompt,
            fallback="Keep the selected plan's stay structure, but only split stays when reduced backtracking clearly beats check-in, luggage, and bed-validation friction.",
        )

    def advise_island_experience(
        self,
        intake: TripIntake,
        draft: TripPlanDraft,
    ) -> PlanningAdviceResult:
        prompt = self._prompt(
            PlanningAdviceKind.ISLAND_EXPERIENCE,
            user_goal=(
                "Recommend how to experience this island or region set day-to-day: base areas, "
                "activity clusters, chill days, food access, driving loops, weather backups, and what not to overpack."
            ),
            intake=intake,
            draft_payload=_compact_dump(draft.model_dump(mode="json"), ["advisor"]),
        )
        return self._call_or_fallback(
            PlanningAdviceKind.ISLAND_EXPERIENCE,
            prompt,
            fallback="Experience the island through a small number of strong geographic clusters with downtime and weather backups, not by chasing every sight.",
        )

    def advise_next_steps(
        self,
        intake: TripIntake | None = None,
        draft: TripPlanDraft | None = None,
        shortlists: list[ResearchShortlistState] | None = None,
        user_question: str = "",
    ) -> PlanningAdviceResult:
        prompt = self._prompt(
            PlanningAdviceKind.NEXT_STEPS,
            user_goal=(
                user_question
                or "Determine the next best planning step. Prefer concrete actions that reduce uncertainty and move the trip toward booking readiness."
            ),
            intake=intake,
            draft_payload=_compact_dump(draft.model_dump(mode="json"), ["advisor"])
            if draft is not None
            else {},
            shortlist_payload=[_shortlist_summary(state) for state in shortlists or []],
        )
        return self._call_or_fallback(
            PlanningAdviceKind.NEXT_STEPS,
            prompt,
            fallback="Resolve the earliest high-impact unknown: exact flights, lodging structure, lodging fit, car need, or dated activities.",
        )

    def _prompt(
        self,
        kind: PlanningAdviceKind,
        *,
        user_goal: str,
        intake: TripIntake | None = None,
        request_payload: dict[str, Any] | None = None,
        comparison_payload: dict[str, Any] | None = None,
        draft_payload: dict[str, Any] | None = None,
        plan_option_payload: dict[str, Any] | None = None,
        shortlist_payload: Any = None,
    ) -> str:
        country_signals = []
        if intake and intake.geography and intake.geography.country:
            signal = self._country_priors.fit_for_country(intake.geography.country)
            if signal:
                country_signals.append(signal.model_dump(mode="json"))
        memory_context = self._memory.to_context_string()
        parts = [
            f"# Trippy Planning Advisor ({_PROMPT_VERSION})",
            "You are Trippy's senior trip-strategy LLM for the Chapman family.",
            "",
            "## Non-Negotiables",
            "- Optimize comfort, convenience, safety, family smoothness, and food quality above raw lowest price.",
            "- Never invent prices, availability, flight numbers, bed layouts, drive times, or booking facts.",
            "- If evidence is missing, say what must be verified and keep confidence appropriately limited.",
            "- Treat memory and country priors as directional evidence, not rigid rules.",
            "- Keep recommendations practical: one or two strong calls beat a menu of weak possibilities.",
            "- Preserve review-gated learning: propose lessons only as recommendations for review, never mutate memory.",
            "",
            self._prefs.to_context_string(),
        ]
        if memory_context:
            parts.extend(["", memory_context])
        if country_signals:
            parts.extend(["", "## Matched Country Priors", _json(country_signals)])
        if intake is not None:
            parts.extend(["", "## Current Trip Intake", _json(_intake_payload(intake))])
        if request_payload:
            parts.extend(["", "## Idea Request", _json(request_payload)])
        if comparison_payload:
            parts.extend(["", "## Current Generated Concepts", _json(comparison_payload)])
        if draft_payload:
            parts.extend(["", "## Current Plan Draft", _json(draft_payload)])
        if plan_option_payload:
            parts.extend(["", "## Selected Plan Shape", _json(plan_option_payload)])
        if shortlist_payload:
            parts.extend(["", "## Current Shortlist / Evidence State", _json(shortlist_payload)])

        parts.extend(
            [
                "",
                "## Task",
                user_goal,
                "",
                "## Output Contract",
                "Return JSON only with these keys:",
                _json(
                    {
                        "summary": "one sentence",
                        "recommendation": "plain-English best call",
                        "rationale": ["2-5 concise bullets tied to intake/preferences/evidence"],
                        "next_actions": ["ordered concrete actions"],
                        "questions_for_user": ["only decision-blocking questions"],
                        "warnings": ["hidden friction or trust-boundary issues"],
                        "evidence_needed": ["source facts that must be verified before booking"],
                        "stay_strategy": "single_stay|split_stay|unclear when relevant",
                        "night_plan": [
                            {"region": "base/area", "nights": 3, "reason": "why this allocation"}
                        ],
                        "confidence": 0.0,
                    }
                ),
            ]
        )
        return "\n".join(parts)

    def _call_or_fallback(
        self,
        kind: PlanningAdviceKind,
        prompt: str,
        *,
        fallback: str,
    ) -> PlanningAdviceResult:
        if not self._enabled:
            return PlanningAdviceResult(
                kind=kind,
                status="disabled",
                model=self._model,
                prompt_version=_PROMPT_VERSION,
                prompt=prompt,
                summary=fallback,
                recommendation=fallback,
                next_actions=[
                    "Enable TRIPPY_PLANNING_LLM_ENABLED with ANTHROPIC_API_KEY for LLM strategy calls."
                ],
                confidence=0.35,
            )
        if not config.ANTHROPIC_API_KEY and self._client is None:
            return PlanningAdviceResult(
                kind=kind,
                status="skipped_no_api_key",
                model=self._model,
                prompt_version=_PROMPT_VERSION,
                prompt=prompt,
                summary=fallback,
                recommendation=fallback,
                next_actions=[
                    "Set ANTHROPIC_API_KEY to enable preference-rich LLM planning advice."
                ],
                confidence=0.35,
            )

        try:
            client = self._client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=(
                    "You are a concise, evidence-bound travel planning strategist. "
                    "Return valid JSON only."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            text = _response_text(response)
            parsed = _parse_json_response(text)
            return PlanningAdviceResult(
                kind=kind,
                status="llm_success",
                model=self._model,
                prompt_version=_PROMPT_VERSION,
                prompt=prompt,
                summary=str(parsed.get("summary") or ""),
                recommendation=str(parsed.get("recommendation") or ""),
                rationale=_string_list(parsed.get("rationale")),
                next_actions=_string_list(parsed.get("next_actions")),
                questions_for_user=_string_list(parsed.get("questions_for_user")),
                warnings=_string_list(parsed.get("warnings")),
                evidence_needed=_string_list(parsed.get("evidence_needed")),
                stay_strategy=str(parsed.get("stay_strategy") or ""),
                night_plan=_dict_list(parsed.get("night_plan")),
                confidence=_float(parsed.get("confidence"), 0.55),
                raw_response=text,
            )
        except Exception as exc:
            return PlanningAdviceResult(
                kind=kind,
                status="llm_failed",
                model=self._model,
                prompt_version=_PROMPT_VERSION,
                prompt=prompt,
                summary=fallback,
                recommendation=fallback,
                next_actions=["Retry the planning-advisor call after checking the LLM setup."],
                confidence=0.25,
                error=str(exc),
            )


def _intake_payload(intake: TripIntake) -> dict[str, Any]:
    return {
        "trip_id": intake.trip_id,
        "trip_name": intake.trip_name,
        "mode": intake.mode.value,
        "destinations": intake.destination_seeds,
        "travel_window": intake.travel_window.display(),
        "duration": intake.duration_display(),
        "duration_days": intake.duration_days,
        "duration_min_days": intake.duration_min_days,
        "duration_max_days": intake.duration_max_days,
        "party": intake.party.model_dump(mode="json"),
        "departure_airports": intake.departure_airports,
        "budget_cad": intake.budget_cad,
        "max_travel_time_hours": intake.max_travel_time_hours,
        "flight_preferences": intake.flight_preferences.model_dump(mode="json"),
        "goals": intake.goals,
        "avoidances": intake.avoidances,
        "pace": intake.pace.value,
        "crowd_tolerance": intake.crowd_tolerance.value,
        "food_priority": intake.food_priority.value,
        "lodging_preferences": intake.lodging_preferences.model_dump(mode="json"),
        "car_rental_expectations": intake.car_rental_expectations.model_dump(mode="json"),
        "notes": intake.freeform_notes,
    }


def _shortlist_summary(state: ResearchShortlistState | None) -> dict[str, Any]:
    if state is None:
        return {}
    options = state.options_as_dicts()[:5]
    compact_options = [
        {
            "option_id": option.get("option_id"),
            "rank": option.get("rank"),
            "label": option.get("name")
            or option.get("airline")
            or option.get("booking_source")
            or option.get("activity_name"),
            "region": option.get("island_or_region") or option.get("island_location"),
            "status": option.get("row_status"),
            "grade": option.get("recommendation_grade"),
            "friction_flags": option.get("friction_flags", [])[:4],
            "tradeoffs": option.get("tradeoffs", [])[:3],
            "confidence_notes": option.get("confidence_notes", [])[:3],
        }
        for option in options
    ]
    return {
        "category": state.category.value,
        "recommended_option_id": state.recommended_option_id,
        "recommendation_summary": state.recommendation_summary,
        "warnings": state.warnings[:5],
        "next_actions": state.next_actions[:5],
        "artifacts": _compact_dump(state.artifacts, ["planning_advisor"]),
        "options": compact_options,
    }


def _compact_dump(payload: Any, excluded_keys: list[str]) -> Any:
    if isinstance(payload, dict):
        return {
            key: _compact_dump(value, excluded_keys)
            for key, value in payload.items()
            if key not in excluded_keys
        }
    if isinstance(payload, list):
        return [_compact_dump(value, excluded_keys) for value in payload]
    return payload


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", "") == "text":
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(part for part in parts if part).strip()


def _parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped.removeprefix("json").strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Planning advisor response must be a JSON object")
    return data


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)
