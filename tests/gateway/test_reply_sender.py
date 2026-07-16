"""Tests for gateway.adapters.reply_sender."""
import pytest
from gateway.adapters.reply_sender import send_text_reply


class FakeBot:
    """Minimal stand-in for nonebot.adapters.onebot.v11.Bot."""
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    async def send(self, event: object, message: object, **kwargs: object) -> None:
        self.sent_messages.append({
            "event": event,
            "message": message,
            "kwargs": kwargs,
        })


class TestSendTextReply:
    @pytest.mark.anyio
    async def test_sends_text_segment(self) -> None:
        bot = FakeBot()
        event = object()
        await send_text_reply(bot, event, "hello world")
        assert len(bot.sent_messages) == 1
        sent = bot.sent_messages[0]
        assert sent["message"].type == "text"
        assert sent["message"].data["text"] == "hello world"

    @pytest.mark.anyio
    async def test_empty_text_not_sent(self) -> None:
        bot = FakeBot()
        event = object()
        await send_text_reply(bot, event, "")
        assert len(bot.sent_messages) == 0
