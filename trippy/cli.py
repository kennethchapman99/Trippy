"""Trippy CLI — entry point `trippy`."""

from __future__ import annotations

import json as json_lib
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.table import Table

from trippy.services.learning import FeedbackRating, WorkflowOutcome, WorkflowStatus

if TYPE_CHECKING:
    from trippy.db.models import Trip as TripModel
    from trippy.importers.sheet_importer import ImportResult as ImportResultType

app = typer.Typer(name="trippy", help="Chapman family travel concierge.")
learn_app = typer.Typer(help="Review and apply Trippy learning proposals.")
trip_intake_app = typer.Typer(help="Create and inspect new-trip intake state.")
trip_plan_app = typer.Typer(help="Draft, select, and workspace a new trip plan.")
trip_map_app = typer.Typer(help="Build planning map artifacts for a new trip.")
app.add_typer(learn_app, name="learn")
app.add_typer(trip_intake_app, name="trip-intake")
app.add_typer(trip_plan_app, name="trip-plan")
app.add_typer(trip_map_app, name="trip-map")
console = Console()


@app.command()
def version() -> None:
    """Print version."""
    from trippy import __version__

    typer.echo(f"trippy {__version__}")


@app.command("db-init")
def db_init() -> None:
    """Create ~/.trippy directory and run Alembic migrations."""
    import subprocess

    from trippy import config

    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.VAULT_PATH.mkdir(parents=True, exist_ok=True)
    config.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
    config.TRIPS_PATH.mkdir(parents=True, exist_ok=True)
    config.INTAKES_PATH.mkdir(parents=True, exist_ok=True)
    config.PLANS_PATH.mkdir(parents=True, exist_ok=True)
    config.WORKSPACES_PATH.mkdir(parents=True, exist_ok=True)
    config.SHORTLISTS_PATH.mkdir(parents=True, exist_ok=True)
    config.LEARNING_PATH.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    typer.echo(result.stdout)
    if result.returncode != 0:
        typer.echo(result.stderr, err=True)
        raise typer.Exit(1)
    typer.echo("Database initialised.")


@app.command("agent")
def run_agent() -> None:
    """Start an interactive Trippy agent session."""
    from trippy.agent import main as agent_main

    agent_main()


@app.command("ui")
def run_ui(
    host: str = typer.Option("127.0.0.1", "--host", help="Host for the local UI server"),
    port: int = typer.Option(8787, "--port", help="Port for the local UI server"),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the UI in the default browser",
    ),
) -> None:
    """Start the local Trippy planning UI."""
    from trippy.ui.server import serve_ui

    serve_ui(host=host, port=port, open_browser=open_browser)



@app.command("web")
def run_web(
    api_host: str = typer.Option("127.0.0.1", "--api-host", help="Host for the Trippy backend API"),
    api_port: int = typer.Option(8787, "--api-port", help="Port for the Trippy backend API"),
    web_host: str = typer.Option("127.0.0.1", "--web-host", help="Host for the Vite web UI"),
    web_port: int = typer.Option(8788, "--web-port", help="Port for the Vite web UI"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the new web UI"),
    install: bool = typer.Option(True, "--install/--no-install", help="Run npm install if web/node_modules is missing"),
    kill_ports: bool = typer.Option(True, "--kill-ports/--no-kill-ports", help="Kill stale processes on the backend/frontend ports before starting"),
) -> None:
    """Start the backend API and the new React/Vite Trippy UI with one command."""
    import os
    import subprocess
    import sys
    import time
    import webbrowser
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    web_dir = project_root / "web"
    package_json = web_dir / "package.json"
    node_modules = web_dir / "node_modules"

    if not package_json.exists():
        console.print(f"[red]Missing web/package.json at {package_json}[/red]")
        raise typer.Exit(1)

    if install and not node_modules.exists():
        console.print("[bold]Installing web dependencies...[/bold]")
        install_result = subprocess.run(["npm", "install"], cwd=web_dir)
        if install_result.returncode != 0:
            console.print("[red]npm install failed[/red]")
            raise typer.Exit(install_result.returncode)

    api_url = f"http://{api_host}:{api_port}"
    web_url = f"http://{web_host}:{web_port}"

    if kill_ports:
        for port in (api_port, web_port):
            subprocess.run(
                ["bash", "-lc", f"kill -9 $(lsof -t -i :{port}) 2>/dev/null || true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    env = os.environ.copy()
    env["TRIPPY_API_PROXY_TARGET"] = api_url
    env["VITE_TRIPPY_API_TARGET"] = api_url

    backend_code = (
        "from trippy.ui.server import serve_ui; "
        f"serve_ui(host={api_host!r}, port={api_port!r}, open_browser=False)"
    )

    backend = subprocess.Popen(
        [sys.executable, "-c", backend_code],
        cwd=project_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", web_host, "--port", str(web_port)],
        cwd=web_dir,
        env=env,
    )

    try:
        time.sleep(2)
        if backend.poll() is not None:
            console.print(f"[red]Backend exited with code {backend.returncode}[/red]")
            raise typer.Exit(backend.returncode or 1)
        if frontend.poll() is not None:
            console.print(f"[red]Frontend exited with code {frontend.returncode}[/red]")
            raise typer.Exit(frontend.returncode or 1)

        console.print(f"[green]Trippy backend API:[/green] {api_url}")
        console.print(f"[green]Trippy web UI:[/green] {web_url}")
        console.print("[dim]Press Ctrl-C to stop backend and frontend.[/dim]")
        if open_browser:
            webbrowser.open(web_url)

        while True:
            backend_code_return = backend.poll()
            frontend_code_return = frontend.poll()
            if backend_code_return is not None:
                console.print(f"[red]Backend exited with code {backend_code_return}[/red]")
                raise typer.Exit(backend_code_return or 1)
            if frontend_code_return is not None:
                console.print(f"[red]Frontend exited with code {frontend_code_return}[/red]")
                raise typer.Exit(frontend_code_return or 1)
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\nStopping Trippy web...")
    finally:
        for process in (frontend, backend):
            if process.poll() is None:
                process.terminate()
        for process in (frontend, backend):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()



@app.command("thin-slice")
def thin_slice(
    real_google: bool = typer.Option(False, "--real-google", help="Use real Google credentials"),
) -> None:
    """Run the end-to-end thin slice demo."""
    from trippy.thin_slice import run_thin_slice

    result = run_thin_slice(real_google=real_google)
    workflow_id = _record_cli_workflow(
        workflow_name="thin-slice",
        summary="Ran the end-to-end thin slice demo",
        result=result,
        status=WorkflowStatus.SUCCESS,
    )
    _print_workflow_footer(workflow_id)


@app.command("doctor")
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Check local setup, credentials, scopes, storage, DB, and MCP readiness."""
    from trippy.services.setup import SetupDoctor

    report = SetupDoctor(project_root=Path.cwd()).run()
    if json_output:
        _print_json(report.model_dump(mode="json"))
    else:
        _print_setup_report(report)
    if not report.ok:
        raise typer.Exit(1)


@app.command("auth-google")
def auth_google(
    force: bool = typer.Option(False, "--force", help="Delete existing token and re-run OAuth"),
) -> None:
    """Run Google OAuth and validate Gmail, Sheets write, and Drive access."""
    from trippy.services.setup import GoogleAuthValidator

    result = GoogleAuthValidator().run(force=force)
    _print_setup_report(result)
    if not result.ok:
        raise typer.Exit(1)


@app.command("mine-intelligence")
def mine_intelligence(
    min_support: int = typer.Option(
        1, "--min-support", help="Evidence count required for a signal"
    ),
    propose_learning: bool = typer.Option(
        True,
        "--propose-learning/--no-propose-learning",
        help="Create review-gated memory proposals from extracted signals",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Extract reusable planning intelligence from canonical trip history."""
    from trippy.services.travel_intelligence import TravelIntelligenceService
    from trippy.services.trip_state import TripStateService

    trips = TripStateService().load_all()
    service = TravelIntelligenceService()
    report = service.analyze(trips, min_support=min_support)
    workflow_id = _record_cli_workflow(
        workflow_name="mine-intelligence",
        summary=report.summary,
        result=report.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS if trips else WorkflowStatus.SKIPPED,
        skill_name="trippy-preference-extractor",
    )
    proposals = []
    if propose_learning:
        proposals = service.propose_memory_updates(report, source_workflow_id=workflow_id)

    payload = {
        "workflow_id": workflow_id,
        "report": report.model_dump(mode="json"),
        "learning_proposals": [proposal.id for proposal in proposals],
    }
    if json_output:
        _print_json(payload)
        return
    _print_intelligence_report(report)
    if proposals:
        console.print(f"\nCreated {len(proposals)} review-gated learning proposal(s).")
        console.print("Review with: [bold]trippy learn review[/bold]")
    _print_workflow_footer(workflow_id)


@app.command("trip-ideas")
def trip_ideas(
    time_of_year: str = typer.Option("", "--time", help="Time of year or season"),
    duration_days: int = typer.Option(0, "--days", help="Trip duration in days"),
    budget_cad: float = typer.Option(0.0, "--budget-cad", help="Approximate total budget CAD"),
    max_flight_hours: float = typer.Option(
        0.0, "--max-flight-hours", help="Preferred max flight hours"
    ),
    direct: bool = typer.Option(True, "--direct/--connections-ok", help="Prefer direct flights"),
    goal: list[str] | None = typer.Option(None, "--goal", help="Trip goal; repeatable"),
    avoid: list[str] | None = typer.Option(None, "--avoid", help="Things to avoid; repeatable"),
    vibe: str = typer.Option("", "--vibe", help="Desired trip vibe"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate and rank family-fit trip concepts from loose constraints."""
    from trippy.models.ideas import TripIdeaRequest
    from trippy.services.trip_ideation import TripIdeationService

    request = TripIdeaRequest(
        time_of_year=time_of_year or None,
        duration_days=duration_days or None,
        budget_cad=budget_cad or None,
        max_flight_hours=max_flight_hours or None,
        direct_flight_preferred=direct,
        goals=goal or [],
        avoid=avoid or [],
        desired_vibe=vibe or None,
    )
    comparison = TripIdeationService().compare(request)
    workflow_id = _record_cli_workflow(
        workflow_name="trip-ideas",
        summary="Generated ranked family-fit trip concepts",
        result=comparison.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    payload = {"workflow_id": workflow_id, "comparison": comparison.model_dump(mode="json")}
    if json_output:
        _print_json(payload)
        return
    _print_trip_ideas(comparison)
    _print_workflow_footer(workflow_id)


@trip_intake_app.command("wizard")
def trip_intake_wizard(
    mode: str = typer.Option(
        "selected_destination",
        "--mode",
        help="Intake mode: idea or selected_destination",
    ),
    trip_name: str = typer.Option("", "--trip-name", help="Human trip name"),
    destination: list[str] | None = typer.Option(
        None,
        "--destination",
        help="Destination seed; repeatable or comma-separated",
    ),
    travel_window: str = typer.Option("", "--travel-window", help="Travel window label"),
    season: str = typer.Option("", "--season", help="Season or time of year"),
    start_date: str = typer.Option("", "--start-date", help="Optional YYYY-MM-DD start date"),
    end_date: str = typer.Option("", "--end-date", help="Optional YYYY-MM-DD end date"),
    duration_days: str = typer.Option(
        "",
        "--days",
        "--duration",
        help='Trip duration such as "10", "6 to 8 days", or "about a week"',
    ),
    travelers: int = typer.Option(5, "--travelers", help="Number of travelers"),
    party_type: str = typer.Option(
        "whole_family",
        "--party-type",
        help="whole_family, adults_only, couple, subset_family, family_plus_others, or custom",
    ),
    adults: int = typer.Option(0, "--adults", help="Adults coming on this trip"),
    children: int = typer.Option(0, "--children", help="Children coming on this trip"),
    child_age: list[int] | None = typer.Option(
        None,
        "--child-age",
        help="Child age; repeatable",
    ),
    traveler: list[str] | None = typer.Option(
        None,
        "--traveler",
        help="Traveler roster item; repeatable. Examples: 'Ken|adult', 'Child 1|12', 'Alex|teen'.",
    ),
    sleeping_considerations: str = typer.Option(
        "",
        "--sleeping-considerations",
        help="Trip-specific sleeping/bed notes",
    ),
    separate_rooms: bool = typer.Option(
        False,
        "--separate-rooms",
        help="Separate rooms/privacy matter for this trip",
    ),
    privacy_needs: str = typer.Option(
        "", "--privacy-needs", help="Privacy or room-separation needs"
    ),
    mobility_notes: str = typer.Option("", "--mobility-notes", help="Mobility/stamina notes"),
    child_friendliness_notes: str = typer.Option(
        "",
        "--child-friendliness-notes",
        help="Child-friendliness or age-fit notes",
    ),
    departure_airport: list[str] | None = typer.Option(
        None,
        "--departure-airport",
        help="Departure airport; repeatable or comma-separated",
    ),
    budget_cad: float = typer.Option(0.0, "--budget-cad", help="Approximate budget in CAD"),
    max_travel_time_hours: float = typer.Option(
        0.0,
        "--max-travel-time-hours",
        help="Preferred max total travel time in hours",
    ),
    prefer_direct: bool = typer.Option(
        True, "--direct/--connections-ok", help="Prefer direct flights"
    ),
    goal: list[str] | None = typer.Option(None, "--goal", help="Trip goal; repeatable"),
    avoidance: list[str] | None = typer.Option(
        None,
        "--avoidance",
        "--avoid",
        help="Thing to avoid; repeatable",
    ),
    pace: str = typer.Option("balanced", "--pace", help="relaxed, balanced, or active"),
    crowd_tolerance: str = typer.Option("low", "--crowd-tolerance", help="low, medium, or high"),
    food_priority: str = typer.Option("high", "--food-priority", help="low, medium, or high"),
    lodging_notes: str = typer.Option("", "--lodging-notes", help="Lodging preference notes"),
    car_rental: str = typer.Option("", "--car-rental", help="Car rental expectation notes"),
    notes: str = typer.Option("", "--notes", help="Freeform notes"),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Use flags/defaults without prompts"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Ask intake questions and write canonical new-trip intake state."""
    from trippy.models.trip_planning import (
        CarRentalExpectation,
        CrowdTolerance,
        FlightPreferenceInput,
        FoodPriority,
        LodgingPreferenceInput,
        TravelWindow,
        TripIntake,
        TripIntakeMode,
        TripPace,
        TripParty,
        TripPartyType,
    )
    from trippy.services.trip_intake import TripIntakeService

    destinations = _split_cli_list(destination or [])
    departures = _split_cli_list(departure_airport or []) or ["YYZ"]
    goals = _split_cli_list(goal or [])
    avoidances = _split_cli_list(avoidance or [])

    if not no_prompt:
        mode = str(typer.prompt("Mode (idea or selected_destination)", default=mode)).strip()
        if not trip_name:
            trip_name = str(typer.prompt("Trip name", default="Family trip")).strip()
        if not destinations:
            raw_destination = str(typer.prompt("Destination seed(s)", default="Destination")).strip()
            destinations = _split_cli_list([raw_destination])
        if not travel_window and not season and not start_date:
            travel_window = str(
                typer.prompt("Travel window or season", default="summer 2027")
            ).strip()
        if not duration_days:
            duration_days = str(typer.prompt("Duration in days or range", default="10")).strip()
        party_type = str(
            typer.prompt(
                "Who is coming (whole_family, adults_only, couple, subset_family, family_plus_others, custom)",
                default=party_type,
            )
        ).strip()
        if not adults:
            adults = int(typer.prompt("Adults coming", default=2))
        if not children:
            children = int(typer.prompt("Children coming", default=max(0, travelers - adults)))
        travelers = adults + children
        if children and not child_age:
            raw_ages = str(typer.prompt("Child ages or age bands", default="")).strip()
            child_age = [
                int(part.strip()) for part in raw_ages.split(",") if part.strip().isdigit()
            ]
        if not traveler:
            raw_roster = str(
                typer.prompt(
                    "Traveler names/roster (comma-separated, optional)",
                    default="",
                )
            ).strip()
            traveler = [item.strip() for item in raw_roster.split(",") if item.strip()]
        if departures == ["YYZ"]:
            raw_departures = str(typer.prompt("Departure airport(s)", default="YYZ")).strip()
            departures = _split_cli_list([raw_departures]) or ["YYZ"]
        if not goals:
            raw_goals = str(
                typer.prompt(
                    "Goals",
                    default="nature, food, relaxed adventure, family comfort",
                )
            ).strip()
            goals = _split_cli_list([raw_goals])
        if not avoidances:
            raw_avoid = str(
                typer.prompt(
                    "Avoidances",
                    default="huge crowds, overpacked days, stressful driving",
                )
            ).strip()
            avoidances = _split_cli_list([raw_avoid])

    try:
        duration_input: Any = duration_days or None
        intake = TripIntake(
            mode=TripIntakeMode(_normalise_enum_value(mode)),
            trip_name=trip_name,
            destination_seeds=destinations,
            travel_window=TravelWindow(
                label=travel_window or None,
                season=season or (travel_window or None),
                start_date=_parse_optional_date(start_date),
                end_date=_parse_optional_date(end_date),
            ),
            duration_days=duration_input,
            travelers=travelers,
            departure_airports=departures,
            budget_cad=budget_cad or None,
            max_travel_time_hours=max_travel_time_hours or None,
            flight_preferences=FlightPreferenceInput(prefer_direct=prefer_direct),
            goals=goals,
            avoidances=avoidances,
            pace=TripPace(_normalise_enum_value(pace)),
            crowd_tolerance=CrowdTolerance(_normalise_enum_value(crowd_tolerance)),
            food_priority=FoodPriority(_normalise_enum_value(food_priority)),
            lodging_preferences=LodgingPreferenceInput(notes=lodging_notes or None),
            car_rental_expectations=CarRentalExpectation(notes=car_rental or None),
            party=TripParty(
                party_type=TripPartyType(_normalise_enum_value(party_type)),
                adults=adults or min(2, travelers),
                children=children or max(0, travelers - (adults or min(2, travelers))),
                child_ages=child_age or [],
                roster=_parse_traveler_specs(traveler or []),
                explicit=bool(traveler or adults or children or child_age),
                defaulted_from_family_profile=not bool(traveler or adults or children or child_age),
                sleeping_considerations=sleeping_considerations or None,
                separate_rooms_preferred=separate_rooms,
                privacy_needs=privacy_needs or None,
                mobility_notes=mobility_notes or None,
                child_friendliness_notes=child_friendliness_notes or None,
            ),
            freeform_notes=notes or None,
        )
    except ValueError as exc:
        console.print(f"[red]Invalid intake:[/red] {exc}")
        raise typer.Exit(1) from exc

    intake = TripIntakeService().create(intake)
    workflow_id = _record_cli_workflow(
        workflow_name="trip-intake-wizard",
        trip_id=intake.trip_id,
        summary=f"Created new-trip intake for {intake.trip_name}",
        result=intake.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    payload = {"workflow_id": workflow_id, "intake": intake.model_dump(mode="json")}
    if json_output:
        _print_json(payload)
        return
    _print_trip_intake(intake)
    console.print(f"\nNext: [bold]uv run trippy trip-plan draft --trip-id {intake.trip_id}[/bold]")
    _print_workflow_footer(workflow_id)


@trip_intake_app.command("show")
def trip_intake_show(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Show canonical new-trip intake state."""
    from trippy.services.trip_intake import TripIntakeService

    try:
        intake = TripIntakeService().require(trip_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if json_output:
        _print_json(intake.model_dump(mode="json"))
        return
    _print_trip_intake(intake)


@trip_plan_app.command("draft")
def trip_plan_draft(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate structured planning options from a trip intake."""
    from trippy.services.trip_planner import TripPlannerService

    try:
        draft = TripPlannerService().draft(trip_id)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    workflow_id = _record_cli_workflow(
        workflow_name="trip-plan-draft",
        skill_name="trippy-family-itinerary-builder",
        trip_id=trip_id,
        summary=f"Generated {len(draft.options)} trip plan option(s)",
        result=draft.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    payload = {"workflow_id": workflow_id, "draft": draft.model_dump(mode="json")}
    if json_output:
        _print_json(payload)
        return
    _print_trip_plan_draft(draft)
    if draft.recommended_option_id:
        console.print(
            f"\nSelect: [bold]uv run trippy trip-plan select --trip-id {trip_id} "
            f"--option-id {draft.recommended_option_id}[/bold]"
        )
    _print_workflow_footer(workflow_id)


@trip_plan_app.command("select")
def trip_plan_select(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    option_id: str = typer.Option(..., "--option-id", help="Plan option ID to approve"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Approve the preferred plan option before workspace creation."""
    from trippy.services.trip_planner import TripPlannerService

    try:
        draft = TripPlannerService().select_option(trip_id, option_id)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    workflow_id = _record_cli_workflow(
        workflow_name="trip-plan-select",
        trip_id=trip_id,
        summary=f"Selected trip plan option {option_id}",
        result=draft.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    payload = {"workflow_id": workflow_id, "draft": draft.model_dump(mode="json")}
    if json_output:
        _print_json(payload)
        return
    selected = draft.get_option(option_id)
    console.print(f"[green]Selected:[/green] {selected.title if selected else option_id}")
    console.print(f"Next: [bold]uv run trippy trip-plan workspace --trip-id {trip_id}[/bold]")
    _print_workflow_footer(workflow_id)


@trip_plan_app.command("workspace")
def trip_plan_workspace(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    option_id: str = typer.Option(
        "", "--option-id", help="Optional plan option ID to select inline"
    ),
    folder_id: str = typer.Option("", "--folder-id", help="Optional Google Drive folder ID"),
    google: bool = typer.Option(True, "--google/--no-google", help="Attempt Google Sheet creation"),
    validate_live: bool = typer.Option(
        False,
        "--validate-live",
        help="Attempt live source link validation before hydrating workspace rows",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Create or prepare the selected trip planning workspace."""
    from trippy.models.trip_planning import WorkspaceStatus
    from trippy.services.trip_workspace import TripWorkspaceService

    try:
        state = TripWorkspaceService().prepare(
            trip_id,
            option_id=option_id or None,
            create_google_sheet=google,
            folder_id=folder_id or None,
            validate_live=validate_live,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    workflow_id = _record_cli_workflow(
        workflow_name="trip-plan-workspace",
        skill_name="trippy-trip-sheet-creator",
        trip_id=trip_id,
        summary=f"Prepared planning workspace for {trip_id}",
        result=state.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS
        if state.status != WorkspaceStatus.SHEET_FAILED
        else WorkflowStatus.FAILED,
    )
    payload = {"workflow_id": workflow_id, "workspace": state.model_dump(mode="json")}
    if json_output:
        _print_json(payload)
        return
    _print_trip_workspace(state)
    _print_workflow_footer(workflow_id)


@trip_plan_app.command("flights")
def trip_plan_flights(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    validate_live: bool = typer.Option(
        False,
        "--validate-live",
        help="Attempt live source link validation for shortlist rows",
    ),
    deep_research: bool = typer.Option(
        False,
        "--deep-research",
        help="Run read-only source adapters for richer evidence where supported",
    ),
    adapter: str = typer.Option(
        "auto",
        "--adapter",
        help="Source adapter mode: auto, link, firecrawl, playwright, or openclaw",
    ),
    propose_learning: bool = typer.Option(
        False,
        "--propose-learning",
        help="Create review-gated planning learning proposals from the shortlist",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate a friction-aware flight shortlist for the selected plan."""
    from trippy.services.flight_shortlist import FlightShortlistService

    _run_shortlist_command(
        trip_id=trip_id,
        workflow_name="trip-plan-flights",
        summary="Generated flight shortlist",
        state=FlightShortlistService().build(
            trip_id,
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter,
        ),
        propose_learning=propose_learning,
        json_output=json_output,
    )


@trip_plan_app.command("select-flight")
def trip_plan_select_flight(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    option_id: str = typer.Option(..., "--option-id", help="Flight option ID to use for planning"),
    selection_kind: str = typer.Option("outbound", "--selection-kind", help="Flight role: outbound or return"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Select an outbound or return flight option so timing can drive planning."""
    from trippy.services.flight_shortlist import FlightShortlistService

    state = FlightShortlistService().select_flight(
        trip_id,
        option_id,
        selection_kind=selection_kind,
    )
    _run_shortlist_command(
        trip_id=trip_id,
        workflow_name="trip-plan-select-flight",
        summary=f"Selected {selection_kind} flight {option_id}",
        state=state,
        propose_learning=False,
        json_output=json_output,
    )


@trip_plan_app.command("lodging")
def trip_plan_lodging(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    validate_live: bool = typer.Option(
        False,
        "--validate-live",
        help="Attempt live source link validation for shortlist rows",
    ),
    deep_research: bool = typer.Option(
        False,
        "--deep-research",
        help="Run read-only source adapters for richer lodging evidence",
    ),
    adapter: str = typer.Option(
        "auto",
        "--adapter",
        help="Source adapter mode: auto, link, firecrawl, playwright, or openclaw",
    ),
    propose_learning: bool = typer.Option(
        False,
        "--propose-learning",
        help="Create review-gated planning learning proposals from the shortlist",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate a family-fit lodging shortlist for the selected plan."""
    from trippy.services.lodging_shortlist import LodgingShortlistService

    _run_shortlist_command(
        trip_id=trip_id,
        workflow_name="trip-plan-lodging",
        summary="Generated lodging shortlist",
        state=LodgingShortlistService().build(
            trip_id,
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter,
        ),
        propose_learning=propose_learning,
        json_output=json_output,
    )


@trip_plan_app.command("cars")
def trip_plan_cars(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    validate_live: bool = typer.Option(
        False,
        "--validate-live",
        help="Attempt live source link validation for shortlist rows",
    ),
    deep_research: bool = typer.Option(
        False,
        "--deep-research",
        help="Run read-only source adapters for richer evidence where supported",
    ),
    adapter: str = typer.Option(
        "auto",
        "--adapter",
        help="Source adapter mode: auto, link, firecrawl, playwright, or openclaw",
    ),
    propose_learning: bool = typer.Option(
        False,
        "--propose-learning",
        help="Create review-gated planning learning proposals from the shortlist",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate a family/luggage-aware car rental shortlist for the selected plan."""
    from trippy.services.car_shortlist import CarShortlistService

    _run_shortlist_command(
        trip_id=trip_id,
        workflow_name="trip-plan-cars",
        summary="Generated car rental shortlist",
        state=CarShortlistService().build(
            trip_id,
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter,
        ),
        propose_learning=propose_learning,
        json_output=json_output,
    )


@trip_plan_app.command("activities")
def trip_plan_activities(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    validate_live: bool = typer.Option(
        False,
        "--validate-live",
        help="Attempt live source link validation for shortlist rows",
    ),
    deep_research: bool = typer.Option(
        False,
        "--deep-research",
        help="Run read-only source adapters for richer evidence where supported",
    ),
    adapter: str = typer.Option(
        "auto",
        "--adapter",
        help="Source adapter mode: auto, link, firecrawl, playwright, or openclaw",
    ),
    propose_learning: bool = typer.Option(
        False,
        "--propose-learning",
        help="Create review-gated planning learning proposals from the shortlist",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate a safety/review/pacing-aware activity shortlist for the selected plan."""
    from trippy.services.activity_shortlist import ActivityShortlistService

    _run_shortlist_command(
        trip_id=trip_id,
        workflow_name="trip-plan-activities",
        summary="Generated activity shortlist",
        state=ActivityShortlistService().build(
            trip_id,
            validate_live=validate_live,
            deep_research=deep_research,
            adapter_mode=adapter,
        ),
        propose_learning=propose_learning,
        json_output=json_output,
    )


@trip_plan_app.command("propose-learning")
def trip_plan_propose_learning(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Create review-gated learning proposals from planning choices and shortlists."""
    from trippy.services.planning_learning import PlanningLearningService

    workflow_id = _record_cli_workflow(
        workflow_name="trip-plan-propose-learning",
        trip_id=trip_id,
        summary=f"Reviewed planning outcomes for {trip_id}",
        result={"trip_id": trip_id},
        status=WorkflowStatus.SUCCESS,
    )
    proposals = PlanningLearningService().propose_for_trip(
        trip_id,
        source_workflow_id=workflow_id,
    )
    payload = {
        "workflow_id": workflow_id,
        "learning_proposals": [proposal.model_dump(mode="json") for proposal in proposals],
    }
    if json_output:
        _print_json(payload)
        return
    console.print(f"Created {len(proposals)} review-gated planning proposal(s).")
    if proposals:
        console.print("Review with: [bold]trippy learn review[/bold]")
    _print_workflow_footer(workflow_id)


@trip_map_app.command("build")
def trip_map_build(
    trip_id: str = typer.Option(..., "--trip-id", help="Trip intake ID"),
    option_id: str = typer.Option("", "--option-id", help="Optional plan option ID"),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Directory for planning map outputs. Defaults to TRIPPY_EXPORT_PATH/maps.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate practical map artifacts from the selected planning option."""
    from trippy import config
    from trippy.services.trip_map_builder import TripMapBuilder

    destination = output_dir or config.EXPORT_PATH / "maps"
    try:
        artifact = TripMapBuilder().write_artifacts(
            trip_id,
            destination,
            option_id=option_id or None,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    workflow_id = _record_cli_workflow(
        workflow_name="trip-map-build",
        trip_id=trip_id,
        summary=f"Generated planning map artifacts for {trip_id}",
        result=artifact.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    payload = {"workflow_id": workflow_id, "map": artifact.model_dump(mode="json")}
    if json_output:
        _print_json(payload)
        return
    _print_map_artifact(artifact)
    _print_workflow_footer(workflow_id)


@app.command("sources")
def sources(
    category: str = typer.Option(
        "",
        "--category",
        help="Optional category: flights, city_lodging, private_lodging, tours, car_rentals, deals",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Show Trippy's travel source registry and routing plan."""
    from trippy.models.sources import TravelSourceCategory
    from trippy.services.source_registry import TravelSourceRegistry

    registry = TravelSourceRegistry()
    if category:
        try:
            selected = TravelSourceCategory(category)
        except ValueError as exc:
            console.print(f"[red]Unknown source category:[/red] {category}")
            raise typer.Exit(1) from exc
        plan = registry.plan_for(selected)
        if json_output:
            _print_json(plan.model_dump(mode="json"))
            return
        _print_source_plan(plan)
        return

    items = registry.list_sources()
    if json_output:
        _print_json([item.model_dump(mode="json") for item in items])
        return
    _print_sources(items)


@app.command("country-priors")
def country_priors(
    country: str = typer.Argument("", help="Optional country name to inspect"),
    propose_learning: bool = typer.Option(
        False,
        "--propose-learning",
        help="Create review-gated memory proposals for the shown country priors",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Show historical country-level preference priors."""
    from trippy.services.country_priors import CountryPriorService

    service = CountryPriorService()
    if country:
        prior = service.get(country)
        if prior is None:
            console.print(f"[red]No country prior found for:[/red] {country}")
            raise typer.Exit(1)
        priors = [prior]
    else:
        priors = service.list_priors()

    workflow_id = _record_cli_workflow(
        workflow_name="country-priors",
        summary=f"Reviewed {len(priors)} country-level travel prior(s)",
        result={"country_priors": [prior.model_dump(mode="json") for prior in priors]},
        status=WorkflowStatus.SUCCESS,
    )
    proposals = []
    if propose_learning:
        proposals = service.propose_memory_updates(
            source_workflow_id=workflow_id,
            countries=[prior.country for prior in priors],
        )

    payload = {
        "workflow_id": workflow_id,
        "country_priors": [prior.model_dump(mode="json") for prior in priors],
        "learning_proposals": [proposal.id for proposal in proposals],
    }
    if json_output:
        _print_json(payload)
        return
    _print_country_priors(priors)
    if proposals:
        console.print(f"\nCreated {len(proposals)} review-gated learning proposal(s).")
        console.print("Review with: [bold]trippy learn review[/bold]")
    _print_workflow_footer(workflow_id)


@app.command("maps")
def maps(
    trip_name: str = typer.Argument(..., help="Canonical trip ID or name to map"),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Directory for JSON, GeoJSON, and KML outputs. Defaults to TRIPPY_EXPORT_PATH/maps.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Generate practical Google Maps artifacts for a trip."""
    from trippy import config
    from trippy.services.map_outputs import MapOutputService

    trip = _load_canonical_trip_or_exit(trip_name)
    destination = output_dir or config.EXPORT_PATH / "maps"
    artifact = MapOutputService().write_artifacts(trip, destination)
    workflow_id = _record_cli_workflow(
        workflow_name="maps",
        trip_id=trip.trip_id,
        summary=f"Generated map artifacts for {trip.name}",
        result=artifact.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    if json_output:
        _print_json(artifact.model_dump(mode="json"))
        return
    _print_map_artifact(artifact)
    _print_workflow_footer(workflow_id)


@app.command("dashboard")
def dashboard(
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Dashboard output directory. Defaults to TRIPPY_EXPORT_PATH/dashboard.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Build the static Trippy timeline dashboard."""
    from trippy import config
    from trippy.services.dashboard import DashboardService

    destination = output_dir or config.EXPORT_PATH / "dashboard"
    data = DashboardService().write_dashboard(destination)
    workflow_id = _record_cli_workflow(
        workflow_name="dashboard",
        summary="Built Trippy timeline dashboard",
        result=data.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS,
    )
    if json_output:
        _print_json(data.model_dump(mode="json"))
        return
    _print_dashboard_summary(data)
    _print_workflow_footer(workflow_id)


@app.command("retro")
def retro(
    trip_id: str = typer.Argument(..., help="Canonical trip ID for the completed trip"),
    worked: list[str] | None = typer.Option(None, "--worked", help="What worked; repeatable"),
    worth_money: list[str] | None = typer.Option(
        None, "--worth-money", help="What was worth the money; repeatable"
    ),
    friction: list[str] | None = typer.Option(
        None, "--friction", help="What created friction; repeatable"
    ),
    hard_rule: list[str] | None = typer.Option(
        None, "--hard-rule", help="Hard rule for future trips; repeatable"
    ),
    never_repeat: list[str] | None = typer.Option(
        None, "--never-repeat", help="What not to repeat; repeatable"
    ),
    favorite: list[str] | None = typer.Option(
        None, "--favorite", help="Favorite place, food, hotel, or activity; repeatable"
    ),
    pace: str = typer.Option("", "--pace", help="Whether the pace felt right"),
    expectations: str = typer.Option(
        "", "--expectations", help="Whether destination matched expectations"
    ),
    notes: str = typer.Option("", "--notes", help="General retrospective notes"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Capture a post-trip retrospective and create review-gated learning proposals."""
    from trippy.models.retrospective import TripRetrospectiveInput
    from trippy.services.retrospective import RetrospectiveService

    result = RetrospectiveService().record(
        TripRetrospectiveInput(
            trip_id=trip_id,
            worked=worked or [],
            worth_money=worth_money or [],
            friction=friction or [],
            hard_rules=hard_rule or [],
            never_repeat=never_repeat or [],
            favorites=favorite or [],
            pace=pace or None,
            expectations=expectations or None,
            notes=notes or None,
        )
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[green]{result.summary}[/green]")
    console.print(f"Workflow ID: [dim]{result.workflow_id}[/dim]")
    if result.proposal_ids:
        console.print("Review with: [bold]trippy learn review[/bold]")


@app.command("import")
def import_sheet(
    source: str = typer.Argument(..., help="Path to .xlsx/.csv file or Google Sheets URL"),
) -> None:
    """Import a single trip sheet into the database."""
    from trippy.importers.sheet_importer import SheetImporter
    from trippy.ingest.google_auth import GoogleAuthManager

    importer = SheetImporter(auth_manager=GoogleAuthManager())
    console.print(f"[bold]Importing:[/bold] {source}")
    result = importer.import_file(source)
    _print_import_result(result)
    workflow_id = _record_cli_workflow(
        workflow_name="import-sheet",
        summary=f"Imported trip sheet {source}",
        result={
            "source": result.source,
            "trips_created": result.trips_created,
            "trips_updated": result.trips_updated,
            "errors": result.errors,
            "flagged_fields": len(result.flagged_fields),
        },
        status=WorkflowStatus.FAILED if result.errors else WorkflowStatus.SUCCESS,
    )
    _print_workflow_footer(workflow_id)
    if not result.ok:
        raise typer.Exit(1)


@app.command("import-folder")
def import_folder(
    folder: Path = typer.Argument(..., help="Directory containing .xlsx/.csv files"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing to DB"),
) -> None:
    """Import all trip sheets in a folder."""
    from trippy.importers.sheet_importer import SheetImporter

    if not folder.is_dir():
        console.print(f"[red]Not a directory:[/red] {folder}")
        raise typer.Exit(1)

    importer = SheetImporter()
    mode = "[yellow](dry-run)[/yellow] " if dry_run else ""
    console.print(f"{mode}[bold]Scanning:[/bold] {folder}")
    results = importer.import_folder(folder, dry_run=dry_run)

    if not results:
        console.print("[yellow]No .xlsx or .csv files found.[/yellow]")
        workflow_id = _record_cli_workflow(
            workflow_name="import-folder",
            summary=f"No importable trip sheets found in {folder}",
            result={"folder": str(folder), "files": 0, "dry_run": dry_run},
            status=WorkflowStatus.SKIPPED,
        )
        _print_workflow_footer(workflow_id)
        return

    total_created = total_updated = 0
    for r in results:
        _print_import_result(r)
        total_created += r.trips_created
        total_updated += r.trips_updated

    console.print(
        f"\n[bold]Total:[/bold] {len(results)} files · "
        f"{total_created} created · {total_updated} updated"
    )
    workflow_id = _record_cli_workflow(
        workflow_name="import-folder",
        summary=f"Imported trip sheets from {folder}",
        result={
            "folder": str(folder),
            "files": len(results),
            "trips_created": total_created,
            "trips_updated": total_updated,
            "dry_run": dry_run,
        },
        status=WorkflowStatus.SKIPPED if dry_run else WorkflowStatus.SUCCESS,
    )
    _print_workflow_footer(workflow_id)


@app.command("import-drive-folder")
def import_drive_folder_cmd(
    folder: str = typer.Argument(..., help="Google Drive folder URL or folder ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="List files without importing"),
) -> None:
    """Import all Google Sheets from a Drive folder."""
    from trippy.importers.drive_importer import DriveFolderImporter, _folder_id_from_url_or_id

    try:
        folder_id = _folder_id_from_url_or_id(folder)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    from trippy.ingest.google_auth import GoogleAuthManager

    importer = DriveFolderImporter(auth_manager=GoogleAuthManager())

    if dry_run:
        console.print(f"[yellow](dry-run)[/yellow] [bold]Listing sheets in:[/bold] {folder_id}")
        files = importer.list_files(folder_id)
        if not files:
            console.print("[yellow]No Google Sheets found in this folder.[/yellow]")
        for f in files:
            console.print(f"  · {f.get('name', '?')}  [dim]{f['id']}[/dim]")
        console.print(f"\nFound {len(files)} sheet(s). Run without --dry-run to import.")
        workflow_id = _record_cli_workflow(
            workflow_name="import-drive-folder",
            skill_name="trippy-past-trip-miner",
            summary=f"Previewed Google Sheets in Drive folder {folder_id}",
            result={"folder_id": folder_id, "files_found": len(files), "dry_run": True},
            status=WorkflowStatus.SKIPPED,
        )
        _print_workflow_footer(workflow_id)
        return

    console.print(f"[bold]Importing Drive folder:[/bold] {folder_id}")
    result = importer.import_folder(folder_id)
    console.print(f"Found {result.files_found} sheet(s).")
    for r in result.results:
        _print_import_result(r)
    console.print(
        f"\n[bold]Total:[/bold] {result.total_created} created · {result.total_updated} updated"
    )
    workflow_id = _record_cli_workflow(
        workflow_name="import-drive-folder",
        skill_name="trippy-past-trip-miner",
        summary=f"Imported Google Sheets from Drive folder {folder_id}",
        result={
            "folder_id": folder_id,
            "files_found": result.files_found,
            "trips_created": result.total_created,
            "trips_updated": result.total_updated,
            "errors": result.errors,
        },
        status=WorkflowStatus.FAILED if result.errors else WorkflowStatus.SUCCESS,
    )
    _print_workflow_footer(workflow_id)
    if result.errors:
        raise typer.Exit(1)


@app.command("list-trips")
def list_trips() -> None:
    """List all trips in the database."""
    from sqlalchemy import select

    from trippy.db import make_session_factory
    from trippy.db.models import Leg, Stay, Trip

    factory = make_session_factory()
    with factory() as session:
        trips = session.execute(select(Trip).order_by(Trip.start_date)).scalars().all()

    if not trips:
        console.print("[yellow]No trips found. Try: trippy import <file>[/yellow]")
        return

    t = Table(title="Trips", show_lines=True)
    t.add_column("ID", style="dim")
    t.add_column("Name", style="bold")
    t.add_column("Start", style="cyan")
    t.add_column("End", style="cyan")
    t.add_column("Status", style="green")
    t.add_column("Destination")
    t.add_column("Legs", justify="right")
    t.add_column("Stays", justify="right")

    factory2 = make_session_factory()
    with factory2() as session:
        for trip in trips:
            legs_count = session.query(Leg).filter_by(trip_id=trip.id).count()
            stays_count = session.query(Stay).filter_by(trip_id=trip.id).count()
            t.add_row(
                str(trip.id),
                trip.name,
                str(trip.start_date),
                str(trip.end_date or ""),
                trip.status.value,
                trip.destination_summary or "",
                str(legs_count),
                str(stays_count),
            )

    console.print(t)


@app.command("show")
def show_trip(
    name: str = typer.Argument(..., help="Trip name (partial match supported)"),
) -> None:
    """Show full details of a trip."""
    from sqlalchemy import select

    from trippy.db import make_session_factory
    from trippy.db.models import Trip

    factory = make_session_factory()
    with factory() as session:
        trips = session.execute(select(Trip).where(Trip.name.ilike(f"%{name}%"))).scalars().all()
        if not trips:
            console.print(f"[red]No trip matching:[/red] {name}")
            raise typer.Exit(1)
        if len(trips) > 1:
            console.print(f"[yellow]Multiple matches ({len(trips)}):[/yellow]")
            for tr in trips:
                console.print(f"  [{tr.id}] {tr.name} ({tr.start_date})")
            console.print("Be more specific.")
            raise typer.Exit(1)

        trip = trips[0]
        _print_trip_detail(trip)


@app.command("ingest-emails")
def ingest_emails(
    max_results: int = typer.Option(50, "--max", help="Max emails to fetch"),
    label: str = typer.Option("INBOX", "--label", help="Gmail label to fetch from"),
    query: str = typer.Option("", "--query", help="Optional Gmail search query override"),
    trip_id: str = typer.Option("", "--trip-id", help="Only reconcile confirmations for this trip"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing state"),
) -> None:
    """Fetch new booking confirmation emails from Gmail and ingest them."""
    from trippy.skills.runners.gmail_reconciler import GmailReconcilerRunner

    mode = "[yellow](dry-run)[/yellow] " if dry_run else ""
    console.print(
        f"{mode}[bold]Reconciling[/bold] up to {max_results} Gmail messages from {label}…"
    )
    result = GmailReconcilerRunner().run(
        {
            "max_emails": max_results,
            "label": label,
            "query": query or None,
            "trip_id": trip_id or None,
            "dry_run": dry_run,
        }
    )
    _print_reconcile_summary(result)
    workflow_id = _record_cli_workflow(
        workflow_name="gmail-reconciler",
        skill_name="trippy-gmail-reconciler",
        trip_id=trip_id or result.get("target_trip_id"),
        summary="Reconciled Gmail booking confirmations",
        result=result,
        status=WorkflowStatus.SKIPPED if dry_run else WorkflowStatus.SUCCESS,
    )
    _print_workflow_footer(workflow_id)


@app.command("friction-audit")
def friction_audit(
    trip_name: str = typer.Argument(..., help="Trip name or ID to audit"),
) -> None:
    """Run a friction and risk audit on a trip."""
    from trippy import config
    from trippy.memory.store import MemoryStore
    from trippy.models.preferences import FamilyTravelPreferences
    from trippy.services.friction_detector import FrictionDetector
    from trippy.services.trip_state import TripStateService

    trip_svc = TripStateService()
    memory = MemoryStore(config.MEMORY_PATH)

    # Try by ID first, then search
    trip = trip_svc.load(trip_name.lower().replace(" ", "-"))
    if trip is None:
        all_trips = trip_svc.load_all()
        matches = [t for t in all_trips if trip_name.lower() in t.name.lower()]
        if not matches:
            console.print(f"[red]No trip found matching:[/red] {trip_name}")
            raise typer.Exit(1)
        trip = matches[0]

    raw = memory.get_value("pref:preferences_object")
    prefs = FamilyTravelPreferences.model_validate(raw) if raw else FamilyTravelPreferences()
    detector = FrictionDetector(preferences=prefs)
    risks = detector.audit(trip)

    if not risks:
        console.print(f"[green]✓ No risks found for {trip.name}[/green]")
        workflow_id = _record_cli_workflow(
            workflow_name="friction-audit",
            skill_name="trippy-flight-friction-audit",
            trip_id=trip.trip_id,
            summary=f"No risks found for {trip.name}",
            result={"trip_id": trip.trip_id, "total_risks": 0},
            status=WorkflowStatus.SUCCESS,
        )
        _print_workflow_footer(workflow_id)
        return

    t = Table(title=f"Friction Audit: {trip.name}", show_lines=True)
    t.add_column("Severity", style="bold")
    t.add_column("Category")
    t.add_column("Issue")
    t.add_column("Fix")

    for r in risks:
        colors = {"critical": "red", "high": "red", "medium": "yellow", "low": "dim"}
        c = colors.get(r.severity.value, "white")
        t.add_row(
            f"[{c}]{r.severity.value.upper()}[/{c}]",
            r.category,
            r.description[:80],
            (r.recommended_fix or "")[:60],
        )
    console.print(t)
    workflow_id = _record_cli_workflow(
        workflow_name="friction-audit",
        skill_name="trippy-flight-friction-audit",
        trip_id=trip.trip_id,
        summary=f"Found {len(risks)} risk(s) for {trip.name}",
        result={
            "trip_id": trip.trip_id,
            "total_risks": len(risks),
            "high": len([r for r in risks if r.severity.value == "high"]),
            "critical": len([r for r in risks if r.severity.value == "critical"]),
        },
        status=WorkflowStatus.SUCCESS,
    )
    _print_workflow_footer(workflow_id)


@app.command("phase-status")
def phase_status() -> None:
    """Show roadmap phases 2-6 and what is blocked next."""
    from trippy.services.phase_planner import PhasePlannerService

    planner = PhasePlannerService()
    phases = planner.status()

    table = Table(title="Trippy Roadmap Status", show_lines=True)
    table.add_column("Phase", style="bold")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Blockers")
    table.add_column("Next Step")

    for phase in phases:
        status = "[green]Complete[/green]" if phase.complete else "[yellow]Pending[/yellow]"
        blockers = "None" if not phase.blockers else " • ".join(phase.blockers)
        table.add_row(
            f"{phase.phase}",
            phase.title,
            status,
            blockers,
            phase.next_step,
        )

    console.print(table)

    pending = [p for p in phases if not p.complete]
    if pending:
        next_phase = pending[0]
        console.print(
            f"\n[bold]Next actionable phase:[/bold] Phase {next_phase.phase} — {next_phase.title}"
        )


@app.command("phase-run")
def phase_run(
    phase: int = typer.Argument(..., help="Roadmap phase number (2-6)"),
    folder_id: str = typer.Option("", "--folder-id", help="Drive folder ID (phase 3/4)"),
    query: str = typer.Option("", "--query", help="Drive/Gmail query override"),
    max_sheets: int = typer.Option(50, "--max-sheets", help="Max sheets to scan (phase 3)"),
    min_evidence_trips: int = typer.Option(
        2, "--min-evidence-trips", help="Trips required for preference extraction (phase 3)"
    ),
    trip_idea: str = typer.Option("", "--trip-idea", help="Trip idea text (phase 4)"),
    template_sheet_id: str = typer.Option("", "--template-sheet-id", help="Sheet template ID"),
    max_emails: int = typer.Option(50, "--max-emails", help="Max emails to reconcile (phase 5)"),
    trip_id: str = typer.Option("", "--trip-id", help="Trip ID for friction audit (phase 6)"),
    label: str = typer.Option("INBOX", "--label", help="Gmail label for phase 5"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview phase workflow without writes where supported"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Run one roadmap phase workflow and print structured output."""
    from trippy.services.phase_planner import PhasePlannerService

    if phase < 2 or phase > 6:
        console.print("[red]Phase must be between 2 and 6.[/red]")
        raise typer.Exit(1)

    planner = PhasePlannerService()
    result = planner.run_phase(
        phase=phase,
        folder_id=folder_id or None,
        query=query or ("trip" if phase == 3 else None),
        max_sheets=max_sheets,
        min_evidence_trips=min_evidence_trips,
        trip_idea=trip_idea,
        template_sheet_id=template_sheet_id or None,
        max_emails=max_emails,
        trip_id=trip_id or None,
        label=label,
        dry_run=dry_run,
    )

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)

    workflow_id = _record_cli_workflow(
        workflow_name=f"phase-{phase}",
        skill_name=_phase_skill_name(phase),
        trip_id=trip_id or _result_trip_id(result),
        summary=f"Ran roadmap phase {phase}",
        result=result,
        status=_phase_workflow_status(result, dry_run=dry_run),
    )
    result["workflow_id"] = workflow_id

    if json_output:
        _print_json(result)
    else:
        _print_phase_run_summary(result)
        _print_workflow_footer(workflow_id)


@app.command("feedback")
def feedback(
    workflow_id: str = typer.Argument(..., help="Workflow ID printed by Trippy"),
    rating: FeedbackRating = typer.Option(..., "--rating", help="helpful, needs-work, or wrong"),
    notes: str = typer.Option(..., "--notes", help="What was helpful or wrong"),
    correction: str = typer.Option("", "--correction", help="Corrected behavior or preference"),
    future_learning: bool = typer.Option(
        False,
        "--future-learning",
        help="Create reviewable memory/skill proposals from this feedback",
    ),
) -> None:
    """Attach explicit feedback to a workflow and optionally create learning proposals."""
    from trippy.services.learning import LearningEventStore, UserFeedback

    store = LearningEventStore()
    fb = UserFeedback(
        workflow_id=workflow_id,
        rating=rating,
        notes=notes,
        correction=correction or None,
        future_learning=future_learning,
    )
    proposals = store.add_feedback(fb)
    console.print(f"[green]Feedback recorded:[/green] {fb.id}")
    if future_learning:
        if proposals:
            console.print(f"Created {len(proposals)} reviewable learning proposal(s).")
            console.print("Review with: [bold]trippy learn review[/bold]")
        else:
            console.print(
                "[yellow]No proposals created. Check that the workflow ID exists.[/yellow]"
            )


@learn_app.command("review")
def learn_review(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Show pending memory and skill learning proposals."""
    from trippy.services.learning import LearningEventStore

    proposals = LearningEventStore().list_proposals()
    if json_output:
        _print_json([p.model_dump(mode="json") for p in proposals])
        return
    _print_learning_proposals(proposals)


@learn_app.command("approve")
def learn_approve(
    proposal_id: str = typer.Argument(..., help="Learning proposal ID"),
) -> None:
    """Approve and apply a pending learning proposal."""
    from trippy.services.learning import LearningEventStore

    proposal = LearningEventStore().approve(proposal_id)
    console.print(f"[green]Approved:[/green] {proposal.id} — {proposal.summary}")


@learn_app.command("reject")
def learn_reject(
    proposal_id: str = typer.Argument(..., help="Learning proposal ID"),
) -> None:
    """Reject a pending learning proposal."""
    from trippy.services.learning import LearningEventStore

    proposal = LearningEventStore().reject(proposal_id)
    console.print(f"[yellow]Rejected:[/yellow] {proposal.id} — {proposal.summary}")


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


def _load_canonical_trip_or_exit(trip_name: str) -> Any:
    from trippy.services.trip_state import TripStateService

    trip_svc = TripStateService()
    trip = trip_svc.load(trip_name.lower().replace(" ", "-"))
    if trip is not None:
        return trip
    matches = [t for t in trip_svc.load_all() if trip_name.lower() in t.name.lower()]
    if not matches:
        console.print(f"[red]No canonical trip found matching:[/red] {trip_name}")
        raise typer.Exit(1)
    return matches[0]


def _print_json(data: Any) -> None:
    typer.echo(json_lib.dumps(data, indent=2, sort_keys=True, default=str))


def _record_cli_workflow(
    *,
    workflow_name: str,
    summary: str,
    result: dict[str, Any],
    status: WorkflowStatus,
    skill_name: str | None = None,
    trip_id: str | None = None,
) -> str:
    from trippy.services.learning import LearningEventStore

    ended_at = datetime.utcnow()
    safe_result = _jsonable(result)
    metrics = _numeric_metrics(safe_result)
    outcome = WorkflowOutcome(
        workflow_name=workflow_name,
        skill_name=skill_name,
        trip_id=trip_id,
        status=status,
        started_at=ended_at,
        ended_at=ended_at,
        summary=summary,
        metrics=metrics,
        artifacts={"result": safe_result},
    )
    LearningEventStore().record_workflow(outcome)
    return outcome.id


def _jsonable(value: object) -> dict[str, Any]:
    raw = json_lib.dumps(value, default=str)
    loaded = json_lib.loads(raw)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _numeric_metrics(result: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, (int, float, bool, str)) or value is None:
            metrics[key] = value
    return metrics


def _print_workflow_footer(workflow_id: str) -> None:
    console.print(f"\n[dim]Workflow ID:[/dim] {workflow_id}")
    console.print(
        "[dim]Feedback:[/dim] "
        f'trippy feedback {workflow_id} --rating helpful --notes "..." --future-learning'
    )


def _print_setup_report(report: Any) -> None:
    checks = report.checks
    table = Table(title="Trippy Setup", show_lines=True)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Summary")
    table.add_column("Detail")
    colors = {"pass": "green", "warn": "yellow", "fail": "red", "skip": "dim"}
    for check in checks:
        status = check.status.value
        color = colors.get(status, "white")
        table.add_row(
            check.name,
            f"[{color}]{status.upper()}[/{color}]",
            check.summary,
            check.detail or "",
        )
    console.print(table)
    next_actions = getattr(report, "next_actions", [])
    if next_actions:
        console.print("\n[bold]Next actions[/bold]")
        for action in next_actions:
            console.print(f"  · {action}")


def _print_reconcile_summary(result: dict[str, Any]) -> None:
    dry = " [yellow](dry-run)[/yellow]" if result.get("dry_run") else ""
    console.print(
        f"\n[bold]Done{dry}.[/bold] "
        f"{result.get('confirmations_linked', 0)} linked · "
        f"{result.get('confirmations_unlinked', 0)} unlinked · "
        f"{result.get('parse_failures', 0)} parse failures"
    )
    updates = result.get("updates", [])
    if isinstance(updates, list):
        for update in updates[:10]:
            if isinstance(update, dict):
                console.print(
                    "  [green]✓[/green] "
                    f"{update.get('confirmation_code')} → {update.get('trip_canonical_id')}"
                )
    ambiguities = result.get("ambiguities", [])
    if isinstance(ambiguities, list) and ambiguities:
        console.print(f"  [yellow]{len(ambiguities)} item(s) need review.[/yellow]")


def _phase_skill_name(phase: int) -> str | None:
    return {
        3: "trippy-past-trip-miner",
        4: "trippy-trip-sheet-creator",
        5: "trippy-gmail-reconciler",
        6: "trippy-flight-friction-audit",
    }.get(phase)


def _phase_workflow_status(result: dict[str, Any], *, dry_run: bool) -> WorkflowStatus:
    if dry_run:
        return WorkflowStatus.SKIPPED
    if result.get("error") or result.get("setup_ok") is False:
        return WorkflowStatus.FAILED
    return WorkflowStatus.SUCCESS


def _result_trip_id(result: dict[str, Any]) -> str | None:
    for key in ("created", "reconciled", "audit"):
        value = result.get(key)
        if isinstance(value, dict) and value.get("trip_id"):
            return str(value["trip_id"])
    return None


def _print_phase_run_summary(result: dict[str, Any]) -> None:
    phase = result.get("phase")
    console.print(f"[bold]Phase {phase} complete.[/bold]")
    if phase == 2:
        checks = result.get("checks", [])
        failed = [c for c in checks if isinstance(c, dict) and c.get("status") in {"fail", "skip"}]
        if failed:
            for check in failed:
                console.print(f"  [red]✗[/red] {check.get('summary')}")
        else:
            console.print("  [green]✓[/green] Setup checks passed.")
    elif phase == 3:
        mined = result.get("mined", {})
        extracted = result.get("extracted", {})
        if isinstance(mined, dict):
            console.print(
                f"  Trips imported: {mined.get('trips_imported', 0)} · "
                f"updated: {mined.get('trips_updated', 0)}"
            )
        if isinstance(extracted, dict):
            prefs = extracted.get("preferences_proposed", {})
            proposals = extracted.get("learning_proposals", [])
            console.print(f"  Preferences proposed: {len(prefs) if isinstance(prefs, dict) else 0}")
            if isinstance(proposals, list) and proposals:
                console.print(f"  Review-gated learning proposals: {len(proposals)}")
    elif phase == 4:
        created = result.get("created", {})
        if isinstance(created, dict):
            console.print(f"  Trip: {created.get('trip_id')} — {created.get('trip_name')}")
            if created.get("sheet_url"):
                console.print(f"  Sheet: {created.get('sheet_url')}")
            if created.get("sheet_error"):
                console.print(f"  [yellow]Sheet error:[/yellow] {created.get('sheet_error')}")
    elif phase == 5:
        reconciled = result.get("reconciled", {})
        if isinstance(reconciled, dict):
            _print_reconcile_summary(reconciled)
    elif phase == 6:
        audit = result.get("audit", {})
        if isinstance(audit, dict):
            console.print(
                f"  Risks: {audit.get('total_risks', 0)} "
                f"({audit.get('critical', 0)} critical, {audit.get('high', 0)} high)"
            )


def _print_learning_proposals(proposals: list[Any]) -> None:
    if not proposals:
        console.print("[green]No pending learning proposals.[/green]")
        return
    table = Table(title="Pending Learning Proposals", show_lines=True)
    table.add_column("ID", style="dim")
    table.add_column("Type")
    table.add_column("Summary")
    table.add_column("Source")
    for proposal in proposals:
        table.add_row(
            proposal.id,
            proposal.proposal_type.value,
            proposal.summary,
            proposal.source_workflow_id or "",
        )
    console.print(table)
    console.print("\nApprove with: [bold]trippy learn approve <proposal-id>[/bold]")


def _print_intelligence_report(report: Any) -> None:
    console.print(f"[bold]{report.summary}[/bold]")
    table = Table(title="Travel Intelligence Signals", show_lines=True)
    table.add_column("Key", style="dim")
    table.add_column("Category")
    table.add_column("Confidence")
    table.add_column("Rationale")
    for signal in report.all_signals[:20]:
        table.add_row(
            signal.key,
            signal.category.value,
            f"{signal.confidence:.0%}",
            signal.rationale,
        )
    console.print(table)


def _print_trip_ideas(comparison: Any) -> None:
    table = Table(title="Ranked Trip Concepts", show_lines=True)
    table.add_column("Score", justify="right")
    table.add_column("Concept", style="bold")
    table.add_column("Duration")
    table.add_column("Cost Band")
    table.add_column("Travel")
    table.add_column("Fit Notes")
    for concept in comparison.concepts:
        marker = (
            " [green]recommended[/green]"
            if concept.concept_id == comparison.recommended_concept_id
            else ""
        )
        table.add_row(
            str(concept.total_score),
            concept.title + marker,
            f"{concept.recommended_duration_days} days",
            concept.estimated_cost_band_cad,
            concept.estimated_travel_burden,
            "; ".join(concept.rationale[:2]),
        )
    console.print(table)
    console.print("\n[bold]Required research before booking[/bold]")
    if comparison.concepts:
        for item in comparison.concepts[0].required_research:
            console.print(f"  · {item}")
    for note in comparison.scoring_notes:
        console.print(f"[dim]{note}[/dim]")


def _split_cli_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def _normalise_enum_value(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _parse_optional_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Expected date as YYYY-MM-DD, got {value!r}") from exc


def _parse_traveler_specs(values: list[str]) -> list[Any]:
    from trippy.models.trip_planning import TravelerAgeBand, TripTraveler

    travelers = []
    for raw in _split_cli_list(values):
        parts = [part.strip() for part in raw.replace(":", "|").split("|") if part.strip()]
        if not parts:
            continue
        name = parts[0]
        age = None
        age_band = None
        notes = None
        for part in parts[1:]:
            normalized = _normalise_enum_value(part)
            if part.isdigit():
                age = int(part)
            elif normalized in {band.value for band in TravelerAgeBand}:
                age_band = TravelerAgeBand(normalized)
            else:
                notes = part if notes is None else f"{notes}; {part}"
        travelers.append(TripTraveler(name=name, age=age, age_band=age_band, notes=notes))
    return travelers


def _print_trip_intake(intake: Any) -> None:
    table = Table(title=f"Trip Intake: {intake.trip_name}", show_lines=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Trip ID", intake.trip_id)
    table.add_row("Mode", intake.mode.value)
    table.add_row("Destinations", ", ".join(intake.destination_seeds) or "TBD")
    table.add_row("Travel Window", intake.travel_window.display())
    table.add_row("Duration", intake.duration_display())
    table.add_row("Travelers", intake.party_summary())
    table.add_row("Roster", ", ".join(intake.party.traveler_labels()) or "TBD")
    if intake.party.sleeping_considerations:
        table.add_row("Sleeping", intake.party.sleeping_considerations)
    if intake.party.privacy_needs:
        table.add_row("Privacy", intake.party.privacy_needs)
    if intake.party.mobility_notes:
        table.add_row("Mobility", intake.party.mobility_notes)
    table.add_row("Departure", ", ".join(intake.departure_airports))
    table.add_row("Goals", ", ".join(intake.goals))
    table.add_row("Avoidances", ", ".join(intake.avoidances))
    table.add_row("Pace", intake.pace.value)
    table.add_row("Crowd", intake.crowd_tolerance.value)
    table.add_row("Food", intake.food_priority.value)
    console.print(table)


def _print_trip_plan_draft(draft: Any) -> None:
    table = Table(title=f"Trip Plan Draft: {draft.trip_id}", show_lines=True)
    table.add_column("Strength", justify="right")
    table.add_column("Option", style="bold")
    table.add_column("Regions")
    table.add_column("Movement")
    table.add_column("Comfort", justify="right")
    table.add_column("Summary")
    for option in draft.options:
        marker = ""
        if option.option_id == draft.selected_option_id:
            marker = " [green]selected[/green]"
        elif option.option_id == draft.recommended_option_id:
            marker = " [green]recommended[/green]"
        table.add_row(
            str(option.recommendation_strength),
            f"{option.title}{marker}\n[dim]{option.option_id}[/dim]",
            ", ".join(option.regions),
            option.island_region_movement_friction,
            str(option.family_comfort_score),
            option.summary,
        )
    console.print(table)
    if draft.assumptions:
        console.print("\n[bold]Assumptions[/bold]")
        for item in draft.assumptions:
            console.print(f"  · {item}")


def _print_trip_workspace(state: Any) -> None:
    console.print(f"[bold]Workspace {state.status.value}:[/bold] {state.trip_id}")
    console.print(f"Plan option: {state.plan_option_id}")
    if state.google_sheet_url:
        console.print(f"Google Sheet: {state.google_sheet_url}")
    if state.local_workspace_path:
        console.print(f"Local workspace: {state.local_workspace_path}")
    console.print("Tabs: " + ", ".join(tab.name for tab in state.tabs))
    if state.warnings:
        console.print("\n[bold yellow]Warnings[/bold yellow]")
        for warning in state.warnings:
            console.print(f"  · {warning}")
    if state.next_actions:
        console.print("\n[bold]Next actions[/bold]")
        for action in state.next_actions:
            console.print(f"  · {action}")


def _run_shortlist_command(
    *,
    trip_id: str,
    workflow_name: str,
    summary: str,
    state: Any,
    propose_learning: bool,
    json_output: bool,
) -> None:
    workflow_id = _record_cli_workflow(
        workflow_name=workflow_name,
        trip_id=trip_id,
        summary=f"{summary} for {trip_id}",
        result=state.model_dump(mode="json"),
        status=WorkflowStatus.SUCCESS if state.option_count else WorkflowStatus.SKIPPED,
    )
    proposals = []
    if propose_learning:
        from trippy.services.planning_learning import PlanningLearningService

        proposals = PlanningLearningService().propose_for_trip(
            trip_id,
            source_workflow_id=workflow_id,
        )
    payload = {
        "workflow_id": workflow_id,
        "shortlist": state.model_dump(mode="json"),
        "learning_proposals": [proposal.id for proposal in proposals],
    }
    if json_output:
        _print_json(payload)
        return
    _print_shortlist(state)
    if proposals:
        console.print(f"\nCreated {len(proposals)} review-gated learning proposal(s).")
        console.print("Review with: [bold]trippy learn review[/bold]")
    _print_workflow_footer(workflow_id)


def _print_shortlist(state: Any) -> None:
    table = Table(
        title=f"{state.category.value.title()} Shortlist: {state.trip_id}", show_lines=True
    )
    table.add_column("Rank", justify="right")
    table.add_column("Option", style="bold")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Verification")
    table.add_column("Adapter")
    table.add_column("Freshness")
    table.add_column("Confidence")
    table.add_column("Score")
    table.add_column("Why / Tradeoffs")

    for option in state.options_as_dicts():
        source = option.get("booking_source") or option.get("source") or option.get("deep_link", "")
        name = (
            option.get("airline")
            or option.get("name")
            or option.get("vehicle_class")
            or option.get("activity_name")
            or option.get("option_id")
        )
        score = (
            option.get("family_comfort_score")
            or option.get("total_friction_score")
            or option.get("friction_score")
            or ""
        )
        tradeoffs = option.get("tradeoffs", [])
        flags = option.get("friction_flags", [])
        validation = option.get("validation", {}) or {}
        details = "; ".join(
            item
            for item in [
                str(option.get("recommendation_label", "")),
                str(option.get("recommendation_rationale", "")),
                str(option.get("date_viability_signal", "")),
                *(tradeoffs or [])[:1],
                *(flags or [])[:2],
            ]
            if item
        )
        table.add_row(
            str(option.get("rank", "")),
            f"{name}\n[dim]{option.get('option_id')}[/dim]",
            str(source),
            str(option.get("row_status", "")),
            str(validation.get("verification_status", "")),
            str(validation.get("adapter_used", "")),
            str(validation.get("freshness_status", "")),
            f"{float(validation.get('confidence', 0)):.0%}" if validation else "",
            str(score),
            details,
        )
    console.print(table)
    if state.recommended_option_id:
        console.print(f"Recommended: [bold]{state.recommended_option_id}[/bold]")
    if state.recommendation_summary:
        console.print(state.recommendation_summary)
    if state.warnings:
        console.print("\n[bold yellow]Warnings[/bold yellow]")
        for warning in state.warnings:
            console.print(f"  · {warning}")
    if state.next_actions:
        console.print("\n[bold]Next actions[/bold]")
        for action in state.next_actions:
            console.print(f"  · {action}")


def _print_sources(sources: list[Any]) -> None:
    table = Table(title="Travel Source Registry", show_lines=True)
    table.add_column("Platform", style="bold")
    table.add_column("Categories")
    table.add_column("Confidence")
    table.add_column("Access")
    table.add_column("Prefer When")
    for source in sources:
        table.add_row(
            source.platform_name,
            ", ".join(category.value for category in source.categories),
            source.confidence_level.value,
            ", ".join(mode.value for mode in source.access_modes),
            "; ".join(source.prefer_when[:2]),
        )
    console.print(table)


def _print_source_plan(plan: Any) -> None:
    table = Table(title=f"Source Routing: {plan.category.value}", show_lines=True)
    table.add_column("Role", style="bold")
    table.add_column("Sources")
    for role in ("primary", "secondary", "validation"):
        sources = getattr(plan, role)
        table.add_row(role, ", ".join(source.platform_name for source in sources) or "None")
    console.print(table)
    for note in plan.notes:
        console.print(f"  · {note}")


def _print_country_priors(priors: list[Any]) -> None:
    table = Table(title="Historical Country Priors", show_lines=True)
    table.add_column("Country", style="bold")
    table.add_column("Rating")
    table.add_column("Band")
    table.add_column("Positive Signals")
    table.add_column("Cautions")
    for prior in priors:
        table.add_row(
            prior.country,
            str(prior.rating) if prior.rating is not None else "",
            prior.band.value,
            ", ".join(prior.positive_signals[:4]),
            ", ".join(prior.caution_signals[:4]),
        )
    console.print(table)
    console.print(
        "[dim]Country priors are directional. Trip goals, season, sub-region, logistics, "
        "and newer evidence can override them.[/dim]"
    )


def _print_map_artifact(artifact: Any) -> None:
    console.print(f"[bold]{artifact.title}[/bold]")
    console.print(f"Pins: {len(artifact.pins)} · Routes: {len(artifact.routes)}")
    for pin in artifact.pins[:8]:
        console.print(f"  · {pin.label}: {pin.google_maps_url}")
    if artifact.exports:
        console.print("\n[bold]Exports[/bold]")
        for label, path in artifact.exports.items():
            console.print(f"  · {label}: {path}")


def _print_dashboard_summary(data: Any) -> None:
    console.print("[bold]Dashboard built.[/bold]")
    console.print(
        f"Past trips: {len(data.past_trips)} · "
        f"Planned trips: {len(data.planned_trips)} · Ideas: {len(data.ideas)}"
    )
    if data.exports:
        for label, path in data.exports.items():
            console.print(f"  · {label}: {path}")


def _print_import_result(result: ImportResultType) -> None:
    src = result.source
    if result.errors:
        console.print(f"[red]✗[/red] {src}")
        for e in result.errors:
            console.print(f"  [red]error:[/red] {e}")
        return
    console.print(
        f"[green]✓[/green] {src} — {result.trips_created} created, {result.trips_updated} updated"
    )
    if result.parsing_notes:
        console.print(f"  [dim]notes:[/dim] {result.parsing_notes}")
    if result.flagged_fields:
        console.print(f"  [yellow]⚠ {len(result.flagged_fields)} low-confidence field(s):[/yellow]")
        for ff in result.flagged_fields:
            console.print(
                f"    [yellow]{ff.section}.{ff.field}[/yellow] = "
                f"{ff.value!r} (conf={ff.confidence:.2f})"
            )


def _print_trip_detail(trip: TripModel) -> None:
    console.print(f"\n[bold cyan]{'=' * 50}[/bold cyan]")
    console.print(f"[bold]{trip.name}[/bold]  [dim](ID: {trip.id})[/dim]")
    console.print(f"  Dates:  {trip.start_date} → {trip.end_date or '?'}")
    console.print(f"  Status: {trip.status.value}")
    if trip.destination_summary:
        console.print(f"  Where:  {trip.destination_summary}")
    if trip.travelers:
        console.print("\n  [bold]Travelers[/bold]")
        for t in trip.travelers:
            passport = (
                f"{t.passport_country} exp {t.passport_expiry}"
                if t.passport_country
                else "no passport on file"
            )
            console.print(f"    · {t.name} ({passport})")
    if trip.legs:
        console.print("\n  [bold]Legs[/bold]")
        for leg in trip.legs:
            parts = [f"{leg.leg_type.value.upper()} {leg.origin}→{leg.destination}"]
            if leg.carrier:
                parts.append(leg.carrier)
            if leg.flight_number:
                parts.append(leg.flight_number)
            if leg.depart_at:
                parts.append(str(leg.depart_at))
            if leg.cost_cad:
                parts.append(f"CAD {leg.cost_cad:,.0f}")
            console.print("    · " + "  ".join(parts))
    if trip.stays:
        console.print("\n  [bold]Stays[/bold]")
        for stay in trip.stays:
            parts = [stay.property_name]
            if stay.city:
                parts.append(stay.city)
            if stay.check_in:
                parts.append(f"{stay.check_in} → {stay.check_out}")
            if stay.cost_cad:
                parts.append(f"CAD {stay.cost_cad:,.0f}")
            console.print("    · " + "  ".join(parts))
    console.print(f"[bold cyan]{'=' * 50}[/bold cyan]\n")


if __name__ == "__main__":
    app()
