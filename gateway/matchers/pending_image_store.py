"""Process-in-memory store for pending group images (TTL + hard cap)."""
from __future__ import annotations

import time
from typing import NamedTuple


class _Entry(NamedTuple):
    data: bytes
    timestamp: float


class PendingImageStore:
    """Stores the latest image per (group_id, qq) with a 30s TTL.

    Not persisted — data is lost on restart (acceptable).
    """

    def __init__(self, max_entries: int = 500) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._max_entries = max_entries

    def put(self, group_id: str, qq: str, image_bytes: bytes) -> None:
        """Store (or overwrite) the latest image for this user in this group."""
        key = (group_id, qq)
        if len(self._entries) >= self._max_entries and key not in self._entries:
            # Evict the oldest entry
            oldest = min(self._entries, key=lambda k: self._entries[k].timestamp)
            del self._entries[oldest]
        self._entries[key] = _Entry(data=image_bytes, timestamp=time.monotonic())

    def pop(self, group_id: str, qq: str, max_age_s: float = 30) -> bytes | None:
        """Return and remove the latest image for this user if ≤ max_age_s.

        Returns None if no image or the image has expired.
        """
        key = (group_id, qq)
        entry = self._entries.get(key)
        if entry is None:
            return None
        del self._entries[key]
        if time.monotonic() - entry.timestamp > max_age_s:
            return None
        return entry.data
