"""Process-in-memory store for pending group images (TTL + hard cap)."""
from __future__ import annotations

import os
import time
from typing import NamedTuple

_DEFAULT_TTL = float(os.environ.get("PJSK_PENDING_IMAGE_TTL_SECONDS", "120"))


class _Entry(NamedTuple):
    data: bytes
    timestamp: float


class PendingImageStore:
    """Stores the latest image per (group_id, qq) with a configurable TTL.

    Not persisted — data is lost on restart (acceptable).
    """

    def __init__(self, max_entries: int = 500) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._max_entries = max_entries

    def put(self, group_id: str, qq: str, image_bytes: bytes) -> None:
        """Store (or overwrite) the latest image for this user in this group.

        Also sweeps expired entries to prevent unbounded growth in active
        groups where images are posted but never consumed via ``.emu``.
        """
        key = (group_id, qq)
        now = time.monotonic()
        # Sweep expired entries
        expired = [
            k for k, v in self._entries.items()
            if now - v.timestamp > _DEFAULT_TTL
        ]
        for k in expired:
            del self._entries[k]
        if len(self._entries) >= self._max_entries and key not in self._entries:
            # Evict the oldest entry
            oldest = min(self._entries, key=lambda k: self._entries[k].timestamp)
            del self._entries[oldest]
        self._entries[key] = _Entry(data=image_bytes, timestamp=now)

    def pop(self, group_id: str, qq: str, max_age_s: float | None = None) -> bytes | None:
        """Return and remove the latest image for this user if ≤ max_age_s.

        If *max_age_s* is None, the default from the
        ``PJSK_PENDING_IMAGE_TTL_SECONDS`` env var is used (default 120s).

        Returns None if no image or the image has expired.
        """
        if max_age_s is None:
            max_age_s = _DEFAULT_TTL
        key = (group_id, qq)
        entry = self._entries.get(key)
        if entry is None:
            return None
        del self._entries[key]
        if time.monotonic() - entry.timestamp > max_age_s:
            return None
        return entry.data
