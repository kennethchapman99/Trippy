"""Trippy thin slice — end-to-end demo of the full product direction.

This script proves the architecture by running the complete flow:
1. Load a past trip from canonical state (or seed from JSON)
2. Propose durable preferences from the trip
3. Propose family profile updates
4. Start a new trip from a rough idea
5. Create a Google Sheet from template (mocked if no credentials)
6. Ingest one booking confirmation email (from fixture or Gmail)
7. Update canonical trip state
8. Run a friction audit and display results

Run with:
    uv run python -m trippy.thin_slice
    uv run python -m trippy.thin_slice --real-google  # uses real credentials
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trippy.models.trip import Trip

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)


def run_thin_slice(
    real_google: bool = False,
    trips_dir: Path | None = None,
    memory_path: Path | None = None,
) -> dict[str, Any]:
    """Execute the complete thin-slice flow. Returns a results dict."""
    from trippy import config
    from trippy.memory.store import MemoryStore
    from trippy.models.trip import (
        ChecklistItem,
        Confirmation,
        ConfirmationType,
        Segment,
        SegmentType,
        Stay,
        StayType,
        Traveler,
        Trip,
        TripStatus,
    )
    from trippy.services.friction_detector import FrictionDetector
    from trippy.services.trip_state import TripStateService
    from trippy.skills.runners.preference_extractor import PreferenceExtractorRunner

    trips_dir = trips_dir or config.TRIPS_PATH
    memory_path = memory_path or config.MEMORY_PATH

    memory = MemoryStore(memory_path)
    trip_svc = TripStateService(trips_dir=trips_dir)
    results: dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # STEP 1: Seed or load a past trip
    # -----------------------------------------------------------------------
    console.print(Panel("[bold]Step 1:[/bold] Load past trip (Japan 2026)", style="cyan"))

    seed_path = Path(__file__).parent.parent / "tests" / "fixtures" / "seed.json"
    past_trip: Trip | None = None

    if seed_path.exists():
        seed_data = json.loads(seed_path.read_text(encoding="utf-8"))
        trips_seed = (
            seed_data if isinstance(seed_data, list) else seed_data.get("trips", [seed_data])
        )
        for t in trips_seed:
            if "japan" in t.get("name", "").lower():
                # Build a canonical trip from seed data
                past_trip = Trip(
                    trip_id="japan-2026",
                    name=t.get("name", "Japan 2026"),
                    status=TripStatus.BOOKED,
                    destination_summary="Tokyo, Kyoto, Osaka",
                    start_date=date(2026, 3, 10),
                    end_date=date(2026, 3, 24),
                    travelers=[
                        Traveler(
                            name="Ken", passport_country="CAN", passport_expiry=date(2030, 5, 15)
                        ),
                        Traveler(
                            name="Sue", passport_country="CAN", passport_expiry=date(2029, 11, 3)
                        ),
                        Traveler(
                            name="Child 1",
                            passport_country="CAN",
                            passport_expiry=date(2028, 2, 20),
                            is_minor=True,
                        ),
                        Traveler(
                            name="Child 2",
                            passport_country="CAN",
                            passport_expiry=date(2028, 2, 20),
                            is_minor=True,
                        ),
                        Traveler(
                            name="Child 3",
                            passport_country="CAN",
                            passport_expiry=date(2029, 7, 1),
                            is_minor=True,
                        ),
                    ],
                    segments=[
                        Segment(
                            segment_id="leg-1",
                            segment_type=SegmentType.FLIGHT,
                            carrier="Air Canada",
                            flight_number="AC001",
                            origin="YYZ",
                            destination="YVR",
                            depart_at=datetime(2026, 3, 10, 9, 0),
                            arrive_at=datetime(2026, 3, 10, 11, 30),
                            cabin_class="economy",
                            confirmation_code="ABC123",
                        ),
                        Segment(
                            segment_id="leg-2",
                            segment_type=SegmentType.FLIGHT,
                            carrier="Air Canada",
                            flight_number="AC003",
                            origin="YVR",
                            destination="NRT",
                            depart_at=datetime(2026, 3, 10, 13, 15),
                            arrive_at=datetime(2026, 3, 11, 15, 30),
                            cabin_class="economy",
                            confirmation_code="ABC123",
                        ),
                    ],
                    stays=[
                        Stay(
                            stay_id="stay-1",
                            stay_type=StayType.HOTEL,
                            property_name="Shinjuku Prince Hotel",
                            city="Tokyo",
                            country="Japan",
                            check_in=date(2026, 3, 11),
                            check_out=date(2026, 3, 15),
                            confirmation_code="HT-98765",
                        ),
                    ],
                )
                break

    if past_trip is None:
        past_trip = _create_demo_trip()

    trip_svc.save(past_trip)
    console.print(f"  [green]✓[/green] Loaded: {past_trip.summary()}")
    results["step1_trip_id"] = past_trip.trip_id

    # -----------------------------------------------------------------------
    # STEP 2: Extract preferences from past trip
    # -----------------------------------------------------------------------
    console.print(Panel("[bold]Step 2:[/bold] Propose durable preferences", style="cyan"))

    past_trip.status = TripStatus.LIVED  # treat as completed for analysis
    trip_svc.save(past_trip)

    extracted = PreferenceExtractorRunner(memory_store=memory, trips_dir=trips_dir).run(
        {
            "trip_ids": [past_trip.trip_id],
            "min_evidence_trips": 1,
            "learning_dir": memory_path.parent / "learning",
        }
    )
    proposed = extracted.get("preferences_proposed", {})
    proposals = extracted.get("learning_proposals", [])
    console.print(f"  [green]✓[/green] Proposed {len(proposed)} preference(s):")
    for key, desc in proposed.items():
        console.print(f"    · {key}: {desc}")
    console.print(f"  Review-gated proposal(s): {len(proposals)}")
    results["step2_preferences"] = proposed
    results["step2_learning_proposals"] = proposals

    # -----------------------------------------------------------------------
    # STEP 3: Propose family profile updates
    # -----------------------------------------------------------------------
    console.print(Panel("[bold]Step 3:[/bold] Propose family profile updates", style="cyan"))

    profile_updates = extracted.get("profile_updates", [])
    if profile_updates:
        for update in profile_updates:
            console.print(f"    · {update}")
    else:
        console.print("  [green]✓[/green] No profile changes proposed")
    results["step3_profile_count"] = len(past_trip.travelers)

    # -----------------------------------------------------------------------
    # STEP 4: Start a new trip
    # -----------------------------------------------------------------------
    console.print(Panel("[bold]Step 4:[/bold] Create new trip: Japan 2027", style="cyan"))

    new_trip = Trip(
        trip_id="japan-2027",
        name="Japan 2027",
        status=TripStatus.PLANNED,
        destination_summary="Tokyo, Kyoto, Hiroshima",
        start_date=date(2027, 3, 12),
        end_date=date(2027, 3, 26),
        travelers=past_trip.travelers,
        checklist=[
            ChecklistItem(item_id="chk-01", category="booking", title="Book outbound flights"),
            ChecklistItem(item_id="chk-02", category="booking", title="Book return flights"),
            ChecklistItem(item_id="chk-03", category="booking", title="Book all hotels"),
            ChecklistItem(
                item_id="chk-04", category="document", title="Check all passport expiry dates"
            ),
            ChecklistItem(
                item_id="chk-05", category="document", title="Check Japan ETA requirement"
            ),
            ChecklistItem(
                item_id="chk-06", category="logistics", title="Buy JR Pass before departure"
            ),
        ],
        segments=[
            Segment(
                segment_id="leg-1",
                segment_type=SegmentType.FLIGHT,
                carrier="Air Canada",
                origin="YYZ",
                destination="YVR",
                depart_at=datetime(2027, 3, 12, 8, 45),
                arrive_at=datetime(2027, 3, 12, 11, 15),
            ),
            Segment(
                segment_id="leg-2",
                segment_type=SegmentType.FLIGHT,
                carrier="Air Canada",
                origin="YVR",
                destination="NRT",
                depart_at=datetime(2027, 3, 12, 13, 30),
                arrive_at=datetime(2027, 3, 13, 15, 45),
            ),
        ],
    )
    trip_svc.save(new_trip)
    console.print(f"  [green]✓[/green] Created: {new_trip.summary()}")
    results["step4_new_trip_id"] = new_trip.trip_id

    # -----------------------------------------------------------------------
    # STEP 5: Create Google Sheet (mocked unless real_google=True)
    # -----------------------------------------------------------------------
    console.print(Panel("[bold]Step 5:[/bold] Create Google Sheet", style="cyan"))

    if real_google:
        try:
            from trippy.ingest.google_auth import GoogleAuthManager
            from trippy.services.sheet_sync import SheetSyncService

            auth = GoogleAuthManager()
            sync = SheetSyncService(auth_manager=auth)
            sheet_result = sync.create_new_sheet(new_trip)
            new_trip.sync.google_sheet_id = sheet_result.get("spreadsheet_id", "")
            new_trip.sync.google_sheet_url = sheet_result.get("url", "")
            trip_svc.save(new_trip)
            console.print(f"  [green]✓[/green] Sheet created: {new_trip.sync.google_sheet_url}")
            results["step5_sheet_url"] = new_trip.sync.google_sheet_url
        except Exception as exc:
            console.print(
                f"  [yellow]⚠[/yellow] Sheet creation failed (no real credentials?): {exc}"
            )
            results["step5_sheet_url"] = "SKIPPED"
    else:
        # Mock sheet creation
        new_trip.sync.google_sheet_id = "MOCK-SHEET-ID-12345"
        new_trip.sync.google_sheet_url = (
            "https://docs.google.com/spreadsheets/d/MOCK-SHEET-ID-12345"
        )
        new_trip.sync.last_synced_at = datetime.utcnow()
        new_trip.sync.last_synced_by = "agent"
        trip_svc.save(new_trip)
        console.print(f"  [yellow]~[/yellow] Mocked sheet: {new_trip.sync.google_sheet_url}")
        results["step5_sheet_url"] = new_trip.sync.google_sheet_url

    # -----------------------------------------------------------------------
    # STEP 6: Ingest booking confirmation
    # -----------------------------------------------------------------------
    console.print(
        Panel("[bold]Step 6:[/bold] Ingest booking confirmation from email", style="cyan")
    )

    # Use fixture email or mock
    fixture_email = _load_fixture_confirmation()
    conf = Confirmation(
        confirmation_id="conf-001",
        confirmation_type=ConfirmationType.FLIGHT,
        confirmation_code=fixture_email.get("confirmation_code", "AC-MOCK-2027"),
        vendor=fixture_email.get("vendor", "Air Canada"),
        raw_email_subject=fixture_email.get("subject", "Your Air Canada booking confirmation"),
        received_at=datetime.utcnow(),
        parsed_at=datetime.utcnow(),
        linked_segment_id="leg-1",
    )
    new_trip.confirmations.append(conf)

    # Update segment with confirmation code
    if new_trip.segments:
        new_trip.segments[0].confirmation_code = conf.confirmation_code

    trip_svc.save(new_trip)
    console.print(f"  [green]✓[/green] Ingested: {conf.vendor} — {conf.confirmation_code}")
    console.print(f"    Linked to segment: {conf.linked_segment_id}")
    results["step6_confirmation"] = conf.confirmation_code

    # -----------------------------------------------------------------------
    # STEP 7: Run friction audit
    # -----------------------------------------------------------------------
    console.print(Panel("[bold]Step 7:[/bold] Friction audit", style="cyan"))

    from trippy.models.preferences import FamilyTravelPreferences

    prefs = FamilyTravelPreferences()
    detector = FrictionDetector(preferences=prefs)
    risks = detector.audit(new_trip)

    new_trip.risk_flags = risks
    trip_svc.save(new_trip)

    _display_risk_table(risks)
    results["step7_risks"] = [
        {"severity": r.severity.value, "description": r.description} for r in risks
    ]

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    console.print()
    console.print(
        Panel(
            f"[bold green]Thin slice complete.[/bold green]\n\n"
            f"Past trip mined:  [cyan]{results['step1_trip_id']}[/cyan]\n"
            f"Preferences proposed: [cyan]{len(results['step2_preferences'])} entries[/cyan]\n"
            f"Profile evidence:     [cyan]{results['step3_profile_count']} travelers[/cyan]\n"
            f"Learning proposals:   [cyan]{len(results['step2_learning_proposals'])}[/cyan]\n"
            f"New trip:         [cyan]{results['step4_new_trip_id']}[/cyan]\n"
            f"Sheet:            [cyan]{results['step5_sheet_url']}[/cyan]\n"
            f"Confirmation:     [cyan]{results['step6_confirmation']}[/cyan]\n"
            f"Risks found:      [cyan]{len(risks)}[/cyan]"
            + (
                " ([red]" + str(len(new_trip.high_risks)) + " high[/red])"
                if new_trip.high_risks
                else ""
            ),
            style="green",
            title="Results",
        )
    )

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_demo_trip() -> Trip:
    from trippy.models.trip import Traveler, Trip, TripStatus

    return Trip(
        trip_id="japan-2026-demo",
        name="Japan 2026 (demo)",
        status=TripStatus.LIVED,
        destination_summary="Tokyo, Kyoto",
        start_date=date(2026, 3, 10),
        end_date=date(2026, 3, 24),
        travelers=[
            Traveler(name="Ken", passport_country="CAN", passport_expiry=date(2030, 5, 1)),
            Traveler(name="Sue", passport_country="CAN", passport_expiry=date(2029, 8, 15)),
        ],
    )


def _load_fixture_confirmation() -> dict[str, Any]:
    fixture_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "emails"
    air_canada = fixture_dir / "air_canada.txt"
    if air_canada.exists():
        text = air_canada.read_text(encoding="utf-8")
        import re

        code_match = re.search(r"[A-Z]{2}\d{4,}", text)
        return {
            "vendor": "Air Canada",
            "confirmation_code": code_match.group() if code_match else "AC-FIXTURE",
            "subject": "Your Air Canada booking confirmation",
        }
    return {
        "vendor": "Air Canada",
        "confirmation_code": "AC-MOCK-2027",
        "subject": "Your Air Canada booking confirmation",
    }


def _display_risk_table(risks: list[Any]) -> None:
    if not risks:
        console.print("  [green]✓[/green] No risks detected!")
        return

    t = Table(show_lines=True, title=f"{len(risks)} Risk(s) Found")
    t.add_column("Severity", style="bold")
    t.add_column("Category")
    t.add_column("Description")
    t.add_column("Fix")

    severity_colors = {
        "critical": "red",
        "high": "red",
        "medium": "yellow",
        "low": "dim",
    }

    for r in risks:
        color = severity_colors.get(r.severity.value, "white")
        t.add_row(
            f"[{color}]{r.severity.value.upper()}[/{color}]",
            r.category,
            r.description[:80] + ("…" if len(r.description) > 80 else ""),
            (r.recommended_fix or "")[:60],
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Trippy thin-slice demo")
    parser.add_argument(
        "--real-google",
        action="store_true",
        help="Use real Google credentials (requires setup)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    run_thin_slice(real_google=args.real_google)


if __name__ == "__main__":
    main()
