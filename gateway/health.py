"""Health check endpoint — route registered once, not per-startup."""
from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI

from gateway.commands import GATEWAY_VERSION

_START_TIME = time.monotonic()


def build_health(bot_count: int = 0) -> dict[str, Any]:
    """Build health response. bot_count: 0=disconnected, >0=connected."""
    uptime = time.monotonic() - _START_TIME
    connected = bot_count > 0
    return {
        "status": "ok" if connected else "degraded",
        "onebot": "connected" if connected else "disconnected",
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
