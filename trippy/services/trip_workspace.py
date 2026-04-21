"""Create the planning workspace for a selected trip plan."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from trippy.memory.profile_manager import ProfileManager
from trippy.memory.store import MemoryStore
from trippy.models.trip import (
    Budget,
    ChecklistItem,
    RiskFlag,
    RiskSeverity,
    Segment,
    SegmentType,
    Stay,
    StayType,
    SyncMetadata,
    Traveler,
    Trip,
    TripStatus,
)
from trippy.models.trip_planning import (
    TripIntake,
    TripPlanDraft,
    TripPlanOption,
    TripWorkspaceState,
    WorkspaceStatus,
    WorkspaceTab,
)
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService
from trippy.services.trip_state import TripStateService


class TripWorkspaceService:
    """Prepare local and Google Sheet planning workspaces from a chosen plan option."""

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        trip_state: TripStateService | None = None,
        workspaces_dir: Path | None = None,
        auth_manager: Any | None = None,
    ) -> None:
        from trippy import config

        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._trip_state = trip_state or TripStateService()
        self._dir = workspaces_dir or config.WORKSPACES_PATH
        self._auth_manager = auth_manager

    def prepare(
        self,
        trip_id: str,
        *,
        option_id: str | None = None,
        create_google_sheet: bool = True,
        folder_id: str | None = None,
        validate_live: bool | None = None,
    ) -> TripWorkspaceState:
        intake = self._intakes.require(trip_id)
        draft = self._planner.require_draft(trip_id)
        option, draft, warnings = self._resolve_option(draft, option_id)
        trip = self._build_canonical_trip(intake, option)
        canonical_path = self._trip_state.save(trip)
        tabs = self._build_tabs(intake, draft, option, trip, validate_live=validate_live)

        state = TripWorkspaceState(
            trip_id=trip_id,
            plan_option_id=option.option_id,
            status=WorkspaceStatus.PREPARED_LOCAL,
            canonical_trip_path=str(canonical_path),
            tabs=tabs,
            warnings=warnings,
            next_actions=[
                "Review the selected planning shape and confirm the island sequence.",
                "Research exact flights, lodging, car, and tours using the workspace tabs.",
                f"Build maps with: uv run trippy trip-map build --trip-id {trip_id}",
            ],
        )

        if create_google_sheet:
            sheet = self._try_create_google_sheet(trip, tabs, folder_id=folder_id)
            if sheet.get("spreadsheet_id"):
                state.status = WorkspaceStatus.SHEET_CREATED
                state.google_sheet_id = str(sheet["spreadsheet_id"])
                state.google_sheet_url = str(sheet.get("url", ""))
                state.warnings.extend(str(item) for item in sheet.get("partial_failures", []))
                trip.sync = SyncMetadata(
                    google_sheet_id=state.google_sheet_id,
                    google_sheet_url=state.google_sheet_url,
                    last_synced_at=datetime.utcnow(),
                    last_synced_by="trip-workspace",
                )
                self._trip_state.save(trip)
                state.next_actions.insert(0, "Open the generated Google Sheet planning workspace.")
            else:
                state.status = WorkspaceStatus.SHEET_FAILED
                error = str(sheet.get("error", "Google Sheet was not created."))
                state.warnings.append(error)
                state.next_actions.insert(
                    0, "Run trippy doctor and trippy auth-google, then retry workspace creation."
                )
        else:
            state.next_actions.insert(
                0, "Google Sheet creation skipped; local workspace JSON was prepared."
            )

        self._save_workspace_state(state)
        return state

    def load(self, trip_id: str) -> TripWorkspaceState | None:
        path = self._path(trip_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return TripWorkspaceState.model_validate(data)

    def path_for(self, trip_id: str) -> Path:
        return self._path(trip_id)

    def _path(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.workspace.json"

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save_workspace_state(self, state: TripWorkspaceState) -> None:
        self._ensure_dir()
        state.updated_at = datetime.utcnow()
        path = self._path(state.trip_id)
        state.local_workspace_path = str(path)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def _resolve_option(
        self,
        draft: TripPlanDraft,
        option_id: str | None,
    ) -> tuple[TripPlanOption, TripPlanDraft, list[str]]:
        warnings: list[str] = []
        if option_id:
            draft = self._planner.select_option(draft.trip_id, option_id)
        option = draft.get_option(option_id)
        if option is None:
            raise ValueError(f"No selected or recommended plan option for trip {draft.trip_id!r}")
        if draft.selected_option_id is None:
            warnings.append(
                f"No explicit option approval found; using recommended option {option.option_id!r}."
            )
        return option, draft, warnings

    def _build_canonical_trip(self, intake: TripIntake, option: TripPlanOption) -> Trip:
        start = intake.travel_window.start_date
        end = (
            start + timedelta(days=option.duration_days - 1)
            if start
            else intake.travel_window.end_date
        )
        travelers = _travelers_for_intake(intake)
        segments = _placeholder_segments(intake, option)
        stays = _placeholder_stays(intake, option, start)
        checklist = _workspace_checklist(option)
        budgets = _workspace_budgets(intake)
        risks = _risk_flags(option)

        return Trip(
            trip_id=intake.trip_id,
            name=intake.trip_name,
            status=TripStatus.PLANNED,
            destination_summary=", ".join([*intake.destination_seeds, *option.regions]),
            start_date=start,
            end_date=end,
            travelers=travelers,
            segments=segments,
            stays=stays,
            checklist=checklist,
            budgets=budgets,
            risk_flags=risks,
            notes="\n".join(
                [
                    f"Selected plan option: {option.title}",
                    option.summary,
                    *(intake.freeform_notes.splitlines() if intake.freeform_notes else []),
                ]
            ),
        )

    def _build_tabs(
        self,
        intake: TripIntake,
        draft: TripPlanDraft,
        option: TripPlanOption,
        trip: Trip,
        *,
        validate_live: bool | None = None,
    ) -> list[WorkspaceTab]:
        shortlists = _load_or_build_shortlists(
            intake.trip_id,
            self._intakes,
            self._planner,
            validate_live=validate_live,
        )
        map_artifact = _build_planning_map(intake.trip_id, self._intakes, self._planner)
        return [
            WorkspaceTab(
                name="Overview",
                headers=["Field", "Value"],
                rows=_overview_rows(intake, option, shortlists, trip),
            ),
            WorkspaceTab(
                name="Master Timeline",
                headers=[
                    "Day",
                    "Date",
                    "Start Time",
                    "End Time",
                    "Duration",
                    "Event Type",
                    "Title",
                    "Location / Area",
                    "From",
                    "To",
                    "Provider / Confirmation",
                    "Status",
                    "Fixed vs Flexible",
                    "Travel Time",
                    "Buffer Before",
                    "Buffer After",
                    "Friction Flags",
                    "Confidence",
                    "Notes",
                    "Link",
                ],
                rows=_timeline_rows(intake, option, shortlists),
            ),
            WorkspaceTab(
                name="Plan Options",
                headers=["Option ID", "Title", "Strength", "Comfort", "Movement", "Summary"],
                rows=[
                    [
                        plan.option_id,
                        plan.title,
                        plan.recommendation_strength,
                        plan.family_comfort_score,
                        plan.island_region_movement_friction,
                        plan.summary,
                    ]
                    for plan in draft.options
                ],
            ),
            WorkspaceTab(
                name="Flights",
                headers=[
                    "Rank",
                    "Status",
                    "Recommended",
                    "Airline",
                    "Route",
                    "Stops",
                    "Layovers",
                    "Total Duration",
                    "Price Band",
                    "Source",
                    "Traveler Fit",
                    "Friction Score",
                    "Rationale / Notes",
                    "Deep Link",
                    "Verification",
                    "Freshness",
                    "Availability",
                    "Confidence",
                    "Missing / Uncertain",
                ],
                rows=_flight_rows(shortlists.get("flights")),
            ),
            WorkspaceTab(
                name="Lodging",
                headers=[
                    "Rank",
                    "Status",
                    "Recommended",
                    "Property",
                    "Source",
                    "Area",
                    "Type",
                    "Room / Unit",
                    "Bed Layout",
                    "Traveler Fit",
                    "3-Bed Fit",
                    "King Fit",
                    "Privacy Fit",
                    "Parking",
                    "Walkability",
                    "Price Band",
                    "Friction Score",
                    "Rationale / Notes",
                    "Deep Link",
                    "Verification",
                    "Freshness",
                    "Availability",
                    "Confidence",
                    "Fit Category",
                    "Missing / Uncertain",
                ],
                rows=_lodging_rows(shortlists.get("lodging")),
            ),
            WorkspaceTab(
                name="Cars",
                headers=[
                    "Rank",
                    "Status",
                    "Recommended",
                    "Source",
                    "Pickup",
                    "Dropoff",
                    "Vehicle Class",
                    "Seats",
                    "Passenger Fit",
                    "Luggage Fit",
                    "Cancellation",
                    "Fee Caution",
                    "Friction Score",
                    "Rationale / Notes",
                    "Deep Link",
                    "Verification",
                    "Freshness",
                    "Availability",
                    "Confidence",
                    "Missing / Uncertain",
                ],
                rows=_car_rows(shortlists.get("cars")),
            ),
            WorkspaceTab(
                name="Activities",
                headers=[
                    "Rank",
                    "Status",
                    "Recommended",
                    "Activity",
                    "Area",
                    "Source",
                    "Duration",
                    "Traveler Fit",
                    "Group Size",
                    "Review / Safety",
                    "Price Band",
                    "Pace Fit",
                    "Friction Score",
                    "Rationale / Notes",
                    "Deep Link",
                    "Verification",
                    "Freshness",
                    "Availability",
                    "Confidence",
                    "Missing / Uncertain",
                ],
                rows=_activity_rows(shortlists.get("activities")),
            ),
            WorkspaceTab(
                name="Logistics",
                headers=["Area", "Question", "Status", "Notes"],
                rows=[
                    [
                        "Entry",
                        "Portugal/Schengen entry requirements",
                        "seeded",
                        "Check passport validity and any ETIAS timing.",
                    ],
                    [
                        "Health",
                        "Vaccines/precautions",
                        "seeded",
                        "Add weather and motion-sickness backup planning.",
                    ],
                    [
                        "Cash",
                        "Local currency guidance",
                        "seeded",
                        "Estimate euros to carry for small vendors, parking, tips, and markets.",
                    ],
                    [
                        "Inter-island",
                        "Schedule buffers",
                        "seeded",
                        option.island_region_movement_friction,
                    ],
                ],
            ),
            WorkspaceTab(
                name="Maps",
                headers=["Item", "Category", "Status", "Notes", "Link"],
                rows=_map_rows(map_artifact, shortlists),
            ),
            WorkspaceTab(
                name="Risks",
                headers=["Risk", "Severity", "Status", "Mitigation / Notes", "Source"],
                rows=_risk_rows(trip, shortlists),
            ),
        ]

    def _try_create_google_sheet(
        self,
        trip: Trip,
        tabs: list[WorkspaceTab],
        *,
        folder_id: str | None,
    ) -> dict[str, Any]:
        from trippy import config
        from trippy.ingest.google_auth import DRIVE_SCOPES, SHEETS_SCOPES, missing_required_scopes

        missing = (
            missing_required_scopes(config.GOOGLE_TOKEN_PATH, SHEETS_SCOPES + DRIVE_SCOPES)
            if self._auth_manager is None
            else set()
        )
        if missing:
            return {
                "error": (
                    "Google token is missing write-capable Sheets/Drive scopes: "
                    + ", ".join(sorted(missing))
                    + ". Run `uv run trippy auth-google --force`."
                )
            }

        partial_failures: list[str] = []
        try:
            auth = self._auth_manager
            if auth is None:
                from trippy.ingest.google_auth import GoogleAuthManager

                auth = GoogleAuthManager()
            service = auth.build_service("sheets", "v4")
            title = f"Trippy - {trip.name}"
            resp = (
                service.spreadsheets()
                .create(
                    body={
                        "properties": {"title": title},
                        "sheets": [{"properties": {"title": tab.name}} for tab in tabs],
                    }
                )
                .execute()
            )
            sheet_id = str(resp["spreadsheetId"])
            url = str(
                resp.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sheet_id}")
            )

            updates = [
                {"range": f"{_sheet_tab_name(tab.name)}!A1", "values": [tab.headers, *tab.rows]}
                for tab in tabs
            ]
            try:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=sheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": updates},
                ).execute()
            except Exception as exc:
                partial_failures.append(f"Sheet was created but tab values failed: {exc}")

            try:
                meta = (
                    service.spreadsheets()
                    .get(
                        spreadsheetId=sheet_id,
                        fields="sheets.properties(sheetId,title)",
                    )
                    .execute()
                )
                sheet_ids = {
                    str(sheet["properties"]["title"]): int(sheet["properties"]["sheetId"])
                    for sheet in meta.get("sheets", [])
                }
                service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id,
                    body={"requests": _sheet_formatting_requests(tabs, sheet_ids)},
                ).execute()
            except Exception as exc:
                partial_failures.append(f"Sheet values were written but formatting failed: {exc}")

            if folder_id:
                try:
                    drive = auth.build_service("drive", "v3")
                    meta = drive.files().get(fileId=sheet_id, fields="parents").execute()
                    previous = ",".join(meta.get("parents", []))
                    drive.files().update(
                        fileId=sheet_id,
                        addParents=folder_id,
                        removeParents=previous,
                        fields="id,parents",
                    ).execute()
                except Exception as exc:
                    partial_failures.append(
                        f"Sheet was created but Drive folder move failed: {exc}"
                    )

            return {"spreadsheet_id": sheet_id, "url": url, "partial_failures": partial_failures}
        except Exception as exc:
            return {"error": str(exc)}


def _travelers_for_intake(intake: TripIntake) -> list[Traveler]:
    from trippy import config

    if intake.party.roster:
        return [
            Traveler(
                name=traveler.name,
                is_minor=bool(traveler.is_child),
            )
            for traveler in intake.party.roster
        ]
    try:
        profile = ProfileManager(MemoryStore(config.MEMORY_PATH)).load()
    except Exception:
        profile = None
    if profile and profile.travelers:
        return [
            Traveler(
                name=traveler.name,
                passport_country=traveler.passport_country,
                passport_expiry=traveler.passport_expiry,
                date_of_birth=traveler.date_of_birth,
                is_minor=traveler.is_minor,
                dietary_notes=traveler.dietary_notes,
                loyalty_numbers=traveler.loyalty_numbers,
            )
            for traveler in profile.travelers[: intake.party.total_travelers]
        ]
    return [
        Traveler(name=label, is_minor=label.startswith("Child "))
        for label in intake.party.traveler_labels()
    ]


def _placeholder_segments(intake: TripIntake, option: TripPlanOption) -> list[Segment]:
    origin = intake.departure_airports[0] if intake.departure_airports else "YYZ"
    return [
        Segment(
            segment_id="flight-outbound-research",
            segment_type=SegmentType.FLIGHT,
            origin=origin,
            destination="PDL",
            confirmation_code="UNCONFIRMED",
            notes=f"Research outbound for {option.title}; prefer direct or sane one-stop.",
        ),
        Segment(
            segment_id="flight-return-research",
            segment_type=SegmentType.FLIGHT,
            origin="PDL",
            destination=origin,
            confirmation_code="UNCONFIRMED",
            notes="Research return with family-friendly departure time and baggage/seat clarity.",
        ),
    ]


def _placeholder_stays(
    intake: TripIntake,
    option: TripPlanOption,
    start: date | None,
) -> list[Stay]:
    stays: list[Stay] = []
    cursor = start
    for idx, (region, nights) in enumerate(option.nights_by_region.items(), start=1):
        check_in = cursor
        check_out = cursor + timedelta(days=nights) if cursor else None
        stay_type = StayType.AIRBNB if len(option.regions) <= 2 else StayType.HOTEL
        stays.append(
            Stay(
                stay_id=f"stay-research-{idx}",
                stay_type=stay_type,
                property_name=f"{region} lodging shortlist",
                city=region,
                country="Portugal",
                check_in=check_in,
                check_out=check_out,
                confirmation_code="UNCONFIRMED",
                room_type=f"{intake.party.summary()}, 3+ beds if applicable, king preferred",
                notes=option.lodging_strategy,
            )
        )
        cursor = check_out
    return stays


def _workspace_checklist(option: TripPlanOption) -> list[ChecklistItem]:
    items = [
        ("booking", "Research exact outbound and return flights"),
        ("booking", "Shortlist lodging with 3+ beds and safe/practical location"),
        ("booking", "Validate car rental fit, luggage capacity, pickup/dropoff, and cancellation"),
        ("booking", "Research small-group tours and activity safety/review signals"),
        ("logistics", "Validate island movement sequence and schedule buffers"),
        ("document", "Check Portugal/Schengen entry requirements and passport validity"),
        ("health", "Check destination health precautions and motion-sickness/weather backups"),
        ("money", "Estimate euros to carry for parking, markets, tips, and small vendors"),
        ("maps", "Build trip map artifacts and link them from the workspace"),
    ]
    return [
        ChecklistItem(item_id=f"plan-{idx:02d}", category=category, title=title)
        for idx, (category, title) in enumerate(
            items + [("risk", risk) for risk in option.major_risks], start=1
        )
    ]


def _workspace_budgets(intake: TripIntake) -> list[Budget]:
    total = intake.budget_cad
    if total is None:
        return [
            Budget(category="flights"),
            Budget(category="lodging"),
            Budget(category="cars"),
            Budget(category="activities"),
            Budget(category="food"),
            Budget(category="total"),
        ]
    return [
        Budget(category="flights", budgeted_cad=round(total * 0.35, 2)),
        Budget(category="lodging", budgeted_cad=round(total * 0.35, 2)),
        Budget(category="cars", budgeted_cad=round(total * 0.08, 2)),
        Budget(category="activities", budgeted_cad=round(total * 0.10, 2)),
        Budget(category="food", budgeted_cad=round(total * 0.12, 2)),
        Budget(category="total", budgeted_cad=total),
    ]


def _risk_flags(option: TripPlanOption) -> list[RiskFlag]:
    return [
        RiskFlag(
            risk_id=f"plan-risk-{idx:02d}",
            severity=RiskSeverity.MEDIUM if idx <= 3 else RiskSeverity.LOW,
            category="planning",
            description=risk,
            recommended_fix="Resolve during flight/lodging/activity research before booking.",
        )
        for idx, risk in enumerate(option.major_risks, start=1)
    ]


def _load_or_build_shortlists(
    trip_id: str,
    intake_service: TripIntakeService,
    planner_service: TripPlannerService,
    *,
    validate_live: bool | None,
) -> dict[str, Any]:
    from trippy.models.shortlists import ShortlistCategory
    from trippy.services.activity_shortlist import ActivityShortlistService
    from trippy.services.car_shortlist import CarShortlistService
    from trippy.services.flight_shortlist import FlightShortlistService
    from trippy.services.live_validation import LiveValidationService
    from trippy.services.lodging_shortlist import LodgingShortlistService
    from trippy.services.shortlist_store import ShortlistStore

    store = ShortlistStore()
    validator = LiveValidationService()
    builders: dict[Any, Any] = {
        ShortlistCategory.FLIGHTS: FlightShortlistService(intake_service, planner_service, store),
        ShortlistCategory.LODGING: LodgingShortlistService(intake_service, planner_service, store),
        ShortlistCategory.CARS: CarShortlistService(intake_service, planner_service, store),
        ShortlistCategory.ACTIVITIES: ActivityShortlistService(
            intake_service, planner_service, store
        ),
    }
    states: dict[str, Any] = {}
    for category, builder in builders.items():
        state = store.load(trip_id, category)
        if state is None:
            state = builder.build(trip_id, validate_live=validate_live)
        elif validate_live:
            state = validator.validate_state(state, attempt_network=True)
            store.save(state)
        states[category.value] = state
    return states


def _build_planning_map(
    trip_id: str,
    intake_service: TripIntakeService,
    planner_service: TripPlannerService,
) -> Any:
    from trippy.services.trip_map_builder import TripMapBuilder

    return TripMapBuilder(intake_service, planner_service).build(trip_id)


def _overview_rows(
    intake: TripIntake,
    option: TripPlanOption,
    shortlists: dict[str, Any],
    trip: Trip,
) -> list[list[Any]]:
    best_flight = _recommended_option(shortlists.get("flights"))
    best_lodging = _recommended_option(shortlists.get("lodging"))
    best_car = _recommended_option(shortlists.get("cars"))
    activities = _top_options(shortlists.get("activities"), limit=3)
    unresolved = _unresolved_blockers(shortlists, trip)
    warnings = _top_workspace_warnings(trip, shortlists)
    return [
        ["Trip ID", intake.trip_id],
        ["Trip Name", intake.trip_name],
        ["Mode", intake.mode.value],
        ["Selected Option", f"{option.option_id} - {option.title}"],
        ["Selected Plan Summary", option.summary],
        ["Planning Completeness", f"{_workspace_completeness(shortlists, trip)}%"],
        ["Destination Seeds", ", ".join(intake.destination_seeds)],
        ["Travel Window", intake.travel_window.display()],
        ["Duration", intake.duration_display()],
        ["Travelers", intake.party.summary()],
        ["Traveler Roster", ", ".join(intake.party.traveler_labels())],
        ["Sleeping / Privacy", _party_lodging_notes(intake)],
        ["Departure Airports", ", ".join(intake.departure_airports)],
        ["Budget CAD", intake.budget_cad or ""],
        ["Goals", ", ".join(intake.goals)],
        ["Avoidances", ", ".join(intake.avoidances)],
        ["Pace", intake.pace.value],
        ["Crowd Tolerance", intake.crowd_tolerance.value],
        ["Food Priority", intake.food_priority.value],
        ["Best Flight", _option_summary(best_flight)],
        ["Best Lodging", _option_summary(best_lodging)],
        ["Best Car", _option_summary(best_car)],
        ["Best Activities", "; ".join(_option_summary(option) for option in activities)],
        ["Top Friction Warnings", "; ".join(warnings[:4])],
        ["Unresolved Blockers", "; ".join(unresolved[:5])],
        ["Next Actions", "; ".join(_workspace_next_actions(shortlists, trip)[:5])],
    ]


def _flight_rows(state: Any | None) -> list[list[Any]]:
    rows = []
    recommended_id = getattr(state, "recommended_option_id", None)
    for option in getattr(state, "flight_options", []):
        rows.append(
            [
                option.rank,
                option.row_status.value,
                _yes_no(option.option_id == recommended_id),
                option.airline,
                f"{option.departure_airport} to {option.arrival_airport}",
                option.stops,
                ", ".join(option.layover_airports) or "",
                option.total_travel_duration,
                option.price_band,
                option.booking_source,
                option.traveler_fit,
                option.friction_score,
                _notes(option.tradeoffs, option.friction_flags, option.confidence_notes),
                option.deep_link,
                option.validation.verification_status.value,
                option.validation.freshness_status.value,
                option.validation.availability_status.value,
                f"{option.validation.confidence:.0%}",
                ", ".join(option.validation.missing_fields),
            ]
        )
    return rows or [
        [
            "",
            "seeded",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Run trip-plan flights.",
            "",
            "",
            "",
            "",
            "",
        ]
    ]


def _lodging_rows(state: Any | None) -> list[list[Any]]:
    rows = []
    recommended_id = getattr(state, "recommended_option_id", None)
    for option in getattr(state, "lodging_options", []):
        rows.append(
            [
                option.rank,
                option.row_status.value,
                _yes_no(option.option_id == recommended_id),
                option.name,
                option.source,
                f"{option.location_area} / {option.island_or_region}",
                option.lodging_type,
                option.room_layout,
                option.bed_layout,
                option.adult_child_fit,
                _unknown_bool(option.min_three_beds_satisfied),
                _unknown_bool(option.king_bed_preference_satisfied),
                _unknown_bool(option.separate_room_privacy_fit),
                option.parking_practicality,
                option.walkability,
                option.price_band,
                option.friction_score,
                _notes(option.tradeoffs, option.friction_flags, option.confidence_notes),
                option.deep_link,
                option.validation.verification_status.value,
                option.validation.freshness_status.value,
                option.validation.availability_status.value,
                f"{option.validation.confidence:.0%}",
                option.fit_category.value,
                ", ".join(option.validation.missing_fields),
            ]
        )
    return rows or [
        [
            "",
            "seeded",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Run trip-plan lodging.",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    ]


def _car_rows(state: Any | None) -> list[list[Any]]:
    rows = []
    recommended_id = getattr(state, "recommended_option_id", None)
    for option in getattr(state, "car_options", []):
        rows.append(
            [
                option.rank,
                option.row_status.value,
                _yes_no(option.option_id == recommended_id),
                option.booking_source,
                option.pickup_location,
                option.dropoff_location,
                option.vehicle_class,
                option.seating_capacity or "",
                option.passenger_fit,
                option.luggage_fit,
                option.cancellation_notes,
                option.fees_caution,
                option.total_friction_score,
                _notes(option.tradeoffs, option.friction_flags, option.confidence_notes),
                option.deep_link,
                option.validation.verification_status.value,
                option.validation.freshness_status.value,
                option.validation.availability_status.value,
                f"{option.validation.confidence:.0%}",
                ", ".join(option.validation.missing_fields),
            ]
        )
    return rows or [
        [
            "",
            "seeded",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Run trip-plan cars.",
            "",
            "",
            "",
            "",
            "",
        ]
    ]


def _activity_rows(state: Any | None) -> list[list[Any]]:
    rows = []
    recommended_id = getattr(state, "recommended_option_id", None)
    for option in getattr(state, "activity_options", []):
        rows.append(
            [
                option.rank,
                option.row_status.value,
                _yes_no(option.option_id == recommended_id),
                option.activity_name,
                option.island_location,
                option.source,
                option.duration,
                option.age_family_fit,
                option.group_size_signal,
                option.review_safety_signal,
                option.price_band,
                option.family_pace_fit_score,
                option.total_friction_score,
                _notes(option.tradeoffs, option.friction_flags, option.confidence_notes),
                option.deep_link,
                option.validation.verification_status.value,
                option.validation.freshness_status.value,
                option.validation.availability_status.value,
                f"{option.validation.confidence:.0%}",
                ", ".join(option.validation.missing_fields),
            ]
        )
    return rows or [
        [
            "",
            "seeded",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Run trip-plan activities.",
            "",
            "",
            "",
            "",
            "",
        ]
    ]


def _map_rows(map_artifact: Any, shortlists: dict[str, Any]) -> list[list[Any]]:
    rows = [
        [pin.label, pin.category.value, "seeded", pin.notes, pin.google_maps_url]
        for pin in getattr(map_artifact, "pins", [])
    ]
    rows.extend(
        [route.label, "route", "seeded", route.notes, route.google_maps_url]
        for route in getattr(map_artifact, "routes", [])
    )
    for state in shortlists.values():
        recommended = _recommended_option(state)
        recommended_any: Any = recommended
        deep_link = str(getattr(recommended_any, "deep_link", ""))
        if recommended is not None and deep_link:
            rows.append(
                [
                    _option_summary(recommended),
                    f"{state.category.value} recommendation",
                    "recommended",
                    state.recommendation_summary,
                    deep_link,
                ]
            )
    return rows


def _risk_rows(trip: Trip, shortlists: dict[str, Any]) -> list[list[Any]]:
    rows = [
        [
            risk.description,
            risk.severity.value,
            "seeded",
            risk.recommended_fix or "",
            "selected plan",
        ]
        for risk in trip.risk_flags
    ]
    for state in shortlists.values():
        for warning in state.warnings:
            rows.append(
                [
                    warning,
                    "medium",
                    "researched",
                    state.recommendation_summary,
                    state.category.value,
                ]
            )
        for option in state.options_as_dicts():
            for flag in option.get("friction_flags", [])[:3]:
                rows.append(
                    [
                        flag,
                        "medium",
                        _row_status(state, str(option.get("option_id", ""))),
                        _notes(option.get("tradeoffs", []), option.get("confidence_notes", [])),
                        f"{state.category.value}:{option.get('option_id', '')}",
                    ]
                )
    return rows


def _timeline_rows(
    intake: TripIntake,
    option: TripPlanOption,
    shortlists: dict[str, Any],
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    start = intake.travel_window.start_date
    best_flight = _recommended_option(shortlists.get("flights"))
    best_car = _recommended_option(shortlists.get("cars"))
    best_lodging = _recommended_option(shortlists.get("lodging"))
    activities = _top_options(shortlists.get("activities"), limit=4)
    rows.append(
        _timeline_row(
            day=1,
            date_value=start,
            event_type="flight",
            title=_option_summary(best_flight) or "Outbound flight research",
            location=best_flight.arrival_airport
            if best_flight is not None
            else ", ".join(option.regions),
            from_value=", ".join(intake.departure_airports),
            to_value=best_flight.arrival_airport
            if best_flight is not None
            else "destination gateway",
            provider=getattr(best_flight, "booking_source", ""),
            status="recommended" if best_flight is not None else "seeded",
            fixed="flexible",
            travel_time=getattr(best_flight, "total_travel_duration", ""),
            buffer_after="same-day lodging/car buffer required",
            friction_flags=_combine_flags(
                getattr(best_flight, "friction_flags", []),
                ["arrival/check-in timing unverified", "first-day pacing risk"],
            ),
            confidence=_option_confidence(best_flight),
            notes=getattr(best_flight, "traveler_fit", ""),
            link=getattr(best_flight, "deep_link", ""),
        )
    )
    if best_car is not None:
        rows.append(
            _timeline_row(
                day=1,
                date_value=start,
                event_type="car pickup",
                title=f"Pick up {best_car.vehicle_class}",
                location=best_car.pickup_location,
                provider=best_car.booking_source,
                status="recommended",
                fixed="flexible",
                buffer_before="after baggage/arrival",
                friction_flags=_combine_flags(
                    best_car.friction_flags,
                    ["pickup timing must account for baggage and arrival delay"],
                ),
                confidence=_option_confidence(best_car),
                notes=best_car.passenger_fit,
                link=best_car.deep_link,
            )
        )
    cursor_day = 1
    for region, nights in option.nights_by_region.items():
        rows.append(
            _timeline_row(
                day=cursor_day,
                date_value=_add_days(start, cursor_day - 1),
                event_type="lodging",
                title=f"Check in: {region}",
                location=region,
                provider=_option_summary(best_lodging),
                status="recommended" if best_lodging is not None else "seeded",
                fixed="flexible",
                buffer_before="avoid late-arrival access risk",
                buffer_after=f"{nights} night(s)",
                friction_flags=_combine_flags(
                    getattr(best_lodging, "friction_flags", []),
                    ["check-in time must be aligned to arrival"],
                ),
                confidence=_option_confidence(best_lodging),
                notes=getattr(best_lodging, "adult_child_fit", option.lodging_strategy),
                link=getattr(best_lodging, "deep_link", ""),
            )
        )
        cursor_day += max(1, nights)
        rows.append(
            _timeline_row(
                day=cursor_day,
                date_value=_add_days(start, cursor_day - 1),
                event_type="lodging",
                title=f"Check out / transition: {region}",
                location=region,
                status="seeded",
                fixed="flexible",
                buffer_before="pack/load buffer",
                buffer_after="inter-island or airport buffer",
                friction_flags="transition day can become wasted time",
                confidence="medium",
                notes=option.island_region_movement_friction,
            )
        )
    for idx, activity in enumerate(activities, start=2):
        rows.append(
            _timeline_row(
                day=min(idx, max(2, option.duration_days - 1)),
                date_value=_add_days(start, idx - 1),
                event_type="activity",
                title=activity.activity_name,
                location=activity.island_location,
                provider=activity.source,
                status=_row_status(shortlists.get("activities"), activity.option_id),
                fixed="flexible",
                travel_time=activity.duration,
                buffer_before="half-day slack",
                buffer_after="downtime / meal buffer",
                friction_flags=_combine_flags(
                    activity.friction_flags,
                    ["timeline placement tentative until flight/lodging times are fixed"],
                ),
                confidence=_option_confidence(activity),
                notes=activity.age_family_fit,
                link=activity.deep_link,
            )
        )
    rows.append(
        _timeline_row(
            day=max(1, option.duration_days),
            date_value=_add_days(start, option.duration_days - 1),
            event_type="flight",
            title="Return flight research",
            location=", ".join(intake.departure_airports),
            from_value=option.regions[-1] if option.regions else "destination",
            to_value=", ".join(intake.departure_airports),
            status="seeded",
            fixed="flexible",
            buffer_before="avoid early departure if possible",
            friction_flags="return timing risk if car dropoff / island transfer is tight",
            confidence="low",
            notes="Validate exact return after final lodging sequence is settled.",
        )
    )
    return rows


def _timeline_row(
    *,
    day: int,
    date_value: date | None,
    event_type: str,
    title: str,
    location: str = "",
    from_value: str = "",
    to_value: str = "",
    provider: str = "",
    status: str = "seeded",
    fixed: str = "flexible",
    travel_time: str = "",
    buffer_before: str = "",
    buffer_after: str = "",
    friction_flags: str = "",
    confidence: str = "",
    notes: str = "",
    link: str = "",
) -> list[Any]:
    return [
        day,
        str(date_value) if date_value else "",
        "",
        "",
        travel_time,
        event_type,
        title,
        location,
        from_value,
        to_value,
        provider,
        status,
        fixed,
        travel_time,
        buffer_before,
        buffer_after,
        friction_flags,
        confidence,
        notes,
        link,
    ]


def _recommended_option(state: Any | None) -> Any | None:
    if state is None or not getattr(state, "recommended_option_id", None):
        return None
    return next(
        (
            option
            for option in _typed_options(state)
            if getattr(option, "option_id", None) == state.recommended_option_id
        ),
        None,
    )


def _top_options(state: Any | None, *, limit: int) -> list[Any]:
    return _typed_options(state)[:limit] if state is not None else []


def _typed_options(state: Any | None) -> list[Any]:
    if state is None:
        return []
    if getattr(state, "flight_options", []):
        return list(state.flight_options)
    if getattr(state, "lodging_options", []):
        return list(state.lodging_options)
    if getattr(state, "car_options", []):
        return list(state.car_options)
    if getattr(state, "activity_options", []):
        return list(state.activity_options)
    return []


def _option_summary(option: Any | None) -> str:
    if option is None:
        return ""
    return (
        getattr(option, "airline", "")
        or getattr(option, "name", "")
        or getattr(option, "vehicle_class", "")
        or getattr(option, "activity_name", "")
        or getattr(option, "option_id", "")
    )


def _option_confidence(option: Any | None) -> str:
    if option is None:
        return "low"
    validation = getattr(option, "validation", None)
    if validation is None:
        return "medium"
    return f"{validation.confidence:.0%}"


def _combine_flags(existing: list[str], extra: list[str]) -> str:
    return ", ".join([*existing, *extra])


def _row_status(state: Any | None, option_id: str) -> str:
    if state is not None and option_id == getattr(state, "recommended_option_id", None):
        return "recommended"
    return "researched"


def _yes_no(value: bool) -> str:
    return "yes" if value else ""


def _unknown_bool(value: bool | None) -> str:
    if value is None:
        return "verify"
    return "yes" if value else "no"


def _notes(*groups: list[str]) -> str:
    items: list[str] = []
    for group in groups:
        items.extend(str(item) for item in group if item)
    return "; ".join(items)


def _party_lodging_notes(intake: TripIntake) -> str:
    notes = [
        intake.party.sleeping_considerations or "",
        "separate rooms preferred" if intake.party.separate_rooms_preferred else "",
        intake.party.privacy_needs or "",
    ]
    return "; ".join(note for note in notes if note) or "Use default bed/privacy rules."


def _workspace_completeness(shortlists: dict[str, Any], trip: Trip) -> int:
    checks = [
        bool(trip.travelers),
        bool(trip.segments),
        bool(trip.stays),
        all(category in shortlists for category in ("flights", "lodging", "cars", "activities")),
        any(
            item.category in {"document", "logistics", "health", "money"} for item in trip.checklist
        ),
        bool(trip.risk_flags),
    ]
    return int(sum(1 for item in checks if item) / len(checks) * 100)


def _unresolved_blockers(shortlists: dict[str, Any], trip: Trip) -> list[str]:
    blockers: list[str] = []
    for category in ("flights", "lodging", "cars", "activities"):
        if category not in shortlists:
            blockers.append(f"{category} shortlist missing")
    if trip.unconfirmed_segments:
        blockers.append("flight confirmations not booked")
    if trip.unconfirmed_stays:
        blockers.append("lodging confirmations not booked")
    blockers.append("live prices/availability still need human verification")
    return blockers


def _top_workspace_warnings(trip: Trip, shortlists: dict[str, Any]) -> list[str]:
    warnings = [risk.description for risk in trip.risk_flags[:3]]
    for state in shortlists.values():
        warnings.extend(state.warnings[:2])
    return warnings


def _workspace_next_actions(shortlists: dict[str, Any], trip: Trip) -> list[str]:
    actions = []
    for category in ("flights", "lodging", "cars", "activities"):
        state = shortlists.get(category)
        if state is None:
            actions.append(f"Generate {category} shortlist")
        elif getattr(state, "recommended_option_id", None):
            actions.append(
                f"Open and live-verify recommended {category}: {state.recommended_option_id}"
            )
    if trip.unconfirmed_segments or trip.unconfirmed_stays:
        actions.append("Promote selected recommendations to approved/booked once human confirms.")
    return actions


def _add_days(start: date | None, offset: int) -> date | None:
    return start + timedelta(days=offset) if start else None


def _sheet_tab_name(name: str) -> str:
    escaped = name.replace("'", "''")
    return f"'{escaped}'"


def _sheet_formatting_requests(
    tabs: list[WorkspaceTab],
    sheet_ids: dict[str, int],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for tab in tabs:
        sheet_id = sheet_ids.get(tab.name)
        if sheet_id is None:
            continue
        requests.extend(
            [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {"red": 0.9, "green": 0.94, "blue": 0.92},
                            }
                        },
                        "fields": "userEnteredFormat(textFormat,backgroundColor)",
                    }
                },
            ]
        )
        status_index = _status_column_index(tab)
        if status_index is not None:
            requests.extend(_status_format_requests(sheet_id, status_index))
    return requests


def _status_column_index(tab: WorkspaceTab) -> int | None:
    for idx, header in enumerate(tab.headers):
        if header == "Status":
            return idx
    return None


def _status_format_requests(sheet_id: int, status_index: int) -> list[dict[str, Any]]:
    return [
        _conditional_status_rule(sheet_id, status_index, "recommended", 0.83, 0.93, 0.88),
        _conditional_status_rule(sheet_id, status_index, "verified_live", 0.78, 0.9, 1.0),
        _conditional_status_rule(sheet_id, status_index, "approved", 0.81, 0.93, 0.75),
        _conditional_status_rule(sheet_id, status_index, "booked", 0.72, 0.88, 0.72),
        _conditional_status_rule(sheet_id, status_index, "risk", 1.0, 0.86, 0.82),
        _conditional_status_rule(sheet_id, status_index, "rejected", 0.93, 0.93, 0.93),
    ]


def _conditional_status_rule(
    sheet_id: int,
    status_index: int,
    text: str,
    red: float,
    green: float,
    blue: float,
) -> dict[str, Any]:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [
                    {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": status_index,
                        "endColumnIndex": status_index + 1,
                    }
                ],
                "booleanRule": {
                    "condition": {
                        "type": "TEXT_EQ",
                        "values": [{"userEnteredValue": text}],
                    },
                    "format": {"backgroundColor": {"red": red, "green": green, "blue": blue}},
                },
            },
            "index": 0,
        }
    }
