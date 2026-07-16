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


def build_health(bot_count: int = 0) -> dict[str, Any]:
    """Build health response.

    bot_count: 0=disconnected, >0=connected.
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

    # ── Database ─────────────────────────────────────────────────────────
    database_status = "unknown"
    if _runtime is not None:
        try:
            # Check if we have db connections that are still alive
            conns = [
                c for c in (
                    getattr(_runtime, "db_conn", None),
                    getattr(_runtime, "chart_db_conn", None),
                    getattr(_runtime, "score_db_conn", None),
                )
                if c is not None
            ]
            if conns:
                database_status = "ok" if runtime_status == "ready" else runtime_status
        except Exception:
            database_status = "error"

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
        return build_health(bot_count=bot_count)
