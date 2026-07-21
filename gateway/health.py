"""Health check endpoint — route registered once, not per-startup.

Responds with Gateway, OneBot, Runtime, and Database status.
No paths, secrets, or exception details are exposed.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI

from gateway.commands import GATEWAY_VERSION

_START_TIME = time.monotonic()

# Injected by bootstrap — read by /health to report Runtime state.
# Set to a Runtime instance after assembly completes.
_runtime: Any | None = None


def set_runtime(runtime: Any) -> None:
    """Register the Runtime instance so /health can read its status."""
    global _runtime
    _runtime = runtime


def build_health(
    bot_count: int = 0,
    database_ok: bool | None = None,
    renderer_ok: bool | None = None,
) -> dict[str, Any]:
    """Build health response.

    bot_count: 0=disconnected, >0=connected.
    database_ok: result of a live ``SELECT 1`` probe.  ``None`` means
        the probe was skipped (no connection available to test).
    renderer_ok: result of a renderer route-smoke test.  ``None`` means
        skipped, ``True`` means routes verified, ``False`` means stale/broken.
    """
    uptime = time.monotonic() - _START_TIME
    connected = bot_count > 0

    # ── Gateway ──────────────────────────────────────────────────────────
    gateway_status = "ok"

    # ── OneBot ───────────────────────────────────────────────────────────
    onebot_status = "connected" if connected else "disconnected"

    # ── Runtime ──────────────────────────────────────────────────────────
    runtime_status = "unknown"
    if _runtime is not None:
        try:
            runtime_status = _runtime.status.value
        except Exception:
            runtime_status = "error"

    # ── Database (live probe takes precedence over connection existence) ──
    if database_ok is True:
        database_status = "ok"
    elif database_ok is False:
        database_status = "error"
    elif _runtime is not None:
        try:
            conns = [
                c for c in (
                    getattr(_runtime, "db_conn", None),
                    getattr(_runtime, "chart_db_conn", None),
                    getattr(_runtime, "score_db_conn", None),
                )
                if c is not None
            ]
            database_status = "ok" if conns else "unknown"
        except Exception:
            database_status = "error"
    else:
        database_status = "unknown"

    # ── Renderer ─────────────────────────────────────────────────────────
    if renderer_ok is True:
        renderer_status = "ok"
    elif renderer_ok is False:
        renderer_status = "error"
    else:
        renderer_status = "unknown"

    # ── Overall status ───────────────────────────────────────────────────
    if not connected:
        overall = "degraded"
    elif runtime_status == "ready":
        overall = "ok"
    elif runtime_status in ("starting", "degraded"):
        overall = "degraded"
    elif runtime_status in ("stopping", "stopped", "error"):
        overall = "down"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "gateway": gateway_status,
        "onebot": onebot_status,
        "runtime": runtime_status,
        "database": database_status,
        "renderer": renderer_status,
        "gateway_version": GATEWAY_VERSION,
        "uptime_seconds": round(uptime, 1),
    }


def register_health_route(app: FastAPI) -> None:
    """Register GET /health. Call once after app creation, before startup."""

    @app.get("/health")
    async def health() -> dict[str, Any]:
        try:
            import nonebot
            bot_count = len(nonebot.get_bots())
        except ValueError:
            # NoneBot not initialized (test environments)
            bot_count = 0

        # Live database probe — a real SELECT 1, not just "connection exists"
        database_ok: bool | None = None
        if _runtime is not None:
            conn = getattr(_runtime, "db_conn", None)
            if conn is not None:
                try:
                    import asyncio
                    row = await asyncio.wait_for(
                        conn.execute_fetchall("SELECT 1 AS ok"), timeout=3.0,
                    )
                    database_ok = len(row) > 0 and row[0]["ok"] == 1
                except Exception:
                    database_ok = False

        # Renderer probe — verify the renderer is the one we deployed, not
        # a stale leftover process masking as healthy.  A 404 on any expected
        # route means the renderer is running old code or is otherwise broken.
        import httpx
        renderer_ok: bool | None = None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get("http://127.0.0.1:3000/health")
                if resp.status_code == 200:
                    data = resp.json()
                    functions = data.get("functions", [])
                    if len(functions) >= 2:
                        # Smoke-test one route — 404 means stale renderer
                        route_check = await client.post(
                            "http://127.0.0.1:3000/render/b20",
                            json={},
                        )
                        renderer_ok = route_check.status_code != 404
                    else:
                        renderer_ok = False
                else:
                    renderer_ok = False
        except Exception:
            renderer_ok = False

        return build_health(
            bot_count=bot_count, database_ok=database_ok,
            renderer_ok=renderer_ok,
        )
