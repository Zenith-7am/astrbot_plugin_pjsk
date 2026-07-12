"""PJSK AstrBot plugin entry point.

This plugin provides score screenshot OCR, personal best tracking,
B20 ranking, and chart difficulty rankings for Project SEKAI.
"""

from astrbot.api.star import Context, Star, register
from astrbot.api import logger


@register(
    "pjsk-astrbot",
    "leoviria",
    "PJSK score tracking, B20, and chart rankings via multi-model vision OCR",
    "0.0.0",
)
class PjskPlugin(Star):  # type: ignore[misc]  # Star is Any without astrbot stubs
    """PJSK AstrBot plugin — score tracking and rankings."""

    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def initialize(self) -> None:
        """Called after plugin class is instantiated."""
        logger.info("pjsk-astrbot plugin initialized")

    async def terminate(self) -> None:
        """Called when plugin is unloaded or disabled."""
        logger.info("pjsk-astrbot plugin terminated")
