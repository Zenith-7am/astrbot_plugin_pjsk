"""Reply sender — maps internal reply types to OneBot message segments."""
from __future__ import annotations

import logging
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, MessageSegment

from pjsk_core.application.replies import TextReply

_logger = logging.getLogger(__name__)


async def send_text_reply(bot: Bot, event: Any, reply: TextReply) -> None:
    """Send a TextReply via OneBot. Empty text is silently dropped."""
    text = reply.text.strip()
    if not text:
        return
    _logger.info("reply: text=%d chars", len(text))
    await bot.send(event, MessageSegment.text(text))

