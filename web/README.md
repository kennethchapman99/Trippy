# Trippy Web UI

This is the canonical Trippy frontend. The older Python-rendered UI under `trippy/ui/templates` is only a backend fallback / API shell.

## Run locally

From the repo root:

```bash
# Terminal 1: backend API
uv run trippy ui --port 8787 --no-open

# Terminal 2: canonical React UI
cd web
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:8788
```

## Ports

| Port | Purpose |
|---|---|
| 8787 | Python backend/API server |
| 8788 | React/Vite frontend |

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8787` by default.

Override the backend target when needed:

```bash
TRIPPY_API_PROXY_TARGET=http://127.0.0.1:8790 npm run dev
```

## Do not regress

- Do not run the Python backend directly on `8788` unless you intentionally want the legacy fallback shell
- Do not restore `trippy-canvas` as the source of truth
- Keep the canonical UI inside this repo under `web/`
