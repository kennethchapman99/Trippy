"""Generate the Trippy family travel dashboard artifacts."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote_plus

from trippy.models.dashboard import (
    DashboardIdeaTile,
    DashboardLink,
    DashboardTripTile,
    TravelDashboard,
)
from trippy.models.ideas import TripComparison, TripConcept, TripIdeaRequest
from trippy.models.trip import RiskSeverity, Trip, TripStatus
from trippy.services.map_outputs import MapOutputService
from trippy.services.trip_ideation import TripIdeationService
from trippy.services.trip_state import TripStateService


class DashboardService:
    """Build a static dashboard and machine-readable dashboard data."""

    def __init__(
        self,
        trip_state: TripStateService | None = None,
        map_service: MapOutputService | None = None,
    ) -> None:
        self._trip_state = trip_state or TripStateService()
        self._map_service = map_service or MapOutputService()

    def build(self, comparison: TripComparison | None = None) -> TravelDashboard:
        trips = self._trip_state.load_all()
        if comparison is None:
            comparison = TripIdeationService().compare(TripIdeaRequest(), limit=3)

        return TravelDashboard(
            past_trips=[self._trip_tile(trip) for trip in trips if trip.status == TripStatus.LIVED],
            planned_trips=[
                self._trip_tile(trip)
                for trip in trips
                if trip.status in {TripStatus.DREAM, TripStatus.PLANNED, TripStatus.BOOKED}
            ],
            ideas=[self._idea_tile(concept) for concept in comparison.concepts],
        )

    def write_dashboard(self, output_dir: Path) -> TravelDashboard:
        dashboard = self.build()
        output_dir.mkdir(parents=True, exist_ok=True)
        data_path = output_dir / "dashboard.json"
        html_path = output_dir / "index.html"
        data_path.write_text(dashboard.model_dump_json(indent=2), encoding="utf-8")
        html_path.write_text(self.render_html(dashboard), encoding="utf-8")
        dashboard.exports = {"json": str(data_path), "html": str(html_path)}
        data_path.write_text(dashboard.model_dump_json(indent=2), encoding="utf-8")
        return dashboard

    def render_html(self, dashboard: TravelDashboard) -> str:
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="en">',
                "<head>",
                '  <meta charset="utf-8">',
                '  <meta name="viewport" content="width=device-width, initial-scale=1">',
                "  <title>Trippy Dashboard</title>",
                "  <style>",
                _CSS,
                "  </style>",
                "</head>",
                "<body>",
                '  <header class="topbar">',
                '    <div class="brand"><span class="mark">T</span><span>Trippy</span></div>',
                '    <div class="stamp">Chapman family travel dashboard</div>',
                "  </header>",
                '  <main class="shell">',
                _section("Planned Trips", dashboard.planned_trips),
                _ideas_section("Ideas Bucket", dashboard.ideas),
                _section("Past Trips", dashboard.past_trips),
                "  </main>",
                "</body>",
                "</html>",
                "",
            ]
        )

    def _trip_tile(self, trip: Trip) -> DashboardTripTile:
        risks = [risk for risk in trip.risk_flags if not risk.resolved]
        high_risks = [
            risk for risk in risks if risk.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL}
        ]
        map_query = trip.destination_summary or trip.name
        map_artifact = self._map_service.build_trip_map(trip)
        map_url = (
            map_artifact.pins[0].google_maps_url
            if map_artifact.pins
            else f"https://www.google.com/maps/search/?api=1&query={quote_plus(map_query)}"
        )
        quick_links = [DashboardLink(label="Map", url=map_url)]
        if trip.sync.google_sheet_url:
            quick_links.append(DashboardLink(label="Sheet", url=trip.sync.google_sheet_url))

        return DashboardTripTile(
            trip_id=trip.trip_id,
            name=trip.name,
            status=trip.status.value,
            destination=trip.destination_summary or "Destination TBD",
            date_label=_date_label(trip),
            family_fit_score=max(45, 92 - len(high_risks) * 12 - len(risks) * 3),
            comfort_score=max(40, 88 - len(high_risks) * 15 - len(risks) * 4),
            budget_band=_budget_band(trip),
            planning_completeness=_planning_completeness(trip),
            hero_label=(trip.destination_summary or trip.name)[:60],
            quick_links=quick_links,
            next_actions=_next_actions(trip),
            key_risks=[risk.description for risk in risks[:3]],
            lessons=_lessons(trip),
        )

    def _idea_tile(self, concept: TripConcept) -> DashboardIdeaTile:
        return DashboardIdeaTile(
            concept_id=concept.concept_id,
            title=concept.title,
            destination=", ".join(concept.destinations),
            why_interesting=concept.rationale[0]
            if concept.rationale
            else "Strong family-fit concept.",
            constraints=concept.required_research[:3],
            estimated_cost_band=concept.estimated_cost_band_cad,
            estimated_travel_burden=concept.estimated_travel_burden,
            family_fit_score=concept.family_fit_score,
            comfort_score=concept.comfort_convenience_score,
            comparison_notes=concept.why_it_may_not_fit[:3],
            promote_to_planning_action=f"uv run trippy phase-run 4 --trip-idea {concept.title!r}",
        )


def _date_label(trip: Trip) -> str:
    if trip.start_date and trip.end_date:
        return f"{trip.start_date} to {trip.end_date}"
    if trip.start_date:
        return str(trip.start_date)
    return "Dates TBD"


def _budget_band(trip: Trip) -> str:
    total = trip.total_booked_cad
    if total <= 0:
        return "Budget TBD"
    if total < 15000:
        return "Under CAD 15k booked"
    if total < 30000:
        return "CAD 15k-30k booked"
    return "CAD 30k+ booked"


def _planning_completeness(trip: Trip) -> int:
    checks = [
        bool(trip.segments),
        bool(trip.stays),
        bool(trip.travelers),
        bool(trip.sync.google_sheet_url or trip.sync.google_sheet_id),
        not trip.unconfirmed_segments,
        not trip.unconfirmed_stays,
        any(item.category in {"visa", "document", "logistics"} for item in trip.checklist),
    ]
    return int(sum(1 for item in checks if item) / len(checks) * 100)


def _next_actions(trip: Trip) -> list[str]:
    actions: list[str] = []
    if not trip.segments:
        actions.append("Research exact flight options and total travel burden.")
    if trip.unconfirmed_segments:
        actions.append("Resolve unconfirmed flights and add confirmation codes.")
    if not trip.stays:
        actions.append("Shortlist lodging with explicit 3-bed family fit.")
    if trip.unconfirmed_stays:
        actions.append("Resolve unconfirmed lodging and check-in details.")
    if not any(item.category == "visa" for item in trip.checklist):
        actions.append("Add visa, entry, health, and cash checklist items.")
    return actions[:4]


def _lessons(trip: Trip) -> list[str]:
    lessons = []
    for risk in trip.risk_flags:
        if risk.resolved:
            lessons.append(f"Resolved {risk.category}: {risk.description}")
    if trip.notes:
        lessons.append(trip.notes[:160])
    return lessons[:3]


def _section(title: str, trips: list[DashboardTripTile]) -> str:
    cards = "\n".join(_trip_card(trip) for trip in trips) or '<p class="empty">No trips yet.</p>'
    return f"""
    <section>
      <div class="section-head">
        <h1>{html.escape(title)}</h1>
        <span>{len(trips)} item(s)</span>
      </div>
      <div class="grid">{cards}</div>
    </section>
    """


def _ideas_section(title: str, ideas: list[DashboardIdeaTile]) -> str:
    cards = "\n".join(_idea_card(idea) for idea in ideas) or '<p class="empty">No ideas yet.</p>'
    return f"""
    <section>
      <div class="section-head">
        <h1>{html.escape(title)}</h1>
        <span>{len(ideas)} item(s)</span>
      </div>
      <div class="grid">{cards}</div>
    </section>
    """


def _trip_card(trip: DashboardTripTile) -> str:
    links = " ".join(
        f'<a href="{html.escape(link.url)}">{html.escape(link.label)}</a>'
        for link in trip.quick_links
    )
    actions = "".join(f"<li>{html.escape(action)}</li>" for action in trip.next_actions[:3])
    risks = "".join(f"<li>{html.escape(risk)}</li>" for risk in trip.key_risks[:2])
    return f"""
      <article class="card">
        <div class="hero">{html.escape(trip.hero_label)}</div>
        <div class="meta">{html.escape(trip.status)} · {html.escape(trip.date_label)}</div>
        <h2>{html.escape(trip.name)}</h2>
        <p>{html.escape(trip.destination)}</p>
        <div class="scores">
          <span>Family {trip.family_fit_score}</span>
          <span>Comfort {trip.comfort_score}</span>
          <span>{trip.planning_completeness}% planned</span>
        </div>
        <p class="budget">{html.escape(trip.budget_band)}</p>
        <div class="links">{links}</div>
        <h3>Next</h3>
        <ul>{actions or "<li>No immediate action recorded.</li>"}</ul>
        <h3>Risks</h3>
        <ul>{risks or "<li>No key risks recorded.</li>"}</ul>
      </article>
    """


def _idea_card(idea: DashboardIdeaTile) -> str:
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in idea.comparison_notes[:2])
    constraints = "".join(f"<li>{html.escape(item)}</li>" for item in idea.constraints[:2])
    return f"""
      <article class="card idea">
        <div class="hero">{html.escape(idea.destination)}</div>
        <h2>{html.escape(idea.title)}</h2>
        <p>{html.escape(idea.why_interesting)}</p>
        <div class="scores">
          <span>Family {idea.family_fit_score}</span>
          <span>Comfort {idea.comfort_score}</span>
        </div>
        <p class="budget">{html.escape(idea.estimated_cost_band)}</p>
        <p>{html.escape(idea.estimated_travel_burden)} travel burden</p>
        <h3>Research</h3>
        <ul>{constraints}</ul>
        <h3>Watch</h3>
        <ul>{notes or "<li>No major concern recorded.</li>"}</ul>
      </article>
    """


_CSS = """
:root {
  color-scheme: light;
  --ink: #15171a;
  --muted: #667085;
  --line: #d9dde3;
  --paper: #f7f8fa;
  --surface: #ffffff;
  --accent: #146c5f;
  --accent-2: #9a4b26;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: var(--paper);
}
.topbar {
  min-height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 32px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.brand { display: flex; align-items: center; gap: 12px; font-size: 24px; font-weight: 760; }
.mark {
  width: 38px;
  height: 38px;
  display: inline-grid;
  place-items: center;
  background: var(--accent);
  color: white;
  font-weight: 800;
}
.stamp { color: var(--muted); font-size: 14px; }
.shell { max-width: 1280px; margin: 0 auto; padding: 28px; }
section { margin-bottom: 42px; }
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 14px;
}
h1 { font-size: 26px; margin: 0; }
.section-head span { color: var(--muted); }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
}
.hero {
  min-height: 86px;
  display: flex;
  align-items: end;
  padding: 12px;
  margin: -16px -16px 14px;
  background: #dfe8e2;
  color: #12352f;
  font-size: 18px;
  font-weight: 720;
}
.idea .hero { background: #efe1d5; color: #4a2110; }
.meta { color: var(--muted); font-size: 13px; text-transform: uppercase; }
h2 { margin: 8px 0; font-size: 20px; }
h3 { margin: 16px 0 6px; font-size: 13px; text-transform: uppercase; color: var(--muted); }
p { margin: 8px 0; line-height: 1.45; }
ul { margin: 6px 0 0; padding-left: 18px; }
li { margin: 4px 0; }
.scores { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.scores span {
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-size: 13px;
  background: #fbfcfd;
}
.budget { font-weight: 650; }
.links { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0; }
a { color: var(--accent); font-weight: 650; }
.empty { color: var(--muted); }
@media (max-width: 700px) {
  .topbar { align-items: flex-start; flex-direction: column; padding: 18px; }
  .shell { padding: 18px; }
}
"""
