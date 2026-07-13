"""Tests for EventMapper."""
from dataclasses import dataclass, field
from typing import Any

from plugin.event_mapper import EventMapper


# ── Fake AstrBot types ─────────────────────────────────────────────────


@dataclass
class FakeImage:
    """Stand-in for astrbot.api.message_components.Image."""

    url: str = ""
    file: str = ""


@dataclass
class FakeMessageObject:
    message: list[Any] = field(default_factory=list)


@dataclass
class FakeMessageEvent:
    message_obj: FakeMessageObject = field(default_factory=FakeMessageObject)
    platform_id: str = "onebot_v11"
    raw_message: str = ""
    sender_id: str = "123456789"

    def get_platform_id(self) -> str:
        return self.platform_id

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str | None:
        return None  # default: private chat

    def get_message_type(self) -> str:
        return "private"


class TestEventMapper:
    def test_extracts_qq_from_sender_id(self) -> None:
        event = FakeMessageEvent(sender_id="987654321")
        mapper = EventMapper()
        qq = mapper.extract_qq(event)
        assert qq.value == "987654321"

    def test_extract_returns_none_for_text_only_message(self) -> None:
        event = FakeMessageEvent(
            message_obj=FakeMessageObject(message=[]),
        )
        mapper = EventMapper()
        ctx = mapper.extract(event)
        assert ctx is None

    def test_extract_returns_context_for_image_message(self) -> None:
        # A local class whose __class__.__name__ matches the duck-typing
        # check in EventMapper._has_image (c.__class__.__name__ == "Image").
        # Without a real AstrBot runtime, extracting bytes from this would
        # raise — we test that the image component IS detected.
        class Image:  # noqa: N801
            url = "http://example.com/img.png"
            file = ""
        event = FakeMessageEvent(
            message_obj=FakeMessageObject(message=[Image()]),
        )
        mapper = EventMapper()
        assert mapper._has_image(event)

    def test_conversation_id_private_chat(self) -> None:
        event = FakeMessageEvent(sender_id="987654321")
        mapper = EventMapper()
        cid = mapper.extract_conversation_id(event)
        assert cid == "private:987654321"
