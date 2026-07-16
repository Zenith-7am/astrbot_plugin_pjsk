"""OneBot event → platform-agnostic IncomingMessage."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConversationType(Enum):
    PRIVATE = "private"
    GROUP = "group"


@dataclass(frozen=True)
class IncomingMessage:
    gateway: str
    external_user_id: str
    conversation_type: ConversationType
    group_id: str | None
    message_id: str
    text: str
    is_bot_mentioned: bool

    def __repr__(self) -> str:
        return (
            f"IncomingMessage(gateway={self.gateway!r}, "
            f"conversation_type={self.conversation_type.value!r}, "
            f"text={self.text[:40]!r}, "
            f"is_bot_mentioned={self.is_bot_mentioned})"
        )


def map_event(event: Any) -> IncomingMessage:
    is_private = event.message_type == "private"
    return IncomingMessage(
        gateway="onebot",
        external_user_id=str(event.user_id),
        conversation_type=(
            ConversationType.PRIVATE if is_private else ConversationType.GROUP
        ),
        group_id=None if is_private else str(getattr(event, "group_id", "") or ""),
        message_id=str(event.message_id),
        text=event.get_plaintext().strip(),
        is_bot_mentioned=is_private or bool(getattr(event, "to_me", False)),
    )
