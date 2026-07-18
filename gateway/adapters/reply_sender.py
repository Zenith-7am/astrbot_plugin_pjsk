"""Reply sender — maps internal reply types to OneBot message segments."""
from __future__ import annotations

import base64
import logging
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, MessageSegment

from pjsk_core.application.replies import ImageReply, TextReply

_logger = logging.getLogger(__name__)


async def send_text_reply(bot: Bot, event: Any, reply: TextReply) -> None:
    """Send a TextReply via OneBot. Empty text is silently dropped."""
    text = reply.text.strip()
    if not text:
        return
    _logger.info("reply: text=%d chars", len(text))
    await bot.send(event, MessageSegment.text(text))


async def send_image_reply(bot: Bot, event: Any, reply: ImageReply) -> None:
    """Send an ImageReply via OneBot as a base64-encoded JPEG segment.

    PNG renders from the render service (200-500 KB) are converted to JPEG
    for 3-5× smaller QQ message payloads.  Falls back to raw PNG on
    conversion failure.
    """
    from gateway.adapters.image_utils import png_to_jpeg

    image_bytes = reply.image_bytes
    if reply.mime_type == "image/png":
        jpg = png_to_jpeg(image_bytes)
        if jpg is not None:
            image_bytes = jpg

    b64 = base64.b64encode(image_bytes).decode()
    _logger.info(
        "reply: image=%d bytes, mime=%s",
        len(image_bytes), reply.mime_type,
    )
    await bot.send(event, MessageSegment.image(f"base64://{b64}"))

