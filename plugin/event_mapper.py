"""EventMapper — extract identity and image bytes from AstrBot events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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

    async def extract_async(self, event: Any, http_client: Any = None) -> ImageContext | None:
        """Extract with async HTTP support for URL images."""
        images = [
            c for c in event.message_obj.message
            if c.__class__.__name__ == "Image"
        ]
        if len(images) != 1:
            return None
        image_bytes = await self._read_image_bytes_async(images[0], http_client)
        if image_bytes is None or len(image_bytes) > 10 * 1024 * 1024:
            return None
        return self._build_context(event, image_bytes)

    def extract(self, event: Any) -> ImageContext | None:
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
        # Check 10 MiB size limit AFTER reading
        if len(image_bytes) > 10 * 1024 * 1024:
            return None
        return self._build_context(event, image_bytes)

    def extract_qq(self, event: AstrMessageEvent) -> QqNumber:
        """Extract QQ number from sender_id.

        For OneBot platforms, sender_id is the QQ number.
        For QQ Official Bot, sender_id is an OpenID — caller must use
        ``is_qq_official()`` to detect this case and handle accordingly.
        """
        return QqNumber(event.get_sender_id())

    @staticmethod
    def is_qq_official(event: Any) -> bool:
        """Return True if the event is from a QQ Official Bot platform."""
        try:
            pid = event.get_platform_id()
        except (AttributeError, TypeError):
            return False
        return "qq_official" in str(pid).lower() or "qqofficial" in str(pid).lower()

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
    async def _read_image_bytes_async(img: Any, http_client: Any = None) -> bytes | None:
        """Read image bytes with async HTTP fallback for URL images."""
        if hasattr(img, 'file') and img.file:
            import os
            if os.path.isfile(img.file):
                with open(img.file, 'rb') as f:
                    return f.read()
        if hasattr(img, 'url') and img.url:
            if http_client is not None and hasattr(http_client, 'get'):
                try:
                    resp = await http_client.get(img.url, timeout=15.0)
                    resp.raise_for_status()
                    return bytes(resp.content)
                except Exception:
                    return None
            # Fallback: sync httpx (only if no async client available)
            try:
                import httpx
                resp = httpx.get(img.url, timeout=15.0)
                resp.raise_for_status()
                return resp.content
            except Exception:
                return None
        return None

    def _build_context(self, event: Any, image_bytes: bytes) -> ImageContext:
        platform_id = event.get_platform_id()
        sender_id = event.get_sender_id()
        if self.is_qq_official(event):
            openid = sender_id
            qq = QqNumber("0")
        else:
            openid = None
            qq = QqNumber(sender_id)
        conv_id = self.extract_conversation_id(event)
        gateway = self._gateway_name(platform_id)
        return ImageContext(
            image_bytes=image_bytes,
            qq_number=qq,
            openid=openid,
            platform_id=platform_id,
            conversation_id=conv_id,
            source_gateway=gateway,
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
