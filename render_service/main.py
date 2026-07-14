"""PJSK Render Service — FastAPI + Playwright + Chrome headless.

Canvas-page architecture: JS render functions are loaded once at startup
into a shared page. Each request calls the registered function, which
draws on ``#render-canvas``, and the service screenshots the result.

Listens on ``127.0.0.1``, systemd-managed. All rating/level values are
pre-computed by Python — JS only draws.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

# ─── Config ──────────────────────────────────────────────────────────────────

HOST = os.getenv("RENDER_HOST", "127.0.0.1")
PORT = int(os.getenv("RENDER_PORT", "3000"))
FUNCTIONS_DIR = Path(__file__).parent / "functions"
CANVAS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;overflow:hidden;">
  <canvas id="render-canvas"></canvas>
</body></html>"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("render-service")

# ─── Globals ─────────────────────────────────────────────────────────────────

_start_time: float = 0.0
_pw: Optional[Playwright] = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_canvas_page: Optional[Page] = None
_function_names: list[str] = []
_browser_restart_attempted: bool = False


async def _load_functions(page: Page, functions_dir: Path) -> list[str]:
    """Load _loader.js + all *.js files into *page*. Returns function names."""
    names: list[str] = []
    loader = functions_dir / "_loader.js"
    if loader.exists():
        await page.add_script_tag(path=str(loader))

    for js_file in sorted(functions_dir.glob("*.js")):
        if js_file.name == "_loader.js":
            continue
        await page.add_script_tag(path=str(js_file))
        names.append(js_file.stem)

    return names


async def _check_browser() -> bool:
    """Return True if the browser is connected."""
    if _browser is None:
        return False
    try:
        return _browser.is_connected()
    except Exception:
        return False


async def _ensure_browser() -> bool:
    """Ensure browser is alive; restart once if crashed.

    Returns True when the browser is ready to serve requests.
    """
    global _browser, _context, _canvas_page, _function_names, _browser_restart_attempted

    if await _check_browser():
        _browser_restart_attempted = False
        return True

    if _browser_restart_attempted:
        logger.error("Browser restart already attempted — giving up")
        return False

    _browser_restart_attempted = True
    logger.warning("Browser disconnected — attempting restart...")

    try:
        # Clean up stale references
        if _canvas_page:
            try:
                await _canvas_page.close()
            except Exception:
                pass
            _canvas_page = None
        if _context:
            try:
                await _context.close()
            except Exception:
                pass
            _context = None
        if _browser:
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None

        assert _pw is not None, "Playwright not initialised"
        _browser = await _pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--disable-extensions", "--disable-background-networking",
                "--disable-sync", "--no-first-run",
            ],
        )
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 1600},
        )
        _canvas_page = await _context.new_page()

        # Reload canvas page + functions
        await _canvas_page.set_content(CANVAS_HTML, wait_until="load")
        _function_names = await _load_functions(_canvas_page, FUNCTIONS_DIR)

        logger.info("Browser restarted. Functions: %s", _function_names)
        return True
    except Exception:
        logger.exception("Browser restart failed")
        return False


# ─── Lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _start_time, _pw, _browser, _context, _canvas_page, _function_names

    logger.info("Starting Playwright + Chrome headless...")
    _pw = await async_playwright().start()

    _browser = await _pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-extensions", "--disable-background-networking",
            "--disable-sync", "--no-first-run",
        ],
    )

    _context = await _browser.new_context(
        viewport={"width": 1280, "height": 1600},
    )
    _canvas_page = await _context.new_page()

    # Pre-load render functions into canvas page
    await _canvas_page.set_content(CANVAS_HTML, wait_until="load")
    _function_names = await _load_functions(_canvas_page, FUNCTIONS_DIR)
    logger.info("Loaded render functions: %s", _function_names)

    _start_time = time.time()
    logger.info("Render service ready on %s:%d", HOST, PORT)

    yield

    # Shutdown
    logger.info("Shutting down...")
    if _context:
        await _context.close()
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()


app = FastAPI(title="PJSK Render Service", lifespan=lifespan)


# ─── /health ─────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "uptime": int(time.time() - _start_time),
        "functions": _function_names,
        "browser": "connected" if await _check_browser() else "disconnected",
    }


# ─── /render/{name} ──────────────────────────────────────────────────────────


@app.post("/render/{name}")
async def render_fn(name: str, request: Request) -> Response:
    """Execute a registered JS render function and screenshot the canvas.

    Path: ``/render/b20`` → calls ``window.__renderFunctions['b20'](data)``.
    Request body: JSON data passed directly to the render function.
    Response: ``image/png`` (canvas region only).
    """
    if _function_names and name not in _function_names:
        raise HTTPException(
            status_code=404,
            detail=f"unknown render function: {name}",
        )

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body") from None

    if not await _ensure_browser():
        raise HTTPException(status_code=503, detail="browser unavailable")

    assert _canvas_page is not None, "Canvas page not initialised"

    # Execute the render function — it draws on #render-canvas
    data_json = json.dumps(data, ensure_ascii=False)
    script = f"window.__renderFunctions['{name}']({data_json})"
    try:
        await _canvas_page.evaluate(script)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"render function error: {str(e)[:300]}",
        ) from e

    # Read canvas dimensions (support dynamic sizing)
    canvas_dims: dict[str, Any] = await _canvas_page.evaluate("""() => {
        const c = document.getElementById('render-canvas');
        return { width: c.width, height: c.height };
    }""")
    cw = max(1, canvas_dims.get("width", 800))
    ch = max(1, canvas_dims.get("height", 600))

    # Resize viewport to fit canvas before screenshot
    await _canvas_page.set_viewport_size({"width": cw, "height": ch})

    # Screenshot only the canvas area
    try:
        png = await _canvas_page.screenshot(
            clip={"x": 0, "y": 0, "width": cw, "height": ch},
            type="png",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"screenshot failed: {str(e)[:200]}",
        ) from e

    return Response(content=png, media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
