#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRIPPY_ROOT="${TRIPPY_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CANVAS_ROOT="${1:-${TRIPPY_CANVAS_ROOT:-$(cd "$TRIPPY_ROOT/.." && pwd)/trippy-canvas}}"
WEB_ROOT="$TRIPPY_ROOT/web"
INTEGRATION_DOCS="$TRIPPY_ROOT/docs/integration"

if [[ ! -d "$CANVAS_ROOT" ]]; then
  echo "Could not find trippy-canvas at: $CANVAS_ROOT" >&2
  echo "Usage: scripts/import_trippy_canvas_ui.sh /path/to/trippy-canvas" >&2
  exit 1
fi

if [[ ! -f "$CANVAS_ROOT/package.json" ]]; then
  echo "Expected package.json in trippy-canvas root: $CANVAS_ROOT" >&2
  exit 1
fi

mkdir -p "$WEB_ROOT" "$INTEGRATION_DOCS"

rsync -av \
  --delete \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='.lovable' \
  --exclude='.env' \
  --exclude='.env.local' \
  "$CANVAS_ROOT/" "$WEB_ROOT/"

{
  echo "# Backend route inventory"
  echo
  grep -R "app\.route\|@.*route\|app\.get\|app\.post\|router\.get\|router\.post\|/api/" -n "$TRIPPY_ROOT/trippy" 2>/dev/null || true
} > "$INTEGRATION_DOCS/backend_route_inventory.md"

{
  echo "# Frontend data inventory"
  echo
  grep -R "fetch(\|axios\|mock\|dummy\|placeholder\|const .*Data\|useState" -n \
    "$WEB_ROOT/src" "$WEB_ROOT/app" "$WEB_ROOT/components" 2>/dev/null || true
} > "$INTEGRATION_DOCS/frontend_data_inventory.md"

{
  echo "# Frontend file inventory"
  echo
  find "$WEB_ROOT" -maxdepth 4 -type f | sed "s#^$TRIPPY_ROOT/##" | sort
} > "$INTEGRATION_DOCS/frontend_file_inventory.md"

cat <<'MSG'
Imported trippy-canvas into Trippy/web.

Next local checks:
  cd web && npm install && npm run build
  cd .. && uv run pytest

Review docs/integration/*.md for mock-data and backend-route mapping gaps.
MSG
