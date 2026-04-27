# Trippy Canvas Backend Mapping

## Goal

Replace the legacy static Trippy browser UI with the Lovable-built `trippy-canvas` React/Vite UI while preserving the existing Trippy backend as the source of truth.

This is a frontend replacement and API-contract exercise, not a rewrite of the trip-planning engine.

## Current source repos

| Repo | Role | Treatment |
|---|---|---|
| `kennethchapman99/Trippy` | Canonical backend, CLI, local UI server, services, tests | Source of truth |
| `kennethchapman99/trippy-canvas` | Lovable React/Vite UI | Design/UI source to import into `Trippy/web` |

## Target repo layout

```text
Trippy/
  trippy/                 Python backend, services, CLI, local API
  trippy/ui/              Legacy UI server plus Canvas API adapter surface
  web/                    Imported Lovable React/Vite app
  docs/                   Mapping and migration docs
  scripts/                Import/wiring automation
  tests/                  Backend tests
```

## Backend ownership boundaries

| Capability | Backend owner | Frontend responsibility |
|---|---|---|
| Trip list/state | `TrippyUIService.app_state`, `TripIntakeService`, `DashboardService` | Render cards, filters, and active trip state |
| Trip workspace | `TrippyUIService.trip_state`, `TripWorkspaceService` | Render plan status, timeline, risks, links |
| Ideation | `TripIdeationService`, `TrippyUIService.suggest_ideas` | Collect prompt/form fields, show ranked ideas |
| Intake creation | `TripIntakeService`, `TrippyUIService.create_intake` | Submit user-approved trip intake |
| Plan options | `TripPlannerService`, `TrippyUIService.draft_plan/select_plan` | Show trip-shape options and selection CTA |
| Shortlists | `FlightShortlistService`, `LodgingShortlistService`, `CarShortlistService`, `ActivityShortlistService` | Show cards, selected state, evidence, warnings |
| Maps | `TripMapBuilder`, map artifact endpoints | Show map links/files/pins when available |
| Advisor | `PlanningAdvisorService`, `TrippyUIService.planning_advice` | Show next-best-action guidance |
| Execution packet | `TripExecutionService` | Show booking readiness and missing confirmations |
| Learning | `LearningEventStore` | Show review-gated proposals and workflow feedback |

## Existing local API surface

The current legacy browser UI already calls these local endpoints and should be treated as the first integration contract until a formal `/api/v1` router exists:

| Endpoint | Method | Purpose | Canvas usage |
|---|---:|---|---|
| `/api/state` | GET | App/dashboard/intake/workflow/log summary | Home dashboard |
| `/api/trip?trip_id=...` | GET | Hydrated trip state | Trip detail/workspace |
| `/api/logs` | GET | Learning/run log | Activity feed |
| `/api/ideas` or existing suggest route | POST | Generate destination concepts | New-trip ideation |
| `/api/intake` or existing intake route | POST | Save trip intake | New-trip form |
| `/api/draft-plan` or existing draft route | POST | Build plan options | Trip-shape page |
| `/api/select-plan` or existing select route | POST | Select plan option | Trip-shape page |
| `/api/advice` or existing planning-advice route | POST | Advisor guidance | Decision cards |
| `/api/shortlist` or existing shortlist route | POST | Build flights/lodging/cars/activities | Timeline/workspace cards |
| `/api/workspace` or existing workspace route | POST | Build workspace/timeline | Timeline page |
| `/api/map` or existing map route | POST | Build map artifact | Map/timeline page |
| `/api/trip-packet` or existing packet route | POST | Update confirmations | Execution/readiness UI |
| `/api/feedback` | POST | Record workflow feedback | Learning review UI |

## Frontend route mapping

| Canvas route | Current Lovable intent | Backend data needed | Integration status |
|---|---|---|---|
| `/` | Dashboard / trips overview | `GET /api/state` + Canvas adapter | Phase 7 vertical slice |
| `/new` | Brain-dump ideation + structured intake | `POST ideas`, `POST intake` | Phase 7 vertical slice |
| `/trip/shape` | Trip shape selection | `GET trip`, `POST draft-plan`, `POST select-plan`, `POST advice` | Next slice |
| `/trip/timeline` | Workspace/timeline | `GET trip`, `POST workspace`, shortlists, map artifact | Next slice |

## Canvas view models

The UI should consume friendly view models instead of raw backend internals.

```ts
export type CanvasTripCard = {
  id: string;
  title: string;
  destination: string;
  dates: string;
  who: string;
  status: 'ideating' | 'planning' | 'booked' | 'complete';
  progress: number;
  legs: number;
  nextStep?: string;
};

export type CanvasIdeaCard = {
  id: string;
  place: string;
  region: string;
  fit: number;
  tags: string[];
  why: string;
  friction?: string[];
  payload: unknown;
};

export type CanvasHomeView = {
  trips: CanvasTripCard[];
  spotlight?: {
    tripId?: string;
    title: string;
    body: string;
    cta: string;
  };
  recentActivity: Array<{ actor: string; summary: string; when?: string }>;
};
```

## Migration phases

### Phase 1 — Integration branch

Use `feature/trippy-canvas-ui-integration` for all migration work.

### Phase 2 — Import UI

Import `trippy-canvas` into `Trippy/web`, excluding `.git`, `node_modules`, build artifacts, and Lovable deployment metadata.

### Phase 3 — Backend route inventory

Inventory existing `/api/*` routes and confirm what the legacy UI already relies on.

### Phase 4 — Frontend mock/API inventory

Find hardcoded Lovable data arrays, mock helpers, fake cards, and direct component state that must be replaced.

### Phase 5 — API contract

Centralize all browser-to-backend calls in:

```text
web/src/api/trippyClient.ts
web/src/hooks/useTrippyApi.ts
web/src/types/trippy.ts
web/src/lib/trippyViewModels.ts
```

### Phase 6 — Thin vertical slice

Wire only this first:

```text
Load real dashboard -> show real trip cards -> submit ideation request -> show backend-ranked ideas -> create trip intake from selected idea
```

### Phase 7 — Build/test gate

Required local checks:

```bash
uv run pytest
cd web && npm install && npm run build
```

## Definition of done for the first real slice

- `web` runs as a Vite React app.
- Vite dev server proxies `/api` to the Trippy local backend.
- Home page no longer uses hardcoded trip cards when backend is reachable.
- New-trip page calls the backend for ideas instead of using static cards.
- Selecting/approving an idea creates a real Trippy intake.
- Legacy backend services remain untouched except for narrow adapter/view-model additions.
- README tells the user how to run backend + frontend together.

## Non-goals

- Do not rewrite Trippy services in TypeScript.
- Do not move Google/Gmail/Sheets credentials to the browser.
- Do not make the frontend call Python internals directly.
- Do not silently apply learning/memory updates.
- Do not remove the legacy UI until Canvas reaches functional parity.
