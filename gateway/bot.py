"""PJSK Bot — NoneBot 2 + OneBot v11 Gateway."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Configure Python logging early so _logger.info() calls in gateway/
# and pjsk_core/ are visible (default is WARNING, which silences them).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
from gateway.log_config import sanitize_third_party_loggers  # noqa: E402
sanitize_third_party_loggers()

# Ensure the project root is on sys.path so that gateway.* imports resolve
# regardless of how the process is launched.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from gateway.adapters.config_loader import load_config
from gateway.health import register_health_route

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
    nonebot.logger.info(
        "[PJSK] gateway starting — access_token=<present>"
    )
    # Bootstrap Runtime so matchers can access repositories and use cases.
    # ImportError / ValueError = gateway not available (test / import check).
    try:
        from pjsk_emubot.bootstrap import assemble_plugin_runtime
        nonebot.logger.info("[PJSK] assembling Runtime …")
        _rt = await assemble_plugin_runtime()
        nonebot.logger.info("[PJSK] Runtime ready — status=%s", _rt.status.value)
    except Exception:
        nonebot.logger.exception("[PJSK] Runtime assembly failed — gateway degraded")


@driver.on_shutdown
async def _shutdown() -> None:
    nonebot.logger.info("[PJSK] gateway stopped")


if __name__ == "__main__":
    nonebot.run()
