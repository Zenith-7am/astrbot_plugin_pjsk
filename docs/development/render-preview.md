# Render Preview — Local Development Workflow

How to preview PJSK render templates (B20, difficulty ranking) on your
local machine **without touching the VPS, production database, or real
user data**.

## Prerequisites

Run these once:

```powershell
# Install project with dev + render dependencies
pip install -e ".[dev,render]"

# Install Chromium for Playwright (downloads ~150 MB)
python -m playwright install chromium
```

## Quick Start

### 1. Start the dev render service

```powershell
.\ops\run-render-dev.ps1
```

This starts a FastAPI + Playwright service on **`127.0.0.1:3001`** with
auto-reload for Python changes. JS changes do NOT require a restart —
just re-POST the payload.

Production uses port **3000**; the dev service never touches it.

### 2. Generate a preview PNG

In a second terminal:

```powershell
# B20 (uses bundled fixture)
python tools/render_preview.py --template b20

# Difficulty ranking (requires a custom payload)
python tools/render_preview.py --template difficulty --payload my_data.json

# Custom output path
python tools/render_preview.py --template b20 --output my-snapshot.png
```

Output goes to `artifacts/render-preview/` by default (git-ignored).

### 3. View the PNG

Open `artifacts/render-preview/` in File Explorer or your image viewer.

### 4. Stop the dev service

Press `Ctrl+C` in the terminal running the dev service.

## How It Works

```
tools/render_preview.py
  → POST 127.0.0.1:3001/render/b20  (JSON payload)
  → render_service/main.py           (FastAPI + Playwright)
  → render_service/functions/b20.js  (canvas drawing)
  → PNG screenshot
  → validated + saved to disk
```

- The bundled fixture (`tests/fixtures/render/b20_preview.json`) contains
  two fictional songs with `null` jacket URLs (gray placeholder).
- `render_preview.py` validates the response: HTTP 200, `Content-Type:
  image/png`, valid PNG signature.
- On failure it prints a concise error and exits with code 1.

## Visual Baseline

To capture a baseline snapshot for visual comparison:

```powershell
python tools/render_preview.py --template b20 --output tests/fixtures/render/baseline/b20_baseline.png
```

Visual comparison tests are marked with `@pytest.mark.visual` and
skipped when Chromium is not available (e.g. CI). They are not part of
the normal `pytest` run.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `cannot connect to 127.0.0.1:3001` | Start the dev service first (`ops/run-render-dev.ps1`) |
| `503: browser unavailable` | Run `python -m playwright install chromium` |
| `404: unknown render function` | Check that `render_service/functions/b20.js` exists |
| `500: render failed` | Check the dev service terminal for JS error details |

## Production Service

The production render service runs via systemd on the HK VPS
(`pjsk-renderer.service`), listening on `127.0.0.1:3000`.  See
`docs/production/PRODUCTION-OPERATIONS.md` for deployment details.
