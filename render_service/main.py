"""PJSK Render Service — FastAPI + Playwright + Chrome headless.

**Architecture:** shared Browser (expensive), per-request Context + Page
(isolated, ``finally`` closed).  A semaphore caps concurrent renders.

Listens on ``127.0.0.1``, systemd-managed.  All rating/level values are
pre-computed by Python — JS only draws.
"""

from __future__ import annotations

import asyncio
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
_MAX_CONCURRENT = int(os.getenv("RENDER_MAX_CONCURRENT", "4"))
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
_function_names: list[str] = []
_browser_restart_attempted: bool = False
_render_sem: asyncio.Semaphore = asyncio.Semaphore(_MAX_CONCURRENT)


async def _load_functions(page: Page, functions_dir: Path) -> list[str]:
    """Load ``_loader.js`` + all ``*.js`` files into *page*."""
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
    """Return True if the shared browser is connected."""
    if _browser is None:
        return False
    try:
        return _browser.is_connected()
    except Exception:
        return False


async def _ensure_browser() -> bool:
    """Ensure the shared browser is alive; restart once if crashed."""
    global _browser, _function_names, _browser_restart_attempted

    if await _check_browser():
        _browser_restart_attempted = False
        return True

    if _browser_restart_attempted:
        logger.error("Browser restart already attempted — giving up")
        return False

    _browser_restart_attempted = True
    logger.warning("Browser disconnected — attempting restart...")

    try:
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

        # Warm-up: create a throwaway page to load and verify functions
        warmup_context = await _browser.new_context(
            viewport={"width": 1280, "height": 1600},
        )
        try:
            warmup_page = await warmup_context.new_page()
            await warmup_page.set_content(CANVAS_HTML, wait_until="load")
            _function_names = await _load_functions(warmup_page, FUNCTIONS_DIR)
            await warmup_page.close()
        finally:
            await warmup_context.close()

        logger.info("Browser restarted. Functions: %s", _function_names)
        return True
    except Exception:
        logger.exception("Browser restart failed")
        return False


# ─── Lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _start_time, _pw, _browser, _function_names

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

    # Warm-up: load functions into a throwaway page to verify they work
    warmup_context = await _browser.new_context(
        viewport={"width": 1280, "height": 1600},
    )
    try:
        warmup_page = await warmup_context.new_page()
        await warmup_page.set_content(CANVAS_HTML, wait_until="load")
        _function_names = await _load_functions(warmup_page, FUNCTIONS_DIR)
        await warmup_page.close()
    finally:
        await warmup_context.close()

    logger.info("Loaded render functions: %s", _function_names)
    _start_time = time.time()
    logger.info("Render service ready on %s:%d", HOST, PORT)

    yield

    # Shutdown
    logger.info("Shutting down...")
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


# ─── /jacket/{song_id} ───────────────────────────────────────────────────────
# Serve cached jacket images so Chromium can load them via HTTP (file://
# URLs are blocked in pages created with page.set_content()).

_JACKET_DIR = os.getenv("PJSK_JACKET_CACHE_DIR", "/opt/pjsk-astrbot/shared/cache/jackets")
_JACKET_EXTENSIONS = (".webp", ".png", ".jpg")


@app.get("/jacket/{song_id}")
async def serve_jacket(song_id: int) -> Response:
    """Serve a cached jacket image by song_id."""
    for ext in _JACKET_EXTENSIONS:
        path = Path(_JACKET_DIR) / f"{song_id}{ext}"
        if path.is_file():
            content_type = {
                ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
            }.get(ext, "image/webp")
            return Response(content=path.read_bytes(), media_type=content_type)
    raise HTTPException(status_code=404, detail=f"jacket not found: {song_id}")


# ─── /render/html ─────────────────────────────────────────────────────────────
# Must be registered BEFORE /render/{name} so FastAPI matches the literal
# route first — otherwise "html" is captured as {name}.


@app.post("/render/html")
async def render_html(request: Request) -> Response:
    """Render an arbitrary HTML string and return a PNG screenshot.

    Accepts JSON: ``{"html": "<!DOCTYPE html>…", "width": 960, "height": 600}``.
    A fresh Page + Context is created per request (isolated from other renders).
    The semaphore caps concurrent rendering.
    """
    import re as _re

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body") from None

    html: str | None = body.get("html")
    if not html or not isinstance(html, str):
        raise HTTPException(status_code=400, detail="missing or invalid 'html' field")
    width: int = body.get("width", 960)
    height: int = body.get("height", 600)
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise HTTPException(status_code=400, detail="invalid width/height")

    # Strip <script> tags (defence-in-depth — service is localhost-only)
    html = _re.sub(
        r"<script[^>]*>.*?</script>", "", html,
        flags=_re.DOTALL | _re.IGNORECASE,
    )

    if not await _ensure_browser():
        raise HTTPException(status_code=503, detail="browser unavailable")

    assert _browser is not None

    async with _render_sem:
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        try:
            context = await _browser.new_context(
                viewport={"width": width, "height": height},
            )
            page = await context.new_page()
            await page.set_content(html, wait_until="load", timeout=15000)

            png = await page.screenshot(
                clip={"x": 0, "y": 0, "width": width, "height": height},
                type="png",
            )
            return Response(content=png, media_type="image/png")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"render failed: {str(e)[:300]}",
            ) from e
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass


# ─── /render/{name} ──────────────────────────────────────────────────────────


@app.post("/render/{name}")
async def render_fn(name: str, request: Request) -> Response:
    """Execute a registered JS render function and screenshot the canvas.

    Each request gets a **fresh** Page + Context (isolated from other
    in-flight renders).  A semaphore caps concurrent rendering.
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

    assert _browser is not None

    # ── Acquire concurrency slot ──────────────────────────────────────
    async with _render_sem:
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        try:
            context = await _browser.new_context(
                viewport={"width": 1280, "height": 1600},
            )
            page = await context.new_page()
            await page.set_content(CANVAS_HTML, wait_until="load")
            await _load_functions(page, FUNCTIONS_DIR)

            # Execute the render function — it draws on #render-canvas
            data_json = json.dumps(data, ensure_ascii=False)
            script = f"window.__renderFunctions['{name}']({data_json})"
            await page.evaluate(script)

            # Read canvas dimensions (support dynamic sizing)
            canvas_dims: dict[str, Any] = await page.evaluate("""() => {
                const c = document.getElementById('render-canvas');
                return { width: c.width, height: c.height };
            }""")
            cw = max(1, canvas_dims.get("width", 800))
            ch = max(1, canvas_dims.get("height", 600))

            # Resize viewport to fit canvas before screenshot
            await page.set_viewport_size({"width": cw, "height": ch})

            png = await page.screenshot(
                clip={"x": 0, "y": 0, "width": cw, "height": ch},
                type="png",
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"render failed: {str(e)[:300]}",
            ) from e
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

    return Response(content=png, media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
