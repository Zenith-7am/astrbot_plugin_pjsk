"""Tests for gateway.adapters.event_mapper."""
import pytest
from gateway.adapters.event_mapper import map_event, IncomingMessage, ConversationType


class FakeOneBotEvent:
    """Minimal stand-in for nonebot.adapters.onebot.v11.Event."""
    def __init__(self, *, message_type, user_id, message_id,
                 raw_message, group_id=None, to_me=False):
        self.message_type = message_type
        self.user_id = user_id
        self.message_id = message_id
        self.raw_message = raw_message
        self.group_id = group_id
        self.to_me = to_me

    def get_user_id(self):
        return str(self.user_id)

    def get_message_id(self):
        return str(self.message_id)

    def get_plaintext(self):
        return self.raw_message

    def is_tome(self):
        return self.to_me


class TestMapEvent:
    def test_private_message(self):
        event = FakeOneBotEvent(
            message_type="private", user_id="123456789",
            message_id="msg-001", raw_message="/emu status",
        )
        msg = map_event(event)
        assert isinstance(msg, IncomingMessage)
        assert msg.gateway == "onebot"
        assert msg.conversation_type == ConversationType.PRIVATE
        assert msg.group_id is None
        assert msg.text == "/emu status"
        assert msg.is_bot_mentioned is True

    def test_group_message_with_at(self):
        event = FakeOneBotEvent(
            message_type="group", user_id="111111",
            message_id="msg-002", raw_message="/emu help",
            group_id="987654321", to_me=True,
        )
        msg = map_event(event)
        assert msg.conversation_type == ConversationType.GROUP
        assert msg.group_id == "987654321"
        assert msg.is_bot_mentioned is True

    def test_group_message_without_at(self):
        event = FakeOneBotEvent(
            message_type="group", user_id="111111",
            message_id="msg-003", raw_message="today weather",
            group_id="987654321", to_me=False,
        )
        msg = map_event(event)
        assert msg.is_bot_mentioned is False

    def test_repr_never_exposes_external_user_id(self):
        event = FakeOneBotEvent(
            message_type="private", user_id="999999999",
            message_id="msg-004", raw_message="/emu help",
        )
        msg = map_event(event)
        r = repr(msg)
        assert "999999999" not in r
