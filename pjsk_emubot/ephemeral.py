"""EphemeralImageBuffer -- short-lived in-memory image cache for group chat."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Entry:
    image_bytes: bytes
    stored_at: float  # monotonic timestamp


def _key_from_identity(sender_qq: object) -> str:
    """Extract a string key from a QQ identity object."""
    return str(getattr(sender_qq, "value", sender_qq))


class EphemeralImageBuffer:
    """In-memory buffer for group-chat images awaiting an @Bot trigger.

    Keyed by (platform_id, group_id, sender_qq). Only the most recent
    image per user is retained. Size-limited and TTL-gated.

    ``arm`` / ``consume_arm`` implement the "mention-first" direction of
    the 15-second window: a user @mentions the bot, *then* sends an image
    within the TTL.  The arm is a lightweight boolean marker — it does not
    hold image data.
    """

    MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB

    def __init__(
        self,
        max_size_bytes: int = 10 * 1024 * 1024,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        self._arm_timestamps: dict[tuple[str, str, str], float] = {}
        self._max_size_bytes = max_size_bytes
        self._total_bytes = 0
        self._clock = clock if clock is not None else time.monotonic

    def put(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: object,
        image_bytes: bytes,
    ) -> None:
        key = (platform_id, group_id, _key_from_identity(sender_qq))
        if len(image_bytes) > self._max_size_bytes:
            return
        # Remove old entry BEFORE eviction loop so it isn't double-counted
        old = self._entries.pop(key, None)
        if old is not None:
            self._total_bytes -= len(old.image_bytes)
        # Evict until enough room (may need multiple rounds)
        while self._entries and self._total_bytes + len(image_bytes) > self.MAX_TOTAL_BYTES:
            self._evict_oldest()
        self._entries[key] = _Entry(
            image_bytes=image_bytes,
            stored_at=self._clock(),
        )
        self._total_bytes += len(image_bytes)

    def consume(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: object,
        *,
        within_seconds: float = 15.0,
    ) -> bytes | None:
        key = (platform_id, group_id, _key_from_identity(sender_qq))
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        self._total_bytes -= len(entry.image_bytes)
        age = self._clock() - entry.stored_at
        if age >= within_seconds:
            return None
        return entry.image_bytes

    def arm(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: object,
    ) -> None:
        """Mark that this user is waiting to send an image within the TTL.

        Call after an empty @Bot mention — the next image from this user
        in this group on this platform will trigger OCR immediately.
        """
        key = (platform_id, group_id, _key_from_identity(sender_qq))
        self._arm_timestamps[key] = self._clock()

    def consume_arm(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: object,
        *,
        within_seconds: float = 15.0,
    ) -> bool:
        """Return True if there is an active arm for this user, consuming it.

        An arm is "active" if it was set within ``within_seconds``.
        Consuming removes the marker — it is one-shot.
        """
        key = (platform_id, group_id, _key_from_identity(sender_qq))
        ts = self._arm_timestamps.pop(key, None)
        if ts is None:
            return False
        age = self._clock() - ts
        return age < within_seconds

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
        self._arm_timestamps.clear()
        self._total_bytes = 0
