"""Persistence and shared helpers for research shortlists."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

from trippy.models.shortlists import ResearchShortlistState, ShortlistCategory
from trippy.models.sources import SourcePlan, TravelSourceCategory
from trippy.models.trip_planning import TripIntake, TripPlanDraft, TripPlanOption
from trippy.services.source_registry import TravelSourceRegistry
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class ShortlistStore:
    """Save and load category-specific shortlist state."""

    def __init__(self, shortlists_dir: Path | None = None) -> None:
        from trippy import config

        self._dir = shortlists_dir or config.SHORTLISTS_PATH

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, trip_id: str, category: ShortlistCategory) -> Path:
        return self._dir / f"{trip_id}-{category.value}.json"

    def save(self, state: ResearchShortlistState) -> ResearchShortlistState:
        self._ensure_dir()
        self.path_for(state.trip_id, state.category).write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return state

    def load(self, trip_id: str, category: ShortlistCategory) -> ResearchShortlistState | None:
        path = self.path_for(trip_id, category)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ResearchShortlistState.model_validate(data)

    def load_all(self, trip_id: str) -> list[ResearchShortlistState]:
        states = []
        for category in ShortlistCategory:
            state = self.load(trip_id, category)
            if state is not None:
                states.append(state)
        return states


class ShortlistContext:
    """Loaded intake/draft/selected option context used by shortlist services."""

    def __init__(
        self,
        trip_id: str,
        *,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
    ) -> None:
        self.intakes = intake_service or TripIntakeService()
        self.planner = planner_service or TripPlannerService(self.intakes)
        self.intake = self.intakes.require(trip_id)
        self.draft = self.planner.require_draft(trip_id)
        option = self.draft.get_option()
        if option is None:
            raise ValueError(f"No selected or recommended plan option for trip {trip_id!r}")
        self.option = option

    intake: TripIntake
    draft: TripPlanDraft
    option: TripPlanOption


def source_plan(category: TravelSourceCategory) -> SourcePlan:
    return TravelSourceRegistry().plan_for(category)


def source_plan_payload(plan: SourcePlan) -> dict[str, object]:
    return {
        "category": plan.category.value,
        "primary": [source.platform_name for source in plan.primary],
        "secondary": [source.platform_name for source in plan.secondary],
        "validation": [source.platform_name for source in plan.validation],
        "notes": plan.notes,
    }


def source_search_url(
    source: str,
    query: str,
    *,
    category: TravelSourceCategory | None = None,
) -> str:
    encoded = quote_plus(query)
    if source == "Google Flights":
        return f"https://www.google.com/travel/flights?q={encoded}"
    if source == "Kayak.ca":
        if category == TravelSourceCategory.CAR_RENTALS:
            return f"https://www.ca.kayak.com/cars/{encoded}"
        return f"https://www.ca.kayak.com/flights/{encoded}"
    if source == "Expedia":
        if category == TravelSourceCategory.CAR_RENTALS:
            return f"https://www.expedia.ca/Cars-Search?searchProduct=cars&query={encoded}"
        return f"https://www.expedia.ca/Flights-Search?searchProduct=flights&query={encoded}"
    if source == "Flighthub":
        return f"https://www.flighthub.com/search/flights?query={encoded}"
    if source == "Booking.com":
        if category == TravelSourceCategory.CAR_RENTALS:
            return f"https://www.booking.com/cars/index.html?ss={encoded}"
        return f"https://www.booking.com/searchresults.html?ss={encoded}"
    if source == "Airbnb":
        return f"https://www.airbnb.ca/s/{encoded}/homes"
    if source == "VRBO":
        return f"https://www.vrbo.com/search/keywords:{encoded}"
    if source == "Tripadvisor":
        return f"https://www.tripadvisor.ca/Search?q={encoded}"
    if source == "Trivago":
        return f"https://www.trivago.ca/en-CA/srl?search={encoded}"
    if source == "GetYourGuide":
        return f"https://www.getyourguide.com/s/?q={encoded}"
    if source == "Airbnb Experiences":
        return f"https://www.airbnb.ca/s/{encoded}/experiences"
    return f"https://www.google.com/search?q={encoded}"


def trip_query(intake: TripIntake, extra: str) -> str:
    destinations = " ".join(intake.destination_seeds)
    timing = intake.travel_window.display()
    return " ".join(part for part in [destinations, timing, extra] if part).strip()


def selected_regions(option: TripPlanOption) -> str:
    return ", ".join(option.regions)
