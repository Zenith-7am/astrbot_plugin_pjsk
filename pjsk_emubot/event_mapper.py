"""EventMapper — extract identity and image bytes from AstrBot events."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pjsk_core.domain.users import QqNumber

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)

# 10 MiB hard limit
MAX_IMAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ImageContext:
    """Extracted image and identity from an AstrBot event.

    ``qq_number`` is ``None`` for QQ Official Bot (OpenID sender_id).
    Callers must detect this and handle accordingly — the QQ number
    cannot be derived from an OpenID.
    """

    image_bytes: bytes
    qq_number: QqNumber | None
    openid: str | None
    platform_id: str
    conversation_id: str
    source_gateway: str


class EventMapper:
    """Extract identity, image bytes, and session id from AstrBot events.

    Must be called within the handler (before AstrBot cleans up temp files).
    """

    # ── Public API ────────────────────────────────────────────────────────

    async def extract_async(
        self, event: Any, http_client: Any = None,
    ) -> ImageContext | None:
        """Extract image context with async HTTP support for URL images.

        This is the primary extraction path.  Uses ``convert_to_file_path()``
        on the Image component (AstrBot API), then falls back to async HTTP
        streaming with Content-Length gating.
        """
        images = [
            c for c in event.message_obj.message
            if c.__class__.__name__ == "Image"
        ]
        if len(images) != 1:
            return None
        image_bytes = await self._read_image_bytes_async(images[0], http_client)
        if image_bytes is None:
            return None
        if len(image_bytes) > MAX_IMAGE_BYTES:
            return None
        return self._build_context(event, image_bytes)

    def extract_qq(self, event: Any) -> QqNumber:
        """Extract QQ number from sender_id.

        For OneBot platforms, sender_id is the QQ number.
        For QQ Official Bot, sender_id is an OpenID — caller must use
        ``is_qq_official()`` to detect this case first.
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

    def extract_conversation_id(self, event: Any) -> str:
        group_id = event.get_group_id()
        if group_id:
            return f"group:{group_id}"
        return f"private:{event.get_sender_id()}"

    def _has_image(self, event: Any) -> bool:
        return any(
            c.__class__.__name__ == "Image"
            for c in event.message_obj.message
        )

    # ── Image byte reading ────────────────────────────────────────────────

    @staticmethod
    async def _read_image_bytes_async(
        img: Any, http_client: Any = None,
    ) -> bytes | None:
        """Read image bytes with async streaming and size gating.

        Priority:
        1. ``convert_to_file_path()`` on the Image component (AstrBot API)
           → read via ``asyncio.to_thread()`` with file-size check first.
        2. ``img.url`` → HTTP download via ``AsyncClient.stream()``.
           Content-Length is checked before streaming; without it, bytes
           are accumulated chunk-by-chunk and the stream is aborted when
           the 10 MiB limit is exceeded.

        Returns ``None`` on any failure (missing file, HTTP error, timeout).
        """
        # 1. Local file (AstrBot temp file)
        file_path = getattr(img, 'file', None) or ''
        # AstrBot v3 Image component may provide convert_to_file_path()
        if hasattr(img, 'convert_to_file_path') and callable(img.convert_to_file_path):
            try:
                # convert_to_file_path may be sync or async
                result = img.convert_to_file_path()
                if asyncio.iscoroutine(result):
                    file_path = await result
                else:
                    file_path = result
            except Exception:
                file_path = ''

        if file_path and os.path.isfile(file_path):
            try:
                fsize = os.path.getsize(file_path)
                if fsize > MAX_IMAGE_BYTES:
                    return None
                return await asyncio.to_thread(_read_local_file, file_path)
            except OSError:
                return None

        # 2. HTTP URL (remote image)
        url = getattr(img, 'url', None)
        if url and http_client is not None and hasattr(http_client, 'stream'):
            return await _stream_http_image(http_client, url)
        if url:
            # No async client available → can't read safely
            return None

        return None

    # ── Internal helpers ──────────────────────────────────────────────────

    def _build_context(self, event: Any, image_bytes: bytes) -> ImageContext:
        platform_id = event.get_platform_id()
        sender_id = event.get_sender_id()
        if self.is_qq_official(event):
            openid = sender_id
            qq: QqNumber | None = None
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
    def _gateway_name(platform_id: str) -> str:
        if "onebot" in platform_id.lower():
            return "onebot"
        if "qq_official" in platform_id.lower() or "qqofficial" in platform_id.lower():
            return "qq_official"
        return platform_id


# ── Module-level helpers (not methods — testable independently) ──────────


def _read_local_file(path: str) -> bytes:
    """Read a local file synchronously (called via ``asyncio.to_thread``)."""
    with open(path, 'rb') as f:
        return f.read()


async def _stream_http_image(http_client: Any, url: str) -> bytes | None:
    """Stream an image URL, gating on Content-Length and 10 MiB limit."""
    try:
        async with http_client.stream("GET", url, timeout=15.0) as resp:
            resp.raise_for_status()
            content_length = resp.headers.get("Content-Length")
            if content_length is not None:
                cl = int(content_length)
                if cl > MAX_IMAGE_BYTES:
                    return None
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    return None
            return b"".join(chunks)
    except Exception:
        return None
