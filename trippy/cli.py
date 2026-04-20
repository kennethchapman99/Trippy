"""Trippy CLI — entry point `trippy`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

if TYPE_CHECKING:
    from trippy.db.models import Trip as TripModel
    from trippy.importers.sheet_importer import ImportResult as ImportResultType

app = typer.Typer(name="trippy", help="Chapman family travel concierge.")
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


@app.command("thin-slice")
def thin_slice(
    real_google: bool = typer.Option(False, "--real-google", help="Use real Google credentials"),
) -> None:
    """Run the end-to-end thin slice demo."""
    from trippy.thin_slice import run_thin_slice

    run_thin_slice(real_google=real_google)


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
        return

    console.print(f"[bold]Importing Drive folder:[/bold] {folder_id}")
    result = importer.import_folder(folder_id)
    console.print(f"Found {result.files_found} sheet(s).")
    for r in result.results:
        _print_import_result(r)
    console.print(
        f"\n[bold]Total:[/bold] {result.total_created} created · {result.total_updated} updated"
    )
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
) -> None:
    """Fetch new booking confirmation emails from Gmail and ingest them."""
    from trippy import config
    from trippy.db import make_session_factory
    from trippy.ingest.gmail_watcher import GmailWatcher
    from trippy.ingest.google_auth import GoogleAuthManager
    from trippy.ingest.linker import ingest_email
    from trippy.ingest.parser import ConfirmationParser

    auth = GoogleAuthManager()
    watcher = GmailWatcher(auth_manager=auth)
    watcher.authenticate()

    console.print(f"[bold]Fetching[/bold] up to {max_results} messages from {label}…")
    emails = watcher.fetch_new_messages(label=label, max_results=max_results)
    console.print(f"Found {len(emails)} message(s) from trusted senders.")

    parser = ConfirmationParser()
    factory = make_session_factory()
    linked = unlinked = skipped = 0

    for email_content in emails:
        eml_path = watcher.save_to_vault(email_content, config.VAULT_PATH)
        atts = [(a.filename, a.content_type, a.data) for a in email_content.attachments]
        result = parser.parse(
            body_text=email_content.body_text,
            body_html=email_content.body_html,
            attachments=atts,
            eml_path=eml_path,
        )
        if not result.ok or result.confirmation is None:
            console.print(f"  [yellow]skipped[/yellow] {email_content.subject!r}: {result.error}")
            skipped += 1
            continue

        with factory() as session:
            link = ingest_email(result.confirmation, session, raw_email_path=str(eml_path))

        icon = "[green]✓[/green]" if link.linked else "[yellow]?[/yellow]"
        trip_label = f"trip {link.trip_id}" if link.linked else "unlinked inbox"
        console.print(
            f"  {icon} {result.confirmation.confirmation_code!r} "
            f"({result.confirmation.vendor}) → {trip_label} [{link.method}]"
        )
        if link.linked:
            linked += 1
        else:
            unlinked += 1

    console.print(f"\n[bold]Done.[/bold] {linked} linked · {unlinked} unlinked · {skipped} skipped")


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


@app.command("phase-status")
def phase_status() -> None:
    """Show roadmap phases 2-8 and what is blocked next."""
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




@app.command("phase-ready-new-trip")
def phase_ready_new_trip() -> None:
    """Check if Trippy is ready for a high-quality new trip test."""
    from trippy.services.phase_planner import PhasePlannerService

    planner = PhasePlannerService()
    readiness = planner.new_trip_test_readiness()
    console.print(JSON.from_data(readiness))

    if readiness.get("ready"):
        console.print("\n[green]Ready: run trippy phase-run 4 --trip-idea \"<your trip idea>\"[/green]")
    else:
        failing = readiness.get("failing") or []
        if failing:
            next_phase = failing[0]
            console.print(
                f"\n[yellow]Not ready yet.[/yellow] Next: Phase {next_phase['phase']} — {next_phase['title']}"
            )
@app.command("phase-run")
def phase_run(
    phase: int = typer.Argument(..., help="Roadmap phase number (2-8)"),
    folder_id: str = typer.Option("", "--folder-id", help="Drive folder ID (phase 3/4)"),
    query: str = typer.Option("trip", "--query", help="Drive search query (phase 3)"),
    max_sheets: int = typer.Option(50, "--max-sheets", help="Max sheets to scan (phase 3)"),
    min_evidence_trips: int = typer.Option(
        2, "--min-evidence-trips", help="Trips required for preference extraction (phase 3)"
    ),
    trip_idea: str = typer.Option("", "--trip-idea", help="Trip idea text (phase 4)"),
    template_sheet_id: str = typer.Option("", "--template-sheet-id", help="Sheet template ID"),
    max_emails: int = typer.Option(50, "--max-emails", help="Max emails to reconcile (phase 5)"),
    trip_id: str = typer.Option("", "--trip-id", help="Trip ID for friction audit (phase 6)"),
) -> None:
    """Run one roadmap phase workflow and print structured output."""
    from trippy.services.phase_planner import PhasePlannerService

    if phase < 2 or phase > 8:
        console.print("[red]Phase must be between 2 and 8.[/red]")
        raise typer.Exit(1)

    planner = PhasePlannerService()
    result = planner.run_phase(
        phase=phase,
        folder_id=folder_id or None,
        query=query,
        max_sheets=max_sheets,
        min_evidence_trips=min_evidence_trips,
        trip_idea=trip_idea,
        template_sheet_id=template_sheet_id or None,
        max_emails=max_emails,
        trip_id=trip_id or None,
    )

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)

    console.print(JSON.from_data(result))


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


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
