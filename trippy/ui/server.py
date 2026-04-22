"""Small local web UI server for Trippy planning workflows."""

from __future__ import annotations

import json
import mimetypes
import webbrowser
from datetime import date
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from trippy import config
from trippy.models.ideas import TripIdeaRequest
from trippy.models.shortlists import ShortlistCategory
from trippy.models.trip_planning import (
    CarRentalExpectation,
    CrowdTolerance,
    FlightPreferenceInput,
    FoodPriority,
    LodgingPreferenceInput,
    TravelerAgeBand,
    TravelWindow,
    TripIntake,
    TripIntakeMode,
    TripPace,
    TripParty,
    TripPartyType,
    TripTraveler,
)
from trippy.services.activity_shortlist import ActivityShortlistService
from trippy.services.car_shortlist import CarShortlistService
from trippy.services.dashboard import DashboardService
from trippy.services.flight_shortlist import FlightShortlistService
from trippy.services.learning import (
    FeedbackRating,
    LearningEventStore,
    UserFeedback,
    WorkflowOutcome,
    WorkflowStatus,
)
from trippy.services.lodging_shortlist import LodgingShortlistService
from trippy.services.shortlist_store import ShortlistStore
from trippy.services.trip_ideation import TripIdeationService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_management import TripManagementService
from trippy.services.trip_map_builder import TripMapBuilder
from trippy.services.trip_planner import TripPlannerService
from trippy.services.trip_workspace import TripWorkspaceService

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATE_DIR = PACKAGE_DIR / "templates"


class TrippyUIService:
    """Browser-facing service facade over the deterministic Trippy services."""

    def __init__(
        self,
        *,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        learning_store: LearningEventStore | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._learning = learning_store or LearningEventStore()

    def app_state(self) -> dict[str, Any]:
        dashboard = DashboardService().build()
        intakes = self._intakes.list_intakes()
        workflows = self._learning.list_workflows()[-12:]
        logs = self.logs(limit=16)
        return {
            "dashboard": dashboard.model_dump(mode="json"),
            "intakes": [intake.model_dump(mode="json") for intake in intakes],
            "recent_workflows": [workflow.model_dump(mode="json") for workflow in workflows],
            "run_log": logs["events"],
            "backend_log_path": logs["events_path"],
            "pending_learning_proposals": logs["pending_proposals"],
            "suggested_trip_id": _suggested_trip_id(dashboard.model_dump(mode="json"), intakes),
        }

    def trip_state(self, trip_id: str) -> dict[str, Any]:
        intake = self._intakes.load(trip_id)
        draft = self._planner.load_draft(trip_id)
        workspace = TripWorkspaceService(self._intakes, self._planner).load(trip_id)
        shortlists = ShortlistStore().load_all(trip_id)
        workflows = [
            workflow for workflow in self._learning.list_workflows() if workflow.trip_id == trip_id
        ][-12:]
        logs = self.logs(trip_id=trip_id, limit=30)
        return {
            "trip_id": trip_id,
            "intake": intake.model_dump(mode="json") if intake else None,
            "draft": draft.model_dump(mode="json") if draft else None,
            "workspace": workspace.model_dump(mode="json") if workspace else None,
            "map_artifact": _load_map_artifact(trip_id),
            "shortlists": [shortlist.model_dump(mode="json") for shortlist in shortlists],
            "recent_workflows": [workflow.model_dump(mode="json") for workflow in workflows],
            "run_log": logs["events"],
            "backend_log_path": logs["events_path"],
            "pending_learning_proposals": logs["pending_proposals"],
            "next_step": _next_step_for_state(
                bool(intake),
                bool(draft),
                bool(draft and draft.selected_option_id),
                {shortlist.category.value for shortlist in shortlists},
                bool(workspace),
            ),
        }

    def logs(self, trip_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        events = self._learning.list_events()
        workflow_trip_ids = _workflow_trip_index(events)
        summaries = [_event_summary(event, workflow_trip_ids) for event in events]
        if trip_id:
            summaries = [
                event
                for event in summaries
                if event.get("trip_id") == trip_id
                or (event.get("severity") == "error" and not event.get("trip_id"))
            ]
        return {
            "events_path": str(self._learning.events_path),
            "proposals_path": str(self._learning.proposals_path),
            "events": summaries[-max(limit, 0) :],
            "pending_proposals": [
                proposal.model_dump(mode="json") for proposal in self._learning.list_proposals()
            ],
        }

    def suggest_ideas(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = TripIdeaRequest(
            time_of_year=_optional_str(payload.get("time_of_year")),
            duration_days=_int_or_none(payload.get("duration_days")),
            budget_cad=_float_or_none(payload.get("budget_cad")),
            travelers=_int(payload.get("travelers"), 5),
            max_flight_hours=_float_or_none(
                payload.get("max_flight_hours") or payload.get("max_travel_time_hours")
            ),
            direct_flight_preferred=bool(payload.get("direct_flight_preferred", True)),
            goals=_split_list(payload.get("goals") or payload.get("desires")),
            avoid=_split_list(payload.get("avoidances") or payload.get("avoid")),
            desired_vibe=_optional_str(payload.get("desired_vibe")),
            activity_level=_optional_str(payload.get("activity_level")),
        )
        comparison = TripIdeationService().compare(request, limit=3)
        result = comparison.model_dump(mode="json")
        workflow = self._record_workflow(
            workflow_name="ui-trip-ideas-suggest",
            skill_name="trippy-family-itinerary-builder",
            summary=f"Generated {len(comparison.concepts)} UI trip suggestion(s)",
            result=result,
        )
        return {
            "workflow_id": workflow.id,
            "comparison": result,
            "next_step": "Choose a suggestion to prefill the detailed trip intake.",
        }

    def create_intake(self, payload: dict[str, Any]) -> dict[str, Any]:
        intake = TripIntake(
            trip_id=str(payload.get("trip_id") or ""),
            mode=TripIntakeMode(_normalise_enum(payload.get("mode"), "selected_destination")),
            trip_name=str(payload.get("trip_name") or "Azores 2027"),
            destination_seeds=_split_list(
                payload.get("destinations") or payload.get("destination")
            ),
            travel_window=TravelWindow(
                label=_optional_str(payload.get("travel_window")),
                season=_optional_str(payload.get("season")),
                start_date=_parse_date(payload.get("start_date")),
                end_date=_parse_date(payload.get("end_date")),
            ),
            duration_days=payload.get("duration") or payload.get("duration_days") or None,
            travelers=_int(payload.get("travelers"), 5),
            departure_airports=_split_list(payload.get("departure_airports")) or ["YYZ"],
            budget_cad=_float_or_none(payload.get("budget_cad")),
            max_travel_time_hours=_float_or_none(payload.get("max_travel_time_hours")),
            flight_preferences=FlightPreferenceInput(
                prefer_direct=bool(payload.get("prefer_direct", True))
            ),
            goals=_split_list(payload.get("goals")),
            avoidances=_split_list(payload.get("avoidances")),
            pace=TripPace(_normalise_enum(payload.get("pace"), "balanced")),
            crowd_tolerance=CrowdTolerance(_normalise_enum(payload.get("crowd_tolerance"), "low")),
            food_priority=FoodPriority(_normalise_enum(payload.get("food_priority"), "high")),
            lodging_preferences=LodgingPreferenceInput(
                notes=_optional_str(payload.get("lodging_notes"))
            ),
            car_rental_expectations=CarRentalExpectation(
                notes=_optional_str(payload.get("car_rental"))
            ),
            party=TripParty(
                party_type=TripPartyType(
                    _normalise_enum(payload.get("party_type"), "whole_family")
                ),
                adults=_int(payload.get("adults"), 2),
                children=_int(payload.get("children"), 3),
                child_ages=_int_list(payload.get("child_ages")),
                roster=_parse_roster(payload.get("roster")),
                explicit=True,
                defaulted_from_family_profile=False,
                sleeping_considerations=_optional_str(payload.get("sleeping_considerations")),
                separate_rooms_preferred=bool(payload.get("separate_rooms_preferred", False)),
                privacy_needs=_optional_str(payload.get("privacy_needs")),
                mobility_notes=_optional_str(payload.get("mobility_notes")),
                child_friendliness_notes=_optional_str(payload.get("child_friendliness_notes")),
            ),
            freeform_notes=_optional_str(payload.get("notes")),
        )
        saved = self._intakes.create(intake, overwrite=bool(payload.get("overwrite", False)))
        workflow = self._record_workflow(
            workflow_name="ui-trip-intake",
            trip_id=saved.trip_id,
            summary=f"Created UI intake for {saved.trip_name}",
            result=saved.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "intake": saved.model_dump(mode="json"),
            "next_step": f"Draft plan options for {saved.trip_id}.",
        }

    def draft_plan(self, trip_id: str) -> dict[str, Any]:
        draft = self._planner.draft(trip_id)
        workflow = self._record_workflow(
            workflow_name="ui-trip-plan-draft",
            skill_name="trippy-family-itinerary-builder",
            trip_id=trip_id,
            summary=f"Generated {len(draft.options)} UI plan option(s)",
            result=draft.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "draft": draft.model_dump(mode="json"),
            "next_step": f"Pick a plan option for {trip_id}.",
        }

    def select_plan(self, trip_id: str, option_id: str) -> dict[str, Any]:
        draft = self._planner.select_option(trip_id, option_id)
        workflow = self._record_workflow(
            workflow_name="ui-trip-plan-select",
            trip_id=trip_id,
            summary=f"Selected UI plan option {option_id}",
            result=draft.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "draft": draft.model_dump(mode="json"),
            "next_step": "Generate exact shortlists and prepare the workspace.",
        }

    def build_shortlist(
        self,
        trip_id: str,
        category: str,
        *,
        validate_live: bool = False,
        deep_research: bool = False,
        adapter: str = "auto",
    ) -> dict[str, Any]:
        shortlist_category = ShortlistCategory(category)
        if shortlist_category == ShortlistCategory.FLIGHTS:
            state = FlightShortlistService(self._intakes, self._planner).build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            skill_name = "trippy-flight-friction-audit"
        elif shortlist_category == ShortlistCategory.LODGING:
            state = LodgingShortlistService(self._intakes, self._planner).build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            skill_name = "trippy-family-itinerary-builder"
        elif shortlist_category == ShortlistCategory.CARS:
            state = CarShortlistService(self._intakes, self._planner).build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            skill_name = "trippy-family-itinerary-builder"
        else:
            state = ActivityShortlistService(self._intakes, self._planner).build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            skill_name = "trippy-family-itinerary-builder"
        workflow = self._record_workflow(
            workflow_name=f"ui-trip-plan-{shortlist_category.value}",
            skill_name=skill_name,
            trip_id=trip_id,
            summary=(
                f"Generated {shortlist_category.value} shortlist from UI"
                + (" with deep source research" if deep_research else "")
            ),
            result=state.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "shortlist": state.model_dump(mode="json"),
            "next_step": _next_after_shortlist(shortlist_category.value),
        }

    def add_lodging_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        trip_id = _trip_id(payload)
        state = LodgingShortlistService(self._intakes, self._planner).add_candidate(
            trip_id,
            link=str(payload.get("link") or ""),
            notes=str(payload.get("notes") or ""),
            name=str(payload.get("name") or ""),
            validate_live=bool(payload.get("validate_live", False)),
            deep_research=bool(payload.get("deep_research", False)),
            adapter_mode=str(payload.get("adapter") or "auto"),
        )
        workflow = self._record_workflow(
            workflow_name="ui-trip-plan-lodging-candidate",
            skill_name="trippy-family-itinerary-builder",
            trip_id=trip_id,
            summary="Added user-supplied lodging candidate for comparison",
            result=state.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "shortlist": state.model_dump(mode="json"),
            "next_step": "Compare the user candidate against sourced lodging options.",
        }

    def add_flight_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        trip_id = _trip_id(payload)
        state = FlightShortlistService(self._intakes, self._planner).add_candidate(
            trip_id,
            link=str(payload.get("link") or ""),
            notes=str(payload.get("notes") or ""),
            name=str(payload.get("name") or ""),
            validate_live=bool(payload.get("validate_live", False)),
            deep_research=bool(payload.get("deep_research", False)),
            adapter_mode=str(payload.get("adapter") or "auto"),
        )
        workflow = self._record_workflow(
            workflow_name="ui-trip-plan-flight-candidate",
            skill_name="trippy-flight-friction-audit",
            trip_id=trip_id,
            summary="Added user-supplied flight candidate for comparison",
            result=state.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "shortlist": state.model_dump(mode="json"),
            "next_step": "Compare the user flight candidate against sourced flight options.",
        }

    def select_flight(self, payload: dict[str, Any]) -> dict[str, Any]:
        trip_id = _trip_id(payload)
        option_id = str(payload.get("option_id") or "")
        state = FlightShortlistService(self._intakes, self._planner).select_flight(
            trip_id,
            option_id,
        )
        workflow = self._record_workflow(
            workflow_name="ui-trip-plan-flight-select",
            skill_name="trippy-flight-friction-audit",
            trip_id=trip_id,
            summary=f"Selected flight option {option_id} for planning",
            result=state.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "shortlist": state.model_dump(mode="json"),
            "next_step": "Review lodging check-in, car pickup, Master Timeline, and date-fit implications.",
        }

    def delete_trip(self, trip_id: str) -> dict[str, Any]:
        result = TripManagementService(
            intake_service=self._intakes,
            planner_service=self._planner,
        ).delete_trip(trip_id)
        workflow = self._record_workflow(
            workflow_name="ui-trip-delete",
            trip_id=trip_id,
            summary=f"Deleted local planning artifacts for {trip_id}",
            result=result,
        )
        return {
            "workflow_id": workflow.id,
            "deletion": result,
            "next_step": "Trip removed from the local planning UI.",
        }

    def build_workspace(
        self,
        trip_id: str,
        *,
        create_google_sheet: bool = False,
        validate_live: bool = False,
    ) -> dict[str, Any]:
        state = TripWorkspaceService(self._intakes, self._planner).prepare(
            trip_id,
            create_google_sheet=create_google_sheet,
            validate_live=validate_live,
        )
        status = (
            WorkflowStatus.FAILED
            if state.status.value == "sheet_failed"
            else WorkflowStatus.SUCCESS
        )
        workflow = self._record_workflow(
            workflow_name="ui-trip-plan-workspace",
            skill_name="trippy-trip-sheet-creator",
            trip_id=trip_id,
            summary=f"Prepared UI planning workspace for {trip_id}",
            result=state.model_dump(mode="json"),
            status=status,
        )
        return {
            "workflow_id": workflow.id,
            "workspace": state.model_dump(mode="json"),
            "next_step": "Review the Master Timeline, Risks, Maps, and best current options.",
        }

    def build_map(self, trip_id: str) -> dict[str, Any]:
        artifact = TripMapBuilder(self._intakes, self._planner).write_artifacts(
            trip_id,
            config.EXPORT_PATH / "maps",
        )
        workflow = self._record_workflow(
            workflow_name="ui-trip-map-build",
            trip_id=trip_id,
            summary=f"Generated UI map artifacts for {trip_id}",
            result=artifact.model_dump(mode="json"),
        )
        return {
            "workflow_id": workflow.id,
            "map": artifact.model_dump(mode="json"),
            "next_step": "Open the map links from the dashboard or planning workspace.",
        }

    def add_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(payload.get("workflow_id") or "")
        if not workflow_id:
            raise ValueError("workflow_id is required")
        feedback = UserFeedback(
            workflow_id=workflow_id,
            rating=FeedbackRating(str(payload.get("rating") or "helpful")),
            notes=str(payload.get("notes") or "").strip(),
            correction=_optional_str(payload.get("correction")),
            future_learning=bool(payload.get("future_learning", False)),
        )
        proposals = self._learning.add_feedback(feedback)
        return {
            "feedback": feedback.model_dump(mode="json"),
            "learning_proposals": [proposal.model_dump(mode="json") for proposal in proposals],
            "next_step": _feedback_next_step(feedback),
        }

    def record_ui_error(
        self,
        *,
        path: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._learning.record_event(
            "ui_error",
            {
                "path": path,
                "message": message,
                "trip_id": str((payload or {}).get("trip_id") or "") or None,
                "workflow_id": str((payload or {}).get("workflow_id") or "") or None,
                "category": str((payload or {}).get("category") or "") or None,
                "payload_keys": sorted((payload or {}).keys()),
            },
        )

    def _record_workflow(
        self,
        *,
        workflow_name: str,
        summary: str,
        result: dict[str, Any],
        trip_id: str | None = None,
        skill_name: str | None = None,
        status: WorkflowStatus = WorkflowStatus.SUCCESS,
    ) -> WorkflowOutcome:
        return self._learning.record_workflow(
            WorkflowOutcome(
                workflow_name=workflow_name,
                skill_name=skill_name,
                trip_id=trip_id,
                status=status,
                summary=summary,
                artifacts={"ui": True},
                quality_notes=[summary],
                metrics=_metrics_for_result(result),
            )
        )


class TrippyUIHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local Trippy UI."""

    server_version = "TrippyUI/0.1"

    def __init__(
        self,
        *args: Any,
        ui_service: TrippyUIService,
        static_dir: Path,
        template_dir: Path,
        **kwargs: Any,
    ) -> None:
        self._ui = ui_service
        self._static_dir = static_dir
        self._template_dir = template_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path in {"/", "/index.html"}:
                self._send_file(self._template_dir / "index.html")
                return
            if path == "/favicon.ico":
                self._send_file(self._static_dir / "trippy-logo.png")
                return
            if path == "/api/state":
                self._send_json(self._ui.app_state())
                return
            if path == "/api/logs":
                query = parse_qs(urlparse(self.path).query)
                trip_id = query.get("trip_id", [""])[0] or None
                limit = _int(query.get("limit", ["50"])[0], 50)
                self._send_json(self._ui.logs(trip_id=trip_id, limit=limit))
                return
            if path == "/api/trip":
                query = parse_qs(urlparse(self.path).query)
                trip_id = query.get("trip_id", [""])[0]
                if not trip_id:
                    self._send_error("trip_id is required", HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(self._ui.trip_state(trip_id))
                return
            if path.startswith("/static/"):
                self._send_static(path.removeprefix("/static/"))
                return
            self._send_error("Not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pragma: no cover - exercised through manual UI use
            self._ui.record_ui_error(path=path, message=str(exc))
            self._send_error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload: dict[str, Any] = {}
        try:
            payload = self._read_json()
            if path == "/api/intake":
                self._send_json(self._ui.create_intake(payload))
                return
            if path == "/api/suggest-ideas":
                self._send_json(self._ui.suggest_ideas(payload))
                return
            if path == "/api/draft":
                self._send_json(self._ui.draft_plan(_trip_id(payload)))
                return
            if path == "/api/select":
                self._send_json(
                    self._ui.select_plan(_trip_id(payload), str(payload.get("option_id") or ""))
                )
                return
            if path == "/api/shortlist":
                self._send_json(
                    self._ui.build_shortlist(
                        _trip_id(payload),
                        str(payload.get("category") or ""),
                        validate_live=bool(payload.get("validate_live", False)),
                        deep_research=bool(payload.get("deep_research", False)),
                        adapter=str(payload.get("adapter") or "auto"),
                    )
                )
                return
            if path == "/api/lodging-candidate":
                self._send_json(self._ui.add_lodging_candidate(payload))
                return
            if path == "/api/flight-candidate":
                self._send_json(self._ui.add_flight_candidate(payload))
                return
            if path == "/api/select-flight":
                self._send_json(self._ui.select_flight(payload))
                return
            if path == "/api/workspace":
                self._send_json(
                    self._ui.build_workspace(
                        _trip_id(payload),
                        create_google_sheet=bool(payload.get("create_google_sheet", False)),
                        validate_live=bool(payload.get("validate_live", False)),
                    )
                )
                return
            if path == "/api/map":
                self._send_json(self._ui.build_map(_trip_id(payload)))
                return
            if path == "/api/feedback":
                self._send_json(self._ui.add_feedback(payload))
                return
            if path == "/api/delete-trip":
                self._send_json(self._ui.delete_trip(_trip_id(payload)))
                return
            self._send_error("Not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._ui.record_ui_error(path=path, message=str(exc), payload=payload)
            self._send_error(str(exc), HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON request body must be an object")
        return data

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "text/html")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, relative: str) -> None:
        candidate = (self._static_dir / relative).resolve()
        static_root = self._static_dir.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self._send_error("Invalid static path", HTTPStatus.BAD_REQUEST)
            return
        if not candidate.exists() or not candidate.is_file():
            self._send_error("Static file not found", HTTPStatus.NOT_FOUND)
            return
        self._send_file(candidate)


def serve_ui(host: str = "127.0.0.1", port: int = 8787, *, open_browser: bool = True) -> None:
    """Serve the local Trippy UI until interrupted."""
    service = TrippyUIService()
    handler = partial(
        TrippyUIHandler,
        ui_service=service,
        static_dir=STATIC_DIR,
        template_dir=TEMPLATE_DIR,
    )
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}"
    print(f"Trippy UI running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Trippy UI.")
    finally:
        server.server_close()


def _workflow_trip_index(events: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for event in events:
        if event.get("event_type") != "workflow_outcome":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        workflow_id = _optional_str(payload.get("id"))
        trip_id = _optional_str(payload.get("trip_id"))
        if workflow_id and trip_id:
            index[workflow_id] = trip_id
    return index


def _load_map_artifact(trip_id: str) -> dict[str, Any] | None:
    path = config.EXPORT_PATH / "maps" / f"{trip_id}-planning-map.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _event_summary(event: dict[str, Any], workflow_trip_ids: dict[str, str]) -> dict[str, Any]:
    payload_obj = event.get("payload")
    payload: dict[str, Any] = payload_obj if isinstance(payload_obj, dict) else {}
    event_type = str(event.get("event_type") or "event")
    workflow_id = _optional_str(
        payload.get("id")
        if event_type == "workflow_outcome"
        else payload.get("workflow_id") or payload.get("source_workflow_id")
    )
    trip_id = _optional_str(payload.get("trip_id"))
    if not trip_id and workflow_id:
        trip_id = workflow_trip_ids.get(workflow_id)
    summary: dict[str, Any] = {
        "event_id": str(event.get("event_id") or ""),
        "event_type": event_type,
        "created_at": str(event.get("created_at") or ""),
        "trip_id": trip_id,
        "workflow_id": workflow_id,
        "proposal_id": _optional_str(payload.get("id"))
        if event_type.startswith("learning")
        else None,
        "status": _optional_str(payload.get("status")) or _status_for_event(event_type, payload),
        "title": _title_for_event(event_type, payload),
        "summary": _summary_for_event(event_type, payload),
        "metrics": payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
        "path": _optional_str(payload.get("path")),
        "severity": _severity_for_event(event_type, payload),
    }
    return summary


def _title_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "workflow_outcome":
        return str(payload.get("workflow_name") or "Workflow")
    if event_type == "user_feedback":
        return f"Feedback: {payload.get('rating') or 'unrated'}"
    if event_type.startswith("learning_proposal"):
        return f"Learning proposal: {payload.get('proposal_type') or 'proposal'}"
    if event_type == "ui_error":
        return f"UI error: {payload.get('path') or 'request'}"
    return event_type.replace("_", " ").title()


def _summary_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "workflow_outcome":
        return _compact_text(payload.get("summary"))
    if event_type == "user_feedback":
        notes = _compact_text(payload.get("notes"))
        correction = _compact_text(payload.get("correction"))
        return correction or notes or "Feedback recorded."
    if event_type.startswith("learning_proposal"):
        return _compact_text(payload.get("summary"))
    if event_type == "ui_error":
        return _compact_text(payload.get("message"))
    return _compact_text(payload)


def _status_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "user_feedback":
        return str(payload.get("rating") or "feedback")
    if event_type == "ui_error":
        return "error"
    if event_type.startswith("learning_proposal"):
        return str(payload.get("status") or "pending")
    return "recorded"


def _severity_for_event(event_type: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").lower()
    if event_type == "ui_error" or status == "failed":
        return "error"
    if event_type == "user_feedback":
        rating = str(payload.get("rating") or "").lower()
        return "ok" if rating == "helpful" else "warn"
    if event_type.startswith("learning_proposal"):
        return "proposal"
    return "ok"


def _compact_text(value: object, limit: int = 220) -> str:
    text = json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value or "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."


def _split_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(str(item).replace("\n", ",").split(","))
    else:
        parts = [str(value)]
    return [part.strip() for part in parts if part.strip()]


def _int(value: object, default: int) -> int:
    try:
        if value in (None, ""):
            return default
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _int_or_none(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _int_list(value: object) -> list[int]:
    ages: list[int] = []
    for item in _split_list(value):
        try:
            ages.append(int(item))
        except ValueError:
            continue
    return ages


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _normalise_enum(value: object, default: str) -> str:
    raw = str(value or default).strip().lower()
    return raw.replace("-", "_").replace(" ", "_")


def _parse_roster(value: object) -> list[TripTraveler]:
    travelers: list[TripTraveler] = []
    for item in _split_list(value):
        parts = [part.strip() for part in item.split("|")]
        name = parts[0]
        age: int | None = None
        age_band: TravelerAgeBand | None = None
        if len(parts) > 1 and parts[1]:
            if parts[1].isdigit():
                age = int(parts[1])
            else:
                age_band = TravelerAgeBand(_normalise_enum(parts[1], "adult"))
        travelers.append(TripTraveler(name=name, age=age, age_band=age_band))
    return travelers


def _trip_id(payload: dict[str, Any]) -> str:
    trip_id = str(payload.get("trip_id") or "").strip()
    if not trip_id:
        raise ValueError("trip_id is required")
    return trip_id


def _metrics_for_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if "options" in result:
        metrics["options"] = len(result.get("options") or [])
    if "concepts" in result:
        metrics["concepts"] = len(result.get("concepts") or [])
    for key in ("flight_options", "lodging_options", "car_options", "activity_options"):
        if key in result:
            metrics[key] = len(result.get(key) or [])
    return metrics


def _suggested_trip_id(dashboard: dict[str, Any], intakes: list[TripIntake]) -> str | None:
    planned = dashboard.get("planned_trips") or []
    if planned:
        return str(planned[0].get("trip_id") or "")
    if intakes:
        return intakes[-1].trip_id
    return None


def _next_step_for_state(
    has_intake: bool,
    has_draft: bool,
    has_selection: bool,
    shortlist_categories: set[str],
    has_workspace: bool,
) -> str:
    if not has_intake:
        return "Create a trip intake."
    if not has_draft:
        return "Generate plan options."
    if not has_selection:
        return "Select the best plan option."
    missing = [
        category
        for category in ("flights", "lodging", "cars", "activities")
        if category not in shortlist_categories
    ]
    if missing:
        return f"Research {missing[0]} next."
    if not has_workspace:
        return "Prepare the planning workspace."
    return "Review the timeline, risks, maps, and feedback proposals."


def _next_after_shortlist(category: str) -> str:
    order = ["flights", "lodging", "cars", "activities"]
    try:
        index = order.index(category)
    except ValueError:
        return "Continue exact research."
    if index + 1 < len(order):
        return f"Research {order[index + 1]} next."
    return "Prepare the workspace and map output."


def _feedback_next_step(feedback: UserFeedback) -> str:
    if feedback.rating == FeedbackRating.HELPFUL:
        return "Continue to the next planning stage."
    if feedback.future_learning:
        return "Review the generated learning proposal before applying it."
    return "Use the correction to rerun or adjust this stage before moving on."
