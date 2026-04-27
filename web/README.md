# Trippy Canvas Web

This folder is the integration home for the Lovable-built `trippy-canvas` React/Vite UI.

## Local workflow

1. Start the Trippy backend API:

```bash
uv run trippy ui --port 8788 --no-open
```

2. Import or refresh the Lovable UI from the sibling repo:

```bash
scripts/import_trippy_canvas_ui.sh /Users/kchapman/Hermes/trippy-canvas
```

3. Run the Canvas frontend:

```bash
cd web
npm install
npm run dev
```

The Vite dev server runs on port `8080` and proxies `/api` to `http://127.0.0.1:8788` by default.

Override the backend target with:

```bash
TRIPPY_API_PROXY=http://127.0.0.1:8788 npm run dev
```

## Integration rule

The React UI should never call Trippy Python services directly. It should call local `/api/*` endpoints only. The backend remains the source of truth for trip state, ideation, shortlists, maps, planning advice, execution packet state, and review-gated learning.

## First vertical slice

Wire this first:

```text
GET /api/state -> real dashboard cards
POST idea endpoint -> real ranked trip ideas
POST intake endpoint -> create a real trip from a selected idea
GET /api/trip?trip_id=... -> hydrate the selected trip workspace
```

Do not wire flights, lodging, activities, maps, or learning review until the first slice is clean.
