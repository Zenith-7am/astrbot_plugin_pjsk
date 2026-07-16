"""PJSK Bot — NoneBot 2 + OneBot v11 Gateway."""
from pathlib import Path
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


@driver.on_shutdown
async def _shutdown() -> None:
    nonebot.logger.info("[PJSK] gateway stopped")


if __name__ == "__main__":
    nonebot.run()
