"""Tests for gateway reply sender."""
import base64
from unittest.mock import AsyncMock, MagicMock

from pjsk_core.application.replies import ImageReply


class TestSendImageReply:
    async def test_sends_image_segment(self) -> None:
        from gateway.adapters.reply_sender import send_image_reply

        bot = MagicMock()
        bot.send = AsyncMock()
        event = MagicMock()
        reply = ImageReply(
            image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            mime_type="image/png",
        )

        await send_image_reply(bot, event, reply)

        bot.send.assert_called_once()
        seg = bot.send.call_args[0][1]
        assert seg.type == "image"
        assert seg.data["file"].startswith("base64://")

    async def test_base64_encoding(self) -> None:
        from gateway.adapters.reply_sender import send_image_reply

        bot = MagicMock()
        bot.send = AsyncMock()
        event = MagicMock()
        test_data = b"test-image-bytes"
        reply = ImageReply(image_bytes=test_data, mime_type="image/png")

        await send_image_reply(bot, event, reply)

        seg = bot.send.call_args[0][1]
        expected_b64 = base64.b64encode(test_data).decode()
        assert seg.data["file"] == f"base64://{expected_b64}"
