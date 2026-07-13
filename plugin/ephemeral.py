"""EphemeralImageBuffer -- short-lived in-memory image cache for group chat."""
from __future__ import annotations

import time
from dataclasses import dataclass

from pjsk_core.domain.users import QqNumber


@dataclass
class _Entry:
    image_bytes: bytes
    stored_at: float  # monotonic timestamp


class EphemeralImageBuffer:
    """In-memory buffer for group-chat images awaiting an @Bot trigger.

    Keyed by (platform_id, group_id, sender_qq). Only the most recent
    image per user is retained. Size-limited and TTL-gated.
    """

    MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB

    def __init__(self, max_size_bytes: int = 10 * 1024 * 1024) -> None:
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        self._max_size_bytes = max_size_bytes
        self._total_bytes = 0

    def put(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: QqNumber,
        image_bytes: bytes,
    ) -> None:
        key = (platform_id, group_id, sender_qq.value)
        if len(image_bytes) > self._max_size_bytes:
            return
        if self._total_bytes + len(image_bytes) > self.MAX_TOTAL_BYTES:
            self._evict_oldest()
        self._entries[key] = _Entry(
            image_bytes=image_bytes,
            stored_at=time.monotonic(),
        )
        self._total_bytes += len(image_bytes)

    def consume(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: QqNumber,
        *,
        within_seconds: float = 15.0,
    ) -> bytes | None:
        key = (platform_id, group_id, sender_qq.value)
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        self._total_bytes -= len(entry.image_bytes)
        age = time.monotonic() - entry.stored_at
        if age > within_seconds:
            return None
        return entry.image_bytes

    def _evict_oldest(self) -> None:
        if not self._entries:
            return
        oldest_key = min(
            self._entries.keys(),
            key=lambda k: self._entries[k].stored_at,
        )
        old = self._entries.pop(oldest_key)
        self._total_bytes -= len(old.image_bytes)

    async def close(self) -> None:
        self._entries.clear()
        self._total_bytes = 0
