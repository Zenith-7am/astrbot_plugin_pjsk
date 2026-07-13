"""EventMapper — extract identity and image bytes from AstrBot events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pjsk_core.domain.users import QqNumber

if TYPE_CHECKING:
    from astrbot.api.message_components import Image as AstrBotImage
    from astrbot.api.event import AstrMessageEvent


@dataclass(frozen=True)
class ImageContext:
    """Extracted image and identity from an AstrBot event."""

    image_bytes: bytes
    qq_number: QqNumber
    openid: str | None
    platform_id: str
    conversation_id: str
    source_gateway: str


class EventMapper:
    """Extract identity, image bytes, and session id from AstrBot events.

    Must be called within the handler (before AstrBot cleans up temp files).
    """

    def extract(self, event: AstrMessageEvent) -> ImageContext | None:
        """Extract image context from event, or None if no image found."""
        images = [
            c for c in event.message_obj.message
            if c.__class__.__name__ == "Image"
        ]
        if len(images) != 1:
            return None
        img = images[0]
        image_bytes = self._read_image_bytes(img, event)
        if image_bytes is None:
            return None

        platform_id = event.get_platform_id()
        sender_id = event.get_sender_id()
        qq = QqNumber(sender_id)
        conv_id = self.extract_conversation_id(event)
        gateway = self._gateway_name(platform_id)

        return ImageContext(
            image_bytes=image_bytes,
            qq_number=qq,
            openid=None,  # QQ official bot OpenID — resolved later
            platform_id=platform_id,
            conversation_id=conv_id,
            source_gateway=gateway,
        )

    def extract_qq(self, event: AstrMessageEvent) -> QqNumber:
        return QqNumber(event.get_sender_id())

    def extract_conversation_id(self, event: AstrMessageEvent) -> str:
        group_id = event.get_group_id()
        if group_id:
            return f"group:{group_id}"
        return f"private:{event.get_sender_id()}"

    def _has_image(self, event: AstrMessageEvent) -> bool:
        return any(
            c.__class__.__name__ == "Image"
            for c in event.message_obj.message
        )

    @staticmethod
    def _read_image_bytes(img: AstrBotImage, event: AstrMessageEvent) -> bytes | None:
        """Read image bytes from AstrBot Image component.

        AstrBot downloads images to temp files and cleans them after the
        handler returns. We must read before returning.
        """
        if hasattr(img, 'file') and img.file:
            import os
            if os.path.isfile(img.file):
                with open(img.file, 'rb') as f:
                    return f.read()
        if hasattr(img, 'url') and img.url:
            import httpx
            try:
                resp = httpx.get(img.url, timeout=15.0)
                resp.raise_for_status()
                return resp.content
            except Exception:
                return None
        return None

    @staticmethod
    def _gateway_name(platform_id: str) -> str:
        if "onebot" in platform_id.lower():
            return "onebot"
        if "qq_official" in platform_id.lower() or "qqofficial" in platform_id.lower():
            return "qq_official"
        return platform_id
