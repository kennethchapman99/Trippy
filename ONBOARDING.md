# Trippy Agent — Getting Started (Ken's Guide)

## Install in 60 seconds

```bash
# 1. Clone and enter the project
cd ~/Hermes

# 2. Install everything
uv sync --all-extras

# 3. Copy the env file and add your Anthropic API key
cp .env.example .env
# Open .env and set ANTHROPIC_API_KEY=sk-ant-...

# 4. Create the database
alembic upgrade head
```

That's it. The database lives at `~/.trippy/state.db`.

---

## Set up your inbox folder

```bash
mkdir -p ~/trippy-inbox
```

Drop any trip sheet here — Numbers exports, Excel files, Google Sheets CSV exports, plain CSV. Any format works.

---

## Import your first trip

```bash
trippy import ~/trippy-inbox/japan-2024.xlsx
```

**What you'll see:**

```
Importing: japan-2024.xlsx
✓ japan-2024.xlsx — 1 created, 0 updated
  ⚠ 3 low-confidence field(s):
    traveler:2.passport_expiry = None (conf=0.00)
    leg:0.cost_cad = None (conf=0.00)
    trip.status = 'planned' (conf=0.60)
```

Anything with confidence < 0.70 is flagged. Null fields (not in the sheet) are normal. Low-confidence non-null fields need your eye.

---

## Fix flagged fields

```bash
trippy review <trip_id>
```

The interactive TUI is coming in a later phase. For now, the fastest fix is to **add the missing data to your sheet and re-import** — re-imports are idempotent (update, never duplicate).

---

## Bulk import

```bash
# Preview first (no writes)
trippy import-folder ~/trippy-inbox/ --dry-run

# Then import for real
trippy import-folder ~/trippy-inbox/
```

---

## Verify your data

```bash
trippy list-trips
trippy show "Japan 2024"
```

---

## Top 5 failure modes

| Symptom | Fix |
|---------|-----|
| **Encoding error** on import | Re-export from Numbers/Excel as UTF-8 CSV (`File → Export → CSV → Unicode UTF-8`) |
| **Merged cells** cause weird parsing | Unmerge cells before exporting, or just export as CSV |
| **Multi-trip sheet** — only 1 trip imported | Hermes handles multi-trip sheets; if a trip is missing, it likely has no name or date in a recognisable field. Add a "Trip Name" label. |
| **Missing dates** — start/end flagged | Add an explicit `Start Date` and `End Date` row/column. Prose like "March 2026" works but confidence will be lower. |
| **Currency confusion** — costs wrong | Add a currency indicator in the header or a note cell (e.g. `Cost (CAD)` or `Cost USD`). Hermes converts to CAD but marks it lower confidence. |

---

## Exit criterion

Once 3+ trips are imported cleanly and spot-checked, run the pipeline health test:

```bash
uv run pytest tests/integration/test_thin_slice.py -v
```

All non-skipped tests should pass. Then proceed to Phase 2 (Gmail confirmation ingest) setup.

---

## Command reference

| Command | What it does |
|---------|-------------|
| `trippy import <path>` | Import one file (xlsx, csv, or Google Sheets URL) |
| `trippy import-folder <dir>` | Import all xlsx/csv in a folder |
| `trippy import-folder <dir> --dry-run` | Preview without writing |
| `trippy list-trips` | Table of all trips |
| `trippy show "<name>"` | Full detail for one trip (partial name match) |
| `trippy review <id>` | Review low-confidence fields (TUI, Phase 2+) |
| `trippy db-init` | Re-run migrations (safe to run again) |
| `trippy version` | Print version |
