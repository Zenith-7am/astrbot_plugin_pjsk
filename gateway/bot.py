"""PJSK Bot — NoneBot 2 + OneBot v11 Gateway.

Import order is deliberately non-standard: sys.path must be fixed,
logging configured, and third-party loggers silenced BEFORE any
gateway / nonebot imports.  ``# ruff: noqa: E402`` applies file-wide.
"""
# ruff: noqa: E402
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# ── sys.path MUST be set before any gateway.* import ──────────────────────
# When an editable install from a previous release is present in site-packages,
# Python's import system resolves ``gateway.*`` through the old .pth file
# *unless* the project root is at position 0 in sys.path.  By computing
# _project_root and inserting it first, we guarantee that the running source
# tree wins over any stale editable-install pointer.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# The git SHA is read at import time so it is available even if the startup
# bootstrap fails later.
_GIT_SHA = "unknown"
try:
    import subprocess
    _git_dir = str(Path(_project_root) / ".git")
    if os.path.isdir(_git_dir):
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=_project_root, timeout=5,
        )
        if result.returncode == 0:
            _GIT_SHA = result.stdout.strip()
except Exception:
    pass

# Configure Python logging early so _logger.info() calls in gateway/
# and pjsk_core/ are visible (default is WARNING, which silences them).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# AFTER sys.path fix — safe to import gateway submodules
from gateway.log_config import sanitize_third_party_loggers  # noqa: E402
sanitize_third_party_loggers()

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from gateway.adapters.config_loader import load_config
from gateway.health import register_health_route, set_runtime

# ── Module-level Runtime reference ───────────────────────────────────────
# Saved by _startup(), read by /health and cleared by _shutdown().
_runtime: Any | None = None

# Config MUST be loaded before nonebot.init() — token is injected into the adapter
config = load_config()

nonebot.init(access_token=config.onebot_access_token)
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# Register health route once (not per-startup)
register_health_route(nonebot.get_app())

nonebot.load_plugins(str(Path(__file__).parent / "matchers"))


@driver.on_startup
async def _startup() -> None:
    global _runtime
    nonebot.logger.info(
        "[PJSK] gateway starting — access_token=<present>"
    )
    # ── Release identity — print paths so operators can verify all modules
    #     belong to the SAME release directory (no mixed-code deployment).
    nonebot.logger.info(f"[PJSK] git_sha={_GIT_SHA} project_root={_project_root}")
    nonebot.logger.info(f"[PJSK] gateway.__file__ = {__file__}")
    try:
        import pjsk_core
        nonebot.logger.info(f"[PJSK] pjsk_core.__file__ = {pjsk_core.__file__}")
    except Exception:
        nonebot.logger.warning("[PJSK] pjsk_core path unavailable")
    try:
        import pjsk_runtime
        nonebot.logger.info(f"[PJSK] pjsk_runtime.__file__ = {pjsk_runtime.__file__}")
    except Exception:
        nonebot.logger.warning("[PJSK] pjsk_runtime path unavailable")
    # ── Bootstrap ────────────────────────────────────────────────────────
    # Bootstrap Runtime so matchers can access repositories and use cases.
    # ImportError / ValueError = gateway not available (test / import check).
    try:
        from pjsk_emubot.bootstrap import assemble_plugin_runtime
        nonebot.logger.info("[PJSK] assembling Runtime …")
        _runtime = await assemble_plugin_runtime()
        set_runtime(_runtime)
        nonebot.logger.info("[PJSK] Runtime ready — status=%s", _runtime.status.value)
    except Exception:
        nonebot.logger.exception("[PJSK] Runtime assembly failed — gateway degraded")
        _runtime = None
        set_runtime(None)


@driver.on_shutdown
async def _shutdown() -> None:
    global _runtime
    nonebot.logger.info("[PJSK] gateway shutting down …")
    if _runtime is not None:
        try:
            await _runtime.close()
            nonebot.logger.info("[PJSK] Runtime closed")
        except Exception:
            nonebot.logger.exception("[PJSK] Runtime close failed")
        finally:
            _runtime = None
            set_runtime(None)
    nonebot.logger.info("[PJSK] gateway stopped")


if __name__ == "__main__":
    nonebot.run()
