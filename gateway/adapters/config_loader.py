"""Config loader — env vars only, no YAML in this phase."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass
class GatewayConfig:
    onebot_access_token: str = field(repr=False)

    @classmethod
    def from_env(cls) -> GatewayConfig:
        token = os.environ.get("ONEBOT_ACCESS_TOKEN")
        if not token:
            raise ConfigError(
                "ONEBOT_ACCESS_TOKEN is required. "
                "Set it in the environment before starting the bot."
            )
        _logger.info("Config loaded: onebot_access_token=<present>")
        return cls(onebot_access_token=token)


# Public API — used by bot.py before nonebot.init()
load_config = GatewayConfig.from_env
